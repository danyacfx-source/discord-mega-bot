"""Конфигурация приложения из переменных окружения."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REQUIRED_VARS = ("BOT_TOKEN",)


def _ints(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    return tuple(int(part) for part in value.split(",") if part.strip().isdigit())


def _strs(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


@dataclass(slots=True, frozen=True)
class Config:
    token: str
    prefix: str
    db_path: str
    log_level: str
    status_activity: str
    owner_id: int | None
    version: str = "3.2.0"

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

    # Twitch
    twitch_client_id: str | None = None
    twitch_client_secret: str | None = None
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

    # Расширенные логи
    logs_ignore_channel_ids: tuple[int, ...] = ()
    logs_ignore_category_ids: tuple[int, ...] = ()

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
    panel_public_url: str | None = None

    # Дни рождения
    birthday_channel_id: int | None = None
    birthday_announce_hour: int = 9
    birthday_ping_role_id: int | None = None

    # Оверлей (OBS)
    overlay_host: str = "127.0.0.1"
    overlay_port: int | None = None
    overlay_token: str | None = None
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

    # Соцсети (/socials)
    socials_discord: str | None = None
    socials_site: str | None = None
    socials_youtube: str | None = None
    socials_twitch: str | None = None
    socials_donate: str | None = None

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

    # YouTube (youtube, как в Node youtube.js / youtube_growth.js)
    youtube_enabled: bool = False
    youtube_api_key: str | None = None
    youtube_channel: str | None = None

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
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            status_activity=os.getenv("STATUS_ACTIVITY", "играет с кодом"),
            owner_id=int(owner_raw) if owner_raw and owner_raw.isdigit() else None,
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
            twitch_client_id=os.getenv("TWITCH_CLIENT_ID"),
            twitch_client_secret=os.getenv("TWITCH_CLIENT_SECRET"),
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
            kick_pusher_app_key=os.getenv("KICK_PUSHER_APP_KEY", "32cbd69e4b950bf97679"),
            kick_pusher_host=os.getenv("KICK_PUSHER_HOST", "ws-us2.pusher.com"),
            logs_ignore_channel_ids=_ints(os.getenv("LOGS_IGNORE_CHANNEL_IDS")),
            logs_ignore_category_ids=_ints(os.getenv("LOGS_IGNORE_CATEGORY_IDS")),
            rules_message_id=_single_int(os.getenv("RULES_MESSAGE_ID")),
            rules_role_id=_single_int(os.getenv("RULES_ROLE_ID")),
            temp_voice_trigger_ids=_ints(os.getenv("TEMP_VOICE_TRIGGER_IDS")),
            temp_voice_category_id=_single_int(os.getenv("TEMP_VOICE_CATEGORY_ID")),
            panel_host=os.getenv("PANEL_HOST", "127.0.0.1"),
            panel_port=_single_int(os.getenv("PANEL_PORT")),
            panel_password=os.getenv("PANEL_PASSWORD"),
            panel_public_url=os.getenv("PANEL_PUBLIC_URL"),
            birthday_channel_id=_single_int(os.getenv("BIRTHDAY_CHANNEL_ID")),
            birthday_announce_hour=_clamp_hour(os.getenv("BIRTHDAY_ANNOUNCE_HOUR", "9")),
            birthday_ping_role_id=_single_int(os.getenv("BIRTHDAY_PING_ROLE_ID")),
            overlay_host=os.getenv("OVERLAY_HOST", "127.0.0.1"),
            overlay_port=_single_int(os.getenv("OVERLAY_PORT")),
            overlay_token=os.getenv("OVERLAY_TOKEN"),
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
            socials_discord=os.getenv("SOCIALS_DISCORD"),
            socials_site=os.getenv("SOCIALS_SITE"),
            socials_youtube=os.getenv("SOCIALS_YOUTUBE"),
            socials_twitch=os.getenv("SOCIALS_TWITCH"),
            socials_donate=os.getenv("SOCIALS_DONATE"),
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
            season_enabled=_bool(os.getenv("SEASON_ENABLED")),
            season_reward_roles=_strs(os.getenv("SEASON_REWARD_ROLES")),
            season_announce_channel_id=_single_int(os.getenv("SEASON_ANNOUNCE_CHANNEL_ID")),
            youtube_enabled=_bool(os.getenv("YOUTUBE_ENABLED")),
            youtube_api_key=os.getenv("YOUTUBE_API_KEY"),
            youtube_channel=os.getenv("YOUTUBE_CHANNEL"),
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
