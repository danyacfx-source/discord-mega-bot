"""Проверка публичного YouTube /live через уже установленный yt-dlp.

YouTube может отдавать запланированную трансляцию или запись вместо LIVE:
стрим считается активным *только* при явном `live_status=is_live`.
Экстрактор синхронный, поэтому вызывается из asyncio.to_thread.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")


def parse_youtube_live(info: dict[str, Any] | None) -> dict[str, Any] | None:
    """Нормализованный live-статус либо None (offline/upcoming/recording)."""
    if not isinstance(info, dict):
        return None
    if info.get("live_status") != "is_live" and info.get("is_live") is not True:
        return None
    video_id = str(info.get("id") or "")
    if not _VIDEO_ID.fullmatch(video_id):
        return None
    timestamp = info.get("release_timestamp") or info.get("timestamp")
    try:
        started = datetime.fromtimestamp(int(timestamp), tz=UTC).isoformat() if timestamp else None
    except (TypeError, ValueError, OverflowError, OSError):
        started = None

    thumbnails = info.get("thumbnails") or []
    thumbnail = ""
    if isinstance(thumbnails, list):
        for item in reversed(thumbnails):
            if isinstance(item, dict) and str(item.get("url") or "").startswith("https://"):
                thumbnail = str(item["url"])
                break
    if not thumbnail and str(info.get("thumbnail") or "").startswith("https://"):
        thumbnail = str(info["thumbnail"])

    return {
        "id": video_id,
        "title": str(info.get("title") or "DENDICH — прямой эфир")[:200],
        "description": str(info.get("description") or "")[:500],
        "viewers": max(0, int(info.get("concurrent_view_count") or 0)),
        "thumbnail": thumbnail,
        "started_at": started,
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }


def probe_youtube_live(channel_url: str) -> dict[str, Any] | None:
    """Blocking yt-dlp metadata extraction; errors bubble up (not 'offline')."""
    from yt_dlp import YoutubeDL

    live_url = channel_url.rstrip("/") + "/live"
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 18,
        "retries": 1,
        "extractor_retries": 1,
        "ignore_no_formats_error": True,
    }
    with YoutubeDL(options) as ydl:
        # Resolve /live redirects to the actual video so live_status is available.
        # This extracts metadata only; no video is downloaded.
        info = ydl.extract_info(live_url, download=False)
    return parse_youtube_live(info)
