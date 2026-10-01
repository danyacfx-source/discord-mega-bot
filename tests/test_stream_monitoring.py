"""Мониторинг стримов: дедуп ошибок поллинга и алерт о прерванном эфире."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from app.cogs.streams.abort_alert import abort_alert
from app.cogs.streams.poll_guard import PollGuard


def _fail_once(guard: PollGuard, key: str = "twitch:a") -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        guard.fail(key, "Twitch: ошибка проверки канала a")


def test_guard_first_error_has_stack_then_dedupes(caplog):
    guard = PollGuard()
    with caplog.at_level(logging.DEBUG, logger="bot.cogs"):
        _fail_once(guard)
        _fail_once(guard)
        _fail_once(guard)
        _fail_once(guard)  # 4-я подряд — не логируется до порога 30

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(errors) == 1, "первая ошибка серии — одна, со стеком"
    assert errors[0].exc_info is not None
    assert len(warnings) == 2, "повторы (2-й и 3-й) — короткие warning'и"
    assert guard.failures == {"twitch:a": 4}


def test_guard_ok_recovers_after_three_failures(caplog):
    guard = PollGuard()
    with caplog.at_level(logging.INFO, logger="bot.cogs"):
        for _ in range(3):
            _fail_once(guard)
        guard.ok("twitch:a")

    infos = [r for r in caplog.records if r.levelno == logging.INFO]
    assert any("восстановился" in r.getMessage() for r in infos)
    assert guard.failures == {}


def test_guard_ok_is_quiet_after_single_error(caplog):
    guard = PollGuard()
    with caplog.at_level(logging.INFO, logger="bot.cogs"):
        _fail_once(guard)
        guard.ok("twitch:a")
    assert not [r for r in caplog.records if r.levelno == logging.INFO]
    assert guard.failures == {}


class FakeChannel:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list = []
        self.fail = fail

    async def send(self, content: str | None = None, *, embed: discord.Embed | None = None) -> None:
        if self.fail:
            raise discord.HTTPException(SimpleNamespace(status=403, reason="Forbidden"), "no perms")
        self.sent.append(embed)


def _session(minutes: float) -> dict:
    started = datetime.now(UTC) - timedelta(minutes=minutes)
    return {
        "title": "Вечерний стрим",
        "started_at": started.isoformat(),
        "captured_at": datetime.now(UTC).isoformat(),
    }


@pytest.mark.asyncio
async def test_abort_alert_fires_for_short_stream():
    channel = FakeChannel()
    await abort_alert(
        channel, session=_session(3), label="Twitch", url="https://twitch.tv/a", threshold_minutes=10
    )
    assert len(channel.sent) == 1
    embed = channel.sent[0]
    assert embed.title == "⚠️ Стрим прерван"
    assert "Вечерний стрим" in (embed.description or "")
    fields = {f.name: f.value for f in embed.fields}
    assert fields["⏱ Длился"] == "3 мин"


@pytest.mark.asyncio
async def test_abort_alert_silent_for_normal_stream_or_disabled():
    channel = FakeChannel()
    await abort_alert(
        channel, session=_session(120), label="Twitch", url="u", threshold_minutes=10
    )
    await abort_alert(
        channel, session=_session(3), label="Twitch", url="u", threshold_minutes=0
    )
    await abort_alert(channel, session=None, label="Twitch", url="u", threshold_minutes=10)
    await abort_alert(
        channel,
        session={"title": "без времени"},
        label="Twitch",
        url="u",
        threshold_minutes=10,
    )
    assert channel.sent == []


@pytest.mark.asyncio
async def test_abort_alert_survives_send_failure():
    channel = FakeChannel(fail=True)
    await abort_alert(
        channel, session=_session(1), label="Kick", url="u", threshold_minutes=10
    )  # не должно поднять исключение
