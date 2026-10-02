"""Вебпанель: конструктор карточек стримов (/api/stream-cards)."""
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
        panel_port=17894,
    )
    return MegaBot(config)


@pytest.mark.asyncio
async def test_stream_cards_api_roundtrip(tmp_path):
    bot = _panel(tmp_path)
    await bot.setup_hook()
    panel = WebPanel(bot)
    headers = {"X-Panel-Token": panel._static_token or ""}
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                # дефолт: пресета нет
                resp = await client.get("/api/stream-cards", headers=headers)
                assert resp.status == 200
                body = await resp.json()
                assert body["ok"] and body["preset"] == {}

                # сохранение с вычисткой мусора
                resp = await client.post(
                    "/api/stream-cards",
                    json={
                        "preset": {
                            "live": {
                                "titles": {"twitch": "В эфире"},
                                "colors": {"kick": "53FC18", "twitch": "не цвет"},
                                "footer": "Эфир • {bot}",
                                "fields": {"viewers": "Зрели", "bogus": "мусор"},
                            }
                        }
                    },
                    headers=headers,
                )
                body = await resp.json()
                assert body["ok"] and body["custom"] is True
                live = body["preset"]["live"]
                assert live["titles"] == {"twitch": "В эфире"}
                assert live["colors"] == {"kick": "#53FC18"}
                assert live["fields"] == {"viewers": "Зрели"}
                assert "bogus" not in live["fields"]

                # читается из KV и обратно через GET
                resp = await client.get("/api/stream-cards", headers=headers)
                body = await resp.json()
                assert body["preset"]["live"]["footer"] == "Эфир • {bot}"

                # сброс
                resp = await client.post("/api/stream-cards", json={"reset": True}, headers=headers)
                body = await resp.json()
                assert body["ok"] and body["custom"] is False
                assert await bot.services.kv.get("stream:cards") is None
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_stream_cards_get_survives_corrupt_kv(tmp_path):
    bot = _panel(tmp_path)
    await bot.setup_hook()
    panel = WebPanel(bot)
    headers = {"X-Panel-Token": panel._static_token or ""}
    try:
        await bot.services.kv.set("stream:cards", "сломанный json{{{")
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                resp = await client.get("/api/stream-cards", headers=headers)
                assert resp.status == 200
                body = await resp.json()
                assert body["ok"] and body["preset"] == {}, "мусор в KV деградирует в дефолт"
    finally:
        await bot.close()
