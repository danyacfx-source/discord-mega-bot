"""Сервис сезонной активности."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.base import BaseService
from app.db.season_repository import SeasonRepository

if TYPE_CHECKING:
    from app.db.season_repository import SeasonRepository


class SeasonService(BaseService[SeasonRepository]):
    repo: SeasonRepository

    def __init__(self, repo: SeasonRepository) -> None:
        super().__init__(repo)

    async def add_message(self, guild_id: int, user_id: int) -> None:
        await self._repo.add_message(guild_id, user_id)

    async def add_points(self, guild_id: int, user_ids: list[int], amount: int = 1) -> None:
        if not user_ids:
            return
        await self._repo.add_points(guild_id, user_ids, amount)

    async def leaderboard(self, guild_id: int, limit: int = 10) -> list[dict[str, Any]]:
        return await self._repo.leaderboard(guild_id, limit)

    async def reset(self, guild_id: int) -> None:
        await self._repo.reset(guild_id)
