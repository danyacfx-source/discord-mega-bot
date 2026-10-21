"""Публичные статические файлы нового DENDICH оформления."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.core.webpanel import routes
from app.core.webpanel.webpanel import WebPanel


@pytest.mark.asyncio
async def test_radio_silence_assets_have_public_routes(make_panel_bot, monkeypatch, tmp_path):
    """Браузер должен получать новый фон и маркер сборки без авторизации."""
    (tmp_path / "radio-terrain.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><title>DENDICH</title></svg>',
        encoding="utf-8",
    )
    (tmp_path / "brand-version.json").write_text(
        '{"name":"DENDICH","theme":"radio-silence"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(routes, "_DIST_DIR", tmp_path)

    panel = WebPanel(make_panel_bot())
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            response = await client.get("/radio-terrain.svg")
            assert response.status == 200
            assert "DENDICH" in await response.text()
            assert response.headers.get("Content-Type", "").startswith("image/svg+xml")

            version = await client.get("/brand-version.json")
            assert version.status == 200
            data = await version.json()
            assert data["theme"] == "radio-silence"
            assert version.headers.get("Cache-Control") == "no-store"


@pytest.mark.asyncio
async def test_missing_brand_file_is_404(make_panel_bot, monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "_DIST_DIR", tmp_path)
    panel = WebPanel(make_panel_bot())
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            response = await client.get("/radio-terrain.svg")
            assert response.status == 404
