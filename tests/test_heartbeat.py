"""Тесты HeartbeatCog — алерт о тишине бота в канал логов."""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
import pytest

from app.cogs.monitoring.heartbeat import HeartbeatCog
from app.config import Config


class _Chan:
    def __init__(self, id: int) -> None:
        self.id = id
        self.name = f"chan-{id}"
        self.send = AsyncMock()


class _Guild:
    def __init__(self, id: int, channels: list[_Chan]) -> None:
        self.id = id
        self._channels = {c.id: c for c in channels}

    def get_channel(self, channel_id: int):  # noqa: ANN201
        return self._channels.get(channel_id)


def _cog(*, guilds: list | None = None, silence: int = 30, bot_log: int | None = None, settings_get=None) -> HeartbeatCog:
    config = SimpleNamespace(heartbeat_silence_minutes=silence, bot_log_channel_id=bot_log)
    bot = SimpleNamespace(config=config, guilds=list(guilds or []))
    settings = SimpleNamespace(get=settings_get or AsyncMock(return_value={}))
    return HeartbeatCog(bot, settings)


def _msg(age: timedelta = timedelta(0)) -> SimpleNamespace:
    return SimpleNamespace(created_at=datetime.now(UTC) - age)


@pytest.mark.asyncio
async def test_on_message_rearms_and_updates_activity() -> None:
    cog = _cog(silence=30)
    cog._alerted = True
    cog._last_activity = datetime.now(UTC) - timedelta(minutes=40)
    await cog.on_message(_msg())
    assert cog._alerted is False
    assert datetime.now(UTC) - cog._last_activity < timedelta(seconds=5)


@pytest.mark.asyncio
async def test_on_message_backlog_alerts_once() -> None:
    """Сообщение старше порога = залипание; повторные застрявшие не дублируют алерт."""
    cog = _cog(silence=30)
    cog._log_targets = AsyncMock(return_value=[])
    stale = _msg(age=timedelta(minutes=45))
    await cog.on_message(stale)
    assert cog._log_targets.await_count == 1
    assert cog._alerted is True
    await cog.on_message(stale)
    assert cog._log_targets.await_count == 1
    # Свежее сообщение снова открывает окно.
    await cog.on_message(_msg())
    assert cog._alerted is False


@pytest.mark.asyncio
async def test_on_message_fresh_ignored_when_disabled() -> None:
    cog = _cog(silence=0)
    cog._log_targets = AsyncMock(return_value=[])
    await cog.on_message(_msg(age=timedelta(hours=5)))
    assert cog._log_targets.await_count == 0


@pytest.mark.asyncio
async def test_tick_alerts_once_on_silence() -> None:
    cog = _cog(silence=30)
    cog._log_targets = AsyncMock(return_value=[])
    cog._last_activity = datetime.now(UTC) - timedelta(minutes=35)
    await cog._tick()
    assert cog._log_targets.await_count == 1
    await cog._tick()
    assert cog._log_targets.await_count == 1


@pytest.mark.asyncio
async def test_tick_no_alert_before_threshold() -> None:
    cog = _cog(silence=30)
    cog._log_targets = AsyncMock(return_value=[])
    cog._last_activity = datetime.now(UTC) - timedelta(minutes=10)
    await cog._tick()
    assert cog._log_targets.await_count == 0


@pytest.mark.asyncio
async def test_tick_disabled_when_zero() -> None:
    cog = _cog(silence=0)
    cog._log_targets = AsyncMock(return_value=[])
    cog._last_activity = datetime.now(UTC) - timedelta(days=1)
    await cog._tick()
    assert cog._log_targets.await_count == 0


@pytest.mark.asyncio
async def test_send_alert_delivers_embed_to_targets() -> None:
    channel = _Chan(7)
    guild = _Guild(1, [channel])

    async def get(guild_id: int) -> dict:
        return {"bot_log_channel_id": 7}

    cog = _cog(guilds=[guild], settings_get=get)
    with patch("app.cogs.monitoring.heartbeat.discord.TextChannel", _Chan):
        await cog._send_alert(["нет сообщений уже 35 мин"])
    channel.send.assert_awaited_once()
    assert cog._alerted is True
    embed = channel.send.await_args.kwargs["embed"]
    assert isinstance(embed, discord.Embed)
    assert "нет сообщений уже 35 мин" in (embed.description or "")


@pytest.mark.asyncio
async def test_send_alert_without_targets_keeps_flag() -> None:
    cog = _cog(guilds=[])
    await cog._send_alert(["нет сообщений уже 35 мин"])
    assert cog._alerted is True


@pytest.mark.asyncio
async def test_log_targets_settings_channels_and_env_fallback() -> None:
    chan_a, chan_b = _Chan(100), _Chan(200)
    guild_a, guild_b = _Guild(1, [chan_a]), _Guild(2, [chan_b])

    async def get(guild_id: int) -> dict:
        return {"bot_log_channel_id": 100 if guild_id == 1 else 200}

    cog = _cog(guilds=[guild_a, guild_b], settings_get=get)
    with patch("app.cogs.monitoring.heartbeat.discord.TextChannel", _Chan):
        targets = await cog._log_targets()
    assert {t.id for t in targets} == {100, 200}

    async def empty(guild_id: int) -> dict:
        return {"bot_log_channel_id": None}

    fallback = _Guild(3, [_Chan(55)])
    cog = _cog(guilds=[fallback], bot_log=55, settings_get=empty)
    with patch("app.cogs.monitoring.heartbeat.discord.TextChannel", _Chan):
        targets = await cog._log_targets()
    assert [t.id for t in targets] == [55]


@pytest.mark.asyncio
async def test_log_targets_skips_guild_without_channel() -> None:
    guild = _Guild(1, [])

    async def get(guild_id: int) -> dict:
        return {"bot_log_channel_id": 9}

    cog = _cog(guilds=[guild], settings_get=get)
    with patch("app.cogs.monitoring.heartbeat.discord.TextChannel", _Chan):
        assert await cog._log_targets() == []


def test_config_heartbeat_env(tmp_path, monkeypatch) -> None:
    # load_dotenv пишет в os.environ навсегда — чистим после чтения.
    monkeypatch.delenv("HEARTBEAT_SILENCE_MINUTES", raising=False)
    env = tmp_path / ".env"
    env.write_text("BOT_TOKEN=t\nHEARTBEAT_SILENCE_MINUTES=45\n", encoding="utf-8")
    assert Config.from_env(env).heartbeat_silence_minutes == 45
    os.environ.pop("HEARTBEAT_SILENCE_MINUTES", None)
    base = Config(token="t", prefix="!", db_path="bot.db", log_level="INFO", status_activity="x", owner_id=None)
    assert base.heartbeat_silence_minutes == 0


@pytest.mark.asyncio
async def test_cog_load_disabled_by_default() -> None:
    cog = _cog(silence=0)
    await cog.cog_load()
    await cog.cog_unload()
