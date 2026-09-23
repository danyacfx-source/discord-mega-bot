"""Тесты портированных модулей: конфиг, новые репозитории и DI стрим-сервисов."""
from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta

import discord
import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.config import Config
from app.core.bot import MegaBot
from app.core.overlay import Overlay
from app.core.webpanel.webpanel import (
    _LOGIN_LIMIT,
    WebPanel,
    _components_from_raw,
    _embed_from_dict,
    _trim_components,
    _trim_embeds,
)
from app.db.birthdays_repository import BirthdaysRepository
from app.db.database import Database
from app.db.donations_repository import DonationsRepository
from app.db.kv_repository import KvRepository
from app.db.scheduled_repository import ScheduledRepository
from app.db.temp_voices_repository import TempVoicesRepository
from app.services.birthday_service import BirthdayService
from app.services.donation_service import DonationService
from app.services.kick_service import KickService
from app.services.scheduler_service import ScheduledMessagesService
from app.services.temp_voice_service import TempVoiceService
from app.services.twitch_service import TwitchService


def test_panel_js_token_header():
    from app.core.webpanel.webpanel import _SCRIPT_PATH

    body = _SCRIPT_PATH.read_text(encoding="utf-8")
    assert '"X-Panel-Token"' in body
    assert '"X-Bot-Token"' not in body


