"""Настройки сервера: чтение/запись каналов, витрина модулей, effective logs."""
from __future__ import annotations

import re
from typing import Any

from aiohttp import web

from app.core.webpanel.base_api import _BaseApi
from app.core.webpanel.payload import _SETTING_COLUMNS


class _SettingsApiMixin(_BaseApi):
    """Настройки сервера: чтение/запись каналов, витрина модулей, effective logs."""

    async def _api_settings_get(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        service = self.services.settings
        settings = await service.get(guild.id)
        values = {column: (str(settings[column]) if settings.get(column) else "") for column in _SETTING_COLUMNS}
        return self._json(
            {
                "ok": True,
                "guild_id": str(guild.id),
                "guild_name": guild.name,
                "settings": values,
                "automod_enabled": bool(settings.get("automod_enabled")),
                "blocked_words": await service.blocked_words(guild.id),
                "channels": self._channel_options(),
                "categories": self._category_options(),
                "roles": self._role_options(),
                "modules": self._modules_status(),
                "effective_logs": self._effective_log_channels(settings),
                "db_engine": self._db_engine(),
            }
        )

    async def _api_settings_post(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        payload = await self._read_json(request)
        service = self.services.settings
        values: dict[str, Any] = {}
        for column in _SETTING_COLUMNS:
            if column not in payload:
                continue
            raw = payload.get(column)
            if raw in (None, "", 0):
                values[column] = None
                continue
            try:
                values[column] = int(raw)
            except (TypeError, ValueError):
                return self._json({"ok": False, "error": f"Некорректный ID канала: {column}"}, status=400)
        if "automod_enabled" in payload:
            values["automod_enabled"] = 1 if payload.get("automod_enabled") else 0
        if values:
            await service.update(guild.id, **values)
        if "blocked_words" in payload:
            words = payload.get("blocked_words") or []
            if isinstance(words, str):
                words = re.split(r"[\n,]+", words)
            await service.set_blocked_words(guild.id, list(words))
        return self._json({"ok": True})

    def _effective_log_channels(self, settings: dict[str, Any]) -> dict[str, int | None]:
        config = self.bot.config

        def channel_id(value: Any) -> int | None:
            return int(value) if value else None

        return {
            "log": channel_id(settings.get("log_channel_id")),
            "member": channel_id(settings.get("member_log_channel_id") or config.member_log_channel_id),
            "message": channel_id(settings.get("message_log_channel_id") or config.message_log_channel_id),
            "voice": channel_id(settings.get("voice_log_channel_id") or config.voice_log_channel_id),
            "mod": channel_id(settings.get("mod_log_channel_id") or config.mod_log_channel_id),
            "bot": channel_id(settings.get("bot_log_channel_id") or config.bot_log_channel_id),
        }

    def _modules_status(self) -> dict[str, Any]:
        """Витрина модулей, настраиваемых через .env (только для чтения)."""
        config = self.bot.config
        return {
            "welcome": {
                "enabled": config.welcome_enabled,
                "send_dm": config.welcome_send_dm,
                "channel": config.welcome_channel_id,
                "channel_enabled": config.welcome_channel_enabled,
                "leave_channel": config.welcome_leave_channel_id,
                "leave_enabled": config.welcome_leave_channel_enabled,
            },
            "role_menu": {
                "enabled": config.role_menu_enabled,
                "channel": config.role_menu_channel_id,
                "message": config.role_menu_message,
                "roles": list(config.role_menu_roles),
                "max_values": config.role_menu_max_values,
            },
            "birthdays": {
                "channel": config.birthday_channel_id,
                "hour": config.birthday_announce_hour,
                "ping_role": config.birthday_ping_role_id,
            },
            "temp_voices": {
                "triggers": list(config.temp_voice_trigger_ids),
                "category": config.temp_voice_category_id,
            },
            "donations": {
                "notify_channel": config.donation_notify_channel_id,
                "button_channel": config.donate_button_channel_id,
                "role_id": config.donation_role_id,
                "role_name": config.donation_role_name,
                "bonuses": list(config.donate_bonuses),
                "url": config.donate_url,
            },
            "overlay": {
                "host": config.overlay_host,
                "port": config.overlay_port,
                "goal_enabled": config.overlay_donation_goal_enabled,
                "goal_target": config.overlay_donation_goal_target,
                "goal_current": config.overlay_donation_goal_current,
                "currency": config.overlay_donation_goal_currency,
                "label": config.overlay_donation_goal_label,
            },
            "logs": {
                "ignore_channels": list(config.logs_ignore_channel_ids),
                "ignore_categories": list(config.logs_ignore_category_ids),
            },
            "kick": {
                "slug": config.kick_channel_slug,
                "notify_channel": config.kick_notify_channel_id,
                "mod_channel": config.kick_mod_channel_id,
                "ping_role": config.kick_ping_role_id,
            },
            "twitch": {
                "channels": list(config.twitch_channels),
                "notify_channel": config.twitch_notify_channel_id,
                "ping_role": config.twitch_ping_role_id,
            },
            "automod": {
                "block_links": config.automod_block_links,
                "caps_threshold": config.automod_caps_threshold,
                "max_messages": config.automod_max_messages_in_window,
                "timeout_seconds": config.automod_timeout_seconds,
                "ban_after": config.automod_ban_after_timeouts,
                "banned_words": config.automod_banned_words or "",
            },
            "ai_chat": {
                "enabled": config.ai_enabled,
                "model": config.ai_model,
                "channels": list(config.ai_channels),
                "has_key": bool(config.ai_api_key),
                "proxy": bool(config.ai_proxy),
            },
            "server_stats": {
                "enabled": config.server_stats_enabled,
                "category": config.server_stats_category_name,
                "update_seconds": config.server_stats_update_seconds,
            },
            "seasons": {
                "enabled": config.season_enabled,
                "announce_channel": config.season_announce_channel_id,
                "reward_roles": list(config.season_reward_roles),
            },
            "rules_gate": {
                "message": config.rules_message_id,
                "role": config.rules_role_id,
            },
            "ram_report": {
                "channel": config.ram_report_channel_id,
                "interval": config.ram_report_interval_minutes,
            },
        }

    def _db_engine(self) -> str:
        path = str(getattr(self.bot.db, "path", "")) if self.bot.db is not None else ""
        if path.startswith(("postgresql://", "postgres://")):
            return "PostgreSQL"
        return "SQLite"
