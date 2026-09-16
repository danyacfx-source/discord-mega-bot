"""Сервис розыгрышей."""
from __future__ import annotations

import random
from datetime import datetime
from typing import TYPE_CHECKING, Any

import discord

from app.core.base import BaseService

if TYPE_CHECKING:
    from app.data.giveaways_repository import GiveawaysRepository


class GiveawayService(BaseService):
    repo: GiveawaysRepository

    def __init__(self, repo: GiveawaysRepository) -> None:
        super().__init__(repo)

    async def create(
        self, guild_id: int, channel_id: int, author_id: int, prize: str, winners: int, ends_at: datetime, min_days: int = 0
    ) -> int:
        if winners < 1:
            raise ValueError("Минимум один победитель")
        if ends_at <= datetime.now(ends_at.tzinfo):
            raise ValueError("Дата окончания уже наступила")
        return await self._repo.create(guild_id, channel_id, author_id, prize, winners, ends_at, max(0, min_days))

    async def bind_message(self, giveaway_id: int, message_id: int) -> None:
        await self._repo.set_message_id(giveaway_id, message_id)

    async def get_by_message(self, message_id: int) -> dict[str, Any] | None:
        return await self._repo.get_by_message(message_id)

    async def expired(self, moment: datetime) -> list[dict[str, Any]]:
        return await self._repo.active_expired(moment)

    async def active_with_message(self) -> list[dict[str, Any]]:
        return await self._repo.active_with_message()

    async def embed(self, giveaway: dict[str, Any]) -> discord.Embed:
        from datetime import datetime

        from app.core import embeds
        from app.utils.format import relative

        entries = await self._repo.entries(giveaway["id"])
        embed = embeds.info("🎉 Розыгрыш", giveaway["prize"])
        embed.add_field(name="Участников", value=str(len(entries)), inline=True)
        embed.add_field(name="Победителей", value=str(giveaway["winners"]), inline=True)
        embed.add_field(name="ID", value=str(giveaway["id"]), inline=True)
        min_days = giveaway.get("min_days", 0)
        if min_days > 0:
            embed.add_field(name="Мин. дней на сервере", value=str(min_days), inline=True)
        if giveaway["active"]:
            embed.set_footer(text=f"Окончание: {relative(datetime.fromisoformat(giveaway['ends_at']))}")
        else:
            embed.set_footer(text="Розыгрыш завершён")
        return embed

    async def join(self, giveaway_id: int, user_id: int) -> bool:
        return await self._repo.add_entry(giveaway_id, user_id)

    async def entries(self, giveaway_id: int) -> list[int]:
        return await self._repo.entries(giveaway_id)

    async def finish(self, giveaway_id: int) -> None:
        await self._repo.end(giveaway_id)

    @staticmethod
    def draw(entries: list[int], winners: int) -> list[int]:
        if not entries:
            return []
        pool = list(entries)
        random.shuffle(pool)
        return pool[:winners]
