"""Вебпанель: публичная витрина (/showcase, /api/public/showcase)."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.config import Config
from app.core.bot import MegaBot
from app.core.webpanel.webpanel import WebPanel


def _panel(tmp_path) -> MegaBot:
    config = Config(
        token="x",
        prefix="!",
        db_path=str(tmp_path / "bot.db"),
        log_level="ERROR",
        status_activity="s",
        owner_id=None,
        panel_port=17897,
    )
    return MegaBot(config)


@pytest.mark.asyncio
async def test_public_showcase_and_settings(tmp_path):
    bot = _panel(tmp_path)
    await bot.setup_hook()
    panel = WebPanel(bot)
    headers = {"X-Panel-Token": panel._static_token or ""}
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                # страница отдаётся без токена
                resp = await client.get("/showcase")
                assert resp.status == 200
                assert "text/html" in resp.headers["Content-Type"]

                # публичный payload без авторизации
                resp = await client.get("/api/public/showcase")
                assert resp.status == 200
                body = await resp.json()
                assert body["ok"]
                assert body["settings"]["hero_title"] == ""
                assert body["stats"]["messages_total"] == 0
                assert body["streams"] == []
                assert body["schedule"] == []
                assert body["media"] == []
                assert "bot" in body and "online" in body["bot"]
                # без подключённых гильдий guild — null, но форма устойчива
                assert body["guild"] is None

                # сохранение настроек
                resp = await client.post(
                    "/api/showcase/settings",
                    json={"hero_title": "Асуна Юки", "about": "Проект", "invite_url": "https://discord.gg/x"},
                    headers=headers,
                )
                assert resp.status == 200
                body = await resp.json()
                assert body["ok"] and body["settings"]["hero_title"] == "Асуна Юки"

                # невалидная ссылка отклоняется
                resp = await client.post(
                    "/api/showcase/settings",
                    json={"invite_url": "ftp://evil"},
                    headers=headers,
                )
                assert resp.status == 400

                # публичный payload подхватил настройки
                resp = await client.get("/api/public/showcase")
                body = await resp.json()
                assert body["settings"]["hero_title"] == "Асуна Юки"
                assert body["settings"]["invite_url"] == "https://discord.gg/x"

                # настройки читаются и под авторизацией
                resp = await client.get("/api/showcase/settings", headers=headers)
                body = await resp.json()
                assert body["ok"] and body["settings"]["about"] == "Проект"
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_showcase_corrupt_settings_degrade(tmp_path):
    bot = _panel(tmp_path)
    await bot.setup_hook()
    panel = WebPanel(bot)
    try:
        await bot.services.kv.set("panel.showcase.settings", "не json[[[")
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/public/showcase")
                assert resp.status == 200
                body = await resp.json()
                assert body["ok"] and body["settings"]["hero_title"] == ""
    finally:
        await bot.close()
