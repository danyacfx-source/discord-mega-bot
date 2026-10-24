"""Конструктор оверлея: схема раскладок, KV-хранилище, страница рендера, API панели."""
from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.config import Config
from app.core.bot import MegaBot
from app.core.overlay.layout import (
    MAX_WIDGETS,
    default_layout,
    delete_layout,
    list_layouts,
    load_layout,
    new_id,
    sanitize_layout,
    save_layout,
    save_layouts,
)
from app.core.overlay.overlay import Overlay
from app.core.webpanel.webpanel import WebPanel, overlay_url_base

ROOT = Path(__file__).resolve().parent.parent


class _KV:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str, default: str | None = None) -> str | None:
        return self.data.get(key, default)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None


def _config(tmp_path, **overrides) -> Config:
    values = {
        "token": "x",
        "prefix": "!",
        "db_path": str(tmp_path / "bot.db"),
        "log_level": "ERROR",
        "status_activity": "s",
        "owner_id": None,
        **overrides,
    }
    return Config(**values)  # type: ignore[arg-type]


def test_sanitize_rejects_garbage() -> None:
    layout = sanitize_layout(
        {
            "width": "мусор",
            "widgets": [
                {"type": "evil"},
                "junk",
                {"type": "text", "props": {"size": 99999, "color": "red", "align": "diagonal"}},
            ],
        },
        layout_id="x",
    )
    assert layout["width"] == 1920
    assert len(layout["widgets"]) == 1
    props = layout["widgets"][0]["props"]
    assert props["size"] == 120
    assert props["color"] == "#ffffff"
    assert props["align"] == "left"


def test_sanitize_caps_widgets_and_clamps_boxes() -> None:
    widgets = [{"type": "text", "x": -500, "y": 99999, "w": 99999, "h": 1} for _ in range(MAX_WIDGETS + 10)]
    layout = sanitize_layout({"width": 800, "height": 600, "widgets": widgets}, layout_id="a")
    assert len(layout["widgets"]) == MAX_WIDGETS
    first = layout["widgets"][0]
    assert first["w"] <= 800
    assert first["h"] >= 30
    assert first["x"] >= 0
    assert first["y"] + first["h"] <= 600


def test_sanitize_chat_widget_props() -> None:
    layout = sanitize_layout(
        {"widgets": [{"type": "chat", "props": {"limit": 9999, "title": "   ", "bg": "red"}}]},
        layout_id="c",
    )
    props = layout["widgets"][0]["props"]
    assert props["limit"] == 25, "лимит сообщений зажат верхней границей виджета"
    assert props["title"] == "", "пустой заголовок выключает шапку виджета"
    assert props["bg"] == ""


def test_chat_titles_default_when_key_missing() -> None:
    layout = sanitize_layout(
        {"widgets": [{"type": "chat", "props": {}}, {"type": "chat_top", "props": {}}, {"type": "chat", "props": {"title": "Своя"}}]},
        layout_id="t",
    )
    titles = [w["props"]["title"] for w in layout["widgets"]]
    assert titles == ["Лента чата", "Топ чата", "Своя"], "без ключа — дефолт, с пустым значением — без шапки"


def test_layout_page_renders_headers_only_when_title_set() -> None:
    html = (ROOT / "app" / "core" / "overlay" / "layout.html").read_text(encoding="utf-8")
    assert 'function h3(t){return t?"<h3>"+esc(t)+"</h3>":""}' in html
    assert 'h3(p.title||"Лента чата")' not in html
    assert 'h3(p.title||"Топ чата")' not in html


def test_default_layout_has_widgets() -> None:
    layout = default_layout("abc123")
    assert layout["id"] == "abc123"
    assert {w["type"] for w in layout["widgets"]} == {"stream", "goal", "donation", "chat_top"}


@pytest.mark.asyncio
async def test_layout_kv_roundtrip() -> None:
    kv = _KV()
    assert await list_layouts(kv) == []
    saved = await save_layout(kv, default_layout(new_id()))
    await save_layouts(kv, [{"id": saved["id"], "name": saved["name"]}])
    assert (await list_layouts(kv))[0]["name"] == "Основная"
    assert await load_layout(kv, saved["id"]) == saved
    assert await load_layout(kv, "../evil") is None
    assert await load_layout(kv, "absent") is None
    assert await delete_layout(kv, saved["id"]) is True
    assert await list_layouts(kv) == []
    assert await load_layout(kv, saved["id"]) is None


