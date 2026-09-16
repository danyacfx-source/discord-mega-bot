"""Сервис музыки: хранилище плееров по серверам и резолвер треков."""
from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING

from app.services.audio.player import GuildPlayer
from app.services.audio.resolver import TrackNotFoundError, TrackResolver
from app.services.audio.track import Track
from app.services.audio.yandex_resolver import YandexMusicResolver, parse_yandex_track_id

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
        self._yandex: YandexMusicResolver | None = None

    def get_player(self, guild_id: int) -> GuildPlayer:
        if guild_id not in self._players:
            self._players[guild_id] = GuildPlayer(self._bot, guild_id)
        return self._players[guild_id]

    async def resolve(self, query: str) -> Track:
        yandex_id = parse_yandex_track_id(query)
        if yandex_id is None:
            return await self.resolver.resolve(query)
        token = self._bot.config.yandex_music_token
        if not token:
            raise TrackNotFoundError(
                "Для ссылок Яндекс Музыки задайте YANDEX_MUSIC_TOKEN в .env (токен аккаунта с Яндекс Плюс)."
            )
        if self._yandex is None:
            self._yandex = YandexMusicResolver(token)
        return await self._yandex.resolve(query, yandex_id)


__all__ = ["MusicService", "TrackNotFoundError", "Track", "ffmpeg_available"]
