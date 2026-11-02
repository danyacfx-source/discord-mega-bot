"""Нарушители сканирования переживают рестарт и уведомляют владельца."""
from __future__ import annotations

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.core.webpanel.payload import _SCAN_LIMIT
from app.core.webpanel.webpanel import WebPanel
from app.db.database import Database


async def _boot_db(bot) -> None:
    bot.db = Database(bot.config.database_url or bot.config.db_path)
    await bot.db.connect()


async def _probe_until_banned(client: TestClient) -> None:
    for _ in range(_SCAN_LIMIT):
        await client.get("/.env")


@pytest.mark.asyncio
async def test_scan_offenses_and_bans_survive_restart(make_panel_bot):
    bot = make_panel_bot()
    await _boot_db(bot)
    try:
        panel = WebPanel(bot)
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                await _probe_until_banned(client)
                panel._scan_bans.clear()  # бан истёк, нарушитель вернулся
                await _probe_until_banned(client)
                count, until = panel._scan_offenses["127.0.0.1"]
        assert count == 2
        # Имитируем рестарт: новый процесс знает только БД.
        restarted = WebPanel(bot)
        await restarted._restore_scan_state()
        assert restarted._scan_offenses["127.0.0.1"] == (count, until)
        assert restarted._scan_bans["127.0.0.1"] == until
    finally:
        await bot.db.close()


@pytest.mark.asyncio
async def test_expired_ban_keeps_counter_and_is_not_restored_as_active(make_panel_bot):
    bot = make_panel_bot()
    await _boot_db(bot)
    try:
        panel = WebPanel(bot)
        await panel._save_scan_ban("10.0.0.5", 3, 1.0)  # бан истёк в 1970 году
        restarted = WebPanel(bot)
        await restarted._restore_scan_state()
        assert restarted._scan_offenses["10.0.0.5"] == (3, 1.0)
        assert "10.0.0.5" not in restarted._scan_bans
    finally:
        await bot.db.close()


@pytest.mark.asyncio
async def test_each_ban_notifies_owner(make_panel_bot, monkeypatch):
    bot = make_panel_bot()
    panel = WebPanel(bot)
    calls: list[tuple[str, int]] = []

    async def record(ip, detail, count, until, now):
        calls.append((ip, count))

    monkeypatch.setattr(panel, "_notify_scan_ban", record)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            await _probe_until_banned(client)
    assert calls == [("127.0.0.1", 1)]