def test_config_new_options(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "BOT_TOKEN=t",
                "TWITCH_CHANNELS=a,b",
                "TEMP_VOICE_TRIGGER_IDS=111,222",
                "LOGS_IGNORE_CHANNEL_IDS=5",
                "KICK_BAN_WORDS=слово1,слово2",
                "RULES_MESSAGE_ID=42",
                "DONATION_NOTIFY_CHANNEL_ID=777",
                "DONATION_MIN_AMOUNT=150",
                "DONATION_ROLE_ID=7331",
                "DONATE_BUTTON_CHANNEL_ID=2311",
                "DONATE_BONUSES=Смотреть раньше,Проверка",
                "PANEL_PORT=17890",
                "OVERLAY_PORT=8765",
                "OVERLAY_HOST=127.0.0.1",
                "OVERLAY_TOKEN=overlay-secret-token-32chars",
                "OVERLAY_DONATION_GOAL_ENABLED=1",
                "OVERLAY_DONATION_GOAL_TARGET=500",
                "OVERLAY_DONATION_GOAL_LABEL=Планка",
                "RAM_REPORT_CHANNEL_ID=4242",
                "RAM_REPORT_INTERVAL_MINUTES=15",
                "RAM_REPORT_TRACEMALLOC=0",
                "LOGS_IGNORE_CATEGORY_IDS=111,222",
                "BIRTHDAY_CHANNEL_ID=31337",
                "BIRTHDAY_ANNOUNCE_HOUR=27",
                "BIRTHDAY_PING_ROLE_ID=555",
                "STATUS_ACTIVITY=Стрим офлайн",
                "ROLE_MENU_CHANNEL_ID=7777",
                "ROLE_MENU_ROLES=War Thunder,Minecraft",
                "ROLE_MENU_MAX_VALUES=2",
                "GUILD_ID=1524743223866556456",
                "AI_ENABLED=1",
                "AI_CHANNELS=11,22",
                "AI_MODEL=gemini-3.6-flash",
                "AI_COOLDOWN_SECONDS=7",
                "AI_TEMPERATURE=0.5",
                "AI_MAX_TOKENS=333",
                "AI_HISTORY_SIZE=5",
                "AI_TIMEOUT_SECONDS=12",
                "GEMINI_API_KEY=key123",
                "WELCOME_CHANNEL_ID=8",
                "WELCOME_SEND_DM=0",
                "WELCOME_FOOTER=foot",
                "WELCOME_HIDDEN_VOICE=[\"Спонсорский войс\"]",
                "AUTOMOD_BANNED_WORDS=а,б,заходи на",
                "AUTOMOD_BLOCK_LINKS=0",
                "AUTOMOD_ALLOWED_LINKS=tv.com",
                "AUTOMOD_CAPS_THRESHOLD=0.9",
                "AUTOMOD_MAX_MESSAGES_IN_WINDOW=7",
                "AUTOMOD_TIMEOUT_SECONDS=120",
                "AUTOMOD_BAN_AFTER_TIMEOUTS=2",
                "AUTOMOD_IGNORE_ROLES=Owner",
                "SOCIALS_DISCORD=https://d",
                "SOCIALS_TWITCH=https://t",
                "SERVER_STATS_ENABLED=1",
                "SERVER_STATS_CATEGORY_ID=9",
                "SERVER_STATS_UPDATE_SECONDS=120",
                "SERVER_STATS_CHANNELS=[{\"type\":\"members\"}]",
                "PERMISSIONS_AUTO_APPLY=1",
            ]
        ),
        encoding="utf-8",
    )
    config = Config.from_env(env)
    assert config.twitch_channels == ("a", "b")
    assert config.temp_voice_trigger_ids == (111, 222)
    assert config.logs_ignore_channel_ids == (5,)
    assert config.kick_ban_words == ("слово1", "слово2")
    assert config.rules_message_id == 42
    assert config.donation_notify_channel_id == 777
    assert config.donation_min_amount == 150.0
    assert config.donation_role_id == 7331
    assert config.donate_button_channel_id == 2311
    assert config.donate_bonuses == ("Смотреть раньше", "Проверка")
    assert config.version == "3.2.0"
    assert config.panel_port == 17890
    assert config.panel_host == "127.0.0.1"
    assert config.overlay_port == 8765
    assert config.overlay_host == "127.0.0.1"
    assert config.overlay_token == "overlay-secret-token-32chars"
    assert config.overlay_donation_goal_enabled is True
    assert config.overlay_donation_goal_target == 500.0
    assert config.overlay_donation_goal_label == "Планка"
    assert config.ram_report_channel_id == 4242
    assert config.ram_report_interval_minutes == 15
    assert config.ram_report_tracemalloc is False
    assert config.logs_ignore_category_ids == (111, 222)
    assert config.birthday_channel_id == 31337
    assert config.birthday_announce_hour == 23  # «27» усекается до 23
    assert config.birthday_ping_role_id == 555
    assert config.status_activity == "Стрим офлайн"
    assert config.role_menu_enabled is True
    assert config.role_menu_channel_id == 7777
    assert config.role_menu_roles == ("War Thunder", "Minecraft")
    assert config.role_menu_max_values == 2
    assert config.guild_id == 1524743223866556456
    assert config.ai_enabled is True
    assert config.ai_channels == (11, 22)
    assert config.ai_model == "gemini-3.6-flash"
    assert config.ai_cooldown_seconds == 7.0
    assert config.ai_temperature == 0.5
    assert config.ai_max_tokens == 333
    assert config.ai_history_size == 5
    assert config.ai_timeout_seconds == 12.0
    assert config.ai_api_key == "key123"
    assert config.welcome_channel_id == 8
    assert config.welcome_send_dm is False
    assert config.welcome_footer == "foot"
    assert config.welcome_hidden_voice == '["Спонсорский войс"]'
    assert config.automod_banned_words == "а,б,заходи на"
    assert config.automod_block_links is False
    assert config.automod_allowed_links == "tv.com"
    assert config.automod_caps_threshold == 0.9
    assert config.automod_max_messages_in_window == 7
    assert config.automod_timeout_seconds == 120
    assert config.automod_ban_after_timeouts == 2
    assert config.automod_ignore_roles == ("Owner",)
    assert config.socials_discord == "https://d"
    assert config.socials_twitch == "https://t"
    assert config.server_stats_enabled is True
    assert config.server_stats_category_id == 9
    assert config.server_stats_update_seconds == 120
    assert config.server_stats_channels.startswith("[{\"type\":\"members\"}]")
    assert config.permissions_auto_apply is True


