"""Сервис музыки: хранилище плееров по серверам и резолвер треков."""
from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING

from app.services.audio.player import GuildPlayer
from app.services.audio.resolver import TrackNotFoundError, TrackResolver
from app.services.audio.spotify import SpotifyResolver
from app.services.audio.track import Track

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.services")


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


class MusicService:
    def __init__(self, bot: MegaBot, playlists=None) -> None:
        self._bot = bot
        self._players: dict[int, GuildPlayer] = {}
        self.resolver = TrackResolver()
        self.spotify = SpotifyResolver(
            getattr(bot.config, "spotify_client_id", None),
            getattr(bot.config, "spotify_client_secret", None),
        )
        self.playlists = playlists
        self._restored: set[int] = set()

    async def save_playlist(self, guild_id: int, name: str, author_id: int, tracks: list[Track]) -> None:
        if self.playlists is None:
            raise RuntimeError("Хранилище плейлистов недоступно")
        await self.playlists.save_playlist(guild_id, name, author_id, tracks)

    async def list_playlists(self, guild_id: int):
        if self.playlists is None:
            return []
        return await self.playlists.list_playlists(guild_id)

    async def load_playlist(self, guild_id: int, name: str) -> list[Track]:
        if self.playlists is None:
            return []
        tracks = await self.playlists.get_playlist(guild_id, name)
        refreshed: list[Track] = []
        for track in tracks:
            try:
                refreshed.append(await self.resolve(track.url))
            except Exception:
                logger.warning("Не удалось обновить трек из плейлиста: %s", track.url)
        return refreshed

    async def delete_playlist(self, guild_id: int, name: str) -> bool:
        if self.playlists is None:
            return False
        return await self.playlists.delete_playlist(guild_id, name)

    async def record_history(self, guild_id: int, user_id: int, track: Track) -> None:
        if self.playlists is not None and hasattr(self.playlists, "record_history"):
            await self.playlists.record_history(guild_id, user_id, track)

    async def history(self, guild_id: int, limit: int = 20):
        if self.playlists is None or not hasattr(self.playlists, "history"):
            return []
        return await self.playlists.history(guild_id, limit)

    def get_player(self, guild_id: int) -> GuildPlayer:
        if guild_id not in self._players:
            self._players[guild_id] = GuildPlayer(self._bot, guild_id)
        return self._players[guild_id]

    async def restore_queue(self, guild_id: int) -> None:
        if guild_id in self._restored:
            return
        self._restored.add(guild_id)
        if self.playlists is None or not hasattr(self.playlists, "load_queue"):
            return
        player = self.get_player(guild_id)
        for track in await self.playlists.load_queue(guild_id):
            try:
                player.enqueue(await self.resolve(track.url))
            except Exception:
                logger.warning("Не удалось восстановить трек очереди: %s", track.url)

    async def persist_queue(self, guild_id: int) -> None:
        if self.playlists is None or not hasattr(self.playlists, "save_queue"):
            return
        player = self.get_player(guild_id)
        tracks = ([player.current] if player.current is not None else []) + list(player.queue)
        await self.playlists.save_queue(guild_id, tracks)

    async def resolve(self, query: str) -> Track:
        return await self.resolver.resolve(query)

    async def resolve_many(self, query: str) -> list[Track]:
        if "open.spotify.com/" in query:
            queries = await self.spotify.track_queries(query)
            tracks: list[Track] = []
            for item in queries:
                try:
                    tracks.append(await self.resolve(item))
                except TrackNotFoundError:
                    logger.warning("Spotify track не найден через YouTube: %s", item)
            return tracks
        return await self.resolver.resolve_many(query)

    async def aclose(self) -> None:
        """Останавливает все голосовые плееры при завершении бота."""
        players = tuple(self._players.values())
        for player in players:
            try:
                await self.persist_queue(player.guild_id)
            except Exception:
                logger.exception("Не удалось сохранить очередь %s", player.guild_id)
        self._players.clear()
        for player in players:
            try:
                await player.disconnect()
            except Exception:
                logger.exception("Не удалось отключить музыкальный плеер %s", player.guild_id)
        await self.spotify.close()


__all__ = ["MusicService", "TrackNotFoundError", "Track", "ffmpeg_available"]
