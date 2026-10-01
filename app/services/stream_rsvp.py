"""Анонс стрима в KV: id поста «кто откликнулся» (реакция 🔔)."""
from __future__ import annotations

from app.db.kv_repository import KvRepository


class StreamRsvpStore:
    """Хранит id старт-анонса стрима для команды /stream_rsvp."""

    def __init__(self, repo: KvRepository, key: str) -> None:
        self._repo = repo
        self._key = key

    async def save(self, message_id: int) -> None:
        await self._repo.set(self._key, str(message_id))

    async def message_id(self) -> int | None:
        raw = await self._repo.get(self._key)
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    async def clear(self) -> None:
        await self._repo.delete(self._key)
