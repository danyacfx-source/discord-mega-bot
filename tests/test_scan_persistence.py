"""Нарушители сканирования переживают рестарт и уведомляют владельца."""
from __future__ import annotations

import json

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
async def test_scan_location_survives_restart_and_is_not_erased(make_panel_bot):
    bot = make_panel_bot()
    await _boot_db(bot)
    try:
        panel = WebPanel(bot)
        await panel._save_scan_ban("10.0.0.6", 1, 5e9, "Frankfurt, DE")
        await panel._save_scan_ban("10.0.0.6", 2, 5e9)  # повторный бан без заголовков
        restarted = WebPanel(bot)
        await restarted._restore_scan_state()
        assert restarted._scan_locations["10.0.0.6"] == "Frankfurt, DE"
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


@pytest.mark.asyncio
async def test_probes_during_active_ban_are_counted(make_panel_bot):
    bot = make_panel_bot()
    await _boot_db(bot)
    try:
        panel = WebPanel(bot)
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                await _probe_until_banned(client)
                count_before, _ = panel._scan_offenses["127.0.0.1"]
                # Бан активен: дополнительные попытки продолжают эскалацию.
                await _probe_until_banned(client)
                count_after, _ = panel._scan_offenses["127.0.0.1"]
        assert count_after == count_before + 1
    finally:
        await bot.db.close()


class _FakeRequest:
    """Запрос администратора с другого IP: сам забаненный IP до панели не достучится."""

    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_unban_clears_ban_but_keeps_counter(make_panel_bot):
    bot = make_panel_bot()
    await _boot_db(bot)
    try:
        panel = WebPanel(bot)
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                await _probe_until_banned(client)
        assert "127.0.0.1" in panel._scan_bans

        listing = await panel._api_scan_bans_get(_FakeRequest({}))
        items = json.loads(listing.text)["items"]
        assert items[0]["ip"] == "127.0.0.1"
        assert items[0]["banned"] is True

        cleared = await panel._api_scan_ban_clear(_FakeRequest({"ip": "127.0.0.1"}))
        assert cleared.status == 200
        assert "127.0.0.1" not in panel._scan_bans
        assert panel._scan_offenses["127.0.0.1"][0] == 1
        restarted = WebPanel(bot)
        await restarted._restore_scan_state()
        assert "127.0.0.1" not in restarted._scan_bans
        assert restarted._scan_offenses["127.0.0.1"][0] == 1

        missing = await panel._api_scan_ban_clear(_FakeRequest({"ip": "10.9.9.9"}))
        assert missing.status == 404
    finally:
        await bot.db.close()


@pytest.mark.asyncio
async def test_clear_scan_ban_helper_keeps_counter_and_reports_unknown_ip(make_panel_bot):
    bot = make_panel_bot()
    await _boot_db(bot)
    try:
        panel = WebPanel(bot)
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                await _probe_until_banned(client)
        assert await panel.clear_scan_ban("127.0.0.1", "тест") == 1
        assert "127.0.0.1" not in panel._scan_bans
        assert await panel.clear_scan_ban("10.9.9.9", "тест") is None
    finally:
        await bot.db.close()


@pytest.mark.asyncio
async def test_scanbans_unban_command_is_owner_only_and_clears_ban(make_panel_bot):
    from app.cogs.administration.scan_bans import ScanBansCog

    bot = make_panel_bot()
    await _boot_db(bot)
    try:
        panel = WebPanel(bot)
        bot.webpanel = panel
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                await _probe_until_banned(client)
        cog = ScanBansCog(bot)
        assert "127.0.0.1" in panel._scan_bans

        class _Resp:
            def __init__(self):
                self.messages = []

            async def send_message(self, text=None, **kwargs):
                self.messages.append(text or kwargs.get("embed"))

        class _Interaction:
            def __init__(self, user_id):
                self.user = type("U", (), {"id": user_id, "__str__": lambda s: "u"})()
                self.response = _Resp()

        assert cog.unban.checks, "команда должна быть закрыта проверкой is_owner"
        owner = _Interaction(user_id=bot.config.owner_id)
        await cog.unban.callback(cog, owner, "127.0.0.1")
        assert "127.0.0.1" not in panel._scan_bans
        assert "снят" in owner.response.messages[0]
    finally:
        await bot.db.close()
