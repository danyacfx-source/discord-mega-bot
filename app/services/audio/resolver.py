"""Резолвер треков через yt-dlp."""
from __future__ import annotations

import asyncio
import logging

import yt_dlp

from app.services.audio.track import Track

logger = logging.getLogger("bot.audio")

_YDL_OPTIONS = {
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
        self._ydl = yt_dlp.YoutubeDL(_YDL_OPTIONS)

    async def resolve(self, query: str) -> Track:
        try:
            data = await asyncio.to_thread(self._extract, query)
        except yt_dlp.utils.DownloadError as exc:
            raise TrackNotFoundError(f"Не удалось получить трек: {exc}") from exc

        entry = data
        if isinstance(data, dict) and data.get("entries"):
            entry = data["entries"][0]

        if not entry:
            raise TrackNotFoundError("Ничего не найдено по запросу.")

        return Track(
            title=entry.get("title") or "Неизвестный трек",
            url=entry.get("webpage_url") or query,
            stream_url=entry.get("url") or "",
            duration=entry.get("duration"),
            uploader=entry.get("uploader") or entry.get("channel"),
            thumbnail=entry.get("thumbnail"),
        )

    def _extract(self, query: str) -> dict:
        source = query if query.startswith(("http://", "https://")) else f"ytsearch1:{query}"
        return self._ydl.extract_info(source, download=False)
