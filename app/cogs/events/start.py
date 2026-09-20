"""Старт бота: статус, прогрев настроек, проверка окружения."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from app.core.base import MegaCog
from app.core.stream_state import stream_activity
from app.services.music_service import ffmpeg_available
from app.services.settings_service import SettingsService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot")


class StartCog(MegaCog, name="Lifecycle"):
    def __init__(self, bot: MegaBot, settings: SettingsService) -> None:
        super().__init__(bot)
        self.settings = settings

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        logger.info("Бот %s готов, серверов: %d", self.bot.user, len(self.bot.guilds))
        await self.settings.ensure_all_guilds(self.bot)
        self._warn_on_missing_tools()
        try:
            await self.bot.change_presence(activity=stream_activity(None))
        except Exception:
            logger.debug("Не удалось установить статус", exc_info=True)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self.settings.ensure_all_guilds(self.bot)
        logger.info("Добавлен на сервер %s (%d)", guild.name, guild.id)

    def _warn_on_missing_tools(self) -> None:
        if not ffmpeg_available():
            logger.warning("FFmpeg не найден — музыкальные команды будут недоступны")
        try:
            if not discord.opus.is_loaded():
                discord.opus.load_opus()
        except Exception:
            logger.warning("libopus не загружен — голосовые каналы могут не работать")
