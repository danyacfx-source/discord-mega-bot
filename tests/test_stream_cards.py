"""Карточки стримов: сессия в KV (пик/сброс) и embed-построители."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.cogs.streams.stream_cards import _duration, live_card, offline_card
from app.services.stream_session import StreamSessionStore


class FakeKv:
    """Дак-тайп KvRepository на словаре для юнит-тестов сессии."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str, default: str | None = None) -> str | None:
        return self.data.get(key, default)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None


# Один и тот же started_at для всех поллингов одного «стрима» — иначе
# capture() посчитает каждый вызов новым стримом (часы идут, now() растёт).
_SAME_STREAM_STARTED = "2026-01-01T20:00:00+00:00"


def _status(**overrides):
    status = {
        "title": "Вечерний стрим",
        "viewers": 100,
        "category": "Just Chatting",
        "started_at": _SAME_STREAM_STARTED,
        "thumbnail": "https://static.example/preview.png",
    }
    status.update(overrides)
    return status


@pytest.mark.asyncio
async def test_session_accumulates_peak_and_keeps_metadata():
    store = StreamSessionStore(FakeKv(), "stream:session:test")

    first = await store.capture(_status(viewers=100), url="https://example/ch")
    assert first["peak"] == 100 and first["url"] == "https://example/ch"

    second = await store.capture(_status(viewers=70))
    assert second["peak"] == 100, "пик не должен падать при просадке зрителей"

    third = await store.capture(_status(viewers=250))
    assert third["peak"] == 250

    loaded = await store.load()
    assert loaded is not None and loaded["title"] == "Вечерний стрим"

    await store.clear()
    assert await store.load() is None


@pytest.mark.asyncio
async def test_session_resets_peak_on_new_stream():
    store = StreamSessionStore(FakeKv(), "stream:session:test")
    old_started = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
    await store.capture(_status(viewers=500, started_at=old_started))

    new_started = datetime.now(UTC).isoformat()
    session = await store.capture(_status(viewers=10, started_at=new_started))
    assert session["peak"] == 10, "новый стрим начинает накопление заново"


def test_duration_formats_hours_and_minutes():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    assert _duration(base.isoformat(), base + timedelta(seconds=309)) == "5:09"
    assert _duration(base.isoformat(), base + timedelta(seconds=3909)) == "1:05:09"
    assert _duration(None) is None
    assert _duration("not-a-date") is None


def test_live_card_twitch_has_preview_and_stats():
    started = datetime.now(UTC) - timedelta(minutes=65)
    status = _status(started_at=started.isoformat())
    session = {"peak": 300}
    embed = live_card("twitch", url="https://www.twitch.tv/alice", status=status, session=session)

    assert embed.color.value == 0x9146FF
    assert "alice" not in (embed.title or "")  # платформа в заголовке, линк — в описании
    assert "Вечерний стрим" in (embed.description or "")
    assert embed.image.url == "https://static.example/preview.png"
    fields = {f.name: f.value for f in embed.fields}
    assert fields["👁 Зрители"] == "100"
    assert fields["📈 Пик"] == "300"
    assert fields["⏱ В эфире"] == "1:05:00"
    assert fields["🎮 Категория"] == "Just Chatting"


def test_live_card_vk_without_viewers_or_thumbnail():
    status = {"title": "Трансляция", "description": "расписание", "live": True, "url": "https://live.vkvideo.ru/x"}
    embed = live_card("vk_video", url=status["url"], status=status)
    names = [f.name for f in embed.fields]
    assert "👁 Зрители" not in names
    assert "📝 Описание" in names
    assert embed.image.url is None


def test_offline_card_with_session_shows_results():
    started = datetime.now(UTC) - timedelta(hours=2)
    captured = datetime.now(UTC)
    session = {
        "title": "Вечерний стрим",
        "category": "Just Chatting",
        "started_at": started.isoformat(),
        "captured_at": captured.isoformat(),
        "peak": 450,
        "thumbnail": "https://static.example/final.png",
    }
    embed = offline_card("kick", url="https://kick.com/bob", session=session)

    assert "kick.com/bob" in (embed.description or "")
    fields = {f.name: f.value for f in embed.fields}
    assert fields["📈 Пик зрителей"] == "450"
    assert fields["⏱ Длительность"].startswith("2:0")
    assert embed.image.url == "https://static.example/final.png"
    assert embed.color.value == 0x272D3A


def test_offline_card_without_session_is_neutral():
    embed = offline_card("twitch", url="https://www.twitch.tv/alice", session=None)
    assert "офлайн" in (embed.description or "").lower()
    assert not embed.fields


def test_offline_card_shows_vod_link_even_without_session():
    embed = offline_card(
        "twitch", url="https://www.twitch.tv/alice", session=None,
        vod_url="https://www.twitch.tv/videos/123",
    )
    fields = {f.name: f.value for f in embed.fields}
    assert fields["📼 Запись"] == "[Посмотреть запись](https://www.twitch.tv/videos/123)"


def test_offline_card_without_vod_has_no_vod_field():
    embed = offline_card("twitch", url="https://www.twitch.tv/alice", session=None)
    assert "📼 Запись" not in [f.name for f in embed.fields]


@pytest.mark.asyncio
async def test_session_keeps_user_id_for_vod_lookup():
    store = StreamSessionStore(FakeKv(), "stream:session:test")
    session = await store.capture(_status(user_id="745201"), url="https://example/ch")
    assert session["user_id"] == "745201"


def test_offline_card_shows_top_talkers_field():
    session = {"title": "Вечерний стрим", "peak": 100, "started_at": _SAME_STREAM_STARTED}
    card = offline_card(
        "kick",
        url="https://kick.com/x",
        session=session,
        top_talkers=[{"name": "vasya", "count": 42}, {"name": "petya", "count": 17}],
    )
    field = next(f for f in card.fields if f.name == "💬 Говорили в чате")
    assert "vasya" in field.value and "42" in field.value
    assert "petya" in field.value and "17" in field.value


def test_offline_card_without_talkers_has_no_field():
    session = {"title": "Вечерний стрим", "peak": 100, "started_at": _SAME_STREAM_STARTED}
    card = offline_card("kick", url="https://kick.com/x", session=session)
    assert not any(f.name == "💬 Говорили в чате" for f in card.fields)
