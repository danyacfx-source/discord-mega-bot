"""Вебпанель: прокси /overlay* на локальный оверлей-сервер (один порт на домен)."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.config import Config
from app.core.bot import MegaBot
from app.core.overlay.layout import default_layout, save_layout
from app.core.webpanel.webpanel import WebPanel

_TOKEN = "overlay-secret-token-32chars"


def _bot(tmp_path, panel_port: int, **overrides) -> MegaBot:
    config = Config(
        token="x",
        prefix="!",
        db_path=str(tmp_path / "bot.db"),
        log_level="ERROR",
        status_activity="s",
        owner_id=None,
        panel_port=panel_port,
        **overrides,  # type: ignore[arg-type]
    )
    return MegaBot(config)


@pytest.mark.asyncio
async def test_overlay_proxy_end_to_end(tmp_path) -> None:
    bot = _bot(tmp_path, 17895, overlay_port=18770, overlay_token=_TOKEN)
    await bot.setup_hook()
    panel = WebPanel(bot)
    try:
        await save_layout(bot.services.kv, default_layout("main"))  # type: ignore[union-attr]
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                # без токена оверлей отвечает 401 — заголовок дошёл через прокси
                assert (await client.get("/overlay/api/main")).status == 401
                # запрос уходит в настоящий оверлей на 127.0.0.1:OVERLAY_PORT
                resp = await client.get("/overlay/api/main", headers={"X-Overlay-Token": _TOKEN})
                assert resp.status == 200
                data = await resp.json()
                assert data["layout"]["id"] == "main"
                # хвост пути не искажается
                assert (await client.get("/overlay/nope", headers={"X-Overlay-Token": _TOKEN})).status == 404
                page = await client.get("/overlay", headers={"X-Overlay-Token": _TOKEN})
                assert page.status == 200
                assert "<title>Overlay</title>" in await page.text()
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_overlay_proxy_offline_returns_502(tmp_path) -> None:
    bot = _bot(tmp_path, 17896, overlay_port=18771, overlay_token=_TOKEN)
    await bot.setup_hook()
    panel = WebPanel(bot)
    try:
        # setup_hook поднимает оверлей — глушим, чтобы получить адрес без слушателя
        await bot.overlay.stop()
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                resp = await client.get("/overlay/api/main")
                assert resp.status == 502
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_overlay_proxy_disabled_returns_404(tmp_path) -> None:
    bot = _bot(tmp_path, 17897)
    await bot.setup_hook()
    panel = WebPanel(bot)
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                resp = await client.get("/overlay")
                assert resp.status == 404
    finally:
        await bot.close()
