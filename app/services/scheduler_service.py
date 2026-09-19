"""Сервис отложенных сообщений: создание, доставка, история."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import discord

from app.core import embeds
from app.core.base import BaseService

if TYPE_CHECKING:
    from app.db.scheduled_repository import ScheduledRepository


class ScheduledMessagesService(BaseService):
    repo: ScheduledRepository

    def __init__(self, repo: ScheduledRepository) -> None:
        super().__init__(repo)

    async def create(
        self,
        guild_id: int,
        channel_id: int,
        author_id: int,
        send_at: datetime,
        *,
        content: str = "",
        embed: dict[str, Any] | None = None,
    ) -> int:
        if send_at.tzinfo is None:
            send_at = send_at.replace(tzinfo=UTC)
        if send_at <= datetime.now(UTC):
            raise ValueError("Дата отправки уже наступила")
        embed_json = json.dumps(embed or {}, ensure_ascii=False, separators=(",", ":"))
        return await self._repo.create(guild_id, channel_id, author_id, content[:2000], embed_json, send_at)

    async def upcoming(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self._repo.upcoming(limit)

    async def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self._repo.recent(limit)

    async def get(self, scheduled_id: int) -> dict[str, Any] | None:
        return await self._repo.get(scheduled_id)

    async def delete(self, scheduled_id: int) -> bool:
        return await self._repo.delete(scheduled_id)

    async def due(self, moment: datetime) -> list[dict[str, Any]]:
        return await self._repo.due_up_to(moment)

    async def mark_done(self, scheduled_id: int) -> None:
        await self._repo.mark_done(scheduled_id)

    @staticmethod
    def build_embed(data: dict[str, Any], *, finished: bool = False) -> discord.Embed:
        """Собирает эмбед из JSON-схемы, хранимой в планировщике."""
        raw = {}
        if data.get("embed_json"):
            try:
                raw = json.loads(data["embed_json"]) or {}
            except (TypeError, ValueError):
                raw = {}
        raw = raw if isinstance(raw, dict) else {}
        color = raw.get("color")
        if isinstance(color, str) and color.lower().startswith("#"):
            try:
                color = int(color.lstrip("#"), 16)
            except ValueError:
                color = None
        embed = embeds.info(raw.get("title") or "", raw.get("description") or "")
        if isinstance(color, int):
            embed.color = discord.Color(color)
        image = raw.get("image")
        if image:
            embed.set_image(url=str(image))
        thumbnail = raw.get("thumbnail")
        if thumbnail:
            embed.set_thumbnail(url=str(thumbnail))
        for field in (raw.get("fields") or [])[:25]:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            embed.add_field(
                name=str(field["name"])[:256],
                value=str(field.get("value") or "")[:1024],
                inline=bool(field.get("inline")),
            )
        footer = raw.get("footer")
        if footer:
            embed.set_footer(text=str(footer)[:2048])
        if finished:
            embed.set_footer(text="Отправлено по расписанию")
        return embed
