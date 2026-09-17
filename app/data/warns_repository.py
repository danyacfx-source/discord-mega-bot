"""Репозиторий предупреждений (warn-система)."""
from __future__ import annotations

from app.data.base_repository import BaseRepository

ORDERED = "ORDER BY id DESC"


class WarnsRepository(BaseRepository):
    async def add(self, guild_id: int, user_id: int, moderator_id: int, reason: str, created_at: str) -> int:
        cursor = await self.db.execute(
            "INSERT INTO warns (guild_id, user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, moderator_id, reason, created_at),
        )
        return cursor.lastrowid

    async def list_for_user(self, guild_id: int, user_id: int, limit: int = 50) -> list:
        rows = await self.db.fetchall(
            f"SELECT id, reason, moderator_id, created_at FROM warns WHERE guild_id = ? AND user_id = ? "
            f"ORDER BY id DESC LIMIT ?",
            (guild_id, user_id, limit),
        )
        return [dict(row) for row in rows]

    async def count_for_user(self, guild_id: int, user_id: int) -> int:
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS total FROM warns WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        return int(row["total"]) if row else 0

    async def total_for_guild(self, guild_id: int) -> int:
        row = await self.db.fetchone("SELECT COUNT(*) AS total FROM warns WHERE guild_id = ?", (guild_id,))
        return int(row["total"]) if row else 0

    async def clear_for_user(self, guild_id: int, user_id: int) -> int:
        cursor = await self.db.execute("DELETE FROM warns WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
        return cursor.rowcount

    async def delete(self, guild_id: int, warn_id: int) -> bool:
        cursor = await self.db.execute("DELETE FROM warns WHERE id = ? AND guild_id = ?", (warn_id, guild_id))
        return cursor.rowcount > 0