"""Репозиторий напоминаний."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.data.base_repository import BaseRepository

if TYPE_CHECKING:
    from datetime import datetime


class RemindersRepository(BaseRepository):
    async def add(self, user_id: int, guild_id: int | None, channel_id: int | None, message: str, remind_at: datetime) -> int:
        cursor = await self.db.execute(
            "INSERT INTO reminders (user_id, guild_id, channel_id, message, remind_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, guild_id, channel_id, message, remind_at.isoformat(), _now_iso()),
        )
        return cursor.lastrowid

    async def active_for_user(self, user_id: int) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT id, message, remind_at FROM reminders WHERE user_id = ? AND active = 1 ORDER BY remind_at",
            (user_id,),
        )
        return [dict(row) for row in rows]

    async def count_for_user(self, user_id: int) -> int:
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS total FROM reminders WHERE user_id = ? AND active = 1", (user_id,)
        )
        return int(row["total"]) if row else 0

    async def due_up_to(self, moment: datetime) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT id, user_id, guild_id, channel_id, message, remind_at FROM reminders "
            "WHERE active = 1 AND remind_at <= ? ORDER BY remind_at",
            (moment.isoformat(),),
        )
        return [dict(row) for row in rows]

    async def cancel(self, user_id: int, reminder_id: int) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, user_id)
        )
        return cursor.rowcount > 0

    async def cancel_all(self, user_id: int) -> int:
        cursor = await self.db.execute("DELETE FROM reminders WHERE user_id = ? AND active = 1", (user_id,))
        return cursor.rowcount

    async def deactivate(self, reminder_id: int) -> None:
        await self.db.execute("UPDATE reminders SET active = 0 WHERE id = ?", (reminder_id,))


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()