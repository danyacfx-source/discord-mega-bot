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


def _cog(
    *,
    guilds: list | None = None,
    silence: int = 30,
    bot_log: int | None = None,
    settings_get=None,
    disk_mb: int = 0,
    latency: float = 0.0,
    ws_latency: float = 0.05,
    db_path: str = "data/bot.db",
) -> HeartbeatCog:
    config = SimpleNamespace(
        heartbeat_silence_minutes=silence,
        bot_log_channel_id=bot_log,
        disk_alert_mb=disk_mb,
        latency_alert_seconds=latency,
        db_path=db_path,
    )
    bot = SimpleNamespace(config=config, guilds=list(guilds or []), latency=ws_latency)
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
    assert cog._enabled() is False


def test_enabled_gates() -> None:
    assert _cog(silence=0, disk_mb=0, latency=0.0)._enabled() is False
    assert _cog(silence=0, disk_mb=100)._enabled() is True
    assert _cog(silence=0, latency=1.5)._enabled() is True
    assert _cog(silence=5)._enabled() is True


@pytest.mark.asyncio
async def test_disk_alert_fires_once_and_rearms(monkeypatch) -> None:
    import app.cogs.monitoring.heartbeat as hb

    cog = _cog(silence=0, disk_mb=1000)
    cog._log_targets = AsyncMock(return_value=[])
    monkeypatch.setattr(hb.shutil, "disk_usage", lambda p: SimpleNamespace(free=100 * 1024**2))
    await cog._tick()
    assert cog._log_targets.await_count == 1
    assert cog._disk_alerted is True
    await cog._tick()
    assert cog._log_targets.await_count == 1  # не дублируем
    # Места стало хватать — детектор перевзводится, затем срабатывает снова.
    monkeypatch.setattr(hb.shutil, "disk_usage", lambda p: SimpleNamespace(free=500 * 1024**3))
    await cog._tick()
    assert cog._disk_alerted is False
    monkeypatch.setattr(hb.shutil, "disk_usage", lambda p: SimpleNamespace(free=100 * 1024**2))
    await cog._tick()
    assert cog._log_targets.await_count == 2


@pytest.mark.asyncio
async def test_disk_alert_disabled_by_zero() -> None:
    cog = _cog(silence=0, disk_mb=0)
    cog._log_targets = AsyncMock(return_value=[])
    assert cog._disk_check() is None
    await cog._tick()
    assert cog._log_targets.await_count == 0


@pytest.mark.asyncio
async def test_latency_alert_requires_strikes(monkeypatch) -> None:
    cog = _cog(silence=0, latency=0.5, ws_latency=1.0)
    cog._log_targets = AsyncMock(return_value=[])
    await cog._tick()
    await cog._tick()
    assert cog._log_targets.await_count == 0  # пока 2 удара из 3
    await cog._tick()
    assert cog._log_targets.await_count == 1  # третий удар подряд
    assert cog._latency_alerted is True
    await cog._tick()
    assert cog._log_targets.await_count == 1  # не дублируем
    # Шлюз ожил — перевзвод; порог пробивается снова только после 3 тиков.
    cog.bot.latency = 0.1
    await cog._tick()
    assert cog._latency_alerted is False
    cog.bot.latency = 1.0
    await cog._tick()
    await cog._tick()
    assert cog._log_targets.await_count == 1
    await cog._tick()
    assert cog._log_targets.await_count == 2


@pytest.mark.asyncio
async def test_latency_alert_ignores_not_ready_gateway() -> None:
    cog = _cog(silence=0, latency=0.5, ws_latency=-1.0)
    cog._log_targets = AsyncMock(return_value=[])
    await cog._tick()
    assert cog._log_targets.await_count == 0
    assert cog._latency_strikes == 0


@pytest.mark.asyncio
async def test_silence_and_disk_report_together(monkeypatch) -> None:
    """Обе проблемы в одном тике — один эмбед со всеми причинами."""
    import app.cogs.monitoring.heartbeat as hb

    channel = _Chan(7)
    guild = _Guild(1, [channel])

    async def get(guild_id: int) -> dict:
        return {"bot_log_channel_id": 7}

    cog = _cog(guilds=[guild], silence=30, disk_mb=1000, settings_get=get)
    cog._last_activity = datetime.now(UTC) - timedelta(minutes=40)
    monkeypatch.setattr(hb.shutil, "disk_usage", lambda p: SimpleNamespace(free=100 * 1024**2))
    with patch("app.cogs.monitoring.heartbeat.discord.TextChannel", _Chan):
        await cog._tick()
    channel.send.assert_awaited_once()
    embed = channel.send.await_args.kwargs["embed"]
    assert "нет сообщений" in (embed.description or "")
    assert "на диске" in (embed.description or "")
    assert cog._alerted is True
