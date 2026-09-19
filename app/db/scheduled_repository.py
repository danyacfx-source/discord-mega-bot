"""Репозиторий отложенных сообщений (планировщик)."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.db.base_repository import BaseRepository

if TYPE_CHECKING:
    from datetime import datetime


class ScheduledRepository(BaseRepository):
    async def create(
        self, guild_id: int, channel_id: int, author_id: int, content: str, embed_json: str, send_at: datetime
    ) -> int:
        cursor = await self.db.execute(
            "INSERT INTO scheduled_messages (guild_id, channel_id, author_id, content, embed_json, send_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, author_id, content, embed_json, send_at.isoformat(), _now_iso()),
        )
        return cursor.lastrowid

    async def get(self, scheduled_id: int) -> dict[str, Any] | None:
        row = await self.db.fetchone("SELECT * FROM scheduled_messages WHERE id = ?", (scheduled_id,))
        return dict(row) if row else None

    async def due_up_to(self, moment: datetime) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM scheduled_messages WHERE done = 0 AND send_at <= ? ORDER BY send_at", (moment.isoformat(),)
        )
        return [dict(row) for row in rows]

    async def upcoming(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM scheduled_messages WHERE done = 0 ORDER BY send_at LIMIT ?", (limit,)
        )
        return [dict(row) for row in rows]

    async def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT * FROM scheduled_messages ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in rows]

    async def delete(self, scheduled_id: int) -> bool:
        cursor = await self.db.execute("DELETE FROM scheduled_messages WHERE id = ?", (scheduled_id,))
        return cursor.rowcount > 0

    async def mark_done(self, scheduled_id: int) -> None:
        await self.db.execute("UPDATE scheduled_messages SET done = 1 WHERE id = ?", (scheduled_id,))


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
