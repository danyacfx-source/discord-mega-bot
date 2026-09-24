"""Резолвер треков через yt-dlp."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

import yt_dlp

from app.services.audio.track import Track

logger = logging.getLogger("bot.audio")

_YDL_OPTIONS: dict[str, Any] = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": False,
}


class TrackNotFoundError(Exception):
    """Трек по запросу не найден."""


class TrackResolver:
    def __init__(self) -> None:
        self._ydl = yt_dlp.YoutubeDL(cast(Any, _YDL_OPTIONS))

    async def resolve(self, query: str) -> Track:
        try:
            data = await asyncio.to_thread(self._extract, query)
        except yt_dlp.utils.DownloadError as exc:
            raise TrackNotFoundError(f"Не удалось получить трек: {exc}") from exc

        entry: dict[str, Any] | None = data
        if isinstance(data, dict) and data.get("entries"):
            entry = data["entries"][0]

        if not entry:
            raise TrackNotFoundError("Ничего не найдено по запросу.")

        if not isinstance(entry, dict):
            raise TrackNotFoundError("Результат поиска имеет неизвестный формат.")

        return Track(
            title=entry.get("title") or "Неизвестный трек",
            url=entry.get("webpage_url") or query,
            stream_url=entry.get("url") or "",
            duration=entry.get("duration"),
            uploader=entry.get("uploader") or entry.get("channel"),
            thumbnail=entry.get("thumbnail"),
        )

    async def resolve_many(self, query: str, limit: int = 100) -> list[Track]:
        """Импортирует публичный YouTube Playlist, обновляя каждый stream URL."""
        if not query.startswith(("http://", "https://")):
            return [await self.resolve(query)]
        entries = await asyncio.to_thread(self._extract_playlist, query)
        tracks: list[Track] = []
        for entry in entries[: max(1, min(limit, 100))]:
            source = str(entry.get("webpage_url") or entry.get("url") or "").strip()
            if not source:
                continue
            try:
                tracks.append(await self.resolve(source))
            except TrackNotFoundError:
                logger.warning("Пропущен недоступный трек плейлиста: %s", source)
        return tracks

    def _extract(self, query: str) -> dict[str, Any]:
        source = query if query.startswith(("http://", "https://")) else f"ytsearch1:{query}"
        data = self._ydl.extract_info(source, download=False)
        if not isinstance(data, dict):
            raise TrackNotFoundError("yt-dlp вернул пустой результат.")
        return cast(dict[str, Any], data)

    def _extract_playlist(self, query: str) -> list[dict[str, Any]]:
        options = {**_YDL_OPTIONS, "noplaylist": False, "extract_flat": True}
        with yt_dlp.YoutubeDL(cast(Any, options)) as ydl:
            data = ydl.extract_info(query, download=False)
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            return []
        return [cast(dict[str, Any], entry) for entry in entries if isinstance(entry, dict)]
