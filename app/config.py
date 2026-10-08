"""Конфигурация приложения из переменных окружения."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REQUIRED_VARS = ("BOT_TOKEN",)
_DEFAULT_WARDOGS_SERVER_ID = "c89b3266-aed5-40d1-b022-6da6f6eba377"


def _ints(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    return tuple(int(part) for part in value.split(",") if part.strip().isdigit())


def _strs(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _pair_rules(value: str | None) -> tuple[tuple[str, str], ...]:
    """``триггер=>ответ|триггер2=>ответ2`` → кортеж пар; куски без => пропускаются."""
    if not value:
        return ()
    rules: list[tuple[str, str]] = []
    for part in value.split("|"):
        if "=>" not in part:
            continue
        trigger, _, reply = part.partition("=>")
        trigger, reply = trigger.strip().lower(), reply.strip()
        if trigger and reply:
            rules.append((trigger, reply))
    return tuple(rules)


def _hour_range(value: str | None) -> tuple[int, int] | None:
    """``23-8`` → ``(23, 8)``: окно тихих часов; мусор или равные границы → None."""
    if not value:
        return None
    parts = value.split("-")
    if len(parts) != 2:
        return None
    try:
        start, end = int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        return None
    if not (0 <= start <= 23 and 0 <= end <= 23) or start == end:
        return None
    return (start, end)


@dataclass(slots=True, frozen=True)
class Config:
    token: str
    prefix: str
    db_path: str
    log_level: str
    status_activity: str
    owner_id: int | None
    version: str = "3.5.0"
    database_url: str | None = None

    # Резервные копии SQLite (для single-server deployment).
    db_backup_dir: str = str(_PROJECT_ROOT / "data" / "backups")
    db_backup_interval_hours: float = 24.0
    db_backup_retention: int = 7

    # Общий сетевой слой внешних API
    api_timeout_seconds: float = 20.0
    api_proxy: str | None = None
    api_max_concurrency: int = 8
    api_circuit_failure_threshold: int = 5
    api_circuit_reset_seconds: float = 60.0

    # Spotify Client Credentials для импорта треков/плейлистов
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None

    # Донаты (DonationAlerts)
    donations_token: str | None = None
    donations_client_id: str | None = None
    donations_refresh_token: str | None = None
    donation_role_name: str = "Спонсор"
    donation_code_prefix: str = "VIP"
    donation_role_id: int | None = None
    donation_min_amount: float = 0.0
    donate_button_channel_id: int | None = None
    donate_bonuses: tuple[str, ...] = ()
    donation_notify_channel_id: int | None = None
    donate_url: str | None = None
    donation_poll_seconds: float = 15.0

    # Стримы (общее для Twitch/Kick/VK)
    stream_role_id: int | None = None
    stream_role_user_ids: tuple[int, ...] = ()
    stream_rsvp_role_id: int | None = None
    stream_sticky_poll_seconds: float = 60.0
    stream_quiet_hours: tuple[int, int] | None = None
    stream_quiet_tz: str = "Europe/Moscow"
    stream_abort_alert_minutes: int = 10
    stream_archive_days: int = 90

    # Twitch
    twitch_client_id: str | None = None
    twitch_client_secret: str | None = None
    twitch_refresh_token: str | None = None
    twitch_channels: tuple[str, ...] = ()
    twitch_notify_channel_id: int | None = None
    twitch_ping_role_id: int | None = None
    twitch_poll_seconds: float = 300.0

    # Kick (стримы и модерация)
    kick_channel_slug: str | None = None
    kick_notify_channel_id: int | None = None
    kick_ping_role_id: int | None = None
    kick_poll_seconds: float = 300.0
    kick_mod_channel_id: int | None = None
    kick_access_token: str | None = None
    kick_ban_words: tuple[str, ...] = ()
    kick_pusher_app_key: str = "32cbd69e4b950bf97679"
    kick_pusher_host: str = "ws-us2.pusher.com"

    # Отправка сообщений в чат Kick (Dev API POST /public/v1/chat, scope chat:write)
    kick_chat_auto_link: bool = False
    kick_chat_link_text: str = "Стрим уже на Kick! Ссылка на стрим в шапке канала."
    kick_chat_send_as_user: bool = False

    # Команды чата стримов (Kick/Twitch): монеты, опросы, топ
    chat_commands_enabled: bool = True
    chat_command_prefix: str = "!"
    chat_coin_reward: int = 5
    chat_cmd_cooldown: float = 3.0
    chat_poll_seconds: int = 90
    twitch_chat_token: str = ""  # oauth с chat:edit — без него Twitch читается read-only

    # VK Видео Live
    vk_channel_slug: str | None = None
    vk_notify_channel_id: int | None = None
    vk_ping_role_id: int | None = None
    vk_poll_seconds: float = 300.0

    # Расширенные логи
    logs_ignore_channel_ids: tuple[int, ...] = ()
    logs_ignore_category_ids: tuple[int, ...] = ()
    bot_log_channel_id: int | None = None
    member_log_channel_id: int | None = None
    message_log_channel_id: int | None = None
    voice_log_channel_id: int | None = None
    mod_log_channel_id: int | None = None

    # Heartbeat: алерт в канал логов, если бот молчит дольше N минут (0 — выкл)
    heartbeat_silence_minutes: int = 0
    # Алерт о нехватке места на диске рядом с БД: свободно меньше N МБ (0 — выкл)
    disk_alert_mb: int = 0
    # Алерт о деградации Discord-шлюза: стабильно дольше N секунд (0 — выкл)
    latency_alert_seconds: float = 0.0
    # Час публикации ежедневного дайджеста в канал логов (-1 — выкл)
    digest_hour: int = 21
    # Starboard: канал «звёздных» постов (не задан — выкл), порог и эмодзи
    starboard_channel_id: int | None = None
    starboard_threshold: int = 5
    starboard_emoji: str = "⭐"
    # Автореспондер: правила "триггер=>ответ" через | (пусто — выкл)
    autorespond_rules: tuple[tuple[str, str], ...] = ()
    # Выдача роли за точную фразу: "фраза1,фраза2" и AUTORESPOND_ROLE_ID
    autorespond_role_phrases: tuple[str, ...] = ()
    autorespond_role_id: int | None = None
    autorespond_cooldown: int = 15
    # Авто-пост нового расписания Twitch в канал (не задан — выкл)
    twitch_schedule_channel_id: int | None = None
    # Час отправки (0..23); -1 — проверять каждый цикл (дедуп по сегментам)
    schedule_post_hour: int = -1

    # Правила-гейт
    rules_message_id: int | None = None
    rules_role_id: int | None = None

    # Временные голосовые каналы
    temp_voice_trigger_ids: tuple[int, ...] = ()
    temp_voice_category_id: int | None = None

    # Вебпанель конструктора эмбедов
    panel_host: str = "127.0.0.1"
    panel_port: int | None = None
    panel_password: str | None = None
    panel_admin_password: str | None = None
    panel_moderator_password: str | None = None
    panel_viewer_password: str | None = None
    panel_password_hash: str | None = None
    panel_admin_password_hash: str | None = None
    panel_moderator_password_hash: str | None = None
    panel_viewer_password_hash: str | None = None
    panel_public_url: str | None = None
    panel_oauth_client_id: str | None = None
    panel_oauth_client_secret: str | None = None
    panel_oauth_redirect_url: str | None = None
    panel_bridge_token: str | None = None
    # Доверенный reverse-proxy перед панелью: с ним rate-limit берёт клиента
    # из X-Forwarded-For. Без него заголовок подделывается любым клиентом,
    # поэтому считается адрес соединения.
    panel_trusted_proxy: bool = False

    # Дни рождения
    birthday_channel_id: int | None = None
    birthday_announce_hour: int = 9
    birthday_ping_role_id: int | None = None

    # Оверлей (OBS)
    overlay_host: str = "127.0.0.1"
    overlay_port: int | None = None
    overlay_token: str | None = None
    overlay_public_url: str | None = None
    overlay_donation_goal_enabled: bool = False
    overlay_donation_goal_target: float = 0.0
    overlay_donation_goal_currency: str = "₽"
    overlay_donation_goal_label: str = "Донат-цель"
    overlay_donation_goal_current: float = 0.0

    # Отчёт по ОЗУ (RamReport)
    ram_report_channel_id: int | None = None
    ram_report_interval_minutes: int = 30
    ram_report_tracemalloc: bool = True

    # Меню ролей (role_menu, как в Node)
    role_menu_enabled: bool = True
    role_menu_channel_id: int | None = None
    role_menu_message: str = "Уведомления и роли меню"
    role_menu_roles: tuple[str, ...] = ()
    role_menu_max_values: int = 10

    # ИИ-чат (Gemini, как в Node chat_ai)
    ai_enabled: bool = False
    ai_api_key: str | None = None
    ai_channels: tuple[int, ...] = ()
    ai_cooldown_seconds: float = 45.0
    ai_model: str = "gemini-1.5-flash"
    ai_temperature: float = 0.9
    ai_max_tokens: int = 220
    ai_history_size: int = 12
    ai_timeout_seconds: float = 45.0
    ai_system_prompt: str = ""
    ai_proxy: str | None = None

    # Соцсети (/socials)
    socials_discord: str | None = None
    socials_site: str | None = None
    socials_youtube: str | None = None
    socials_twitch: str | None = None
    socials_donate: str | None = None

    # WARDOGS: живая карточка сервера и страница подключения
    wardogs_server_name: str = "Wardogs"
    wardogs_server_id: str | None = _DEFAULT_WARDOGS_SERVER_ID
    wardogs_join_url: str | None = None

    # Права категорий (permissions, как в Node)
    guild_id: int | None = None
    permissions_auto_apply: bool = False
    permissions_categories: str = ""

    # Счётчики сервера (server_stats, как в Node)
    server_stats_enabled: bool = False
    server_stats_category_id: int | None = None
    server_stats_category_name: str = "СТАТИСТИКА"
    server_stats_update_seconds: int = 300
    server_stats_channels: str = ""

    # Приветствия (welcome, как в Node welcome.js)
    welcome_enabled: bool = True
    welcome_send_dm: bool = True
    welcome_channel_id: int | None = None
    welcome_channel_enabled: bool = False
    # PNG-карточка приветствия вместо плоского эмбеда (нужен Pillow)
    welcome_card: bool = False
    welcome_leave_channel_id: int | None = None
    welcome_leave_channel_enabled: bool = False
    welcome_title: str = "Добро пожаловать на дискорд сервер dendich!"
    welcome_intro: str = ""
    welcome_footer: str = "Приятного времяпрепровождения! 🔥"
    welcome_channel_descriptions: str = ""
    welcome_voice_descriptions: str = ""
    welcome_hidden_voice: str = ""

    # Сезоны (seasons, как в Node season.js / engagement.js)
    season_enabled: bool = False
    season_reward_roles: tuple[str, ...] = ()
    season_announce_channel_id: int | None = None

    # Авто-модерация (discord_automod, как в Node automod.js)
    automod_enabled: bool = True
    automod_banned_words: str = ""
    automod_block_links: bool = True
    automod_allowed_links: str = ""
    automod_caps_threshold: float = 0.8
    automod_caps_min_len: int = 12
    automod_max_messages_in_window: int = 5
    automod_timeout_seconds: int = 300
    automod_ban_after_timeouts: int = 3
    automod_ban_window_seconds: int = 300
    automod_ignore_roles: tuple[str, ...] = ()
    automod_ignored_channels: tuple[int, ...] = ()
    automod_antiraid_enabled: bool = False
    automod_antiraid_window_seconds: int = 60
    automod_antiraid_join_threshold: int = 8
    automod_antiraid_slowmode_seconds: int = 10
    automod_antiraid_cooldown_seconds: int = 300
    automod_min_account_age_days: int = 0
    automod_exempt_regex: str = ""
    automod_lockdown_seconds: int = 300

    # Guard: глобальный rate-limit инвоков команд и kill-switch
    guard_enabled: bool = True
    guard_user_max: int = 6
    guard_user_window: float = 10.0
    guard_guild_max: int = 40
    guard_guild_window: float = 10.0
    guard_bypass_admin: bool = True
    guard_bypass_roles: tuple[int, ...] = ()

    @classmethod
    def from_env(cls, env_file: str | os.PathLike[str] | None = None) -> Config:
        load_dotenv(env_file, override=False)

        missing = [var for var in _REQUIRED_VARS if not os.getenv(var)]
        if missing:
            raise RuntimeError(f"Отсутствуют обязательные переменные окружения: {', '.join(missing)}")

        owner_raw = os.getenv("OWNER_ID")
        return cls(
            token=os.environ["BOT_TOKEN"],
            prefix=os.getenv("BOT_PREFIX", "!"),
            db_path=os.getenv("DB_PATH", str(_PROJECT_ROOT / "data" / "bot.db")),
            database_url=os.getenv("DATABASE_URL") or None,
            db_backup_dir=os.getenv("DB_BACKUP_DIR", str(_PROJECT_ROOT / "data" / "backups")),
            db_backup_interval_hours=max(1.0, float(os.getenv("DB_BACKUP_INTERVAL_HOURS", "24"))),
            db_backup_retention=max(1, min(90, int(os.getenv("DB_BACKUP_RETENTION", "7")))),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            status_activity=os.getenv("STATUS_ACTIVITY", "играет с кодом"),
            owner_id=int(owner_raw) if owner_raw and owner_raw.isdigit() else None,
            api_timeout_seconds=max(5.0, min(120.0, float(os.getenv("API_TIMEOUT_SECONDS", "20")))),
            api_proxy=os.getenv("API_PROXY") or None,
            api_max_concurrency=max(1, min(64, int(os.getenv("API_MAX_CONCURRENCY", "8")))),
            api_circuit_failure_threshold=max(1, min(20, int(os.getenv("API_CIRCUIT_FAILURE_THRESHOLD", "5")))),
            api_circuit_reset_seconds=max(5.0, min(900.0, float(os.getenv("API_CIRCUIT_RESET_SECONDS", "60")))),
            spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID") or None,
            spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET") or None,
            donations_token=os.getenv("DONATIONS_TOKEN"),
            donations_client_id=os.getenv("DONATIONS_CLIENT_ID"),
            donations_refresh_token=os.getenv("DONATIONS_REFRESH_TOKEN"),
            donation_role_name=os.getenv("DONATION_ROLE_NAME", "Спонсор"),
            donation_code_prefix=os.getenv("DONATION_CODE_PREFIX", "VIP"),
            donation_role_id=_single_int(os.getenv("DONATION_ROLE_ID")),
            donation_min_amount=float(os.getenv("DONATION_MIN_AMOUNT") or 0),
            donate_button_channel_id=_single_int(os.getenv("DONATE_BUTTON_CHANNEL_ID")),
            donate_bonuses=_strs(os.getenv("DONATE_BONUSES")),
            donation_notify_channel_id=_single_int(os.getenv("DONATION_NOTIFY_CHANNEL_ID")),
            donate_url=os.getenv("DONATE_URL"),
            donation_poll_seconds=float(os.getenv("DONATION_POLL_SECONDS", "15")),
            stream_role_id=_single_int(os.getenv("STREAM_ROLE_ID")),
            stream_role_user_ids=_ints(os.getenv("STREAM_ROLE_USER_IDS")),
            stream_rsvp_role_id=_single_int(os.getenv("STREAM_RSVP_ROLE_ID")),
            stream_sticky_poll_seconds=max(30.0, float(os.getenv("STREAM_STICKY_POLL_SECONDS", "60"))),
            stream_quiet_hours=_hour_range(os.getenv("STREAM_QUIET_HOURS")),
            stream_quiet_tz=os.getenv("STREAM_QUIET_TZ") or "Europe/Moscow",
            stream_abort_alert_minutes=max(0, int(os.getenv("STREAM_ABORT_ALERT_MINUTES", "10") or "10")),
            stream_archive_days=max(1, int(os.getenv("STREAM_ARCHIVE_DAYS", "90") or "90")),
            twitch_client_id=os.getenv("TWITCH_CLIENT_ID"),
            twitch_client_secret=os.getenv("TWITCH_CLIENT_SECRET"),
            twitch_refresh_token=os.getenv("TWITCH_REFRESH_TOKEN"),
            twitch_channels=_strs(os.getenv("TWITCH_CHANNELS")),
            twitch_notify_channel_id=_single_int(os.getenv("TWITCH_NOTIFY_CHANNEL_ID")),
            twitch_ping_role_id=_single_int(os.getenv("TWITCH_PING_ROLE_ID")),
            twitch_poll_seconds=float(os.getenv("TWITCH_POLL_SECONDS", "300")),
            kick_channel_slug=os.getenv("KICK_CHANNEL_SLUG"),
            kick_notify_channel_id=_single_int(os.getenv("KICK_NOTIFY_CHANNEL_ID")),
            kick_ping_role_id=_single_int(os.getenv("KICK_PING_ROLE_ID")),
            kick_poll_seconds=float(os.getenv("KICK_POLL_SECONDS", "300")),
            kick_mod_channel_id=_single_int(os.getenv("KICK_MOD_CHANNEL_ID")),
            kick_access_token=os.getenv("KICK_ACCESS_TOKEN"),
            kick_ban_words=_strs(os.getenv("KICK_BAN_WORDS")),
            kick_chat_auto_link=_bool(os.getenv("KICK_CHAT_AUTO_LINK")),
            kick_chat_link_text=os.getenv(
                "KICK_CHAT_LINK_TEXT",
                "Стрим уже на Kick! Ссылка на стрим в шапке канала.",
            ),
            kick_chat_send_as_user=_bool(os.getenv("KICK_CHAT_SEND_AS_USER")),
            kick_pusher_app_key=os.getenv("KICK_PUSHER_APP_KEY", "32cbd69e4b950bf97679"),
            kick_pusher_host=os.getenv("KICK_PUSHER_HOST", "ws-us2.pusher.com"),
            chat_commands_enabled=_bool(os.getenv("CHAT_COMMANDS_ENABLED"), True),
            chat_command_prefix=(os.getenv("CHAT_COMMAND_PREFIX") or "!")[:4].strip() or "!",
            chat_coin_reward=max(0, int(os.getenv("CHAT_COIN_REWARD", "5") or "5")),
            chat_cmd_cooldown=max(0.0, float(os.getenv("CHAT_CMD_COOLDOWN", "3") or "3")),
            chat_poll_seconds=max(30, min(600, int(os.getenv("CHAT_POLL_SECONDS", "90") or "90"))),
            twitch_chat_token=os.getenv("TWITCH_CHAT_TOKEN", ""),
            vk_channel_slug=os.getenv("VK_CHANNEL_SLUG"),
            vk_notify_channel_id=_single_int(os.getenv("VK_NOTIFY_CHANNEL_ID")),
            vk_ping_role_id=_single_int(os.getenv("VK_PING_ROLE_ID")),
            vk_poll_seconds=max(30.0, float(os.getenv("VK_POLL_SECONDS", "300"))),
            logs_ignore_channel_ids=_ints(os.getenv("LOGS_IGNORE_CHANNEL_IDS")),
            logs_ignore_category_ids=_ints(os.getenv("LOGS_IGNORE_CATEGORY_IDS")),
            bot_log_channel_id=_single_int(os.getenv("BOT_LOG_CHANNEL_ID")),
            member_log_channel_id=_single_int(os.getenv("MEMBER_LOG_CHANNEL_ID")),
            message_log_channel_id=_single_int(os.getenv("MESSAGE_LOG_CHANNEL_ID")),
            voice_log_channel_id=_single_int(os.getenv("VOICE_LOG_CHANNEL_ID")),
            mod_log_channel_id=_single_int(os.getenv("MOD_LOG_CHANNEL_ID")),
            heartbeat_silence_minutes=max(0, min(1440, int(os.getenv("HEARTBEAT_SILENCE_MINUTES", "0") or "0"))),
            disk_alert_mb=max(0, int(os.getenv("DISK_ALERT_MB", "0") or "0")),
            latency_alert_seconds=max(0.0, float(os.getenv("DISCORD_LATENCY_ALERT_SECONDS", "0") or "0")),
            digest_hour=max(-1, min(23, int(os.getenv("DIGEST_HOUR", "21") or "21"))),
            starboard_channel_id=_single_int(os.getenv("STARBOARD_CHANNEL_ID")),
            starboard_threshold=max(1, int(os.getenv("STARBOARD_THRESHOLD", "5") or "5")),
            starboard_emoji=os.getenv("STARBOARD_EMOJI", "⭐") or "⭐",
            autorespond_rules=_pair_rules(os.getenv("AUTORESPOND_RULES")),
            autorespond_role_phrases=_strs(os.getenv("AUTORESPOND_ROLE_RULES")),
            autorespond_role_id=_single_int(os.getenv("AUTORESPOND_ROLE_ID")),
            autorespond_cooldown=max(0, int(os.getenv("AUTORESPOND_COOLDOWN", "15") or "15")),
            twitch_schedule_channel_id=_single_int(os.getenv("TWITCH_SCHEDULE_CHANNEL_ID")),
            schedule_post_hour=max(-1, min(23, int(os.getenv("SCHEDULE_POST_HOUR", "-1") or "-1"))),
            rules_message_id=_single_int(os.getenv("RULES_MESSAGE_ID")),
            rules_role_id=_single_int(os.getenv("RULES_ROLE_ID")),
            temp_voice_trigger_ids=_ints(os.getenv("TEMP_VOICE_TRIGGER_IDS")),
            temp_voice_category_id=_single_int(os.getenv("TEMP_VOICE_CATEGORY_ID")),
            # Публичный URL подразумевает запуск наружу (контейнер/платформа):
            # без явного PANEL_HOST слушаем 0.0.0.0, иначе панель сядет на
            # loopback и хостинг вернёт 502, не дойдя до процесса.
            panel_host=os.getenv("PANEL_HOST")
            or ("0.0.0.0" if os.getenv("PANEL_PUBLIC_URL", "").strip() else "127.0.0.1"),
            panel_port=_single_int(os.getenv("PANEL_PORT") or os.getenv("PORT")),
            panel_password=os.getenv("PANEL_PASSWORD"),
            panel_admin_password=os.getenv("PANEL_ADMIN_PASSWORD"),
            panel_moderator_password=os.getenv("PANEL_MODERATOR_PASSWORD"),
            panel_viewer_password=os.getenv("PANEL_VIEWER_PASSWORD"),
            panel_password_hash=os.getenv("PANEL_PASSWORD_HASH") or None,
            panel_admin_password_hash=os.getenv("PANEL_ADMIN_PASSWORD_HASH") or None,
            panel_moderator_password_hash=os.getenv("PANEL_MODERATOR_PASSWORD_HASH") or None,
            panel_viewer_password_hash=os.getenv("PANEL_VIEWER_PASSWORD_HASH") or None,
            panel_public_url=os.getenv("PANEL_PUBLIC_URL"),
            panel_oauth_client_id=os.getenv("PANEL_OAUTH_CLIENT_ID") or None,
            panel_oauth_client_secret=os.getenv("PANEL_OAUTH_CLIENT_SECRET") or None,
            panel_oauth_redirect_url=os.getenv("PANEL_OAUTH_REDIRECT_URL") or None,
            panel_bridge_token=os.getenv("PANEL_BRIDGE_TOKEN") or None,
            panel_trusted_proxy=_bool(os.getenv("PANEL_TRUSTED_PROXY")),
            birthday_channel_id=_single_int(os.getenv("BIRTHDAY_CHANNEL_ID")),
            birthday_announce_hour=_clamp_hour(os.getenv("BIRTHDAY_ANNOUNCE_HOUR", "9")),
            birthday_ping_role_id=_single_int(os.getenv("BIRTHDAY_PING_ROLE_ID")),
            overlay_host=os.getenv("OVERLAY_HOST")
            or ("0.0.0.0" if os.getenv("OVERLAY_PUBLIC_URL", "").strip() else "127.0.0.1"),
            overlay_port=_single_int(os.getenv("OVERLAY_PORT")),
            overlay_token=os.getenv("OVERLAY_TOKEN"),
            overlay_public_url=os.getenv("OVERLAY_PUBLIC_URL"),
            overlay_donation_goal_enabled=_bool(os.getenv("OVERLAY_DONATION_GOAL_ENABLED")),
            overlay_donation_goal_target=float(os.getenv("OVERLAY_DONATION_GOAL_TARGET") or 0),
            overlay_donation_goal_currency=os.getenv("OVERLAY_DONATION_GOAL_CURRENCY", "₽"),
            overlay_donation_goal_label=os.getenv("OVERLAY_DONATION_GOAL_LABEL", "Донат-цель"),
            overlay_donation_goal_current=float(os.getenv("OVERLAY_DONATION_GOAL_CURRENT") or 0),
            ram_report_channel_id=_single_int(os.getenv("RAM_REPORT_CHANNEL_ID")),
            ram_report_interval_minutes=max(1, int(os.getenv("RAM_REPORT_INTERVAL_MINUTES", "30"))),
            ram_report_tracemalloc=_bool(os.getenv("RAM_REPORT_TRACEMALLOC", "1")),
            role_menu_enabled=_bool(os.getenv("ROLE_MENU_ENABLED", "1")),
            role_menu_channel_id=_single_int(os.getenv("ROLE_MENU_CHANNEL_ID")),
            role_menu_message=os.getenv("ROLE_MENU_MESSAGE", "Уведомления и роли меню"),
            role_menu_roles=_strs(os.getenv("ROLE_MENU_ROLES")),
            role_menu_max_values=max(1, int(os.getenv("ROLE_MENU_MAX_VALUES", "10"))),
            ai_enabled=_bool(os.getenv("AI_ENABLED")),
            ai_api_key=os.getenv("GEMINI_API_KEY"),
            ai_channels=_ints(os.getenv("AI_CHANNELS")),
            ai_cooldown_seconds=max(5.0, float(os.getenv("AI_COOLDOWN_SECONDS", "45"))),
            ai_model=os.getenv("AI_MODEL", "gemini-1.5-flash"),
            ai_temperature=float(os.getenv("AI_TEMPERATURE", "0.9")),
            ai_max_tokens=max(1, int(os.getenv("AI_MAX_TOKENS", "220"))),
            ai_history_size=max(2, int(os.getenv("AI_HISTORY_SIZE", "12"))),
            ai_timeout_seconds=max(10.0, float(os.getenv("AI_TIMEOUT_SECONDS", "45"))),
            ai_system_prompt=os.getenv("AI_SYSTEM_PROMPT", ""),
            ai_proxy=(os.getenv("AI_PROXY") or os.getenv("GEMINI_PROXY") or None),
            socials_discord=os.getenv("SOCIALS_DISCORD"),
            socials_site=os.getenv("SOCIALS_SITE"),
            socials_youtube=os.getenv("SOCIALS_YOUTUBE"),
            socials_twitch=os.getenv("SOCIALS_TWITCH"),
            socials_donate=os.getenv("SOCIALS_DONATE"),
            wardogs_server_name=os.getenv("WARDOGS_SERVER_NAME", "Wardogs").strip() or "Wardogs",
            wardogs_server_id=os.getenv("WARDOGS_SERVER_ID") or _DEFAULT_WARDOGS_SERVER_ID,
            wardogs_join_url=os.getenv("WARDOGS_JOIN_URL") or None,
            guild_id=_single_int(os.getenv("GUILD_ID")),
            permissions_auto_apply=_bool(os.getenv("PERMISSIONS_AUTO_APPLY")),
            permissions_categories=os.getenv("PERMISSIONS_CATEGORIES", ""),
            server_stats_enabled=_bool(os.getenv("SERVER_STATS_ENABLED")),
            server_stats_category_id=_single_int(os.getenv("SERVER_STATS_CATEGORY_ID")),
            server_stats_category_name=os.getenv("SERVER_STATS_CATEGORY_NAME", "СТАТИСТИКА"),
            server_stats_update_seconds=max(60, int(os.getenv("SERVER_STATS_UPDATE_SECONDS", "300"))),
            server_stats_channels=os.getenv("SERVER_STATS_CHANNELS", ""),
            welcome_enabled=_bool(os.getenv("WELCOME_ENABLED", "1")),
            welcome_send_dm=_bool(os.getenv("WELCOME_SEND_DM", "1")),
            welcome_channel_id=_single_int(os.getenv("WELCOME_CHANNEL_ID")),
            welcome_channel_enabled=_bool(os.getenv("WELCOME_CHANNEL_ENABLED")),
            welcome_card=_bool(os.getenv("WELCOME_CARD")),
            welcome_leave_channel_id=_single_int(os.getenv("WELCOME_LEAVE_CHANNEL_ID")),
            welcome_leave_channel_enabled=_bool(os.getenv("WELCOME_LEAVE_CHANNEL_ENABLED")),
            welcome_title=os.getenv("WELCOME_TITLE", "Добро пожаловать на дискорд сервер dendich!"),
            welcome_intro=os.getenv("WELCOME_INTRO", ""),
            welcome_footer=os.getenv("WELCOME_FOOTER", "Приятного времяпрепровождения! 🔥"),
            welcome_channel_descriptions=os.getenv("WELCOME_CHANNEL_DESCRIPTIONS", ""),
            welcome_voice_descriptions=os.getenv("WELCOME_VOICE_DESCRIPTIONS", ""),
            welcome_hidden_voice=os.getenv("WELCOME_HIDDEN_VOICE", ""),
            automod_enabled=_bool(os.getenv("AUTOMOD_ENABLED", "1")),
            automod_banned_words=os.getenv("AUTOMOD_BANNED_WORDS", ""),
            automod_block_links=_bool(os.getenv("AUTOMOD_BLOCK_LINKS", "1")),
            automod_allowed_links=os.getenv("AUTOMOD_ALLOWED_LINKS", ""),
            automod_caps_threshold=float(os.getenv("AUTOMOD_CAPS_THRESHOLD", "0.8")),
            automod_caps_min_len=max(1, int(os.getenv("AUTOMOD_CAPS_MIN_LEN", "12"))),
            automod_max_messages_in_window=max(1, int(os.getenv("AUTOMOD_MAX_MESSAGES_IN_WINDOW", "5"))),
            automod_timeout_seconds=max(0, int(os.getenv("AUTOMOD_TIMEOUT_SECONDS", "300"))),
            automod_ban_after_timeouts=max(0, int(os.getenv("AUTOMOD_BAN_AFTER_TIMEOUTS", "3"))),
            automod_ban_window_seconds=max(1, int(os.getenv("AUTOMOD_BAN_WINDOW_SECONDS", "300"))),
            automod_ignore_roles=_strs(os.getenv("AUTOMOD_IGNORE_ROLES")),
            automod_ignored_channels=_ints(os.getenv("AUTOMOD_IGNORED_CHANNELS")),
            automod_antiraid_enabled=_bool(os.getenv("AUTOMOD_ANTIRAID_ENABLED", "0")),
            automod_antiraid_window_seconds=max(10, int(os.getenv("AUTOMOD_ANTIRAID_WINDOW_SECONDS", "60"))),
            automod_antiraid_join_threshold=max(2, int(os.getenv("AUTOMOD_ANTIRAID_JOIN_THRESHOLD", "8"))),
            automod_antiraid_slowmode_seconds=max(0, int(os.getenv("AUTOMOD_ANTIRAID_SLOWMODE_SECONDS", "10"))),
            automod_antiraid_cooldown_seconds=max(30, int(os.getenv("AUTOMOD_ANTIRAID_COOLDOWN_SECONDS", "300"))),
            automod_min_account_age_days=max(0, int(os.getenv("AUTOMOD_MIN_ACCOUNT_AGE_DAYS", "0"))),
            automod_exempt_regex=os.getenv("AUTOMOD_EXEMPT_REGEX", ""),
            automod_lockdown_seconds=max(30, int(os.getenv("AUTOMOD_LOCKDOWN_SECONDS", "300"))),
            season_enabled=_bool(os.getenv("SEASON_ENABLED")),
            season_reward_roles=_strs(os.getenv("SEASON_REWARD_ROLES")),
            season_announce_channel_id=_single_int(os.getenv("SEASON_ANNOUNCE_CHANNEL_ID")),
            guard_enabled=_bool(os.getenv("GUARD_ENABLED"), True),
            guard_user_max=max(1, min(100, int(os.getenv("GUARD_USER_MAX", "6") or "6"))),
            guard_user_window=max(1.0, min(600.0, float(os.getenv("GUARD_USER_WINDOW", "10") or "10"))),
            guard_guild_max=max(1, min(1000, int(os.getenv("GUARD_GUILD_MAX", "40") or "40"))),
            guard_guild_window=max(1.0, min(600.0, float(os.getenv("GUARD_GUILD_WINDOW", "10") or "10"))),
            guard_bypass_admin=_bool(os.getenv("GUARD_BYPASS_ADMIN"), True),
            guard_bypass_roles=_ints(os.getenv("GUARD_BYPASS_ROLES")),
        )


def _clamp_hour(value: str) -> int:
    try:
        return max(0, min(23, int(value)))
    except ValueError:
        return 9


def _single_int(value: str | None) -> int | None:
    if value and value.strip().isdigit():
        return int(value.strip())
    return None


def _bool(value: str | None, default: bool = False) -> bool:
    if not value:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on", "да")
