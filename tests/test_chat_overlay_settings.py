"""The standalone OBS chat appearance is persisted without changing old links."""
from __future__ import annotations

import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.config import Config
from app.core.bot import MegaBot
from app.core.overlay.chat_settings import (
    CHAT_SETTINGS_KEY,
    DEFAULT_CHAT_SETTINGS,
    load_chat_settings,
    sanitize_chat_settings,
    save_chat_settings,
)
from app.core.webpanel.webpanel import WebPanel


class _MemoryKv:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str, default: str | None = None) -> str | None:
        return self.data.get(key, default)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value


def test_chat_settings_are_clamped_and_do_not_allow_css_injection() -> None:
    cleaned = sanitize_chat_settings({
        "size": 500,
        "limit": -10,
        "idle": "0",
        "gap": 9999,
        "padding": -30,
        "opacity": 150,
        "theme": "dangerous",
        "font": "url(https://evil)",
        "text_color": "red;body{display:none}",
        "accent_color": "#FFBB99",
        "show_platform": "false",
    })
    assert cleaned == {
        **DEFAULT_CHAT_SETTINGS,
        "size": 44,
        "limit": 1,
        "idle": 0,
        "gap": 20,
        "padding": 0,
        "opacity": 100,
        "accent_color": "#ffbb99",
    }


@pytest.mark.asyncio
async def test_chat_settings_roundtrip_and_backward_compatibility() -> None:
    kv = _MemoryKv()
    assert await load_chat_settings(kv) is None, "legacy URL parameters still work before first save"
    old_link = "/overlay/chat?token=existing-token&size=24&limit=8&idle=0"

    stored = await save_chat_settings(kv, {"size": 28, "theme": "radio", "show_platform": True})
    assert stored["size"] == 28
    assert stored["show_platform"] is True
    assert stored["theme"] == "radio"
    assert json.loads(kv.data[CHAT_SETTINGS_KEY]) == stored
    assert await load_chat_settings(kv) == stored
    assert old_link.startswith("/overlay/chat?token=existing-token")

    kv.data[CHAT_SETTINGS_KEY] = "{broken"
    assert await load_chat_settings(kv) is None


@pytest.mark.asyncio
async def test_panel_chat_settings_roundtrip_and_obs_source_url_preserved(tmp_path) -> None:
    config = Config(
        token="x",
        prefix="!",
        db_path=str(tmp_path / "bot.db"),
        log_level="ERROR",
        status_activity="s",
        owner_id=None,
        panel_port=17879,
        overlay_port=18779,
        overlay_token="existing-obs-overlay-token-32chars",
    )
    bot = MegaBot(config)
    await bot.setup_hook()
    panel = WebPanel(bot)
    owner = {"X-Panel-Token": panel._static_token or ""}
    obs_token = {"X-Overlay-Token": "existing-obs-overlay-token-32chars"}
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                before = await (await client.get("/api/overlay", headers=owner)).json()
                assert before["chat_settings_saved"] is False
                assert before["chat_settings"]["size"] == 17
                assert (await client.post("/api/overlay/chat/settings", json={"settings": {"size": 25}})).status == 401

                result = await client.post(
                    "/api/overlay/chat/settings",
                    json={"settings": {"size": 25, "limit": 9, "theme": "radio", "gap": 12}},
                    headers=owner,
                )
                assert result.status == 200
                assert (await result.json())["settings"]["size"] == 25

                current = await (await client.get("/api/overlay", headers=owner)).json()
                assert current["chat_settings_saved"] is True
                assert current["chat_settings"]["theme"] == "radio"
                assert current["token"] == before["token"], "no OBS token rotation"

                # Public OBS endpoint stays protected and the exact old URL continues working.
                assert (await client.get("/overlay/api")).status == 401
                old_page = await client.get(
                    "/overlay/chat?token=existing-obs-overlay-token-32chars&size=17&limit=15&idle=10"
                )
                assert old_page.status == 200
                assert "applySettings" in await old_page.text()
                source = await client.get("/overlay/api", headers=obs_token)
                assert source.status == 200
                incoming = await source.json()
                assert incoming["chat_settings"]["size"] == 25
                assert incoming["chat_settings"]["limit"] == 9
    finally:
        await bot.close()
