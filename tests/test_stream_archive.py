"""Архив эфиров: append/trim, печать seal_archive, агрегаты /stream_stats."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.cogs.streams.archive import needs_seal, seal_archive
from app.cogs.streams.stats import _entry_line, _fmt_minutes, _is_fresh, _summary
from app.services.stream_archive import ARCHIVE_LIMIT, StreamArchiveStore


class FakeKv:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str, default: str | None = None) -> str | None:
        return self.data.get(key, default)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None


def _entry(i: int, *, days_ago: float = 0.0) -> dict:
    ended = datetime.now(UTC) - timedelta(days=days_ago)
    return {
        "platform": "twitch",
        "title": f"Стрим {i}",
        "started_at": (ended - timedelta(hours=2)).isoformat(),
        "ended_at": ended.isoformat(),
        "seconds": 7200,
        "peak": 10 + i,
    }


def _session(**over) -> dict:
    started = datetime.now(UTC) - timedelta(hours=2, minutes=30)
    base = {
        "title": "Вечерний стрим",
        "category": "Just Chatting",
        "started_at": started.isoformat(),
        "captured_at": (started + timedelta(hours=2, minutes=30)).isoformat(),
        "peak": 120,
        "viewers": 90,
        "url": "https://www.twitch.tv/x",
    }
    base.update(over)
    return base


def test_append_keeps_newest_first_and_caps() -> None:
    import asyncio

    async def run() -> None:
        store = StreamArchiveStore(FakeKv(), "stream:archive:test")
        for i in range(60):
            await store.append(_entry(i))
        entries = await store.list()
        assert len(entries) == ARCHIVE_LIMIT
        assert entries[0]["title"] == "Стрим 59", "новые сводки впереди"

    asyncio.run(run())


def test_append_drops_expired_entries() -> None:
    import asyncio

    async def run() -> None:
        store = StreamArchiveStore(FakeKv(), "stream:archive:test")
        await store.append(_entry(1, days_ago=100))  # старше 90 дней
        assert await store.list() == [], "протухшая сводка не хранится"
        await store.append(_entry(2))
        entries = await store.list()
        assert [e["title"] for e in entries] == ["Стрим 2"]

    asyncio.run(run())


def test_trim_removes_stale_without_new_streams() -> None:
    import asyncio

    async def run() -> None:
        kv = FakeKv()
        store = StreamArchiveStore(kv, "stream:archive:test")
        await store.append(_entry(1, days_ago=10))
        await store.append(_entry(2, days_ago=200))
        entries = await store.list()
        assert len(entries) == 1, "append уже отсёк старое"
        await store.trim(max_age_days=5)
        assert await store.list() == [], "trim чистит и без новых эфиров"

    asyncio.run(run())


def test_seal_archive_writes_summary_and_is_idempotent() -> None:
    import asyncio

    async def run() -> None:
        store = StreamArchiveStore(FakeKv(), "stream:archive:test")
        session = _session()
        assert await needs_seal(store, session) is True
        assert await seal_archive(store, session, platform="twitch", url="u", vod_url="v") is True

        entries = await store.list()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["platform"] == "twitch"
        assert entry["peak"] == 120
        assert entry["seconds"] == 9000, "20:00 → 22:30 = 2,5 часа"
        assert entry["vod"] == "v"
        assert entry["url"] == "u"

        assert await needs_seal(store, session) is False, "повторный офлайн не дублирует"
        assert await seal_archive(store, session, platform="twitch") is False
        assert len(await store.list()) == 1

    asyncio.run(run())


def test_seal_archive_skips_empty_sessions() -> None:
    import asyncio

    async def run() -> None:
        store = StreamArchiveStore(FakeKv(), "stream:archive:test")
        assert await seal_archive(store, None, platform="twitch") is False
        assert await seal_archive(store, {}, platform="twitch") is False
        assert await seal_archive(store, {"title": "x"}, platform="twitch") is False
        assert await store.list() == []

    asyncio.run(run())


def test_seal_archive_without_captured_at_uses_now() -> None:
    import asyncio

    async def run() -> None:
        store = StreamArchiveStore(FakeKv(), "stream:archive:test")
        started = datetime.now(UTC) - timedelta(minutes=30)
        assert await seal_archive(store, {"started_at": started.isoformat(), "peak": 5}, platform="kick")
        (entry,) = await store.list()
        assert entry["seconds"] >= 1799, "без captured_at длительность считается до «сейчас»"

    asyncio.run(run())


def test_summary_aggregates() -> None:
    assert _summary([]) == "Завершённых эфиров пока нет."
    text = _summary([{"peak": 10, "seconds": 3600}, {"peak": 30, "seconds": 7200}])
    assert "Всего эфиров: **2**" in text
    assert "Средний пик: **20**" in text
    assert "Лучший пик: **30**" in text
    assert "Суммарно в эфире: **3 ч**" in text


def test_entry_line_formats_date_platform_and_links() -> None:
    from zoneinfo import ZoneInfo

    entry = {
        "platform": "twitch",
        "title": "Тестовый эфир",
        "url": "https://twitch.tv/x",
        "vod": "https://twitch.tv/x/clip",
        "ended_at": "2026-01-01T20:00:00+00:00",
        "seconds": 5400,
        "peak": 42,
    }
    line = _entry_line(entry, ZoneInfo("Europe/Moscow"))
    assert "01.01 23:00" in line, "время в московском часовом поясе"
    assert "Twitch" in line
    assert "Тестовый эфир" in line
    assert "📈 42" in line
    assert "⏱ 1 ч 30 мин" in line
    assert "📼" in line


def test_fmt_minutes() -> None:
    assert _fmt_minutes(90) == "1 мин"
    assert _fmt_minutes(3660) == "1 ч 01 мин"
    assert _fmt_minutes(0) == "0 мин"


def test_is_fresh_window() -> None:
    now = datetime.now(UTC)
    fresh = _session(captured_at=now.isoformat())
    stale = _session(captured_at=(now - timedelta(minutes=20)).isoformat())
    assert _is_fresh(fresh, 180) is True
    assert _is_fresh(stale, 180) is False
    assert _is_fresh(None, 180) is False
    assert _is_fresh({}, 180) is False
