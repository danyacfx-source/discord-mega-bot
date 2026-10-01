"""Расписание Twitch: разбор сегментов Helix и строка /stream_schedule."""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.cogs.streams.stats import _segment_line
from app.services.twitch_service import _parse_schedule

_NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def _seg(start: str, end: str, title: str = "Эфир", category: str | None = None) -> dict:
    return {
        "start_time": start,
        "end_time": end,
        "title": title,
        "category": {"name": category} if category else None,
        "url": f"https://www.twitch.tv/x/segment/{title}",
    }


def test_parse_schedule_filters_past_and_sorts():
    segments = [
        _seg("2026-10-05T18:00:00Z", "2026-10-05T21:00:00Z", "Пн"),
        _seg("2026-10-03T18:00:00Z", "2026-10-03T21:00:00Z", "Сб"),
        _seg("2026-10-01T18:00:00Z", "2026-10-01T21:00:00Z", "прошёл"),
    ]
    parsed = _parse_schedule(segments, limit=5, now=_NOW)
    assert [p["title"] for p in parsed] == ["Сб", "Пн"], "прошедшие отброшены, будущие по порядку"


def test_parse_schedule_respects_limit_and_skips_garbage():
    segments = [
        "мусор",
        {"start_time": "не-дата"},
        {"start_time": "2026-10-04T10:00:00Z"},  # без end_time — пропуск
        _seg("2026-10-04T10:00:00Z", "2026-10-04T12:00:00Z", "A"),
        _seg("2026-10-06T10:00:00Z", "2026-10-06T12:00:00Z", "B"),
        _seg("2026-10-07T10:00:00Z", "2026-10-07T12:00:00Z", "C"),
    ]
    parsed = _parse_schedule(segments, limit=2, now=_NOW)
    assert [p["title"] for p in parsed] == ["A", "B"], "лимит и пропуск мусора"


def test_segment_line_renders_moscow_time_and_meta():
    (segment,) = _parse_schedule(
        [_seg("2026-10-03T18:00:00Z", "2026-10-03T19:30:00Z", "Вечерний", category="Just Chatting")],
        limit=1,
        now=_NOW,
    )
    line = _segment_line(segment, ZoneInfo("Europe/Moscow"))
    assert "Сб 03.10 21:00" in line, "18:00 UTC = 21:00 по Москве, 3 октября 2026 — суббота"
    assert "Вечерний" in line
    assert "🎮 Just Chatting" in line
    assert "⏱ 1 ч 30 мин" in line
