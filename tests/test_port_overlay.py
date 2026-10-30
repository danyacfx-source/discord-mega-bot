"""Тесты overlay-сервера: health, токен-гейт, заголовки, API."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.core.crypto import decrypt_text, is_encrypted
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
    assert is_encrypted(saved), "токен на диске должен лежать зашифрованным"
    plain = decrypt_text(saved)
    assert len(plain) >= 16
    overlay2 = Overlay(bot)
    assert overlay2._token == plain


@pytest.mark.asyncio
async def test_overlay_token_survives_redeploy_via_kv(tmp_path, make_panel_bot):
    """Файл .overlay-token умер при редеплое — токен восстанавливается из БД, виджеты OBS живут."""
    from types import SimpleNamespace

    from app.db.database import Database
    from app.db.kv_repository import KvRepository
    from app.services.kv_service import KvService

    bot = make_panel_bot()
    bot.db = Database(bot.config.database_url or bot.config.db_path)
    await bot.db.connect()
    bot.services = SimpleNamespace(kv=KvService(KvRepository(bot.db)))  # type: ignore[assignment]
    try:
        first = Overlay(bot)
        await first._sync_token_to_kv()
        token = first._token
        stored = await bot.services.kv.get(Overlay._KV_KEY)
        assert is_encrypted(stored), "токен в KV должен лежать зашифрованным"
        assert decrypt_text(stored) == token

        (tmp_path / ".overlay-token").unlink()
        second = Overlay(bot)
        assert second._token != token, "без файла сгенерирован новый токен"
        await second._sync_token_to_kv()
        assert second._token == token, "токен должен вернуться из БД"
        assert token in second._page, "страница оверлея пересобрана с восстановленным токеном"
    finally:
        await bot.db.close()