@pytest.mark.asyncio
async def test_kv_repository_roundtrip(tmp_path):
    db = Database(str(tmp_path / "kv.db"))
    await db.connect()
    try:
        repo = KvRepository(db)
        assert await repo.get("key") is None
        assert await repo.get("key", "def") == "def"
        await repo.set("key", "1")
        assert await repo.get("key") == "1"
        await repo.set("key", "2")
        assert await repo.get("key") == "2"
        assert await repo.delete("key")
        assert await repo.get("key") is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_donations_repository(tmp_path):
    db = Database(str(tmp_path / "donations.db"))
    await db.connect()
    try:
        repo = DonationsRepository(db)
        assert not await repo.is_known(1)
        await repo.record(1, "warlord", 100.0, "RUB", "VIP за мужика", True)
        assert await repo.is_known(1)
        await repo.record(1, "warlord", 100.0, "RUB", "VIP за мужика", True)
        row = await db.fetchone("SELECT COUNT(*) AS total FROM donations")
        assert row["total"] == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_scheduled_messages_repository(tmp_path):
    db = Database(str(tmp_path / "scheduled.db"))
    await db.connect()
    try:
        repo = ScheduledRepository(db)
        future = datetime.now(UTC) + timedelta(minutes=5)
        sid = await repo.create(7, 11, 99, "привет", "", future)
        row = await repo.get(sid)
        assert row is not None and row["done"] == 0
        assert await repo.upcoming(50)
        assert [r["id"] for r in await repo.due_up_to(future + timedelta(seconds=1))] == [sid]
        assert [r["id"] for r in await repo.due_up_to(future - timedelta(seconds=1))] == []
        assert await repo.recent(50)
        await repo.mark_done(sid)
        assert (await repo.get(sid))["done"] == 1
        assert await repo.delete(sid)
        assert await repo.get(sid) is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_scheduled_messages_service(tmp_path):
    db = Database(str(tmp_path / "sched_service.db"))
    await db.connect()
    try:
        repo = ScheduledRepository(db)
        service = ScheduledMessagesService(repo)
        future = datetime.now(UTC) + timedelta(minutes=10)

        with pytest.raises(ValueError):
            await service.create(7, 11, 99, datetime.now(UTC) - timedelta(minutes=1), content="в прошлом")

        embed_schema = {
            "title": "Заголовок",
            "description": "Текст",
            "color": "#FF8800",
        }
        sid = await service.create(7, 11, 99, future, content="привет", embed=embed_schema)
        row = await service.get(sid)
        assert row is not None and row["done"] == 0
        assert await service.upcoming(50)
        assert await service.recent(50)
        assert len(await service.due(future + timedelta(seconds=1))) == 1

        embed = service.build_embed(row)
        assert embed.title == "Заголовок" and embed.description == "Текст"
        assert await service.delete(sid)
        assert await service.get(sid) is None
    finally:
        await db.close()


def test_scheduler_cog_higher_than_panel():
    from app.core.loader import COG_PROVIDERS

    assert "scheduled" in COG_PROVIDERS
    assert callable(COG_PROVIDERS["scheduled"])


@pytest.mark.asyncio
async def test_temp_voices_repository(tmp_path):
    db = Database(str(tmp_path / "tempvoice.db"))
    await db.connect()
    try:
        repo = TempVoicesRepository(db)
        await repo.create(7, 100, datetime.now(UTC))
        assert await repo.channel_of_owner(7) == 100
        assert await repo.owner_of_channel(100) == 7
        assert len(await repo.all()) == 1
        assert await repo.delete_by_channel(100)
        assert await repo.owner_of_channel(100) is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_birthdays_repository(tmp_path):
    db = Database(str(tmp_path / "birthdays.db"))
    await db.connect()
    try:
        repo = BirthdaysRepository(db)
        assert await repo.get(10) is None
        await repo.set(10, 3, 15)
        assert await repo.get(10) == (3, 15)
        await repo.set(10, 12, 31)
        assert await repo.get(10) == (12, 31)
        assert len(await repo.with_date(12, 31)) == 1
        await repo.set(11, 12, 31)
        assert len(await repo.with_date(12, 31)) == 2
        assert await repo.remove(10)
        assert await repo.get(10) is None
        assert len(await repo.all()) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_donation_service_codes(tmp_path):
    db = Database(str(tmp_path / "codes.db"))
    await db.connect()
    try:
        config = Config(
            token="x",
            prefix="!",
            db_path=str(tmp_path / "bot.db"),
            log_level="ERROR",
            status_activity="s",
            owner_id=None,
            donation_role_name="Спонсор",
            donation_role_id=None,
        )
        service = DonationService(DonationsRepository(db), KvRepository(db), config)
        code = await service.create_code(123, 456, "Спонсор", None)
        assert len(code) == 12 and code.startswith("VIP-")
        assert all(ch in "0123456789ABCDEF" for ch in code[4:])
        link = await service.lookup_code(code)
        assert link is not None
        assert link["user_id"] == 123 and link["guild_id"] == 456
        assert link["role"] == "Спонсор" and link["role_id"] is None
        await service.delete_code(code)
        assert await service.lookup_code(code) is None

        await service.set_sponsor_message_id(999)
        assert await service.get_sponsor_message_id() == 999
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_ported_services_available_as_singletons(tmp_path):
    with tempfile.TemporaryDirectory() as tmp:
        config = Config(token="x", prefix="!", db_path=os.path.join(tmp, "bot.db"), log_level="ERROR", status_activity="s", owner_id=None)
        bot = MegaBot(config)
        await bot.setup_hook()
        try:
            services = bot.services
            assert isinstance(services.donations, DonationService)
            assert isinstance(services.twitch, TwitchService)
            assert isinstance(services.kick, KickService)
            assert isinstance(services.tempvoice, TempVoiceService)
            assert isinstance(services.birthdays, BirthdayService)

            # Ког получил ровно тот же синглтон, что лежит в services.
            kick_cog = bot.get_cog("Kick")
            assert kick_cog is not None
            assert kick_cog.kick is services.kick
        finally:
            await bot.close()


