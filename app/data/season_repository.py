"""Репозиторий сезонной активности (season_points)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.data.base_repository import BaseRepository

if TYPE_CHECKING:
    from app.data.database import Database


class SeasonRepository(BaseRepository):
    def __init__(self, db: "Database") -> None:
        super().__init__(db)

    async def add_message(self, guild_id: int, user_id: int) -> None:
        await self.db.execute(
            "INSERT INTO season_points (guild_id, user_id, points) VALUES (?, ?, 1) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET points = points + 1",
            (guild_id, user_id),
        )

    async def add_points(self, guild_id: int, user_ids: list[int], amount: int = 1) -> None:
        for user_id in user_ids:
            await self.db.execute(
                "INSERT INTO season_points (guild_id, user_id, points) VALUES (?, ?, ?) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET points = points + ?",
                (guild_id, user_id, amount, amount),
            )

    async def leaderboard(self, guild_id: int, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        rows = await self.db.fetchall(
            "SELECT user_id, points FROM season_points WHERE guild_id = ? ORDER BY points DESC LIMIT ?",
            (guild_id, limit),
        )
        return [dict(row) for row in rows]

    async def reset(self, guild_id: int) -> None:
        await self.db.execute("DELETE FROM season_points WHERE guild_id = ?", (guild_id,))