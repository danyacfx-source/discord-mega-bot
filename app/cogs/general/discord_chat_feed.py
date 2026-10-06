"""Сообщения Discord-сервера — в ленту оверлея «Чат» для OBS."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from app.core.base import MegaCog

logger = logging.getLogger("bot.cogs")


class DiscordChatFeedCog(MegaCog, name="DiscordChatFeed"):
    """Пушит сообщения сервера в ChatFeed — оверлей-чат показывает все платформы разом.

    Лента кольцевая (300), так что Discord-трафик не вытесняет Kick/Twitch
    сильнее, чем новые сообщения вытесняют старые; точечный показ — через
    ``?platform=`` на странице оверлея.
    """

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.content or message.guild is None:
            return
        if message.channel.id in self.bot.config.logs_ignore_channel_ids:
            return
        perms = getattr(message.author, "guild_permissions", None)
        try:
            self.services.chat_feed.push(
                "discord",
                getattr(message.author, "display_name", None) or message.author.name,
                message.content,
                is_mod=bool(perms and perms.manage_messages),
            )
        except Exception:
            logger.debug("DiscordChatFeed: не удалось добавить сообщение в ленту", exc_info=True)
