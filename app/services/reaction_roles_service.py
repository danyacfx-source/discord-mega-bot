"""Сервис reaction-ролей."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.base import BaseService

if TYPE_CHECKING:
    from app.data.reaction_roles_repository import ReactionRolesRepository


class ReactionRolesService(BaseService):
    repo: ReactionRolesRepository

    def __init__(self, repo: ReactionRolesRepository) -> None:
        super().__init__(repo)

    async def add(self, guild_id: int, channel_id: int, message_id: int, role_id: int, emoji: str) -> bool:
        return await self._repo.add(guild_id, channel_id, message_id, role_id, emoji)

    async def remove(self, guild_id: int, message_id: int, emoji: str) -> bool:
        return await self._repo.remove(guild_id, message_id, emoji)

    async def by_message(self, message_id: int) -> list[dict[str, Any]]:
        return await self._repo.by_message(message_id)

    async def list_for_guild(self, guild_id: int) -> list[dict[str, Any]]:
        return await self._repo.list_for_guild(guild_id)

    async def clear_message(self, message_id: int) -> int:
        return await self._repo.clear_message(message_id)
