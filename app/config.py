"""Конфигурация приложения из переменных окружения.

Внутри разбита на под-dataclass'ы по доменам; обратная совместимость
сохранена через ``Config.__getattr__`` — ``config.panel_port`` работает
так же, как раньше, проксируясь в ``config.panel.port``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

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


# ---------------------------------------------------------------------------
# Под-dataclass'ы по доменам
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class ApiConfig:
    """Общий сетевой слой внешних API."""

    timeout_seconds: float = 20.0
    proxy: str | None = None
    max_concurrency: int = 8
    circuit_failure_threshold: int = 5
    circuit_reset_seconds: float = 60.0


@dataclass(slots=True, frozen=True)
class DbConfig:
    """Хранилище и резервные копии."""

    path: str = str(_PROJECT_ROOT / "data" / "bot.db")
    url: str | None = None
    backup_dir: str = str(_PROJECT_ROOT / "data" / "backups")
    backup_interval_hours: float = 24.0
    backup_retention: int = 7
    backup_discord_channel_id: int | None = None


@dataclass(slots=True, frozen=True)
class PanelConfig:
    """Веб-панель."""

    host: str = "127.0.0.1"
    port: int | None = None
    password: str | None = None
    admin_password: str | None = None
    moderator_password: str | None = None
    viewer_password: str | None = None
    password_hash: str | None = None
    admin_password_hash: str | None = None
    moderator_password_hash: str | None = None
    viewer_password_hash: str | None = None
    public_url: str | None = None
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None
    oauth_redirect_url: str | None = None
    bridge_token: str | None = None
    admin_role_ids: str = ""
    trusted_proxy: bool = False


@dataclass(slots=True, frozen=True)
class StreamConfig:
    """Стримы: общее + Twitch + Kick + VK Видео + команды чата."""

    # Общее
    role_id: int | None = None
    role_user_ids: tuple[int, ...] = ()
    rsvp_role_id: int | None = None
    sticky_poll_seconds: float = 60.0
    quiet_hours: tuple[int, int] | None = None
    quiet_tz: str = "Europe/Moscow"
    abort_alert_minutes: int = 10
    archive_days: int = 90

    # Twitch
    twitch_client_id: str | None = None
    twitch_client_secret: str | None = None
    twitch_refresh_token: str | None = None
    twitch_channels: tuple[str, ...] = ()
    twitch_command_channel: str = ""
    twitch_notify_channel_id: int | None = None
    twitch_ping_role_id: int | None = None
    twitch_poll_seconds: float = 300.0
    twitch_chat_token: str = ""
    twitch_polls_token: str = ""
    twitch_bot_login: str = ""
    twitch_bot_refresh_token: str = ""
    twitch_bot_client_id: str = ""
    twitch_bot_refresh_provider: str = "twitch"
    twitch_schedule_channel_id: int | None = None

    # Kick
    kick_channel_slug: str | None = None
    kick_notify_channel_id: int | None = None
    kick_ping_role_id: int | None = None
    kick_poll_seconds: float = 300.0
    kick_mod_channel_id: int | None = None
    kick_access_token: str | None = None
    kick_ban_words: tuple[str, ...] = ()
    kick_pusher_app_key: str = "32cbd69e4b950bf97679"
    kick_pusher_host: str = "ws-us2.pusher.com"
    kick_chat_auto_link: bool = False
    kick_chat_link_text: str = "Стрим уже на Kick! Ссылка на стрим в шапке канала."
    kick_chat_send_as_user: bool = False

    # YouTube LIVE
    youtube_api_key: str | None = None
    youtube_notify_channel_id: int | None = None
    youtube_ping_role_id: int | None = None
    youtube_poll_seconds: float = 300.0

    # VK Видео
    vk_channel_slug: str | None = None
    vk_notify_channel_id: int | None = None
    vk_ping_role_id: int | None = None
    vk_poll_seconds: float = 300.0

    # Команды чата стримов
    chat_commands_enabled: bool = True
    chat_command_prefix: str = "!"
    chat_coin_reward: int = 5
    chat_cmd_cooldown: float = 3.0
    chat_poll_seconds: int = 90


@dataclass(slots=True, frozen=True)
class DonationConfig:
    """Донаты (DonationAlerts)."""

    token: str | None = None
    client_id: str | None = None
    refresh_token: str | None = None
    role_name: str = "Спонсор"
    code_prefix: str = "VIP"
    role_id: int | None = None
    min_amount: float = 0.0
    button_channel_id: int | None = None
    bonuses: tuple[str, ...] = ()
    notify_channel_id: int | None = None
    url: str | None = None
    poll_seconds: float = 15.0


@dataclass(slots=True, frozen=True)
class AutomodConfig:
    """Авто-модерация."""

    enabled: bool = True
    banned_words: str = ""
    block_links: bool = True
    allowed_links: str = ""
    caps_threshold: float = 0.8
    caps_min_len: int = 12
    max_messages_in_window: int = 5
    timeout_seconds: int = 300
    ban_after_timeouts: int = 3
    ban_window_seconds: int = 300
    ignore_roles: tuple[str, ...] = ()
    ignored_channels: tuple[int, ...] = ()
    antiraid_enabled: bool = False
    antiraid_window_seconds: int = 60
    antiraid_join_threshold: int = 8
    antiraid_slowmode_seconds: int = 10
    antiraid_cooldown_seconds: int = 300
    min_account_age_days: int = 0
    exempt_regex: str = ""
    lockdown_seconds: int = 300


@dataclass(slots=True, frozen=True)
class GuardConfig:
    """Глобальный rate-limit команд и kill-switch."""

    enabled: bool = True
    user_max: int = 6
    user_window: float = 10.0
    guild_max: int = 40
    guild_window: float = 10.0
    bypass_admin: bool = True
    bypass_roles: tuple[int, ...] = ()


@dataclass(slots=True, frozen=True)
class LogsConfig:
    """Расширенные логи, heartbeat, дайджест, starboard, автореспондер."""

    ignore_channel_ids: tuple[int, ...] = ()
    ignore_category_ids: tuple[int, ...] = ()
    bot_channel_id: int | None = None
    member_channel_id: int | None = None
    message_channel_id: int | None = None
    voice_channel_id: int | None = None
    mod_channel_id: int | None = None
    heartbeat_silence_minutes: int = 0
    disk_alert_mb: int = 0
    latency_alert_seconds: float = 0.0
    digest_hour: int = 21
    starboard_channel_id: int | None = None
    starboard_threshold: int = 5
    starboard_emoji: str = "⭐"
    autorespond_rules: tuple[tuple[str, str], ...] = ()
    autorespond_role_phrases: tuple[str, ...] = ()
    autorespond_role_id: int | None = None
    autorespond_cooldown: int = 15
    schedule_post_hour: int = -1


@dataclass(slots=True, frozen=True)
class WelcomeConfig:
    """Приветствия."""

    enabled: bool = True
    send_dm: bool = True
    channel_id: int | None = None
    channel_enabled: bool = False
    card: bool = False
    leave_channel_id: int | None = None
    leave_channel_enabled: bool = False
    title: str = "Добро пожаловать на дискорд сервер dendich!"
    intro: str = ""
    footer: str = "Приятного времяпрепровождения! 🔥"
    channel_descriptions: str = ""
    voice_descriptions: str = ""
    hidden_voice: str = ""


@dataclass(slots=True, frozen=True)
class AiConfig:
    """ИИ-чат (Gemini)."""

    enabled: bool = False
    api_key: str | None = None
    channels: tuple[int, ...] = ()
    cooldown_seconds: float = 45.0
    model: str = "gemini-1.5-flash"
    temperature: float = 0.9
    max_tokens: int = 220
    history_size: int = 12
    timeout_seconds: float = 45.0
    system_prompt: str = ""
    proxy: str | None = None


@dataclass(slots=True, frozen=True)
class OverlayConfig:
    """Оверлей (OBS)."""

    host: str = "127.0.0.1"
    port: int | None = None
    token: str | None = None
    public_url: str | None = None
    donation_goal_enabled: bool = False
    donation_goal_target: float = 0.0
    donation_goal_currency: str = "₽"
    donation_goal_label: str = "Донат-цель"
    donation_goal_current: float = 0.0


@dataclass(slots=True, frozen=True)
class SpotifyConfig:
    """Spotify Client Credentials для импорта треков/плейлистов."""

    client_id: str | None = None
    client_secret: str | None = None


@dataclass(slots=True, frozen=True)
class FeaturesConfig:
    """Прочие фичи: дни рождения, сезоны, роли, WARDOGS, соцсети и пр."""

    # Дни рождения
    birthday_channel_id: int | None = None
    birthday_announce_hour: int = 9
    birthday_ping_role_id: int | None = None

    # Правила-гейт
    rules_message_id: int | None = None
    rules_role_id: int | None = None

    # Временные голосовые
    temp_voice_trigger_ids: tuple[int, ...] = ()
    temp_voice_category_id: int | None = None

    # Меню ролей
    role_menu_enabled: bool = True
    role_menu_channel_id: int | None = None
    role_menu_message: str = "Уведомления и роли меню"
    role_menu_roles: tuple[str, ...] = ()
    role_menu_max_values: int = 10

    # Отчёт по ОЗУ
    ram_report_channel_id: int | None = None
    ram_report_interval_minutes: int = 30

    # Соцсети
    socials_discord: str | None = None
    socials_site: str | None = None
    socials_youtube: str | None = None
    socials_twitch: str | None = None
    socials_donate: str | None = None

    # WARDOGS
    wardogs_server_name: str = "Wardogs"
    wardogs_server_id: str | None = _DEFAULT_WARDOGS_SERVER_ID
    wardogs_join_url: str | None = None

    # Права категорий
    permissions_auto_apply: bool = False
    permissions_categories: str = ""

    # Счётчики сервера
    server_stats_enabled: bool = False
    server_stats_category_id: int | None = None
    server_stats_category_name: str = "СТАТИСТИКА"
    server_stats_update_seconds: int = 300
    server_stats_channels: str = ""

    # Сезоны
    season_enabled: bool = False
    season_reward_roles: tuple[str, ...] = ()
    season_announce_channel_id: int | None = None


# ---------------------------------------------------------------------------
# Маппинг «плоское имя → (под-dataclass, имя внутри)» для __getattr__
# ---------------------------------------------------------------------------

_PANEL_FIELDS = {
    "panel_host": "host",
    "panel_port": "port",
    "panel_password": "password",
    "panel_admin_password": "admin_password",
    "panel_moderator_password": "moderator_password",
    "panel_viewer_password": "viewer_password",
    "panel_password_hash": "password_hash",
    "panel_admin_password_hash": "admin_password_hash",
    "panel_moderator_password_hash": "moderator_password_hash",
    "panel_viewer_password_hash": "viewer_password_hash",
    "panel_public_url": "public_url",
    "panel_oauth_client_id": "oauth_client_id",
    "panel_oauth_client_secret": "oauth_client_secret",
    "panel_oauth_redirect_url": "oauth_redirect_url",
    "panel_bridge_token": "bridge_token",
    "panel_admin_role_ids": "admin_role_ids",
    "panel_trusted_proxy": "trusted_proxy",
}

_STREAM_FIELDS = {
    "stream_role_id": "role_id",
    "stream_role_user_ids": "role_user_ids",
    "stream_rsvp_role_id": "rsvp_role_id",
    "stream_sticky_poll_seconds": "sticky_poll_seconds",
    "stream_quiet_hours": "quiet_hours",
    "stream_quiet_tz": "quiet_tz",
    "stream_abort_alert_minutes": "abort_alert_minutes",
    "stream_archive_days": "archive_days",
    "twitch_client_id": "twitch_client_id",
    "twitch_client_secret": "twitch_client_secret",
    "twitch_refresh_token": "twitch_refresh_token",
    "twitch_channels": "twitch_channels",
    "twitch_notify_channel_id": "twitch_notify_channel_id",
    "twitch_ping_role_id": "twitch_ping_role_id",
    "twitch_poll_seconds": "twitch_poll_seconds",
    "twitch_chat_token": "twitch_chat_token",
    "twitch_bot_login": "twitch_bot_login",
    "twitch_bot_refresh_token": "twitch_bot_refresh_token",
    "twitch_bot_client_id": "twitch_bot_client_id",
    "twitch_bot_refresh_provider": "twitch_bot_refresh_provider",
    "twitch_schedule_channel_id": "twitch_schedule_channel_id",
    "kick_channel_slug": "kick_channel_slug",
    "kick_notify_channel_id": "kick_notify_channel_id",
    "kick_ping_role_id": "kick_ping_role_id",
    "kick_poll_seconds": "kick_poll_seconds",
    "kick_mod_channel_id": "kick_mod_channel_id",
    "kick_access_token": "kick_access_token",
    "kick_ban_words": "kick_ban_words",
    "kick_pusher_app_key": "kick_pusher_app_key",
    "kick_pusher_host": "kick_pusher_host",
    "kick_chat_auto_link": "kick_chat_auto_link",
    "kick_chat_link_text": "kick_chat_link_text",
    "kick_chat_send_as_user": "kick_chat_send_as_user",
    "youtube_api_key": "youtube_api_key",
    "youtube_notify_channel_id": "youtube_notify_channel_id",
    "youtube_ping_role_id": "youtube_ping_role_id",
    "youtube_poll_seconds": "youtube_poll_seconds",
    "vk_channel_slug": "vk_channel_slug",
    "vk_notify_channel_id": "vk_notify_channel_id",
    "vk_ping_role_id": "vk_ping_role_id",
    "vk_poll_seconds": "vk_poll_seconds",
    "chat_commands_enabled": "chat_commands_enabled",
    "chat_command_prefix": "chat_command_prefix",
    "chat_coin_reward": "chat_coin_reward",
    "chat_cmd_cooldown": "chat_cmd_cooldown",
    "chat_poll_seconds": "chat_poll_seconds",
}

_DONATION_FIELDS = {
    "donations_token": "token",
    "donations_client_id": "client_id",
    "donations_refresh_token": "refresh_token",
    "donation_role_name": "role_name",
    "donation_code_prefix": "code_prefix",
    "donation_role_id": "role_id",
    "donation_min_amount": "min_amount",
    "donate_button_channel_id": "button_channel_id",
    "donate_bonuses": "bonuses",
    "donation_notify_channel_id": "notify_channel_id",
    "donate_url": "url",
    "donation_poll_seconds": "poll_seconds",
}

_AUTOMOD_FIELDS = {
    "automod_" + key: key
    for key in (
        "enabled", "banned_words", "block_links", "allowed_links",
        "caps_threshold", "caps_min_len", "max_messages_in_window",
        "timeout_seconds", "ban_after_timeouts", "ban_window_seconds",
        "ignore_roles", "ignored_channels", "antiraid_enabled",
        "antiraid_window_seconds", "antiraid_join_threshold",
        "antiraid_slowmode_seconds", "antiraid_cooldown_seconds",
        "min_account_age_days", "exempt_regex", "lockdown_seconds",
    )
}

_GUARD_FIELDS = {
    "guard_" + key: key
    for key in ("enabled", "user_max", "user_window", "guild_max", "guild_window", "bypass_admin", "bypass_roles")
}

_LOGS_FIELDS = {
    "logs_ignore_channel_ids": "ignore_channel_ids",
    "logs_ignore_category_ids": "ignore_category_ids",
    "bot_log_channel_id": "bot_channel_id",
    "member_log_channel_id": "member_channel_id",
    "message_log_channel_id": "message_channel_id",
    "voice_log_channel_id": "voice_channel_id",
    "mod_log_channel_id": "mod_channel_id",
    "heartbeat_silence_minutes": "heartbeat_silence_minutes",
    "disk_alert_mb": "disk_alert_mb",
    "latency_alert_seconds": "latency_alert_seconds",
    "digest_hour": "digest_hour",
    "starboard_channel_id": "starboard_channel_id",
    "starboard_threshold": "starboard_threshold",
    "starboard_emoji": "starboard_emoji",
    "autorespond_rules": "autorespond_rules",
    "autorespond_role_phrases": "autorespond_role_phrases",
    "autorespond_role_id": "autorespond_role_id",
    "autorespond_cooldown": "autorespond_cooldown",
    "schedule_post_hour": "schedule_post_hour",
}

_WELCOME_FIELDS = {
    "welcome_" + key: key
    for key in (
        "enabled", "send_dm", "channel_id", "channel_enabled", "card",
        "leave_channel_id", "leave_channel_enabled", "title", "intro",
        "footer", "channel_descriptions", "voice_descriptions", "hidden_voice",
    )
}

_AI_FIELDS = {
    "ai_" + key: key
    for key in (
        "enabled", "api_key", "channels", "cooldown_seconds", "model",
        "temperature", "max_tokens", "history_size", "timeout_seconds",
        "system_prompt", "proxy",
    )
}

_OVERLAY_FIELDS = {
    "overlay_" + key: key
    for key in (
        "host", "port", "token", "public_url",
        "donation_goal_enabled", "donation_goal_target",
        "donation_goal_currency", "donation_goal_label", "donation_goal_current",
    )
}

_FEATURES_FIELDS = {
    "birthday_channel_id": "birthday_channel_id",
    "birthday_announce_hour": "birthday_announce_hour",
    "birthday_ping_role_id": "birthday_ping_role_id",
    "rules_message_id": "rules_message_id",
    "rules_role_id": "rules_role_id",
    "temp_voice_trigger_ids": "temp_voice_trigger_ids",
    "temp_voice_category_id": "temp_voice_category_id",
    "role_menu_enabled": "role_menu_enabled",
    "role_menu_channel_id": "role_menu_channel_id",
    "role_menu_message": "role_menu_message",
    "role_menu_roles": "role_menu_roles",
    "role_menu_max_values": "role_menu_max_values",
    "ram_report_channel_id": "ram_report_channel_id",
    "ram_report_interval_minutes": "ram_report_interval_minutes",
    "socials_discord": "socials_discord",
    "socials_site": "socials_site",
    "socials_youtube": "socials_youtube",
    "socials_twitch": "socials_twitch",
    "socials_donate": "socials_donate",
    "wardogs_server_name": "wardogs_server_name",
    "wardogs_server_id": "wardogs_server_id",
    "wardogs_join_url": "wardogs_join_url",
    "permissions_auto_apply": "permissions_auto_apply",
    "permissions_categories": "permissions_categories",
    "server_stats_enabled": "server_stats_enabled",
    "server_stats_category_id": "server_stats_category_id",
    "server_stats_category_name": "server_stats_category_name",
    "server_stats_update_seconds": "server_stats_update_seconds",
    "server_stats_channels": "server_stats_channels",
    "season_enabled": "season_enabled",
    "season_reward_roles": "season_reward_roles",
    "season_announce_channel_id": "season_announce_channel_id",
}

#: Плоское имя поля → (имя под-dataclass'а на Config, имя внутри под-dataclass'а)
_PROXY_MAP: dict[str, tuple[str, str]] = {}
for _flat, _inner in _PANEL_FIELDS.items():
    _PROXY_MAP[_flat] = ("panel", _inner)
for _flat, _inner in _STREAM_FIELDS.items():
    _PROXY_MAP[_flat] = ("stream", _inner)
for _flat, _inner in _DONATION_FIELDS.items():
    _PROXY_MAP[_flat] = ("donations", _inner)
for _flat, _inner in _AUTOMOD_FIELDS.items():
    _PROXY_MAP[_flat] = ("automod", _inner)
for _flat, _inner in _GUARD_FIELDS.items():
    _PROXY_MAP[_flat] = ("guard", _inner)
for _flat, _inner in _LOGS_FIELDS.items():
    _PROXY_MAP[_flat] = ("logs", _inner)
for _flat, _inner in _WELCOME_FIELDS.items():
    _PROXY_MAP[_flat] = ("welcome", _inner)
for _flat, _inner in _AI_FIELDS.items():
    _PROXY_MAP[_flat] = ("ai", _inner)
for _flat, _inner in _OVERLAY_FIELDS.items():
    _PROXY_MAP[_flat] = ("overlay", _inner)
for _flat, _inner in _FEATURES_FIELDS.items():
    _PROXY_MAP[_flat] = ("features", _inner)

#: DB/API/Spotify поля проксируются напрямую (имена совпадают или имеют префикс)
_DIRECT_PROXY = {
    "db_path": ("db", "path"),
    "database_url": ("db", "url"),
    "db_backup_dir": ("db", "backup_dir"),
    "db_backup_interval_hours": ("db", "backup_interval_hours"),
    "db_backup_retention": ("db", "backup_retention"),
    "db_backup_discord_channel_id": ("db", "backup_discord_channel_id"),
    "api_timeout_seconds": ("api", "timeout_seconds"),
    "api_proxy": ("api", "proxy"),
    "api_max_concurrency": ("api", "max_concurrency"),
    "api_circuit_failure_threshold": ("api", "circuit_failure_threshold"),
    "api_circuit_reset_seconds": ("api", "circuit_reset_seconds"),
    "spotify_client_id": ("spotify", "client_id"),
    "spotify_client_secret": ("spotify", "client_secret"),
}
_PROXY_MAP.update(_DIRECT_PROXY)

#: Имя домена на Config → класс под-dataclass'а
_DOMAIN_CLASSES: dict[str, type] = {
    "api": ApiConfig,
    "db": DbConfig,
    "panel": PanelConfig,
    "stream": StreamConfig,
    "donations": DonationConfig,
    "automod": AutomodConfig,
    "guard": GuardConfig,
    "logs": LogsConfig,
    "welcome": WelcomeConfig,
    "ai": AiConfig,
    "overlay": OverlayConfig,
    "spotify": SpotifyConfig,
    "features": FeaturesConfig,
}

#: Поля ядра Config → значения по умолчанию
_CORE_DEFAULTS: dict[str, Any] = {
    "prefix": "!",
    "log_level": "INFO",
    "status_activity": "играет с кодом",
    "owner_id": None,
    "version": "3.5.0",
    "guild_id": None,
}


@dataclass(frozen=True, init=False)
class Config:
    """Полная конфигурация бота.

    Поля-домены собраны в под-dataclass'ы (``config.panel.port``);
    плоский доступ (``config.panel_port``) и плоский конструктор
    (``Config(token=..., db_path=..., twitch_channels=...)``) сохранены.
    """

    # Ядро
    token: str
    prefix: str = "!"
    log_level: str = "INFO"
    status_activity: str = "играет с кодом"
    owner_id: int | None = None
    version: str = "3.5.0"
    guild_id: int | None = None

    # Домены
    api: ApiConfig = field(default_factory=ApiConfig)
    db: DbConfig = field(default_factory=DbConfig)
    panel: PanelConfig = field(default_factory=PanelConfig)
    stream: StreamConfig = field(default_factory=StreamConfig)
    donations: DonationConfig = field(default_factory=DonationConfig)
    automod: AutomodConfig = field(default_factory=AutomodConfig)
    guard: GuardConfig = field(default_factory=GuardConfig)
    logs: LogsConfig = field(default_factory=LogsConfig)
    welcome: WelcomeConfig = field(default_factory=WelcomeConfig)
    ai: AiConfig = field(default_factory=AiConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    spotify: SpotifyConfig = field(default_factory=SpotifyConfig)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if args:
            if len(args) > 1:
                raise TypeError(f"Config() takes at most 1 positional argument ({len(args)} given)")
            kwargs.setdefault("token", args[0])
        token = kwargs.pop("token", None)
        if token is None:
            raise TypeError("Config() missing required argument: 'token'")

        core: dict[str, Any] = {"token": token}
        for key in list(kwargs):
            if key in _CORE_DEFAULTS:
                core[key] = kwargs.pop(key)
        for key, default in _CORE_DEFAULTS.items():
            core.setdefault(key, default)

        domain_instances: dict[str, Any] = {}
        for key in list(kwargs):
            if key in _DOMAIN_CLASSES:
                domain_instances[key] = kwargs.pop(key)

        domain_kwargs: dict[str, dict[str, Any]] = {name: {} for name in _DOMAIN_CLASSES}
        for key, value in kwargs.items():
            entry = _PROXY_MAP.get(key)
            if entry is None:
                raise TypeError(f"Config() got an unexpected keyword argument '{key}'")
            sub, inner = entry
            domain_kwargs[sub][inner] = value

        for key, value in core.items():
            object.__setattr__(self, key, value)
        for name, cls in _DOMAIN_CLASSES.items():
            if name in domain_instances:
                inst = domain_instances[name]
                overrides = domain_kwargs[name]
                if overrides and isinstance(inst, cls):
                    vals = {f.name: getattr(inst, f.name) for f in fields(cls)}
                    vals.update(overrides)
                    object.__setattr__(self, name, cls(**vals))
                else:
                    object.__setattr__(self, name, inst)
            else:
                object.__setattr__(self, name, cls(**domain_kwargs[name]))

    def __getattr__(self, name: str) -> Any:
        """Проксирует плоские имена (``panel_port``) в под-dataclass'ы.

        Вызывается только при отсутствии normal lookup — поля-домены
        (``config.panel``) и ядро (``config.token``) резолвятся как обычно.
        """
        entry = _PROXY_MAP.get(name)
        if entry is not None:
            sub_name, inner = entry
            return getattr(getattr(self, sub_name), inner)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

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
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            status_activity=os.getenv("STATUS_ACTIVITY", "играет с кодом"),
            owner_id=int(owner_raw) if owner_raw and owner_raw.isdigit() else None,
            guild_id=_single_int(os.getenv("GUILD_ID")),
            api=ApiConfig(
                timeout_seconds=max(5.0, min(120.0, float(os.getenv("API_TIMEOUT_SECONDS", "20")))),
                proxy=os.getenv("API_PROXY") or None,
                max_concurrency=max(1, min(64, int(os.getenv("API_MAX_CONCURRENCY", "8")))),
                circuit_failure_threshold=max(1, min(20, int(os.getenv("API_CIRCUIT_FAILURE_THRESHOLD", "5")))),
                circuit_reset_seconds=max(5.0, min(900.0, float(os.getenv("API_CIRCUIT_RESET_SECONDS", "60")))),
            ),
            db=DbConfig(
                path=os.getenv("DB_PATH", str(_PROJECT_ROOT / "data" / "bot.db")),
                url=os.getenv("DATABASE_URL") or None,
                backup_dir=os.getenv("DB_BACKUP_DIR", str(_PROJECT_ROOT / "data" / "backups")),
                backup_interval_hours=max(1.0, float(os.getenv("DB_BACKUP_INTERVAL_HOURS", "24"))),
                backup_retention=max(1, min(90, int(os.getenv("DB_BACKUP_RETENTION", "7")))),
                backup_discord_channel_id=_single_int(os.getenv("DB_BACKUP_DISCORD_CHANNEL_ID")),
            ),
            panel=PanelConfig(
                host=os.getenv("PANEL_HOST")
                or ("0.0.0.0" if os.getenv("PANEL_PUBLIC_URL", "").strip() else "127.0.0.1"),
                port=_single_int(os.getenv("PANEL_PORT") or os.getenv("PORT")),
                password=os.getenv("PANEL_PASSWORD"),
                admin_password=os.getenv("PANEL_ADMIN_PASSWORD"),
                moderator_password=os.getenv("PANEL_MODERATOR_PASSWORD"),
                viewer_password=os.getenv("PANEL_VIEWER_PASSWORD"),
                password_hash=os.getenv("PANEL_PASSWORD_HASH") or None,
                admin_password_hash=os.getenv("PANEL_ADMIN_PASSWORD_HASH") or None,
                moderator_password_hash=os.getenv("PANEL_MODERATOR_PASSWORD_HASH") or None,
                viewer_password_hash=os.getenv("PANEL_VIEWER_PASSWORD_HASH") or None,
                public_url=os.getenv("PANEL_PUBLIC_URL"),
                oauth_client_id=os.getenv("PANEL_OAUTH_CLIENT_ID") or None,
                oauth_client_secret=os.getenv("PANEL_OAUTH_CLIENT_SECRET") or None,
                oauth_redirect_url=os.getenv("PANEL_OAUTH_REDIRECT_URL") or None,
                bridge_token=os.getenv("PANEL_BRIDGE_TOKEN") or None,
                admin_role_ids=os.getenv("PANEL_ADMIN_ROLE_IDS", ""),
                trusted_proxy=_bool(os.getenv("PANEL_TRUSTED_PROXY")),
            ),
            stream=StreamConfig(
                role_id=_single_int(os.getenv("STREAM_ROLE_ID")),
                role_user_ids=_ints(os.getenv("STREAM_ROLE_USER_IDS")),
                rsvp_role_id=_single_int(os.getenv("STREAM_RSVP_ROLE_ID")),
                sticky_poll_seconds=max(30.0, float(os.getenv("STREAM_STICKY_POLL_SECONDS", "60"))),
                quiet_hours=_hour_range(os.getenv("STREAM_QUIET_HOURS")),
                quiet_tz=os.getenv("STREAM_QUIET_TZ") or "Europe/Moscow",
                abort_alert_minutes=max(0, int(os.getenv("STREAM_ABORT_ALERT_MINUTES", "10") or "10")),
                archive_days=max(1, int(os.getenv("STREAM_ARCHIVE_DAYS", "90") or "90")),
                twitch_client_id=os.getenv("TWITCH_CLIENT_ID"),
                twitch_client_secret=os.getenv("TWITCH_CLIENT_SECRET"),
                twitch_refresh_token=os.getenv("TWITCH_REFRESH_TOKEN"),
                twitch_channels=_strs(os.getenv("TWITCH_CHANNELS") or os.getenv("TWITCH_CHANNEL", "dend1chlive")),
                twitch_command_channel=(os.getenv("TWITCH_COMMAND_CHANNEL") or os.getenv("TWITCH_CHANNEL", "")).strip().lower(),
                twitch_notify_channel_id=_single_int(os.getenv("TWITCH_NOTIFY_CHANNEL_ID")),
                twitch_ping_role_id=_single_int(os.getenv("TWITCH_PING_ROLE_ID")),
                twitch_poll_seconds=float(os.getenv("TWITCH_POLL_SECONDS", "300")),
                twitch_chat_token=os.getenv("TWITCH_CHAT_TOKEN", ""),
                twitch_polls_token=os.getenv("TWITCH_POLLS_TOKEN", ""),
                twitch_bot_login=os.getenv("TWITCH_BOT_LOGIN", "").strip().lower(),
                twitch_bot_refresh_token=os.getenv("TWITCH_BOT_REFRESH_TOKEN", "").strip(),
                twitch_bot_client_id=os.getenv("TWITCH_BOT_CLIENT_ID", "").strip(),
                twitch_bot_refresh_provider=os.getenv("TWITCH_BOT_REFRESH_PROVIDER", "twitch").strip().lower(),
                twitch_schedule_channel_id=_single_int(os.getenv("TWITCH_SCHEDULE_CHANNEL_ID")),
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
                youtube_api_key=os.getenv("YOUTUBE_API_KEY"),
                youtube_notify_channel_id=_single_int(os.getenv("YOUTUBE_NOTIFY_CHANNEL_ID")),
                youtube_ping_role_id=_single_int(os.getenv("YOUTUBE_PING_ROLE_ID")),
                youtube_poll_seconds=max(120.0, float(os.getenv("YOUTUBE_POLL_SECONDS", "300"))),
                vk_channel_slug=os.getenv("VK_CHANNEL_SLUG"),
                vk_notify_channel_id=_single_int(os.getenv("VK_NOTIFY_CHANNEL_ID")),
                vk_ping_role_id=_single_int(os.getenv("VK_PING_ROLE_ID")),
                vk_poll_seconds=max(30.0, float(os.getenv("VK_POLL_SECONDS", "300"))),
                chat_commands_enabled=_bool(os.getenv("CHAT_COMMANDS_ENABLED"), True),
                chat_command_prefix=(os.getenv("CHAT_COMMAND_PREFIX") or "!")[:4].strip() or "!",
                chat_coin_reward=max(0, int(os.getenv("CHAT_COIN_REWARD", "5") or "5")),
                chat_cmd_cooldown=max(0.0, float(os.getenv("CHAT_CMD_COOLDOWN", "3") or "3")),
                chat_poll_seconds=max(30, min(600, int(os.getenv("CHAT_POLL_SECONDS", "90") or "90"))),
            ),
            donations=DonationConfig(
                token=os.getenv("DONATIONS_TOKEN"),
                client_id=os.getenv("DONATIONS_CLIENT_ID"),
                refresh_token=os.getenv("DONATIONS_REFRESH_TOKEN"),
                role_name=os.getenv("DONATION_ROLE_NAME", "Спонсор"),
                code_prefix=os.getenv("DONATION_CODE_PREFIX", "VIP"),
                role_id=_single_int(os.getenv("DONATION_ROLE_ID")),
                min_amount=float(os.getenv("DONATION_MIN_AMOUNT") or 0),
                button_channel_id=_single_int(os.getenv("DONATE_BUTTON_CHANNEL_ID")),
                bonuses=_strs(os.getenv("DONATE_BONUSES")),
                notify_channel_id=_single_int(os.getenv("DONATION_NOTIFY_CHANNEL_ID")),
                url=os.getenv("DONATE_URL"),
                poll_seconds=float(os.getenv("DONATION_POLL_SECONDS", "15")),
            ),
            automod=AutomodConfig(
                enabled=_bool(os.getenv("AUTOMOD_ENABLED", "1")),
                banned_words=os.getenv("AUTOMOD_BANNED_WORDS", ""),
                block_links=_bool(os.getenv("AUTOMOD_BLOCK_LINKS", "1")),
                allowed_links=os.getenv("AUTOMOD_ALLOWED_LINKS", ""),
                caps_threshold=float(os.getenv("AUTOMOD_CAPS_THRESHOLD", "0.8")),
                caps_min_len=max(1, int(os.getenv("AUTOMOD_CAPS_MIN_LEN", "12"))),
                max_messages_in_window=max(1, int(os.getenv("AUTOMOD_MAX_MESSAGES_IN_WINDOW", "5"))),
                timeout_seconds=max(0, int(os.getenv("AUTOMOD_TIMEOUT_SECONDS", "300"))),
                ban_after_timeouts=max(0, int(os.getenv("AUTOMOD_BAN_AFTER_TIMEOUTS", "3"))),
                ban_window_seconds=max(1, int(os.getenv("AUTOMOD_BAN_WINDOW_SECONDS", "300"))),
                ignore_roles=_strs(os.getenv("AUTOMOD_IGNORE_ROLES")),
                ignored_channels=_ints(os.getenv("AUTOMOD_IGNORED_CHANNELS")),
                antiraid_enabled=_bool(os.getenv("AUTOMOD_ANTIRAID_ENABLED", "0")),
                antiraid_window_seconds=max(10, int(os.getenv("AUTOMOD_ANTIRAID_WINDOW_SECONDS", "60"))),
                antiraid_join_threshold=max(2, int(os.getenv("AUTOMOD_ANTIRAID_JOIN_THRESHOLD", "8"))),
                antiraid_slowmode_seconds=max(0, int(os.getenv("AUTOMOD_ANTIRAID_SLOWMODE_SECONDS", "10"))),
                antiraid_cooldown_seconds=max(30, int(os.getenv("AUTOMOD_ANTIRAID_COOLDOWN_SECONDS", "300"))),
                min_account_age_days=max(0, int(os.getenv("AUTOMOD_MIN_ACCOUNT_AGE_DAYS", "0"))),
                exempt_regex=os.getenv("AUTOMOD_EXEMPT_REGEX", ""),
                lockdown_seconds=max(30, int(os.getenv("AUTOMOD_LOCKDOWN_SECONDS", "300"))),
            ),
            guard=GuardConfig(
                enabled=_bool(os.getenv("GUARD_ENABLED"), True),
                user_max=max(1, min(100, int(os.getenv("GUARD_USER_MAX", "6") or "6"))),
                user_window=max(1.0, min(600.0, float(os.getenv("GUARD_USER_WINDOW", "10") or "10"))),
                guild_max=max(1, min(1000, int(os.getenv("GUARD_GUILD_MAX", "40") or "40"))),
                guild_window=max(1.0, min(600.0, float(os.getenv("GUARD_GUILD_WINDOW", "10") or "10"))),
                bypass_admin=_bool(os.getenv("GUARD_BYPASS_ADMIN"), True),
                bypass_roles=_ints(os.getenv("GUARD_BYPASS_ROLES")),
            ),
            logs=LogsConfig(
                ignore_channel_ids=_ints(os.getenv("LOGS_IGNORE_CHANNEL_IDS")),
                ignore_category_ids=_ints(os.getenv("LOGS_IGNORE_CATEGORY_IDS")),
                bot_channel_id=_single_int(os.getenv("BOT_LOG_CHANNEL_ID")),
                member_channel_id=_single_int(os.getenv("MEMBER_LOG_CHANNEL_ID")),
                message_channel_id=_single_int(os.getenv("MESSAGE_LOG_CHANNEL_ID")),
                voice_channel_id=_single_int(os.getenv("VOICE_LOG_CHANNEL_ID")),
                mod_channel_id=_single_int(os.getenv("MOD_LOG_CHANNEL_ID")),
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
                schedule_post_hour=max(-1, min(23, int(os.getenv("SCHEDULE_POST_HOUR", "-1") or "-1"))),
            ),
            welcome=WelcomeConfig(
                enabled=_bool(os.getenv("WELCOME_ENABLED", "1")),
                send_dm=_bool(os.getenv("WELCOME_SEND_DM", "1")),
                channel_id=_single_int(os.getenv("WELCOME_CHANNEL_ID")),
                channel_enabled=_bool(os.getenv("WELCOME_CHANNEL_ENABLED")),
                card=_bool(os.getenv("WELCOME_CARD")),
                leave_channel_id=_single_int(os.getenv("WELCOME_LEAVE_CHANNEL_ID")),
                leave_channel_enabled=_bool(os.getenv("WELCOME_LEAVE_CHANNEL_ENABLED")),
                title=os.getenv("WELCOME_TITLE", "Добро пожаловать на дискорд сервер dendich!"),
                intro=os.getenv("WELCOME_INTRO", ""),
                footer=os.getenv("WELCOME_FOOTER", "Приятного времяпрепровождения! 🔥"),
                channel_descriptions=os.getenv("WELCOME_CHANNEL_DESCRIPTIONS", ""),
                voice_descriptions=os.getenv("WELCOME_VOICE_DESCRIPTIONS", ""),
                hidden_voice=os.getenv("WELCOME_HIDDEN_VOICE", ""),
            ),
            ai=AiConfig(
                enabled=_bool(os.getenv("AI_ENABLED")),
                api_key=os.getenv("GEMINI_API_KEY"),
                channels=_ints(os.getenv("AI_CHANNELS")),
                cooldown_seconds=max(5.0, float(os.getenv("AI_COOLDOWN_SECONDS", "45"))),
                model=os.getenv("AI_MODEL", "gemini-1.5-flash"),
                temperature=float(os.getenv("AI_TEMPERATURE", "0.9")),
                max_tokens=max(1, int(os.getenv("AI_MAX_TOKENS", "220"))),
                history_size=max(2, int(os.getenv("AI_HISTORY_SIZE", "12"))),
                timeout_seconds=max(10.0, float(os.getenv("AI_TIMEOUT_SECONDS", "45"))),
                system_prompt=os.getenv("AI_SYSTEM_PROMPT", ""),
                proxy=(os.getenv("AI_PROXY") or os.getenv("GEMINI_PROXY") or None),
            ),
            overlay=OverlayConfig(
                host=os.getenv("OVERLAY_HOST")
                or ("0.0.0.0" if os.getenv("OVERLAY_PUBLIC_URL", "").strip() else "127.0.0.1"),
                port=_single_int(os.getenv("OVERLAY_PORT")),
                token=os.getenv("OVERLAY_TOKEN"),
                public_url=os.getenv("OVERLAY_PUBLIC_URL"),
                donation_goal_enabled=_bool(os.getenv("OVERLAY_DONATION_GOAL_ENABLED")),
                donation_goal_target=float(os.getenv("OVERLAY_DONATION_GOAL_TARGET") or 0),
                donation_goal_currency=os.getenv("OVERLAY_DONATION_GOAL_CURRENCY", "₽"),
                donation_goal_label=os.getenv("OVERLAY_DONATION_GOAL_LABEL", "Донат-цель"),
                donation_goal_current=float(os.getenv("OVERLAY_DONATION_GOAL_CURRENT") or 0),
            ),
            spotify=SpotifyConfig(
                client_id=os.getenv("SPOTIFY_CLIENT_ID") or None,
                client_secret=os.getenv("SPOTIFY_CLIENT_SECRET") or None,
            ),
            features=FeaturesConfig(
                birthday_channel_id=_single_int(os.getenv("BIRTHDAY_CHANNEL_ID")),
                birthday_announce_hour=_clamp_hour(os.getenv("BIRTHDAY_ANNOUNCE_HOUR", "9")),
                birthday_ping_role_id=_single_int(os.getenv("BIRTHDAY_PING_ROLE_ID")),
                rules_message_id=_single_int(os.getenv("RULES_MESSAGE_ID")),
                rules_role_id=_single_int(os.getenv("RULES_ROLE_ID")),
                temp_voice_trigger_ids=_ints(os.getenv("TEMP_VOICE_TRIGGER_IDS")),
                temp_voice_category_id=_single_int(os.getenv("TEMP_VOICE_CATEGORY_ID")),
                role_menu_enabled=_bool(os.getenv("ROLE_MENU_ENABLED", "1")),
                role_menu_channel_id=_single_int(os.getenv("ROLE_MENU_CHANNEL_ID")),
                role_menu_message=os.getenv("ROLE_MENU_MESSAGE", "Уведомления и роли меню"),
                role_menu_roles=_strs(os.getenv("ROLE_MENU_ROLES")),
                role_menu_max_values=max(1, int(os.getenv("ROLE_MENU_MAX_VALUES", "10"))),
                ram_report_channel_id=_single_int(os.getenv("RAM_REPORT_CHANNEL_ID")),
                ram_report_interval_minutes=max(1, int(os.getenv("RAM_REPORT_INTERVAL_MINUTES", "30"))),
                socials_discord=os.getenv("TWITCH_DISCORD_URL") or os.getenv("SOCIALS_DISCORD"),
                socials_site=os.getenv("SOCIALS_SITE"),
                socials_youtube=os.getenv("TWITCH_YOUTUBE_URL") or os.getenv("SOCIALS_YOUTUBE"),
                socials_twitch=os.getenv("SOCIALS_TWITCH"),
                socials_donate=os.getenv("TWITCH_DONATE_URL") or os.getenv("SOCIALS_DONATE"),
                wardogs_server_name=os.getenv("WARDOGS_SERVER_NAME", "Wardogs").strip() or "Wardogs",
                wardogs_server_id=os.getenv("WARDOGS_SERVER_ID") or _DEFAULT_WARDOGS_SERVER_ID,
                wardogs_join_url=os.getenv("WARDOGS_JOIN_URL") or None,
                permissions_auto_apply=_bool(os.getenv("PERMISSIONS_AUTO_APPLY")),
                permissions_categories=os.getenv("PERMISSIONS_CATEGORIES", ""),
                server_stats_enabled=_bool(os.getenv("SERVER_STATS_ENABLED")),
                server_stats_category_id=_single_int(os.getenv("SERVER_STATS_CATEGORY_ID")),
                server_stats_category_name=os.getenv("SERVER_STATS_CATEGORY_NAME", "СТАТИСТИКА"),
                server_stats_update_seconds=max(60, int(os.getenv("SERVER_STATS_UPDATE_SECONDS", "300"))),
                server_stats_channels=os.getenv("SERVER_STATS_CHANNELS", ""),
                season_enabled=_bool(os.getenv("SEASON_ENABLED")),
                season_reward_roles=_strs(os.getenv("SEASON_REWARD_ROLES")),
                season_announce_channel_id=_single_int(os.getenv("SEASON_ANNOUNCE_CHANNEL_ID")),
            ),
        )
