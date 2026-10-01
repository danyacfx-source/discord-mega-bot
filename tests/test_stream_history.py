"""Тренд зрителей и спарклайн из истории сэмплов (KV)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.cogs.streams.stream_cards import live_card
from app.services.stream_session import StreamSessionStore
from app.utils.stream_history import sparkline, trend


class FakeKv:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str, default: str | None = None) -> str | None:
        return self.data.get(key, default)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None


def _sample(minutes_ago: int, viewers: int, now: datetime | None = None) -> dict:
    moment = (now or datetime.now(UTC)) - timedelta(minutes=minutes_ago)
    return {"t": moment.isoformat(), "v": viewers}


def test_trend_compares_within_window():
    now = datetime.now(UTC)
    history = [_sample(20, 100, now), _sample(10, 120, now), _sample(0, 150, now)]
    assert trend(history, minutes=10) == 30, "сравниваем с сэмплом ровно 10 минут назад"

    history = [_sample(5, 100, now), _sample(0, 90, now)]
    assert trend(history, minutes=10) is None, "сэмплов старше окна нет"


def test_trend_needs_at_least_two_samples():
    assert trend(None) is None
    assert trend([]) is None
    assert trend([_sample(0, 10)]) is None
    assert trend(["мусор"]) is None


def test_trend_reads_delta_at_window_edge():
    now = datetime.now(UTC)
    history = [_sample(30, 500, now), _sample(15, 300, now), _sample(0, 450, now)]
    # опора — ближайший сэмпл старше 10 минут (15 минут назад): 450 − 300
    assert trend(history, minutes=10) == 150


def test_sparkline_scales_between_min_and_max():
    history = [_sample(i, v) for i, v in [(3, 10), (2, 20), (1, 30), (0, 40)]]
    spark = sparkline(history)
    assert spark is not None
    assert len(spark) == 4
    assert spark[0] == "▁" and spark[-1] == "█"


def test_sparkline_flat_and_sparse():
    flat = [_sample(i, 5) for i in range(3)]
    assert sparkline(flat) == "▁▁▁"
    assert sparkline([_sample(0, 5)]) is None
    assert sparkline(None) is None


@pytest.mark.asyncio
async def test_capture_accumulates_history_and_resets_on_new_stream():
    store = StreamSessionStore(FakeKv(), "stream:session:history")
    base = {"title": "Стрим", "viewers": 0, "started_at": "2026-01-01T20:00:00+00:00"}

    first = await store.capture({**base, "viewers": 100})
    second = await store.capture({**base, "viewers": 130})
    assert len(first["history"]) == 1 and len(second["history"]) == 2
    assert second["history"][-1]["v"] == 130

    third = await store.capture({**base, "viewers": 10, "started_at": "2026-01-01T22:00:00+00:00"})
    assert len(third["history"]) == 1, "новый стрим начинает историю заново"


@pytest.mark.asyncio
async def test_capture_history_is_capped():
    store = StreamSessionStore(FakeKv(), "stream:session:history")
    base = {"title": "Стрим", "started_at": "2026-01-01T20:00:00+00:00"}
    session = {}
    for i in range(70):
        session = await store.capture({**base, "viewers": i})
    assert len(session["history"]) == 60


def test_live_card_shows_trend_and_spark():
    now = datetime.now(UTC)
    history = [
        {"t": (now - timedelta(minutes=10)).isoformat(), "v": 100},
        {"t": now.isoformat(), "v": 145},
    ]
    status = {
        "title": "Вечерний стрим",
        "viewers": 145,
        "started_at": (now - timedelta(minutes=30)).isoformat(),
    }
    embed = live_card(
        "twitch",
        url="https://www.twitch.tv/alice",
        status=status,
        session={"peak": 200, "history": history},
    )
    fields = {f.name: f.value for f in embed.fields}
    assert "📈 Тренд" in fields
    assert "45 ▲ за 10 мин" in fields["📈 Тренд"]
    assert "▁" in fields["📈 Тренд"] or "▄" in fields["📈 Тренд"]


def test_live_card_without_history_has_no_trend_field():
    status = {"title": "Т", "viewers": 10, "started_at": datetime.now(UTC).isoformat()}
    embed = live_card("twitch", url="u", status=status, session={"peak": 10})
    assert "📈 Тренд" not in [f.name for f in embed.fields]
