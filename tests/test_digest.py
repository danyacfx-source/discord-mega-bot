"""Тесты ежедневного дайджеста (счётчики, публикация, поля эмбеда)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from app.cogs.monitoring.digest import DigestCog
from app.config import Config


def _config(**overrides) -> Config:
    config = Config(
        token="x",
        prefix="!",
        db_path="bot.db",
        log_level="ERROR",
        status_activity="s",
        owner_id=None,
    )
    for key, value in overrides.items():
        object.__setattr__(config, key, value)
    return config


def _kv(store: dict[str, str] | None = None) -> SimpleNamespace:
    data = store if store is not None else {}

    async def get(key: str) -> str | None:
        return data.get(key)

    async def set_(key: str, value: str) -> None:
        data[key] = value

    async def delete(key: str) -> None:
        data.pop(key, None)

    return SimpleNamespace(get=get, set=set_, delete=delete, _data=data)


def _cog(config=None, kv=None, guilds=None) -> DigestCog:
    bot = SimpleNamespace(
        config=config or _config(),
        guilds=guilds or [],
        services=SimpleNamespace(),
    )
    kv = kv or _kv()
    logging = SimpleNamespace(send_embed=AsyncMock(), target_channel=AsyncMock())
    return DigestCog(bot, logging, kv)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_bump_and_flush_writes_delta_to_kv() -> None:
    kv = _kv()
    cog = _cog(kv=kv)
    cog._bump(1, "messages")
    cog._bump(1, "messages")
    cog._bump(1, "joins")

    await cog._flush()

    date = cog._local_now().date().isoformat()
    payload = json.loads(kv._data[f"digest:counts:1:{date}"])
    assert payload == {"messages": 2, "joins": 1}


@pytest.mark.asyncio
async def test_flush_merges_with_existing_kv_after_restart() -> None:
    cog = _cog()
    date = cog._local_now().date().isoformat()
    kv = _kv({f"digest:counts:1:{date}": json.dumps({"messages": 5})})
    cog = _cog(kv=kv)
    cog._bump(1, "messages")

    await cog._flush()
    await cog._flush()  # повтор без новых событий — дельта 0, без перезаписи

    payload = json.loads(kv._data[f"digest:counts:1:{date}"])
    assert payload == {"messages": 6}


@pytest.mark.asyncio
async def test_on_message_counts_only_real_members_in_guilds() -> None:
    cog = _cog()

    bot_msg = SimpleNamespace(guild=SimpleNamespace(id=1), author=SimpleNamespace(bot=True))
    user_msg = SimpleNamespace(guild=SimpleNamespace(id=1), author=SimpleNamespace(bot=False))
    dm_msg = SimpleNamespace(guild=None, author=SimpleNamespace(bot=False))

    await cog.on_message(bot_msg)  # type: ignore[arg-type]
    assert sum(c["messages"] for c in cog._counts.values()) == 0
    await cog.on_message(user_msg)  # type: ignore[arg-type]
    await cog.on_message(dm_msg)  # type: ignore[arg-type]
    assert sum(c["messages"] for c in cog._counts.values()) == 1


@pytest.mark.asyncio
async def test_check_posts_once_per_day(monkeypatch: pytest.MonkeyPatch) -> None:
    guild = SimpleNamespace(id=7, name="G", member_count=42)
    kv = _kv()
    cog = _cog(kv=kv, guilds=[guild])
    fixed = datetime(2026, 10, 2, 21, 5, tzinfo=UTC)
    monkeypatch.setattr(cog, "_local_now", lambda: fixed, raising=False)
    publish = AsyncMock()
    monkeypatch.setattr(cog, "_publish", publish, raising=False)

    await cog._check()
    await cog._check()  # второй тик в том же часе — уже опубликовано

    publish.assert_awaited_once()
    assert kv._data["digest:posted:7:2026-10-02"] == "1"


@pytest.mark.asyncio
async def test_check_skips_wrong_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    cog = _cog(guilds=[SimpleNamespace(id=7, name="G")])
    monkeypatch.setattr(
        cog, "_local_now", lambda: datetime(2026, 10, 2, 13, 0, tzinfo=UTC), raising=False
    )
    publish = AsyncMock()
    monkeypatch.setattr(cog, "_publish", publish, raising=False)

    await cog._check()
    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_publish_builds_embed_with_all_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    guild = SimpleNamespace(id=7, name="G", member_count=42)
    date = datetime(2026, 10, 1).date().isoformat()
    kv = _kv({f"digest:counts:7:{date}": json.dumps({"messages": 10, "joins": 2, "leaves": 1})})
    cases = SimpleNamespace(
        daily_stats=AsyncMock(return_value={"warn": 3, "ban": 1})
    )
    archive = SimpleNamespace(list=AsyncMock(return_value=[
        {
            "ended_at": "2026-10-01T20:00:00+00:00",
            "seconds": 3600,
            "peak": 15,
        },
        {"ended_at": "2026-09-30T20:00:00+00:00", "seconds": 60, "peak": 9},
    ]))
    config = _config(twitch_channels=("somedude",))
    bot = SimpleNamespace(
        config=config,
        guilds=[guild],
        services=SimpleNamespace(cases=cases, twitch=SimpleNamespace(archive_store=lambda _: archive)),
    )
    cog = DigestCog(bot, SimpleNamespace(send_embed=AsyncMock()), kv)  # type: ignore[arg-type]

    await cog._publish(guild, datetime(2026, 10, 1).date())

    embed = cog.logging.send_embed.await_args.args[1]
    assert isinstance(embed, discord.Embed)
    assert "01.10.2026" in embed.title
    fields = {f.name: f.value for f in embed.fields}
    assert fields["💬 Сообщений"] == "10"
    assert "+2 / −1" in fields["👋 Участники"]
    assert "варны: **3**" in fields["🛡 Модерация"]
    assert "баны: **1**" in fields["🛡 Модерация"]
    assert "завершено: **1**" in fields["📺 Эфиры"]
    assert "60 мин" in fields["📺 Эфиры"]
    # вчерашние эфиры вне окна не попадают
    assert "завершено: **2**" not in fields["📺 Эфиры"]


@pytest.mark.asyncio
async def test_moderation_field_clean_when_no_cases() -> None:
    cases = SimpleNamespace(daily_stats=AsyncMock(return_value={}))
    guild = SimpleNamespace(id=7, name="G", member_count=1)
    bot = SimpleNamespace(config=_config(), guilds=[], services=SimpleNamespace(cases=cases))
    cog = DigestCog(bot, SimpleNamespace(send_embed=AsyncMock()), _kv())  # type: ignore[arg-type]
    start = datetime(2026, 10, 1, tzinfo=UTC)
    value = await cog._moderation_field(guild, start, start + timedelta(days=1))
    assert "чисто" in value


@pytest.mark.asyncio
async def test_trim_deletes_expired_keys() -> None:
    today = datetime(2026, 10, 2).date()
    kv = _kv()
    cog = _cog(kv=kv)
    kv._data[f"digest:counts:7:{(today - timedelta(days=30)).isoformat()}"] = "{}"
    kv._data[f"digest:posted:7:{(today - timedelta(days=60)).isoformat()}"] = "1"
    kv._data[f"digest:counts:7:{(today - timedelta(days=2)).isoformat()}"] = "{}"

    await cog._trim(7, today)

    assert f"digest:counts:7:{(today - timedelta(days=30)).isoformat()}" not in kv._data
    assert f"digest:posted:7:{(today - timedelta(days=60)).isoformat()}" not in kv._data
    assert f"digest:counts:7:{(today - timedelta(days=2)).isoformat()}" in kv._data


@pytest.mark.asyncio
async def test_cog_load_disabled_when_hour_negative() -> None:
    config = _config()
    object.__setattr__(config, "digest_hour", -1)
    cog = _cog(config=config)
    started: list[str] = []
    cog.check_loop = SimpleNamespace(start=lambda: started.append("check"))  # type: ignore[attr-defined]
    cog.flush_loop = SimpleNamespace(start=lambda: started.append("flush"))  # type: ignore[attr-defined]

    await cog.cog_load()
    assert started == []


@pytest.mark.asyncio
async def test_before_loop_stops_cleanly_without_login() -> None:
    """Вне логина wait_until_ready() кидает RuntimeError — цикл гасится без ошибок."""
    from unittest.mock import MagicMock

    cog = _cog()
    cog.bot.wait_until_ready = AsyncMock(side_effect=RuntimeError("не залогинен"))  # type: ignore[attr-defined]
    loop = SimpleNamespace(stop=MagicMock())

    await cog._wait_ready_or_stop(loop)  # type: ignore[arg-type]

    loop.stop.assert_called_once()


def test_digest_hour_env_clamped(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    # отдельный (несуществующий) env-файл: нельзя засорять os.environ проектным .env
    env_file = tmp_path / "absent.env"
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("DIGEST_HOUR", "99")
    assert Config.from_env(env_file).digest_hour == 23
    monkeypatch.setenv("DIGEST_HOUR", "-5")
    assert Config.from_env(env_file).digest_hour == -1
    monkeypatch.setenv("DIGEST_HOUR", "7")
    assert Config.from_env(env_file).digest_hour == 7
