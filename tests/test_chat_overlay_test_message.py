"""Admin-only synthetic OBS chat test; no Twitch/Kick API traffic."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.config import Config
from app.core.bot import MegaBot
from app.core.webpanel.webpanel import WebPanel


@pytest.mark.asyncio
async def test_overlay_chat_test_shows_in_existing_browser_source(tmp_path) -> None:
    config = Config(
        token="test",
        prefix="!",
        db_path=str(tmp_path / "bot.db"),
        log_level="ERROR",
        status_activity="s",
        owner_id=None,
        panel_port=17684,
        overlay_port=18684,
        overlay_token="stable-overlay-test-token-32chars",
    )
    bot = MegaBot(config)
    await bot.setup_hook()
    panel = WebPanel(bot)
    headers = {"X-Panel-Token": panel._static_token or ""}
    old_obs_token = {"X-Overlay-Token": "stable-overlay-test-token-32chars"}
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                bad_auth = await client.post(
                    "/api/overlay/chat/test", json={"platform": "twitch", "text": "Привет"}
                )
                assert bad_auth.status == 401
                assert bot.services.chat_feed.recent() == []

                wrong_platform = await client.post(
                    "/api/overlay/chat/test",
                    json={"platform": "discord", "text": "Не должно появиться"},
                    headers=headers,
                )
                assert wrong_platform.status == 400
                assert bot.services.chat_feed.recent() == []

                twitch = await client.post(
                    "/api/overlay/chat/test",
                    json={"platform": "twitch", "text": "  Проверка   шрифта 📻  "},
                    headers=headers,
                )
                assert twitch.status == 200
                assert (await twitch.json())["platform"] == "twitch"

                kick = await client.post(
                    "/api/overlay/chat/test",
                    json={"platform": "kick", "text": "!discord"},
                    headers=headers,
                )
                assert kick.status == 200

                obs = await client.get("/overlay/api", headers=old_obs_token)
                assert obs.status == 200
                rows = (await obs.json())["chat"]
                assert [(r["platform"], r["name"]) for r in rows] == [
                    ("twitch", "ТЕСТ OBS"), ("kick", "ТЕСТ OBS")
                ]
                assert rows[0]["text"] == "🧪 ТЕСТ ОВЕРЛЕЯ · Проверка шрифта 📻"
                assert rows[1]["text"] == "🧪 ТЕСТ ОВЕРЛЕЯ · !discord"
                assert (await client.get("/overlay/chat?token=stable-overlay-test-token-32chars")).status == 200
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_overlay_chat_test_is_disabled_when_overlay_off(tmp_path) -> None:
    config = Config(
        token="test", prefix="!", db_path=str(tmp_path / "bot.db"), log_level="ERROR",
        status_activity="s", owner_id=None, panel_port=17685,
    )
    bot = MegaBot(config)
    await bot.setup_hook()
    panel = WebPanel(bot)
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                response = await client.post(
                    "/api/overlay/chat/test",
                    json={"platform": "twitch"},
                    headers={"X-Panel-Token": panel._static_token or ""},
                )
                assert response.status == 503
                assert bot.services.chat_feed.recent() == []
    finally:
        await bot.close()
