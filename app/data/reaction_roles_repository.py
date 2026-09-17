"""Репозиторий reaction-ролей."""
from __future__ import annotations

from typing import Any

from app.data.base_repository import BaseRepository


class ReactionRolesRepository(BaseRepository):
    async def add(self, guild_id: int, channel_id: int, message_id: int, role_id: int, emoji: str) -> bool:
        cursor = await self.db.execute(
            "INSERT OR IGNORE INTO reaction_roles (guild_id, channel_id, message_id, role_id, emoji) "
            "VALUES (?, ?, ?, ?, ?)",
            (guild_id, channel_id, message_id, role_id, emoji),
        )
        return cursor.rowcount > 0

    async def remove(self, guild_id: int, message_id: int, emoji: str) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji = ?",
            (guild_id, message_id, emoji),
        )
        return cursor.rowcount > 0

    async def by_message(self, message_id: int) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM reaction_roles WHERE message_id = ?", (message_id,)
        )
        return [dict(row) for row in rows]

    async def list_for_guild(self, guild_id: int) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM reaction_roles WHERE guild_id = ? ORDER BY message_id", (guild_id,)
        )
        return [dict(row) for row in rows]

    async def clear_message(self, message_id: int) -> int:
        cursor = await self.db.execute("DELETE FROM reaction_roles WHERE message_id = ?", (message_id,))
        return cursor.rowcount