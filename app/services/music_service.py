"""Сервис музыки: хранилище плееров по серверам и резолвер треков."""
from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING

from app.services.audio.player import GuildPlayer
from app.services.audio.resolver import TrackNotFoundError, TrackResolver
from app.services.audio.track import Track

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.services")


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


class MusicService:
    def __init__(self, bot: MegaBot) -> None:
        self._bot = bot
        self._players: dict[int, GuildPlayer] = {}
        self.resolver = TrackResolver()

    def get_player(self, guild_id: int) -> GuildPlayer:
        if guild_id not in self._players:
            self._players[guild_id] = GuildPlayer(self._bot, guild_id)
        return self._players[guild_id]

    async def resolve(self, query: str) -> Track:
        return await self.resolver.resolve(query)


__all__ = ["MusicService", "TrackNotFoundError", "Track", "ffmpeg_available"]
