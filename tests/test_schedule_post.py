"""Тесты авто-поста расписания: дедуп по сегментам, часовые ворота, отказоустойчивость."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.cogs.streams.schedule_post import SchedulePostCog
from app.config import Config


def _config(**overrides) -> Config:
    config = Config(
        token="x",
        prefix="!",
        db_path="bot.db",
        log_level="ERROR",
        status_activity="s",
        owner_id=None,
        twitch_channels=("alice",),
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


def _segment(minutes_from_now: int, title: str = "Эфир") -> dict:
    start = datetime.now(UTC) + timedelta(minutes=minutes_from_now)
    return {
        "start_time": start,
        "end_time": start + timedelta(hours=3),
        "title": title,
        "url": f"https://twitch.tv/schedule?d={minutes_from_now}",
        "category": "Just Chatting",
    }


def _cog(config=None, kv=None, schedule=None, channel=None) -> SchedulePostCog:
    config = config or _config(twitch_schedule_channel_id=555, schedule_post_hour=-1)
    kv = kv or _kv()
    if callable(schedule):
        twitch = SimpleNamespace(schedule=AsyncMock(side_effect=schedule))
    else:
        value = schedule if schedule is not None else [_segment(60)]
        twitch = SimpleNamespace(schedule=AsyncMock(return_value=value))
    bot = SimpleNamespace(
        config=config,
        get_channel=lambda cid: channel if cid == 555 else None,
    )
    return SchedulePostCog(bot, twitch, kv)  # type: ignore[arg-type]


def _channel() -> SimpleNamespace:
    return SimpleNamespace(id=555, send=AsyncMock())


@pytest.mark.asyncio
async def test_posts_new_segments_once() -> None:
    channel = _channel()
    kv = _kv()
    cog = _cog(kv=kv, channel=channel, schedule=[_segment(60, "Первый")])

    await cog._tick()
    await cog._tick()  # тот же сегмент уже анонсирован

    channel.send.assert_awaited_once()
    embed = channel.send.await_args.kwargs["embed"]
    assert "Первый" in embed.description
    assert len(kv._data) == 1


@pytest.mark.asyncio
async def test_posts_only_fresh_segments() -> None:
    old, new = _segment(30, "Старый"), _segment(90, "Новый")
    kv = _kv({f"schedpost:alice:{old['start_time'].isoformat()}": "1"})
    channel = _channel()
    cog = _cog(kv=kv, channel=channel, schedule=[old, new])

    await cog._tick()

    channel.send.assert_awaited_once()
    embed = channel.send.await_args.kwargs["embed"]
    assert "Новый" in embed.description
    assert "Старый" not in embed.description
    assert len(kv._data) == 2


@pytest.mark.asyncio
async def test_skips_when_schedule_unchanged() -> None:
    seg = _segment(60, "Уже был")
    kv = _kv({f"schedpost:alice:{seg['start_time'].isoformat()}": "1"})
    channel = _channel()
    cog = _cog(kv=kv, channel=channel, schedule=[seg])

    await cog._tick()

    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_without_channel_id() -> None:
    cog = _cog(config=_config(twitch_schedule_channel_id=None), channel=_channel())
    await cog._tick()
    assert cog.twitch.schedule.await_count == 0


@pytest.mark.asyncio
async def test_hour_gate_skips_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo

    # сейчас не 21-й час по Москве — часовые ворота должны закрыть цикл
    fixed = dt(2026, 10, 2, 10, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    import app.cogs.streams.schedule_post as mod

    real_now = mod.datetime.now

    class _FixedDateTime(dt):
        @classmethod
        def now(cls, tz=None):
            if tz is not None and getattr(tz, "key", "") == "Europe/Moscow":
                return fixed
            return real_now(tz)

    cog = _cog(config=_config(twitch_schedule_channel_id=555, schedule_post_hour=21))
    monkeypatch.setattr(mod, "datetime", _FixedDateTime)

    await cog._tick()
    assert cog.twitch.schedule.await_count == 0


@pytest.mark.asyncio
async def test_schedule_error_is_swallowed() -> None:
    channel = _channel()

    async def boom(login: str):
        raise RuntimeError("api down")

    cog = _cog(channel=channel, schedule=boom)
    await cog._tick()  # не должно упасть
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_channel_is_noop() -> None:
    cog = _cog(channel=None, schedule=[_segment(60)])
    await cog._tick()
    cog.twitch.schedule.assert_not_awaited()