def _panel_bot(tmp_path, **kwargs) -> MegaBot:
    value = {"panel_port": 17890, **kwargs}
    config = Config(
        token="x",
        prefix="!",
        db_path=str(tmp_path / "bot.db"),
        log_level="ERROR",
        status_activity="s",
        owner_id=None,
        **{key: value[key] for key in value},
    )
    return MegaBot(config)


def _fake_send_capture(target: list) -> discord.TextChannel:
    """Фейк-канал, проходящий isinstance(discord.TextChannel) и поймавший вызов send().

    TextChannel имеет __slots__ без __dict__, поэтому метод send нельзя подменить
    у экземпляра — берём ПОДКЛАСС с переопределённым классовым send().
    """

    class _CaptureChannel(discord.TextChannel):
        def __init__(self) -> None:
            self.id = 555
            self.name = "интеграционные-тесты"

        async def send(self, *args, **kwargs):  # type: ignore[method-assign,override]
            target.append((args, kwargs))
            return discord.Object(id=424242)  # реальный send() вернул бы Message с .id

    return _CaptureChannel()


@pytest.mark.asyncio
async def test_webpanel_api_bot_send_clicks_fake_channel(tmp_path):
    """КЛИК по кнопке отправки: POST /api/bot/send -> _api_bot_send -> channel.send()."""
    calls: list = []

    bot = _panel_bot(tmp_path)
    channel = _fake_send_capture(calls)
    bot.get_channel = lambda cid: channel if int(cid or 0) == 555 else None

    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}
            resp = await client.post(
                "/api/bot/send",
                json={"channel_id": "555", "content": "привет из теста"},
                headers=headers,
            )
            assert resp.status == 200
            body = await resp.json()
            assert body.get("ok") is True
            assert body.get("message_id") == "424242"

    assert len(calls) == 1, "channel.send() должен быть вызван ровно один раз"
    _, kwargs = calls[0]
    assert kwargs.get("content") == "привет из теста"


@pytest.mark.asyncio
async def test_webpanel_api_bot_send_unknown_channel_400(tmp_path):
    """Чужой/несуществующий канал -> 400 «Канал не найден»."""
    bot = _panel_bot(tmp_path)
    bot.get_channel = lambda cid: None

    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}
            resp = await client.post(
                "/api/bot/send",
                json={"channel_id": "999", "content": "х"},
                headers=headers,
            )
            assert resp.status == 400
            body = await resp.json()
            assert body.get("ok") is False
            assert "Канал" in body.get("error", "")


