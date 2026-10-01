"""Онлайн-сессии зрителей Kick: touch/sweep в KV."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.services.viewer_sessions import ViewerSessionStore


class FakeKv:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str, default: str | None = None) -> str | None:
        return self.data.get(key, default)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None


@pytest.mark.asyncio
async def test_touch_opens_session_and_extends_same_user():
    store = ViewerSessionStore(FakeKv())
    first = await store.touch("Alice")
    assert first is not None and first["messages"] == 1

    second = await store.touch("alice")  # тот же ключ (casefold)
    assert second is not None
    assert second["messages"] == 2, "одна сессия на зрителя, счётчик сообщений растёт"
    assert second["name"] == "Alice", "оригинальное имя сохраняется"

    active = await store.active()
    assert list(active) == ["alice"]


@pytest.mark.asyncio
async def test_touch_blank_username_is_noop():
    store = ViewerSessionStore(FakeKv())
    assert await store.touch("") is None
    assert await store.touch("   ") is None
    assert await store.active() == {}


@pytest.mark.asyncio
async def test_sweep_closes_stale_sessions_only():
    kv = FakeKv()
    store = ViewerSessionStore(kv)
    await store.touch("old_user")
    await store.touch("fresh_user")

    # Прямо старим last_seen у old_user, чтобы не спать 5 минут в тесте.
    key = "stream:viewers:kick"
    data = json.loads(kv.data[key])
    stale = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    data["active"]["old_user"]["last_seen"] = stale
    kv.data[key] = json.dumps(data, ensure_ascii=False)

    closed = await store.sweep()
    assert [s["name"] for s in closed] == ["old_user"]
    assert closed[0].get("closed_at"), "закрытая сессия получает closed_at"

    active = await store.active()
    assert list(active) == ["fresh_user"], "свежая сессия остаётся активной"

    history = await store.history()
    assert len(history) == 1 and history[0]["name"] == "old_user"


@pytest.mark.asyncio
async def test_sweep_noop_when_everyone_fresh():
    store = ViewerSessionStore(FakeKv())
    await store.touch("a")
    await store.touch("b")
    assert await store.sweep() == []
    assert len(await store.active()) == 2


@pytest.mark.asyncio
async def test_history_is_capped():
    kv = FakeKv()
    store = ViewerSessionStore(kv)
    for i in range(60):
        await store.touch(f"user{i}")
        data = json.loads(kv.data["stream:viewers:kick"])
        past = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        data["active"][f"user{i}"]["last_seen"] = past
        kv.data["stream:viewers:kick"] = json.dumps(data, ensure_ascii=False)
        await store.sweep()
    assert len(await store.history()) == 50


@pytest.mark.asyncio
async def test_tally_counts_per_stream_and_resets_on_new_one():
    store = ViewerSessionStore(FakeKv())
    await store.touch("alice", stream_id="s1")
    await store.touch("bob", stream_id="s1")
    await store.touch("alice", stream_id="s1")

    top = await store.top_talkers()
    assert top[0] == {"name": "alice", "count": 2}, "топ по числу сообщений за эфир"
    assert top[1]["count"] == 1

    await store.touch("alice", stream_id="s1")
    assert (await store.top_talkers())[0]["count"] == 3, "тот же эфир — счёт продолжается"

    await store.touch("carol", stream_id="s2")
    top = await store.top_talkers()
    assert [t["name"] for t in top] == ["carol"], "новый стрим обнуляет топ"


@pytest.mark.asyncio
async def test_tally_without_stream_id_accumulates():
    store = ViewerSessionStore(FakeKv())
    await store.touch("a")
    await store.touch("a")
    top = await store.top_talkers()
    assert top == [{"name": "a", "count": 2}]


@pytest.mark.asyncio
async def test_top_talkers_limit_and_casefold_dedup():
    store = ViewerSessionStore(FakeKv())
    await store.touch("Alice", stream_id="s")
    await store.touch("alice", stream_id="s")
    for i in range(6):
        await store.touch(f"user{i}", stream_id="s")

    top = await store.top_talkers(limit=3)
    assert len(top) == 3
    assert top[0]["name"] == "alice" and top[0]["count"] == 2, "разный регистр — один зритель"
