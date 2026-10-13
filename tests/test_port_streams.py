"""Тесты webpanel-стримов: список, freshness, watchers, chat, archive CSV."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.core.webpanel.webpanel import WebPanel


@pytest.mark.asyncio
async def test_webpanel_api_streams(make_panel_bot):
    bot = make_panel_bot(
        twitch_channels=("alice",),
        kick_channel_slug="bob",
        stream_quiet_hours=(23, 8),
        stream_role_id=10,
        stream_role_user_ids=(42,),
    )
    await bot.setup_hook()
    panel = WebPanel(bot)
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                assert (await client.get("/api/streams")).status == 401
                headers = {"X-Panel-Token": panel._static_token or ""}
                resp = await client.get("/api/streams", headers=headers)
                assert resp.status == 200
                data = await resp.json()
                assert data["ok"] is True
                labels = [s["label"] for s in data["streams"]]
                assert "Twitch · alice" in labels
                assert "Kick · bob" in labels
                assert all(s["session"] is None for s in data["streams"]), "сессия пуста без стрима"
                assert all(s["rsvp_count"] == 0 for s in data["streams"]), "без откликов счётчик пуст"
                assert data["quiet_hours"] == "23-8"
                assert data["role_id"] == "10"
                assert data["role_user_ids"] == ["42"]
                assert data["rsvp_role_id"] == "", "гильдия не в кэше — роль RSVP не резолвится"
                assert data["rsvp_role_name"] == ""
    finally:
        await bot.close()


def test_webpanel_stream_is_live_freshness(make_panel_bot):
    from datetime import UTC, datetime, timedelta

    bot = make_panel_bot(stream_sticky_poll_seconds=60.0)
    panel = WebPanel(bot)
    fresh = {"captured_at": datetime.now(UTC).isoformat()}
    stale = {"captured_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat()}
    assert panel._stream_is_live(fresh, 300) is True
    assert panel._stream_is_live(stale, 300) is False
    assert panel._stream_is_live(None, 300) is False
    assert panel._stream_is_live({"captured_at": "мусор"}, 300) is False


@pytest.mark.asyncio
async def test_webpanel_api_streams_watchers(make_panel_bot):
    bot = make_panel_bot(kick_channel_slug="bob", twitch_channels=("alice",))
    await bot.setup_hook()
    panel = WebPanel(bot)
    try:
        store = bot.services.kick.viewer_store()
        await store.touch("alice", stream_id="s1")
        await store.touch("bob", stream_id="s1")
        await store.touch("alice", stream_id="s1")
        twitch_store = bot.services.twitch.viewer_store()
        await twitch_store.touch("carol", stream_id="s2")
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                assert (await client.get("/api/streams/watchers")).status == 401
                headers = {"X-Panel-Token": panel._static_token or ""}
                resp = await client.get("/api/streams/watchers", headers=headers)
                assert resp.status == 200
                data = await resp.json()
                assert data["ok"] is True
                assert data["kick_enabled"] is True
                assert [t["name"] for t in data["top"]] == ["alice", "bob"], "топ по сообщениям за эфир"
                assert data["top"][0]["name"] == "alice", "alice с двумя сообщениями впереди"
                assert {r["name"] for r in data["active"]} == {"alice", "bob"}
                kick_block = data["platforms"]["kick"]
                assert kick_block["enabled"] is True
                assert {r["name"] for r in kick_block["active"]} == {"alice", "bob"}
                twitch_block = data["platforms"]["twitch"]
                assert twitch_block["enabled"] is True
                assert [t["name"] for t in twitch_block["top"]] == ["carol"], "чат Twitch отдельно от Kick"
                assert {r["name"] for r in twitch_block["active"]} == {"carol"}
                assert data["platforms"]["vk_video"]["enabled"] is False, "у VK чата нет"
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_webpanel_api_streams_archive_csv(make_panel_bot):
    bot = make_panel_bot(twitch_channels=("alice",))
    await bot.setup_hook()
    panel = WebPanel(bot)
    try:
        store = bot.services.twitch.archive_store("alice")
        await store.append(
            {
                "platform": "twitch",
                "title": "Привет; мир",
                "category": "IRL",
                "url": "https://twitch.tv/videos/1",
                "vod": "123",
                "started_at": "2026-10-01T18:00:00+00:00",
                "ended_at": "2026-10-01T21:00:00+00:00",
                "seconds": 10800,
                "peak": 42,
            }
        )
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                headers = {"X-Panel-Token": panel._static_token or ""}
                assert (await client.get("/api/streams/archive/export")).status == 401
                resp = await client.get("/api/streams/archive/export", headers=headers)
                assert resp.status == 200
                assert resp.headers["Content-Type"].startswith("text/csv")
                assert "attachment" in resp.headers.get("Content-Disposition", "")
                body = await resp.text()
                assert body.startswith("\ufeff"), "BOM нужен для Excel"
                assert "платформа;канал;название" in body
                assert "Привет; мир" in body
                assert "180" in body and "42" in body
    finally:
        await bot.close()
