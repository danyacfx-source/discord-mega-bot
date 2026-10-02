"""Вебпанель: конструктор welcome-карточки (/api/welcome и превью PNG)."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.config import Config
from app.core.bot import MegaBot
from app.core.webpanel.webpanel import WebPanel
from app.utils.welcome_card import WelcomePreset


def _panel(tmp_path) -> MegaBot:
    config = Config(
        token="x",
        prefix="!",
        db_path=str(tmp_path / "bot.db"),
        log_level="ERROR",
        status_activity="s",
        owner_id=None,
        panel_port=17893,
    )
    return MegaBot(config)


@pytest.mark.asyncio
async def test_welcome_api_roundtrip(tmp_path):
    bot = _panel(tmp_path)
    await bot.setup_hook()
    panel = WebPanel(bot)
    headers = {"X-Panel-Token": panel._static_token or ""}
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                # дефолт: сохранённого пресета нет
                resp = await client.get("/api/welcome", headers=headers)
                assert resp.status == 200
                body = await resp.json()
                assert body["ok"] and body["custom"] is False
                assert body["preset"]["bg_top"] == "#1e2444"

                # сохранение кастомного пресета
                resp = await client.post(
                    "/api/welcome",
                    json={"preset": {"bg_top": "#ff0000", "name_color": "#00ff00", "avatar_size": 200}},
                    headers=headers,
                )
                body = await resp.json()
                assert body["ok"] and body["custom"] is True

                # читается и из KV, и обратно через GET
                stored = WelcomePreset.from_json(await bot.services.kv.get("welcome_preset"))
                assert stored.bg_top == "#ff0000"
                assert stored.avatar_size == 200
                resp = await client.get("/api/welcome", headers=headers)
                body = await resp.json()
                assert body["custom"] is True and body["preset"]["bg_top"] == "#ff0000"

                # превью — валидный PNG
                resp = await client.post(
                    "/api/welcome/preview",
                    json={"preset": body["preset"], "name": "Алиса", "guild": "Тест", "count": 7},
                    headers=headers,
                )
                assert resp.status == 200
                assert resp.headers["Content-Type"] == "image/png"
                assert (await resp.read())[:8] == b"\x89PNG\r\n\x1a\n"

                # сброс к дефолту
                resp = await client.post("/api/welcome", json={"reset": True}, headers=headers)
                body = await resp.json()
                assert body["ok"] and body["custom"] is False
                assert await bot.services.kv.get("welcome_preset") is None
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_welcome_preview_rejects_garbage_preset(tmp_path):
    bot = _panel(tmp_path)
    await bot.setup_hook()
    panel = WebPanel(bot)
    headers = {"X-Panel-Token": panel._static_token or ""}
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                resp = await client.post(
                    "/api/welcome/preview",
                    json={"preset": {"bg_top": "red", "font_scale": "мусор"}, "name": ""},
                    headers=headers,
                )
                # невалидные поля деградируют к дефолтам — превью всё равно строится
                assert resp.status == 200
                assert (await resp.read())[:8] == b"\x89PNG\r\n\x1a\n"
    finally:
        await bot.close()