@pytest.mark.asyncio
async def test_overlay_layout_page_and_api(tmp_path) -> None:
    config = _config(tmp_path, overlay_token="overlay-secret-token-32chars")
    bot = MegaBot(config)
    await bot.setup_hook()
    overlay = Overlay(bot)
    try:
        saved = await save_layout(bot.services.kv, default_layout("main"))  # type: ignore[union-attr]
        await save_layouts(bot.services.kv, [{"id": saved["id"], "name": saved["name"]}])  # type: ignore[union-attr]
        bot.services.chat_feed.push("kick", "Алиса", "привет эфиру", is_mod=True)  # type: ignore[union-attr]
        async with TestServer(overlay._create_app()) as server:
            async with TestClient(server) as client:
                headers = {"X-Overlay-Token": "overlay-secret-token-32chars"}
                # без токена — 401
                assert (await client.get("/overlay/main")).status == 401
                assert (await client.get("/overlay/api/main")).status == 401
                # страница и API раскладки
                page = await client.get("/overlay/main", headers=headers)
                assert page.status == 200
                assert "Overlay layout" in await page.text()
                api = await client.get("/overlay/api/main", headers=headers)
                assert api.status == 200
                data = await api.json()
                assert data["layout"]["id"] == "main"
                assert len(data["layout"]["widgets"]) == 4
                assert data["data"]["donation_goal"] == {"enabled": False}
                assert data["data"]["chat_top"] == []
                assert data["data"]["chat"][0]["name"] == "Алиса"
                assert data["data"]["chat"][0]["mod"] is True
                # неизвестная раскладка — 404; старые маршруты не тронуты
                assert (await client.get("/overlay/nope", headers=headers)).status == 404
                assert (await client.get("/overlay/api", headers=headers)).status == 200
                assert (await client.get("/overlay", headers=headers)).status == 200
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_webpanel_overlay_api_roundtrip(tmp_path) -> None:
    config = _config(tmp_path, panel_port=17894)
    bot = MegaBot(config)
    await bot.setup_hook()
    panel = WebPanel(bot)
    headers = {"X-Panel-Token": panel._static_token or ""}
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                body = await (await client.get("/api/overlay", headers=headers)).json()
                assert body["ok"] and body["layouts"] == []
                assert body["enabled"] is False and body["token"] == ""
                assert body["url_base"] == ""

                body = await (await client.post("/api/overlay/layouts", json={"name": "Моя"}, headers=headers)).json()
                assert body["ok"] and body["layout"]["name"] == "Моя"
                layout_id = body["layout"]["id"]
                assert len(body["layout"]["widgets"]) == 4

                # сохранение: имя и виджеты меняются
                body["layout"]["name"] = "Моя v2"
                body["layout"]["widgets"] = body["layout"]["widgets"][:2]
                saved = await (await client.post("/api/overlay/layout", json={"layout": body["layout"]}, headers=headers)).json()
                assert saved["ok"] and saved["layout"]["name"] == "Моя v2"
                assert len(saved["layout"]["widgets"]) == 2
                assert [item["name"] for item in saved["layouts"]] == ["Моя v2"]

                # переименование и удаление
                renamed = await (
                    await client.post("/api/overlay/layout/rename", json={"id": layout_id, "name": "Финал"}, headers=headers)
                ).json()
                assert renamed["ok"] and renamed["layouts"][0]["name"] == "Финал"
                deleted = await (await client.post("/api/overlay/layout/delete", json={"id": layout_id}, headers=headers)).json()
                assert deleted["ok"] and deleted["layouts"] == []
                again = await (await client.post("/api/overlay/layout/delete", json={"id": layout_id}, headers=headers)).json()
                assert again["ok"] is False
    finally:
        await bot.close()


def test_overlay_url_base(tmp_path) -> None:
    cfg = _config(tmp_path, overlay_port=8765, overlay_host="0.0.0.0", overlay_public_url="https://dendich.ru")
    assert overlay_url_base(cfg) == "https://dendich.ru"
    object.__setattr__(cfg, "overlay_public_url", None)
    assert overlay_url_base(cfg) == ""
    object.__setattr__(cfg, "overlay_host", "127.0.0.1")
    assert overlay_url_base(cfg) == "http://127.0.0.1:8765"
    object.__setattr__(cfg, "overlay_port", None)
    assert overlay_url_base(cfg) == ""


@pytest.mark.asyncio
async def test_chat_overlay_page(tmp_path) -> None:
    config = _config(tmp_path, overlay_token="overlay-secret-token-32chars")
    bot = MegaBot(config)
    await bot.setup_hook()
    overlay = Overlay(bot)
    try:
        bot.services.chat_feed.push("kick", "Алиса", "привет эфиру")  # type: ignore[union-attr]
        async with TestServer(overlay._create_app()) as server:
            async with TestClient(server) as client:
                headers = {"X-Overlay-Token": "overlay-secret-token-32chars"}
                # без токена — 401; маршрут /overlay/chat не перехватывается раскладкой
                assert (await client.get("/overlay/chat")).status == 401
                page = await client.get("/overlay/chat", headers=headers)
                assert page.status == 200
                html = await page.text()
                assert 'id="feed"' in html
                assert "overlay-secret-token-32chars" in html
                assert "__TOKEN__" not in html
                # прозрачный фон: цвет ника по платформе (твич/ютуб/кик), без бейджей платформ
                assert "--bg,transparent" in html
                assert "#9146ff" in html and "#ff0000" in html and "#53fc18" in html
                assert "nickColor(m.platform)" in html
                assert ".badge" not in html
                assert 'body class="idle"' in html
                assert '"X-Overlay-Token"' in html
                # общая выдача /overlay/api теперь несёт ленту чата
                data = await (await client.get("/overlay/api", headers=headers)).json()
                assert data["chat"][0]["name"] == "Алиса"
                assert data["chat"][0]["text"] == "привет эфиру"
    finally:
        await bot.close()