@pytest.mark.asyncio
async def test_embed_trims_to_limits():
    raw = _trim_embeds(
        [
            {
                "title": "t" * 400,
                "description": "d" * 5000,
                "color": 0x10102030,
                "fields": [{"name": f"n{i}", "value": "v", "inline": True} for i in range(30)],
            }
        ]
    )
    assert len(raw) == 1
    assert len(raw[0]["title"]) == 256
    assert len(raw[0]["description"]) == 4000
    assert raw[0]["color"] == 0x102030
    assert len(raw[0]["fields"]) == 25
    assert _trim_embeds([{}] * 20) == []
    assert len(_trim_embeds([{"title": "x"}] * 20)) == 10

    embed = _embed_from_dict({"title": "h", "color": 0xFFFFF0, "timestamp": "2026-01-01T12:00:00+00:00"})
    assert embed.title == "h"
    assert embed.color.value == 0xFFFFF0
    assert embed.timestamp is not None


@pytest.mark.asyncio
async def test_webpanel_auth_and_status(tmp_path):
    bot = _panel_bot(tmp_path)
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            page = await client.get("/admin/embed-constructor")
            assert page.status == 200
            assert "Панель управления" in await page.text()

            admin_page = await client.get("/admin")
            assert admin_page.status == 200
            assert "Панель управления" in await admin_page.text()

            rejected = await client.get("/api/status")
            assert rejected.status == 401

            headers = {"X-Panel-Token": panel._static_token or ""}
            status_resp = await client.get("/api/status", headers=headers)
            assert status_resp.status == 200
            data = await status_resp.json()
            assert data["bot_online"] is False

            same_origin = await client.get(
                "/api/status",
                headers={**headers, "Origin": "https://panel.example.com", "Host": "panel.example.com"},
            )
            assert same_origin.status == 200

            foreign_origin = await client.get("/api/status", headers={**headers, "Origin": "https://evil.example.com"})
            assert foreign_origin.status == 401

            channels_resp = await client.get("/api/bot/channels", headers=headers)
            assert (await channels_resp.json())["channels"] == []

            overview_resp = await client.get("/api/overview", headers=headers)
            assert overview_resp.status == 200
            overview = await overview_resp.json()
            assert overview["ok"] is True and overview["bot_online"] is False
            assert overview["latency_ms"] == 0 and overview["uptime_seconds"] >= 0

            settings_resp = await client.get("/api/settings", headers=headers)
            assert settings_resp.status == 400
            assert (await settings_resp.json())["ok"] is False

            bad_url = await client.post("/api/webhook/send", headers=headers, json={"webhook_url": "https://example.com/1/2"})
            assert bad_url.status == 400
            assert (await bad_url.json())["ok"] is False


@pytest.mark.asyncio
async def test_webpanel_components_trim():
    assert _trim_components(None) == []
    assert _trim_components({"label": "x"}) == []
    rows = _trim_components(
        [
            [
                {"label": "Вход", "style": 3},
                {"label": "Правила", "style": 5, "url": "https://example.com"},
                {"label": "Плохая ссылка", "style": 5, "url": "ftp://bad"},
                {"label": "", "style": 1},
                {"label": "Лишняя", "style": 1},
                {"label": "Шестая", "style": 1},
            ],
            [{"label": "Без URL", "style": 2, "url": "https://no"}],
        ]
    )
    assert len(rows) == 2
    assert rows[0]["type"] == 1 and len(rows[0]["components"]) == 3
    styles = {c["style"] for c in rows[0]["components"]}
    assert styles == {3, 5, 1}
    assert {c["style"] for c in rows[1]["components"]} == {2}
    assert {c["url"] for c in rows[1]["components"]} == {""}

    raw = [
        {"type": 1, "components": [{"type": 2, "label": "Кнопка", "style": 4, "url": ""}, {"type": 3, "label": "селект"}]},
        {"type": 1, "components": []},
    ]
    parsed = _components_from_raw(raw)
    assert parsed == [[{"label": "Кнопка", "style": "4", "url": ""}]]


@pytest.mark.asyncio
async def test_webpanel_logs_endpoint(tmp_path):
    bot = _panel_bot(tmp_path)
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}
            resp = await client.get("/api/logs?n=50", headers=headers)
            assert resp.status == 200
            body = await resp.json()
            assert body["ok"] is True and body["logs"] == []


@pytest.mark.asyncio
async def test_webpanel_modules_status(tmp_path):
    bot = _panel_bot(tmp_path)
    panel = WebPanel(bot)
    modules = panel._modules_status()
    assert "welcome" in modules and "role_menu" in modules and "temp_voices" in modules
    assert isinstance(modules["donations"]["bonuses"], list)
    assert modules["welcome"]["channel_enabled"] is False
    eff = panel._effective_log_channels({"member_log_channel_id": 123})
    assert eff["log"] is None and eff["member"] == 123
    assert list(panel._role_options()) == []


