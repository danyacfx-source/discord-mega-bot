"""Конфиг, репозитории, DI-синглтоны и прочие не-panel тесты."""
from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config import Config
from app.core.bot import MegaBot
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


def test_panel_api_token_header():
    src = (Path(__file__).resolve().parents[1] / "panel-ui" / "src" / "api.js").read_text(encoding="utf-8")
    assert '"X-Panel-Token"' in src
    assert '"X-Bot-Token"' not in src


def test_config_new_options(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "BOT_TOKEN=t",
            "DB_BACKUP_DIR=var/backups",
            "DB_BACKUP_INTERVAL_HOURS=12",
            "DB_BACKUP_RETENTION=11",
            "DB_BACKUP_DISCORD_CHANNEL_ID=555",
                    "API_TIMEOUT_SECONDS=37",
                    "API_PROXY=http://127.0.0.1:8080",
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
    assert config.api_timeout_seconds == 37.0
    assert config.api_proxy == "http://127.0.0.1:8080"
    assert config.db_backup_dir == "var/backups"
    assert config.db_backup_interval_hours == 12.0
    assert config.db_backup_retention == 11
    assert config.db_backup_discord_channel_id == 555
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
    assert config.version == "3.5.0"
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
        assert await repo.get(10, 100) is None
        await repo.set(10, 100, 3, 15)
        assert await repo.get(10, 100) == (3, 15)
        await repo.set(10, 100, 12, 31)
        assert await repo.get(10, 100) == (12, 31)
        assert len(await repo.with_date(12, 31, 100)) == 1
        await repo.set(11, 100, 12, 31)
        assert len(await repo.with_date(12, 31, 100)) == 2
        # Другая гильдия — изоляция (LOW-fix).
        await repo.set(12, 200, 12, 31)
        assert len(await repo.with_date(12, 31, 100)) == 2
        assert len(await repo.with_date(12, 31, 200)) == 1
        assert await repo.remove(10, 100)
        assert await repo.get(10, 100) is None
        assert len(await repo.all(100)) == 1
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
        # M4-fix: 8 hex (64 бита) вместо 4 (32 бита) — длина кода выросла.
        assert len(code) == 20 and code.startswith("VIP-")
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
