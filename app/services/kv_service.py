"""Общий key-value сервис для когов (счётчики дайджеста, starboard, флаги постов)."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.db.kv_repository import KvRepository


class KvService:
    def __init__(self, repo: KvRepository) -> None:
        self._repo = repo

    async def get(self, key: str, default: str | None = None) -> str | None:
        return await self._repo.get(key, default)

    async def set(self, key: str, value: str) -> None:
        await self._repo.set(key, value)

    async def delete(self, key: str) -> bool:
        return await self._repo.delete(key)