@pytest.mark.asyncio
async def test_webpanel_password_login(tmp_path):
    bot = _panel_bot(tmp_path, panel_password="hunter2")
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            wrong = await client.post("/api/login", json={"password": "nope"})
            assert wrong.status == 401

            ok = await client.post("/api/login", json={"password": "hunter2"})
            body = await ok.json()
            assert body["ok"] is True and body["token"]

            headers = {"X-Panel-Token": body["token"]}
            status_resp = await client.get("/api/status", headers=headers)
            assert status_resp.status == 200


@pytest.mark.asyncio
async def test_webpanel_upload(tmp_path):
    import aiohttp

    bot = _panel_bot(tmp_path)
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}

            fd = aiohttp.FormData()
            png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
            fd.add_field("file", png, filename="kartinka.png", content_type="image/png")
            resp = await client.post("/api/upload", data=fd, headers=headers)
            assert resp.status == 200
            body = await resp.json()
            assert body["ok"] is True and body["name"].endswith(".png")
            assert body["absolute_url"].endswith("/uploads/" + body["name"])

            got = await client.get("/uploads/" + body["name"])
            assert got.status == 200
            assert "image/png" in got.headers.get("Content-Type", "")

            bad = aiohttp.FormData()
            bad.add_field("file", b"hello", filename="a.txt", content_type="text/plain")
            rejected = await client.post("/api/upload", data=bad, headers=headers)
            assert rejected.status == 400


@pytest.mark.asyncio
async def test_webpanel_security_headers(tmp_path):
    bot = _panel_bot(tmp_path)
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            page = await client.get("/admin")
            assert page.status == 200
            assert page.headers.get("X-Content-Type-Options") == "nosniff"
            assert page.headers.get("X-Frame-Options") == "DENY"
            assert page.headers.get("Referrer-Policy") == "no-referrer"
            assert page.headers.get("Cache-Control") == "no-store"
            csp = page.headers.get("Content-Security-Policy", "")
            assert "default-src 'self'" in csp
            assert "script-src 'self'" in csp
            assert "frame-ancestors 'none'" in csp
            assert "style-src 'self' 'unsafe-inline'" in csp

            js = await client.get("/panel.js")
            assert js.status == 200
            assert "text/javascript" in js.headers.get("Content-Type", "")
            assert "X-Frame-Options" in js.headers


@pytest.mark.asyncio
async def test_webpanel_panel_js_injection(tmp_path):
    bot = _panel_bot(tmp_path)
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            js = await client.get("/panel.js")
            body = await js.text()
            assert "__PANEL_LOGIN__" not in body and "__PANEL_TOKEN__" not in body
            assert (panel._static_token or "") in body
            assert '"0" === "1"' in body

    secured = _panel_bot(tmp_path, panel_password="hunter2")
    panel2 = WebPanel(secured)
    async with TestServer(panel2._create_app()) as server:
        async with TestClient(server) as client:
            js = await client.get("/panel.js")
            body = await js.text()
            assert "__PANEL_LOGIN__" not in body and "__PANEL_TOKEN__" not in body
            assert '"1" === "1"' in body


@pytest.mark.asyncio
async def test_webpanel_upload_magic_mismatch(tmp_path):
    import aiohttp

    bot = _panel_bot(tmp_path)
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}
            fd = aiohttp.FormData()
            fd.add_field("file", b"etot file ne png", filename="fake.png", content_type="image/png")
            resp = await client.post("/api/upload", data=fd, headers=headers)
            assert resp.status == 400

            ok = aiohttp.FormData()
            ok.add_field("file", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, filename="real.png", content_type="image/png")
            good = await client.post("/api/upload", data=ok, headers=headers)
            assert good.status == 200


@pytest.mark.asyncio
async def test_webpanel_logout_revokes_session(tmp_path):
    bot = _panel_bot(tmp_path, panel_password="hunter2")
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            login = await client.post("/api/login", json={"password": "hunter2"})
            token = (await login.json())["token"]
            headers = {"X-Panel-Token": token}
            before = await client.get("/api/status", headers=headers)
            assert before.status == 200

            out = await client.post("/api/logout", headers=headers)
            assert out.status == 200

            after = await client.get("/api/status", headers=headers)
            assert after.status == 401


