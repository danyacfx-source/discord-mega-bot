"""Экономный мониторинг публичного YouTube LIVE через Data API v3.

API key передаётся только в заголовке X-Goog-Api-Key, не в URL/логах.
Свежие видео проверяются через uploads playlist и videos.list (дешёвые
запросы), поиск активного эфира — не чаще раза в 20 минут (72/сутки).
"""
from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import Any

import aiohttp

logger = logging.getLogger("bot.cogs")

_API = "https://www.googleapis.com/youtube/v3/"
_SEARCH_INTERVAL_SECONDS = 1200.0


def video_live_status(data: dict[str, Any], *, channel_id: str) -> dict[str, Any] | None:
    """Only a video that is explicitly live, started and not ended passes."""
    snippet = data.get("snippet") or {}
    details = data.get("liveStreamingDetails") or {}
    if (
        snippet.get("channelId") != channel_id
        or snippet.get("liveBroadcastContent") != "live"
        or not details.get("actualStartTime")
        or details.get("actualEndTime")
    ):
        return None
    video_id = str(data.get("id") or "")
    if len(video_id) != 11 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in video_id):
        return None
    thumbs = snippet.get("thumbnails") or {}
    thumbnail = ""
    if isinstance(thumbs, dict):
        for size in ("maxres", "standard", "high", "medium", "default"):
            item = thumbs.get(size) or {}
            if isinstance(item, dict) and str(item.get("url") or "").startswith("https://"):
                thumbnail = str(item["url"])
                break
    try:
        viewers = max(0, int(details.get("concurrentViewers") or 0))
    except (TypeError, ValueError):
        viewers = 0
    return {
        "id": video_id,
        "title": str(snippet.get("title") or "DENDICH — прямой эфир")[:200],
        "description": str(snippet.get("description") or "")[:500],
        "viewers": viewers,
        "thumbnail": thumbnail,
        "started_at": str(details["actualStartTime"]),
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }


class YouTubeDataAPI:
    """Stateful API monitor, caching channel ID and limiting search requests."""

    def __init__(self) -> None:
        self._channel_id: str = ""
        self._uploads_id: str = ""
        self._last_search_at = -_SEARCH_INTERVAL_SECONDS

    async def _get(self, session: aiohttp.ClientSession, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        async with session.get(_API + endpoint, params=params) as response:
            if response.status != 200:
                # Never log response bodies (they may reflect client credentials).
                raise RuntimeError(f"YouTube Data API {endpoint}: HTTP {response.status}")
            result = await response.json()
            if not isinstance(result, dict):
                raise ValueError("YouTube Data API: invalid JSON shape")
            return result

    async def _resolve_channel(self, session: aiohttp.ClientSession) -> None:
        if self._channel_id:
            return
        info = await self._get(session, "channels", {
            "part": "id,contentDetails", "forHandle": "@Dendosich",
        })
        items = info.get("items") or []
        if not items:
            raise RuntimeError("YouTube channel @Dendosich not found")
        self._channel_id = str(items[0]["id"])
        self._uploads_id = str(
            (items[0].get("contentDetails") or {}).get("relatedPlaylists", {}).get("uploads") or ""
        )

    async def channel_status(self, api_key: str, *, active_video_id: str = "") -> dict[str, Any] | None:
        """Return LIVE details or None. API failures raise, never mean offline."""
        headers = {"X-Goog-Api-Key": api_key}
        timeout = aiohttp.ClientTimeout(total=20, connect=8)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers, trust_env=False) as session:
            await self._resolve_channel(session)
            video_ids: set[str] = set()
            if active_video_id:
                video_ids.add(active_video_id)

            if self._uploads_id:
                uploads = await self._get(session, "playlistItems", {
                    "part": "contentDetails", "playlistId": self._uploads_id, "maxResults": "15",
                })
                for item in uploads.get("items") or []:
                    vid = (item.get("contentDetails") or {}).get("videoId")
                    if isinstance(vid, str) and len(vid) == 11:
                        video_ids.add(vid)

            now = monotonic()
            if not active_video_id and now - self._last_search_at >= _SEARCH_INTERVAL_SECONDS:
                results = await self._get(session, "search", {
                    "part": "id", "channelId": self._channel_id,
                    "eventType": "live", "type": "video", "maxResults": "10",
                })
                self._last_search_at = now
                for item in results.get("items") or []:
                    vid = (item.get("id") or {}).get("videoId")
                    if isinstance(vid, str) and len(vid) == 11:
                        video_ids.add(vid)
            if not video_ids:
                return None

            details = await self._get(session, "videos", {
                "part": "snippet,liveStreamingDetails",
                "id": ",".join(sorted(video_ids)),
            })
            lives = [
                status for item in details.get("items") or []
                if (status := video_live_status(item, channel_id=self._channel_id)) is not None
            ]
            if not lives:
                return None
            return max(lives, key=lambda item: item["started_at"])
