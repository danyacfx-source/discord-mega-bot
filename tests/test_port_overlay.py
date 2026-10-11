"""Тесты overlay-сервера: health, токен-гейт, заголовки, API."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.core.overlay import Overlay


@pytest.mark.asyncio
async def test_overlay_server(make_panel_bot):
    bot = make_panel_bot(overlay_token="overlay-secret-token-32chars")
    overlay = Overlay(bot)
    assert overlay._token == "overlay-secret-token-32chars"
    async with TestServer(overlay._create_app()) as server:
        async with TestClient(server) as client:
            health = await client.get("/overlay/health")
            assert health.status == 200
            assert (await health.json())["ok"] is True

            page = await client.get("/overlay")
            assert page.status == 401

            ok_page = await client.get("/overlay?token=overlay-secret-token-32chars")
            assert ok_page.status == 200
            assert "Overlay" in await ok_page.text()
            assert ok_page.headers.get("X-Content-Type-Options") == "nosniff"
            assert ok_page.headers.get("X-Frame-Options") == "SAMEORIGIN"
            assert ok_page.headers.get("Referrer-Policy") == "no-referrer"
            assert ok_page.headers.get("Cache-Control") == "no-store"
            csp = ok_page.headers.get("Content-Security-Policy", "")
            assert "default-src 'self'" in csp and "object-src 'none'" in csp

            api = await client.get("/overlay/api")
            assert api.status == 401

            api_ok = await client.get("/overlay/api", headers={"X-Overlay-Token": "overlay-secret-token-32chars"})
            assert api_ok.status == 200
            data = await api_ok.json()
            assert data["stream"] is None and data["channels"] == {}
            assert data["donation_goal"] == {"enabled": False}
            assert api_ok.headers.get("Cache-Control") == "no-store"


@pytest.mark.asyncio
async def test_overlay_token_file(tmp_path, make_panel_bot):
    bot = make_panel_bot()
    Overlay(bot)
    token_file = tmp_path / ".overlay-token"
    assert token_file.exists()
    saved = token_file.read_text(encoding="utf-8").strip()
    assert len(saved) >= 16
    overlay2 = Overlay(bot)
    assert overlay2._token == saved
