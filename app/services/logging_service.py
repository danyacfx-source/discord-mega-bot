"""Сервис логирования событий сервера."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from app.core import embeds

if TYPE_CHECKING:
    from app.core.bot import MegaBot
    from app.services.settings_service import SettingsService

logger = logging.getLogger("bot.services")

_CATEGORY_COLUMNS: dict[str, str] = {
    "bot": "bot_log_channel_id",
    "member": "member_log_channel_id",
    "message": "message_log_channel_id",
    "voice": "voice_log_channel_id",
    "mod": "mod_log_channel_id",
}


class LoggingService:
    def __init__(self, settings: SettingsService, bot: MegaBot) -> None:
        self._settings = settings
        self._bot = bot

    async def target_channel(
        self, guild: discord.Guild, *, category: str | None = None
    ) -> discord.TextChannel | None:
        settings = await self._settings.get(guild.id)
        column = _CATEGORY_COLUMNS.get(category or "")
        channel_id = settings.get(column) if column else None
        if not channel_id:
            channel_id = settings.get("log_channel_id")
        if not channel_id:
            return None
        channel = guild.get_channel(channel_id)
        if channel is not None and isinstance(channel, discord.TextChannel):
            return channel
        try:
            fetched = await guild.fetch_channel(channel_id)
        except discord.HTTPException:
            return None
        return fetched if isinstance(fetched, discord.TextChannel) else None

    async def send_embed(self, guild: discord.Guild, embed: discord.Embed, *, category: str | None = None) -> None:
        channel = await self.target_channel(guild, category=category)
        if channel is None:
            return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.debug("Не удалось записать лог-событие", exc_info=True)

    async def log_event(
        self,
        guild: discord.Guild,
        title: str,
        description: str | None = None,
        *,
        color: discord.Colour | None = None,
        author: discord.Member | discord.User | None = None,
    ) -> None:
        embed = discord.Embed(description=description, color=color or discord.Color.dark_embed())
        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
        embed.title = title
        if author is not None:
            embed.set_footer(text=f"Инициатор: {author} ({author.id})")
        await self.send_embed(guild, embed)

    async def log_mod_action(
        self,
        guild: discord.Guild,
        action: str,
        target: discord.User | discord.Member,
        moderator: discord.Member,
        reason: str = "",
        description: str | None = None,
    ) -> None:
        embed = embeds.info(f"Модерация: {action}", description)
        embed.add_field(name="Нарушитель", value=f"{target.mention} ({target.id})", inline=True)
        embed.add_field(name="Модератор", value=f"{moderator.mention} ({moderator.id})", inline=True)
        if reason:
            embed.add_field(name="Причина", value=reason, inline=False)
        await self.send_embed(guild, embed, category="mod")
