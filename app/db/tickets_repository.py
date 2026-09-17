"""Репозиторий тикетов."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.db.base_repository import BaseRepository

if TYPE_CHECKING:
    from datetime import datetime


class TicketsRepository(BaseRepository):
    async def create(self, guild_id: int, channel_id: int, creator_id: int, created_at: datetime) -> int:
        cursor = await self.db.execute(
            "INSERT INTO tickets (guild_id, channel_id, creator_id, created_at) VALUES (?, ?, ?, ?)",
            (guild_id, channel_id, creator_id, created_at.isoformat()),
        )
        return cursor.lastrowid

    async def by_channel(self, channel_id: int) -> dict | None:
        row = await self.db.fetchone("SELECT * FROM tickets WHERE channel_id = ?", (channel_id,))
        return dict(row) if row else None

    async def has_open_by_creator(self, guild_id: int, creator_id: int) -> bool:
        row = await self.db.fetchone(
            "SELECT 1 FROM tickets WHERE guild_id = ? AND creator_id = ? AND status = 'open' LIMIT 1",
            (guild_id, creator_id),
        )
        return row is not None

    async def close(self, ticket_id: int, closed_at: datetime) -> None:
        await self.db.execute(
            "UPDATE tickets SET status = 'closed', closed_at = ? WHERE ticket_id = ?",
            (closed_at.isoformat(), ticket_id),
        )
