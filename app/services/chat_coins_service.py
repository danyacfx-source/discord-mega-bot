"""Монеты чата стримов: баланс, начисление, списание, лидерборд."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.db.chat_coins_repository import ChatCoinsRepository


class ChatCoinsService:
    def __init__(self, repo: ChatCoinsRepository) -> None:
        self._repo = repo

    async def get(self, platform: str, username: str) -> dict[str, Any] | None:
        return await self._repo.get(platform, username)

    async def add(
        self, platform: str, username: str, display_name: str, amount: int, *, count_message: bool = False
    ) -> int:
        return await self._repo.add(
            platform, username, display_name, amount, count_message=count_message
        )

    async def spend(self, platform: str, username: str, display_name: str, amount: int) -> int | None:
        return await self._repo.spend(platform, username, display_name, amount)

    async def top(self, platform: str, limit: int = 10) -> list[dict[str, Any]]:
        return await self._repo.top(platform, limit)
