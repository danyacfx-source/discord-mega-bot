"""Сервис напоминаний."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.core.base import BaseService

if TYPE_CHECKING:
    from app.db.reminders_repository import RemindersRepository


class ReminderService(BaseService):
    repo: RemindersRepository

    def __init__(self, repo: RemindersRepository) -> None:
        super().__init__(repo)

    async def schedule(self, user_id: int, guild_id: int | None, channel_id: int | None, message: str, remind_at: datetime) -> int:
        if remind_at <= datetime.now(remind_at.tzinfo):
            raise ValueError("Время уже наступило")
        return await self._repo.add(user_id, guild_id, channel_id, message, remind_at)

    async def due_up_to(self, moment: datetime) -> list[dict[str, Any]]:
        return await self._repo.due_up_to(moment)

    async def cancel(self, user_id: int, reminder_id: int) -> bool:
        return await self._repo.cancel(user_id, reminder_id)

    async def cancel_all(self, user_id: int) -> int:
        return await self._repo.cancel_all(user_id)

    async def active_for_user(self, user_id: int) -> list[dict[str, Any]]:
        return await self._repo.active_for_user(user_id)

    async def count_for_user(self, user_id: int) -> int:
        return await self._repo.count_for_user(user_id)

    async def mark_done(self, reminder_id: int) -> None:
        await self._repo.deactivate(reminder_id)
