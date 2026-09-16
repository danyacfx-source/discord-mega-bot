"""Старт бота: статус, прогрев настроек, проверка окружения."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from app.core.base import MegaCog
from app.services.music_service import ffmpeg_available
from app.services.settings_service import SettingsService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot")

_STATUSES = (
    "!help",
    "музыку на серверах",
    "за порядком",
    "с кодом",
)


class StartCog(MegaCog, name="Lifecycle"):
    _status_index = 0

    def __init__(self, bot: MegaBot, settings: SettingsService) -> None:
        super().__init__(bot)
        self.settings = settings

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        logger.info("Бот %s готов, серверов: %d", self.bot.user, len(self.bot.guilds))
        await self.settings.ensure_all_guilds(self.bot)
        self._warn_on_missing_tools()
        if not self._status_task.is_running():
            self._status_task.start()

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        await self.settings.ensure_all_guilds(self.bot)
        logger.info("Добавлен на сервер %s (%d)", guild.name, guild.id)

    def _warn_on_missing_tools(self) -> None:
        if not ffmpeg_available():
            logger.warning("FFmpeg не найден — музыкальные команды будут недоступны")
        try:
            if not discord.opus.is_loaded():
                discord.opus.load_opus("opus")
        except Exception:
            logger.warning("libopus не загружен — голосовые каналы могут не работать")

    @tasks.loop(seconds=600.0)
    async def _status_task(self) -> None:
        state = _STATUSES[self._status_index % len(_STATUSES)]
        self._status_index += 1
        await self.bot.change_presence(activity=discord.Game(name=state))

    @_status_task.before_loop
    async def _before_status(self) -> None:
        await self.bot.wait_until_ready()

    async def cog_unload(self) -> None:
        self._status_task.cancel()
