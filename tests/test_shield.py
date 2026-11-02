"""Экран от сканеров: path'ы и User-Agent'ы глушатся до хендлеров."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.core.overlay import Overlay
from app.core.webpanel.payload import _SCAN_LIMIT
from app.core.webpanel.webpanel import WebPanel


@pytest.mark.asyncio
async def test_panel_scanner_paths_and_ua_are_blocked(make_panel_bot):
    bot = make_panel_bot()
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            # Нормальный трафик не задет — проверяем до сканов, иначе сработает бан IP.
            ok = await client.get("/admin")
            assert ok.status == 200

            for path in ("/.env", "/wp-login.php", "/xmlrpc.php", "/phpmyadmin"):
                resp = await client.get(path)
                assert resp.status == 404, path

            nikto = await client.get("/admin", headers={"User-Agent": "Mozilla/5.0 Nikto/2.5.0"})
            assert nikto.status == 403


@pytest.mark.asyncio
async def test_panel_scanner_bans_ip_after_repeated_probes(make_panel_bot):
    bot = make_panel_bot()
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            for _ in range(_SCAN_LIMIT):
                assert (await client.get("/.env")).status == 404

            # После бана даже нормальный запрос с того же IP получает 403.
            assert (await client.get("/admin")).status == 403

            # Бан истекает: сбрасываем его вручную, как сделал бы таймаут.
            panel._scan_bans.clear()
            assert (await client.get("/admin")).status == 200


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
