"""Сервис YouTube: статистика канала + устойчивое состояние (как Node youtube.js/youtube_growth.js)."""
from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

import aiohttp

if TYPE_CHECKING:
    from app.config import Config
    from app.data.kv_repository import KvRepository

logger = logging.getLogger("bot.services")

_API_BASE = "https://www.googleapis.com/youtube/v3"
_STATE_KEY = "youtube:growth"


def format_number(n: int) -> str:
    """1 234 567 — пробелы как разделители тысяч (как fmtNum в Node)."""
    return f"{int(n):,}".replace(",", " ")


def parse_duration_seconds(duration: str) -> int:
    """PT1H2M3S → 3723."""
    total = 0
    match_h = re.search(r"(\d+)H", duration)
    match_m = re.search(r"(\d+)M", duration)
    match_s = re.search(r"(\d+)S", duration)
    if match_h:
        total += int(match_h.group(1)) * 3600
    if match_m:
        total += int(match_m.group(1)) * 60
    if match_s:
        total += int(match_s.group(1))
    return total


class YouTubeService:
    def __init__(self, repo: KvRepository, config: Config) -> None:
        self._repo = repo
        self._config = config
        self._session: aiohttp.ClientSession | None = None
        self._channel_id: str | None = None
        self._state: dict[str, Any] = {}
        self._state_loaded = False

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def aclose(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    @property
    def enabled(self) -> bool:
        return self._config.youtube_enabled and bool(self._config.youtube_api_key)

    @property
    def api_key(self) -> str:
        return self._config.youtube_api_key or ""

    @property
    def handle(self) -> str:
        return self._config.youtube_channel or "Dendosich"

    async def _fetch(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("YouTube API key не задан (YOUTUBE_API_KEY)")
        params = {**params, "key": self.api_key}
        timeout = aiohttp.ClientTimeout(total=15)
        async with self.session.get(f"{_API_BASE}{endpoint}", params=params, timeout=timeout) as response:
            if response.status != 200:
                detail = ""
                try:
                    body = await response.json(content_type=None)
                    detail = ((body or {}).get("error") or {}).get("message") or ""
                except (aiohttp.ClientError, ValueError):
                    pass
                raise RuntimeError(f"YouTube API {response.status}: {detail}")
            return await response.json(content_type=None)

    async def resolve_channel_id(self) -> str | None:
        """ID канала по handle (@Dendosich → Dendosich)."""
        if self._channel_id is not None:
            return self._channel_id
        data = await self._fetch("/channels", {"part": "id", "forHandle": self.handle})
        items = data.get("items") or []
        self._channel_id = items[0]["id"] if items else None
        return self._channel_id

    async def channel_stats(self) -> dict[str, Any] | None:
        """Сниппет + статистика канала (subscribers/views/videos)."""
        channel_id = await self.resolve_channel_id()
        if not channel_id:
            return None
        data = await self._fetch("/channels", {"part": "snippet,statistics", "id": channel_id})
        return (data.get("items") or [None])[0]

    async def recent_videos(self, max_results: int = 10) -> list[dict[str, Any]]:
        """Свежие видео канала: id, заголовок, превью, liveBroadcastContent."""
        channel_id = await self.resolve_channel_id()
        if not channel_id:
            return []
        data = await self._fetch(
            "/search",
            {
                "part": "id,snippet",
                "channelId": channel_id,
                "order": "date",
                "maxResults": max_results,
                "type": "video",
            },
        )
        return data.get("items") or []

    async def video_details(self, video_ids: list[str]) -> list[dict[str, Any]]:
        if not video_ids:
            return []
        data = await self._fetch("/videos", {"part": "contentDetails,snippet,statistics", "id": ",".join(video_ids)})
        return data.get("items") or []

    # ------------------------------------------------------------- state (рост канала)

    async def load_state(self) -> dict[str, Any]:
        """Состояние роста (known_shorts/премьеры/analytics) из Kv, с мемкэшем."""
        if not self._state_loaded:
            self._state_loaded = True
            raw = await self._repo.get(_STATE_KEY)
            if raw:
                try:
                    self._state = json.loads(raw)
                except (ValueError, TypeError):
                    self._state = {}
        return self._state

    async def save_state(self) -> None:
        try:
            await self._repo.set(_STATE_KEY, json.dumps(self._state, ensure_ascii=False))
        except Exception:
            logger.exception("YouTube: не удалось сохранить состояние роста")
            self._state_loaded = False
