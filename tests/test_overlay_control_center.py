"""Mission control: persisted overlay blackout, cache clear and safe visual filters."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.config import Config
from app.core.bot import MegaBot
from app.core.overlay.chat_settings import (
    DEFAULT_CHAT_SETTINGS,
    filter_chat_messages,
    get_chat_paused,
    load_chat_settings,
    sanitize_chat_settings,
)
from app.core.webpanel.webpanel import WebPanel


def test_filters_are_sanitized_and_never_act_on_real_chats() -> None:
    settings = sanitize_chat_settings({
        "enabled_platforms": ["twitch", "discord", "twitch"],
        "hidden_users": "BotSpam, СПАМЕР, BOTSPAM",
        "blocked_words": "spoiler, спойлер",
    })
    assert settings["enabled_platforms"] == ["twitch"]
    assert settings["hidden_users"] == ["botspam", "спамер"]
    assert settings["blocked_words"] == ["spoiler", "спойлер"]
    rows = [
        {"platform": "twitch", "name": "Оператор", "text": "Привет!"},
        {"platform": "kick", "name": "Оператор", "text": "Привет!"},
        {"platform": "twitch", "name": "BOTSPAM", "text": "Привет!"},
        {"platform": "twitch", "name": "зритель", "text": "тут СпОйЛеР"},
    ]
    assert filter_chat_messages(rows, settings) == rows[:1]
    assert filter_chat_messages(rows, settings, paused=True) == []
    assert filter_chat_messages(rows, None) == rows
    assert sanitize_chat_settings({"enabled_platforms": []})["enabled_platforms"] == []
    assert sanitize_chat_settings({"blocked_words": ["a" * 999]})["blocked_words"] == ["a" * 40]
    assert sanitize_chat_settings({})["enabled_platforms"] == DEFAULT_CHAT_SETTINGS["enabled_platforms"]


def test_twitch_overlay_defaults_to_primary_channel_but_can_include_secondary() -> None:
    settings = sanitize_chat_settings({})
    rows = [
        {"platform": "twitch", "source": "main", "name": "Алиса", "text": "основной"},
        {"platform": "twitch", "source": "side", "name": "Борис", "text": "второй"},
    ]
    assert filter_chat_messages(rows, settings, primary_twitch_channel="main") == rows[:1]
    settings["enabled_twitch_channels"] = ["__primary__", "side"]
    assert filter_chat_messages(rows, settings, primary_twitch_channel="main") == rows


@pytest.mark.asyncio
async def test_panel_obs_controls_persist_and_old_url_works(tmp_path) -> None:
    token = "existing-overlay-token-32-characters"
    config = Config(
        token="x", prefix="!", db_path=str(tmp_path / "bot.db"),
        log_level="ERROR", status_activity="s", owner_id=None,
        panel_port=17851, overlay_port=18751, overlay_token=token,
    )
    bot = MegaBot(config)
    await bot.setup_hook()
    panel = WebPanel(bot)
    owner = {"X-Panel-Token": panel._static_token or ""}
    obs = {"X-Overlay-Token": token}
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                # No unauthenticated remote blackout or cache clearing.
                assert (await client.get("/api/overlay/chat/control")).status == 401
                assert (await client.post("/api/overlay/chat/control", json={"action": "pause"})).status == 401
                assert (await client.post("/api/overlay/chat/control", json={"action": "reboot"}, headers=owner)).status == 400
                assert (await client.get("/overlay/api")).status == 401

                feed = bot.services.chat_feed
                feed.push("twitch", "Алиса", "Отличный стрим")
                feed.push("kick", "Спамер", "спойлер сегодня")
                feed.push("kick", "Борис", "чистое сообщение")
                active = await (await client.get("/api/overlay/chat/control", headers=owner)).json()
                assert active["paused"] is False
                assert active["activity"]["twitch"]["buffered"] == 1
                assert active["activity"]["kick"]["buffered"] == 2

                settings = {
                    "enabled_platforms": ["twitch", "kick"],
                    "hidden_users": ["Спамер"],
                    "blocked_words": ["запрещённое"],
                }
                saved = await client.post("/api/overlay/chat/settings", json={"settings": settings}, headers=owner)
                assert saved.status == 200
                current = await load_chat_settings(bot.services.kv)
                assert current is not None and current["hidden_users"] == ["спамер"]

                data = await (await client.get("/overlay/api", headers=obs)).json()
                assert [x["name"] for x in data["chat"]] == ["Алиса", "Борис"]
                assert data["chat_paused"] is False
                assert (await client.get("/overlay/chat?token=" + token + "&size=29")).status == 200

                paused = await client.post(
                    "/api/overlay/chat/control", json={"action": "pause"}, headers=owner
                )
                assert paused.status == 200
                assert (await paused.json())["paused"] is True
                assert await get_chat_paused(bot.services.kv) is True
                feed.push("twitch", "Алиса", "Пока скрыто")
                hidden = await (await client.get("/overlay/api", headers=obs)).json()
                assert hidden["chat"] == []
                assert hidden["chat_paused"] is True

                resumed = await client.post(
                    "/api/overlay/chat/control", json={"action": "resume"}, headers=owner
                )
                assert resumed.status == 200
                assert await get_chat_paused(bot.services.kv) is False
                assert feed.recent() == [], "paused backlog must not appear on resume"

                feed.push("twitch", "Алиса", "новое сообщение")
                assert (await (await client.get("/overlay/api", headers=obs)).json())["chat"][0]["text"] == "новое сообщение"

                cleared = await client.post(
                    "/api/overlay/chat/control", json={"action": "clear"}, headers=owner
                )
                assert cleared.status == 200
                assert (await cleared.json())["cleared"] == 1
                assert (await (await client.get("/overlay/api", headers=obs)).json())["chat"] == []
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_disabled_overlay_rejects_control_mutations(tmp_path) -> None:
    config = Config(
        token="x", prefix="!", db_path=str(tmp_path / "bot.db"),
        log_level="ERROR", status_activity="s", owner_id=None, panel_port=17852,
    )
    bot = MegaBot(config)
    await bot.setup_hook()
    panel = WebPanel(bot)
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                resp = await client.post(
                    "/api/overlay/chat/control",
                    json={"action": "pause"},
                    headers={"X-Panel-Token": panel._static_token or ""},
                )
                assert resp.status == 503
                assert await get_chat_paused(bot.services.kv) is False
    finally:
        await bot.close()
