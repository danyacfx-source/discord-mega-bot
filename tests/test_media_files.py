"""Хранилище файлов панели в БД: выживает при удалении FS-каталога (редеплой)."""
from __future__ import annotations

import shutil

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.core.webpanel.webpanel import WebPanel
from app.db.database import Database

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


async def _boot_db(bot) -> None:
    """Реальная SQLite без setup_hook: загрузкам нужен только bot.db."""
    bot.db = Database(bot.config.database_url or bot.config.db_path)
    await bot.db.connect()


async def _upload(client: TestClient, headers: dict[str, str]) -> str:
    fd = aiohttp.FormData()
    fd.add_field("file", _PNG, filename="kadr.png", content_type="image/png")
    resp = await client.post("/api/upload", data=fd, headers=headers)
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    return str(body["name"])


@pytest.mark.asyncio
async def test_upload_survives_fs_wipe(make_panel_bot):
    """Симуляция редеплоя: uploads-каталог уничтожен — файл отдаётся из БД."""
    bot = make_panel_bot()
    await _boot_db(bot)
    panel = WebPanel(bot)
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                headers = {"X-Panel-Token": panel._static_token or ""}
                name = await _upload(client, headers)

                shutil.rmtree(panel._uploads_dir, ignore_errors=True)

                got = await client.get("/uploads/" + name)
                assert got.status == 200
                assert await got.read() == _PNG
                assert "image/png" in got.headers.get("Content-Type", "")
                assert "immutable" in got.headers.get("Cache-Control", "")

                listed = await client.get("/api/uploads", headers=headers)
                body = await listed.json()
                assert body["ok"] is True
                assert [f["name"] for f in body["files"]] == [name]
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_serve_upload_falls_back_to_fs_and_imports(make_panel_bot):
    """Легаси-файл в data/uploads отдаётся и импортируется в БД при первом GET."""
    bot = make_panel_bot()
    await _boot_db(bot)
    panel = WebPanel(bot)
    name = "c" * 32 + ".png"
    try:
        panel._uploads_dir.mkdir(parents=True, exist_ok=True)
        (panel._uploads_dir / name).write_bytes(_PNG)
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                got = await client.get("/uploads/" + name)
                assert got.status == 200
                assert await got.read() == _PNG

                # импортирован в БД: копию в FS удаляем — файл всё равно отдаётся
                (panel._uploads_dir / name).unlink()
                again = await client.get("/uploads/" + name)
                assert again.status == 200
                assert await again.read() == _PNG
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_delete_removes_fs_copy_no_resurrect(make_panel_bot):
    """DELETE чистит и БД, и FS-копию: fallback не воскрешает удалённый файл."""
    bot = make_panel_bot()
    await _boot_db(bot)
    panel = WebPanel(bot)
    name = "d" * 32 + ".png"
    try:
        panel._uploads_dir.mkdir(parents=True, exist_ok=True)
        (panel._uploads_dir / name).write_bytes(_PNG)
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                headers = {"X-Panel-Token": panel._static_token or ""}
                assert (await client.get("/uploads/" + name)).status == 200

                resp = await client.delete("/api/uploads/" + name, headers=headers)
                assert resp.status == 200
                assert (await client.get("/uploads/" + name)).status == 404
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_serve_upload_rejects_bad_name(make_panel_bot):
    """Имя вне uuid-формата (в т.ч. path traversal) — 404."""
    bot = make_panel_bot()
    await _boot_db(bot)
    panel = WebPanel(bot)
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                assert (await client.get("/uploads/not-a-uuid.png")).status == 404
                assert (await client.get("/uploads/..%2F..%2Fetc.png")).status == 404
    finally:
        await bot.close()
