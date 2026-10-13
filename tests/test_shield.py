"""Экран от сканеров: path'ы и User-Agent'ы глушатся до хендлеров."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.core.overlay import Overlay
from app.core.webpanel.webpanel import WebPanel


@pytest.mark.asyncio
async def test_panel_scanner_paths_and_ua_are_blocked(make_panel_bot):
    bot = make_panel_bot()
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            for path in ("/.env", "/wp-login.php", "/xmlrpc.php", "/phpmyadmin", "/.git/HEAD"):
                resp = await client.get(path)
                assert resp.status == 404, path

            nikto = await client.get("/admin", headers={"User-Agent": "Mozilla/5.0 Nikto/2.5.0"})
            assert nikto.status == 403

            sqlmap = await client.get("/api/status", headers={"User-Agent": "sqlmap/1.7.2#stable"})
            assert sqlmap.status == 403

            # Нормальный трафик не задет.
            ok = await client.get("/admin")
            assert ok.status == 200


@pytest.mark.asyncio
async def test_overlay_scanner_paths_and_ua_are_blocked(make_panel_bot):
    bot = make_panel_bot(overlay_token="overlay-secret-token-32chars")
    overlay = Overlay(bot)
    async with TestServer(overlay._create_app()) as server:
        async with TestClient(server) as client:
            assert (await client.get("/.env")).status == 404
            assert (await client.get("/.git/config")).status == 404

            nmap = await client.get(
                "/overlay/health", headers={"User-Agent": "Mozilla/5.0 (Nmap Scripting Engine)"}
            )
            assert nmap.status == 403

            health = await client.get("/overlay/health")
            assert health.status == 200