@pytest.mark.asyncio
async def test_webpanel_login_rate_limit(tmp_path):
    bot = _panel_bot(tmp_path, panel_password="hunter2")
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            for _ in range(_LOGIN_LIMIT):
                resp = await client.post("/api/login", json={"password": "wrong"})
                assert resp.status == 401
            limited = await client.post("/api/login", json={"password": "hunter2"})
            assert limited.status == 429


@pytest.mark.asyncio
async def test_webpanel_logs_page(tmp_path):
    """Страница /logs отдаёт HTML, содержит фильтры и JS-токен-подстановку."""
    bot = _panel_bot(tmp_path)
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            page = await client.get("/logs")
            assert page.status == 200
            text = await page.text()
            assert "Технические логи" in text
            assert "__PANEL_TOKEN__" not in text or panel._static_token in text


@pytest.mark.asyncio
async def test_webpanel_audit_page(tmp_path):
    """Страница /audit отдаёт HTML с лентами Discord-событий."""
    bot = _panel_bot(tmp_path)
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            page = await client.get("/audit")
            assert page.status == 200
            text = await page.text()
            assert "Логи Discord" in text
            assert "audit=1" in text


@pytest.mark.asyncio
async def test_webpanel_admin_page_multiple_embeds(tmp_path):
    """Страница /admin рендерит секцию эмбедов: контейнер, кнопка добавления и элементы редактора."""
    bot = _panel_bot(tmp_path)
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            page = await client.get("/admin")
            assert page.status == 200
            text = await page.text()
            assert 'id="embeds_box"' in text
            assert "addEmbed" in text
            assert "Добавить эмбед" in text


def test_webhook_body_multiple_embeds(tmp_path):
    """_webhook_body сохраняет массив из нескольких эмбедов и обрезает лишние."""
    bot = _panel_bot(tmp_path)
    panel = WebPanel(bot)
    body = panel._webhook_body(
        {
            "content": "много эмбедов",
            "embeds": [{"title": f"Эмбед {i}", "description": f"текст {i}"} for i in range(3)],
        }
    )
    assert body["content"] == "много эмбедов"
    assert len(body["embeds"]) == 3
    assert [e["title"] for e in body["embeds"]] == ["Эмбед 0", "Эмбед 1", "Эмбед 2"]


@pytest.mark.asyncio
async def test_logging_service_writes_to_web_ring(tmp_path):
    """Аудит-события LoggingService попадают в веб-ленту (а не в Discord-канал)."""
    import logging

    from app.core.webpanel.log_ring import RingBufferHandler
    from app.services.logging_service import LoggingService

    ring = RingBufferHandler(50)
    root = logging.getLogger()
    root.addHandler(ring)
    try:
        bot = _panel_bot(tmp_path)
        # LoggingService требует SettingsService + bot; подменяем settings простым объектом.
        class _FakeSettings:
            async def get(self, guild_id):
                return {}

        svc = LoggingService(_FakeSettings(), bot)
        guild = discord.Object(id=111)
        guild.name = "Тест-сервер"
        embed = discord.Embed(title="Сообщение удалено", description="text")
        await svc.send_embed(guild, embed, category="message")

        entries = ring.snapshot()
        assert len(entries) >= 1
        entry = entries[-1]
        assert entry["cat"] == "message"
        assert entry["audit"] == "1"
        assert "Сообщение удалено" in entry["msg"]
    finally:
        root.removeHandler(ring)


