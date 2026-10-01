"""Тихий режим: STREAM_QUIET_HOURS, часовой пояс и is_quiet()."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from app.cogs.streams.quiet import is_quiet
from app.config import Config, _hour_range

MSK = timezone(timedelta(hours=3))


def _config(window, tz: str = "Europe/Moscow"):
    return Config(
        token="x",
        prefix="!",
        db_path=":",
        log_level="INFO",
        status_activity="",
        owner_id=None,
        stream_quiet_hours=window,
        stream_quiet_tz=tz,
    )


def test_hour_range_parsing():
    assert _hour_range("23-8") == (23, 8)
    assert _hour_range("9-17") == (9, 17)
    assert _hour_range(" 1 - 2 ") == (1, 2)
    assert _hour_range(None) is None
    assert _hour_range("") is None
    assert _hour_range("23") is None
    assert _hour_range("a-b") is None
    assert _hour_range("25-8") is None
    assert _hour_range("8-8") is None, "равные границы — режим выключен"


def test_is_quiet_disabled_without_window():
    assert is_quiet(_config(None)) is False


def test_is_quiet_wraps_midnight():
    config = _config((23, 8))
    assert is_quiet(config, now=datetime(2026, 1, 1, 23, 30)) is True
    assert is_quiet(config, now=datetime(2026, 1, 1, 3, 0)) is True
    assert is_quiet(config, now=datetime(2026, 1, 1, 7, 59)) is True
    assert is_quiet(config, now=datetime(2026, 1, 1, 8, 0)) is False
    assert is_quiet(config, now=datetime(2026, 1, 1, 12, 0)) is False
    assert is_quiet(config, now=datetime(2026, 1, 1, 22, 59)) is False


def test_is_quiet_same_day_window():
    config = _config((9, 17))
    assert is_quiet(config, now=datetime(2026, 1, 1, 9, 0)) is True
    assert is_quiet(config, now=datetime(2026, 1, 1, 16, 59)) is True
    assert is_quiet(config, now=datetime(2026, 1, 1, 17, 0)) is False
    assert is_quiet(config, now=datetime(2026, 1, 1, 5, 0)) is False


def test_is_quiet_converts_aware_datetimes_to_moscow():
    config = _config((23, 8))
    # 21:00 UTC = 00:00 по Москве — внутри ночного окна.
    assert is_quiet(config, now=datetime(2026, 1, 1, 21, 0, tzinfo=UTC)) is True
    # 08:00 UTC = 11:00 по Москве — день, не окно.
    assert is_quiet(config, now=datetime(2026, 1, 1, 8, 0, tzinfo=UTC)) is False

    day = _config((9, 17))
    # 06:00 UTC = 09:00 по Москве — начало дневного окна.
    assert is_quiet(day, now=datetime(2026, 1, 1, 6, 0, tzinfo=UTC)) is True
    # 15:00 UTC = 18:00 по Москве — окно закрыто.
    assert is_quiet(day, now=datetime(2026, 1, 1, 15, 0, tzinfo=UTC)) is False


def test_is_quiet_respects_explicit_tz():
    # Нью-Йорк (UTC−5 зимой): 03:00 UTC = 22:00 накануне — не в окне 23-8.
    config = _config((23, 8), tz="America/New_York")
    assert is_quiet(config, now=datetime(2026, 1, 1, 3, 0, tzinfo=UTC)) is False
    # 06:00 UTC = 01:00 по Нью-Йорку — в окне.
    assert is_quiet(config, now=datetime(2026, 1, 1, 6, 0, tzinfo=UTC)) is True


def test_is_quiet_invalid_tz_falls_back_to_utc(caplog):
    config = _config((9, 17), tz="Mars/Olympus")
    with caplog.at_level("WARNING", logger="bot.cogs"):
        # 12:00 UTC = 12:00 при фолбэке — внутри окна 9-17.
        assert is_quiet(config, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC)) is True
        assert is_quiet(config, now=datetime(2026, 1, 1, 12, 0, tzinfo=UTC)) is True
    warnings = [r for r in caplog.records if r.levelno == 30]
    assert len(warnings) == 1, "warning о битой зоне — один раз, не на каждый поллинг"


def test_env_parsing_quiet_hours(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.setenv("STREAM_QUIET_HOURS", "0-6")
    assert Config.from_env().stream_quiet_hours == (0, 6)

    monkeypatch.setenv("STREAM_QUIET_HOURS", "мусор")
    assert Config.from_env().stream_quiet_hours is None


def test_env_parsing_quiet_tz_defaults_to_moscow(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "t")
    monkeypatch.delenv("STREAM_QUIET_TZ", raising=False)
    assert Config.from_env().stream_quiet_tz == "Europe/Moscow"

    monkeypatch.setenv("STREAM_QUIET_TZ", "Asia/Yekaterinburg")
    assert Config.from_env().stream_quiet_tz == "Asia/Yekaterinburg"
