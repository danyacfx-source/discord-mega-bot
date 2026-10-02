"""Вебпанель: PWA-ассеты (manifest, service worker, иконка)."""
from __future__ import annotations

import json

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
        panel_port=17895,
    )
    return MegaBot(config)


@pytest.mark.asyncio
async def test_pwa_assets_are_served(tmp_path):
    bot = _panel(tmp_path)
    await bot.setup_hook()
    panel = WebPanel(bot)
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                # манифест: валидный JSON с иконкой и start_url
                resp = await client.get("/manifest.webmanifest")
                assert resp.status == 200
                manifest = json.loads(await resp.text())
                assert manifest["start_url"] == "/admin"
                assert manifest["display"] == "standalone"
                assert any(icon["src"] == "/icon.svg" for icon in manifest["icons"])

                # service worker: запрет кэша (no-store от security middleware, no-cache от роута)
                resp = await client.get("/sw.js")
                assert resp.status == 200
                assert resp.headers.get("Cache-Control") in ("no-cache", "no-store")
                assert resp.headers.get("Service-Worker-Allowed") == "/"
                body = await resp.text()
                assert "panel-shell-v1" in body
                assert "cache.put" in body

                # иконка
                resp = await client.get("/icon.svg")
                assert resp.status == 200
                assert "<svg" in await resp.text()

                # index подключает манифест
                resp = await client.get("/admin")
                assert resp.status == 200
                html = await resp.text()
                assert 'rel="manifest" href="/manifest.webmanifest"' in html
    finally:
        await bot.close()