@pytest.mark.asyncio
async def test_webpanel_api_logs_filters(tmp_path):
    """/api/logs поддерживает фильтры по категории и аудиту."""
    import logging

    from app.core.webpanel.log_ring import RingBufferHandler

    bot = _panel_bot(tmp_path)
    panel = WebPanel(bot)
    ring = RingBufferHandler(50)
    panel._ring = ring
    root = logging.getLogger()
    root.addHandler(ring)
    try:
        logging.getLogger("bot.services.audit.member").info("участник зашёл [Тест] x")
        logging.getLogger("bot.webpanel").warning("технический warning")

        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                headers = {"X-Panel-Token": panel._static_token or ""}
                all_resp = await client.get("/api/logs", headers=headers)
                body = await all_resp.json()
                assert body.get("ok") is True
                assert body["count"] >= 2

                audit_resp = await client.get("/api/logs?audit=1", headers=headers)
                audit_body = await audit_resp.json()
                assert all(e["audit"] == "1" for e in audit_body["logs"])
                assert len(audit_body["logs"]) == 1
                assert audit_body["logs"][0]["cat"] == "member"

                sys_resp = await client.get("/api/logs?audit=0", headers=headers)
                sys_body = await sys_resp.json()
                assert sys_body["count"] >= 1
                assert all(e["audit"] == "0" for e in sys_body["logs"])
                assert any("технический warning" in e["msg"] for e in sys_body["logs"])

                cat_resp = await client.get("/api/logs?cat=sys", headers=headers)
                cat_body = await cat_resp.json()
                assert all(e["cat"] == "sys" for e in cat_body["logs"])
                assert any("технический warning" in e["msg"] for e in cat_body["logs"])
    finally:
        root.removeHandler(ring)


@pytest.mark.asyncio
async def test_logging_service_does_not_use_discord_channels(tmp_path):
    """LoggingService.send_embed не отправляет ничего в Discord-канал."""
    from app.services.logging_service import LoggingService

    bot = _panel_bot(tmp_path)
    sent = []

    class _FakeSettings:
        async def get(self, guild_id):
            return {"log_channel_id": 555}

    svc = LoggingService(_FakeSettings(), bot)

    class _Guild:
        name = "Тест-сервер"
        id = 111

        def get_channel(self, channel_id):
            class _Ch:
                async def send(self, *args, **kwargs):
                    sent.append((args, kwargs))
                    return discord.Object(id=1)

            return _Ch()

    guild = _Guild()
    embed = discord.Embed(title="Событие", description="описание")
    await svc.send_embed(guild, embed, category="mod")
    assert sent == [], "LoggingService не должен слать в Discord-канал"


@pytest.mark.asyncio
async def test_webpanel_uploads_list_and_delete(tmp_path):
    import aiohttp

    bot = _panel_bot(tmp_path)
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}
            list_resp = await client.get("/api/uploads", headers=headers)
            assert (await list_resp.json())["files"] == []

            fd = aiohttp.FormData()
            fd.add_field("file", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, filename="del.png", content_type="image/png")
            up = await client.post("/api/upload", data=fd, headers=headers)
            name = (await up.json())["name"]

            listed = await client.get("/api/uploads", headers=headers)
            names = [f["name"] for f in (await listed.json())["files"]]
            assert name in names

            deleted = await client.delete("/api/uploads/" + name, headers=headers)
            assert (await deleted.json())["ok"] is True

            listed2 = await client.get("/api/uploads", headers=headers)
            assert name not in [f["name"] for f in (await listed2.json())["files"]]
            missing = await client.delete("/api/uploads/" + name, headers=headers)
            assert missing.status == 404


@pytest.mark.asyncio
async def test_overlay_server(tmp_path):
    bot = _panel_bot(tmp_path, overlay_token="overlay-secret-token-32chars")
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
async def test_overlay_token_file(tmp_path):
    bot = _panel_bot(tmp_path)
    Overlay(bot)
    token_file = tmp_path / ".overlay-token"
    assert token_file.exists()
    saved = token_file.read_text(encoding="utf-8").strip()
    assert len(saved) >= 16
    overlay2 = Overlay(bot)
    assert overlay2._token == saved


def test_tracemalloc_report():
    import tracemalloc

    from app.cogs.monitoring.ram_report import _fit_report, build_tracemalloc_report

    assert build_tracemalloc_report() == ""
    try:
        tracemalloc.start()
        blobs = [bytearray(1024) for _ in range(256)]
        report = build_tracemalloc_report()
        assert "Всего отслежено: **" in report
        assert "Файл и строка" in report and "Кол-во блоков" in report
        assert "MB**" in report
        assert len(report) <= 1024, "Отчёт tracemalloc превышает лимит поля embed"
        assert _fit_report(report) == report
        del blobs
    finally:
        tracemalloc.stop()
