"""Мониторинг прямого эфира YouTube: API, защита от анонса-повтора, Showcase."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.cogs.streams.youtube import YouTubeCog
from app.services.youtube_data_api import YouTubeDataAPI, video_live_status
from app.services.youtube_live import parse_youtube_live

VIDEO_ID = "Abc_123-xYz"
CHANNEL_ID = "UC012345678901234567890"


def _video(status: str = "live") -> dict:
    return {
        "id": VIDEO_ID,
        "snippet": {
            "channelId": CHANNEL_ID,
            "liveBroadcastContent": status,
            "title": "Squad: операция",
            "description": "План был",
            "thumbnails": {"high": {"url": "https://i.ytimg.com/test.jpg"}},
        },
        "liveStreamingDetails": {
            "actualStartTime": "2026-10-22T19:00:00Z",
            "concurrentViewers": "43",
        },
    }


def test_api_live_is_explicit_not_upcoming_or_completed():
    live = video_live_status(_video(), channel_id=CHANNEL_ID)
    assert live is not None
    assert live["url"] == f"https://www.youtube.com/watch?v={VIDEO_ID}"
    assert live["viewers"] == 43
    assert video_live_status(_video("upcoming"), channel_id=CHANNEL_ID) is None
    ended = _video()
    ended["liveStreamingDetails"]["actualEndTime"] = "2026-10-22T21:00:00Z"
    assert video_live_status(ended, channel_id=CHANNEL_ID) is None
    assert video_live_status(_video(), channel_id="another-channel") is None


def test_ytdlp_live_requires_true_status():
    info = {"id": VIDEO_ID, "title": "Squad", "live_status": "is_live", "is_live": True}
    assert parse_youtube_live(info)["id"] == VIDEO_ID
    assert parse_youtube_live({**info, "live_status": "is_upcoming", "is_live": False}) is None
    assert parse_youtube_live({**info, "live_status": "was_live", "is_live": False}) is None


@pytest.mark.asyncio
async def test_api_finds_live_in_uploads_without_search(monkeypatch):
    api = YouTubeDataAPI()
    calls = []

    async def fake_get(session, endpoint, params):
        calls.append(endpoint)
        if endpoint == "channels":
            return {"items": [{"id": CHANNEL_ID, "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}}}]}
        if endpoint == "playlistItems":
            return {"items": [{"contentDetails": {"videoId": VIDEO_ID}}]}
        if endpoint == "search":
            return {"items": []}
        if endpoint == "videos":
            return {"items": [_video()]}
        raise AssertionError(endpoint)

    monkeypatch.setattr(api, "_get", fake_get)
    assert (await api.channel_status("dummy-key"))["id"] == VIDEO_ID
    assert calls == ["channels", "playlistItems", "search", "videos"]
    calls.clear()
    assert (await api.channel_status("dummy-key", active_video_id=VIDEO_ID))["id"] == VIDEO_ID
    assert calls == ["playlistItems", "videos"]


@pytest.mark.asyncio
async def test_no_discord_announcement_without_channel(monkeypatch):
    kv = MagicMock()
    values = {}

    async def get(key, default=None):
        return values.get(key, default)

    async def set_(key, value):
        values[key] = value

    kv.get = get
    kv.set = set_
    kv.delete = AsyncMock()
    bot = MagicMock()
    bot.services.kv = kv
    cog = YouTubeCog(bot)
    monkeypatch.setattr(cog, "_notify_channel", lambda: None)
    status = {"id": VIDEO_ID, "url": f"https://www.youtube.com/watch?v={VIDEO_ID}", "title": "Live",
              "viewers": 12, "started_at": "2026-10-22T19:00:00Z"}
    await cog._live(status)
    assert values["stream:youtube:active"] == VIDEO_ID
    assert "stream:youtube:last_announced" not in values


@pytest.mark.asyncio
async def test_api_failure_does_not_falsely_mark_offline(monkeypatch):
    bot = MagicMock()
    bot.config.youtube_api_key = "dummy-key"
    bot.services.kv.get = AsyncMock(return_value=VIDEO_ID)
    cog = YouTubeCog(bot)
    monkeypatch.setattr(cog, "_channel_url", AsyncMock(return_value="https://www.youtube.com/@Dendosich"))
    cog._api.channel_status = AsyncMock(side_effect=RuntimeError("YouTube API unavailable"))
    cog._offline = AsyncMock()
    with pytest.raises(RuntimeError, match="unavailable"):
        await cog.check_once()
    cog._offline.assert_not_awaited()
