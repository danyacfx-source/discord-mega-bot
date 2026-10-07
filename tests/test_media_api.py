"""Вебпанель: медиатека (/api/media) — добавление, лайки, удаление, деградация KV."""
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
        panel_port=17896,
    )
    return MegaBot(config)


@pytest.mark.asyncio
async def test_media_crud_and_likes(tmp_path):
    bot = _panel(tmp_path)
    await bot.setup_hook()
    panel = WebPanel(bot)
    headers = {"X-Panel-Token": panel._static_token or ""}
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                # пустая галерея
                resp = await client.get("/api/media", headers=headers)
                assert resp.status == 200
                body = await resp.json()
                assert body["ok"] and body["items"] == []

                # добавление с тегами строкой
                resp = await client.post(
                    "/api/media",
                    json={"title": "Кадр со стрима", "url": "/uploads/a1.png", "tags": "стрим, сакура", "public": True},
                    headers=headers,
                )
                assert resp.status == 200
                body = await resp.json()
                assert body["ok"]
                item = body["item"]
                assert item["type"] == "image"
                assert item["tags"] == ["стрим", "сакура"]
                assert item["public"] is True
                assert item["likes"] == 0 and item["liked"] is False

                # javascript-ссылки не принимаются
                resp = await client.post(
                    "/api/media",
                    json={"title": "x", "url": "javascript:alert(1)"},
                    headers=headers,
                )
                assert resp.status == 400

                # gif определяется по расширению
                resp = await client.post(
                    "/api/media",
                    json={"title": "Мем", "url": "/uploads/b2.gif"},
                    headers=headers,
                )
                body = await resp.json()
                assert body["ok"] and body["item"]["type"] == "gif"
                gif_id = body["item"]["id"]

                # список: два элемента, свежий сверху
                resp = await client.get("/api/media", headers=headers)
                body = await resp.json()
                assert body["count"] == 2
                assert body["items"][0]["id"] == gif_id

                # лайк: включили и выключили
                resp = await client.post(f"/api/media/{item['id']}/like", headers=headers)
                body = await resp.json()
                assert body["ok"] and body["likes"] == 1 and body["liked"] is True
                resp = await client.post(f"/api/media/{item['id']}/like", headers=headers)
                body = await resp.json()
                assert body["ok"] and body["likes"] == 0 and body["liked"] is False

                # неизвестный id → 404
                resp = await client.post("/api/media/deadbeef/like", headers=headers)
                assert resp.status == 404

                # удаление
                resp = await client.delete(f"/api/media/{item['id']}", headers=headers)
                assert resp.status == 200
                resp = await client.get("/api/media", headers=headers)
                body = await resp.json()
                assert body["count"] == 1
                resp = await client.delete(f"/api/media/{item['id']}", headers=headers)
                assert resp.status == 404
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_media_corrupt_kv_degrades(tmp_path):
    bot = _panel(tmp_path)
    await bot.setup_hook()
    panel = WebPanel(bot)
    headers = {"X-Panel-Token": panel._static_token or ""}
    try:
        await bot.services.kv.set("panel.media.gallery", "мусор{{{")
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/media", headers=headers)
                assert resp.status == 200
                body = await resp.json()
                assert body["ok"] and body["items"] == []
    finally:
        await bot.close()
