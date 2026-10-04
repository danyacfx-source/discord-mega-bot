"""Статус, health, метрики, обзор, настройки, загрузки, отправка сообщений, аналитика и realtime-каналы."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
import tracemalloc
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp
import discord
import psutil
from aiohttp import web

from app.core.api_client import ApiClient
from app.core.webpanel.payload import (
    _MAGIC,
    _MAX_EMBEDS,
    _MAX_UPLOAD_BYTES,
    _SETTING_COLUMNS,
    _UPLOAD_EXTS,
    _UPLOAD_NAME_RE,
    _embed_from_dict,
    _message_to_client,
    _view_from_components,
)

logger = logging.getLogger("bot.webpanel")

class _CoreApiMixin:
    """Статус, health, метрики, обзор, настройки, загрузки, отправка сообщений, аналитика и realtime-каналы."""

    async def _api_status(self, request: web.Request) -> web.Response:
        online = self.bot.is_ready() and self.bot.user is not None
        data: dict[str, Any] = {"bot_online": online}
        if online and self.bot.user is not None:
            data["bot_name"] = self.bot.user.name
        if self.bot.guilds:
            data["guild_name"] = self.bot.guilds[0].name
        return self._json(data)

    async def _api_health(self, request: web.Request) -> web.Response:
        db = self.bot.db
        db_ok = False
        integrity = "not connected"
        database: dict[str, Any] = {"ok": db_ok, "integrity": integrity}
        if db is not None:
            try:
                integrity = await db.integrity_check()
                db_ok = integrity == "ok"
            except Exception:
                logger.exception("Не удалось проверить целостность БД через /api/health")
                integrity = "error"
            # Доступность считают сами запросы: integrity_check может
            # пройти, пока сбои уже копятся, а docker/k8s должен увидеть
            # degraded до того, как начнут падать хендлеры.
            db_ok = db_ok and db.available
            database = {
                "ok": db_ok,
                "integrity": integrity,
                "available": db.available,
                "consecutive_failures": db.consecutive_failures,
                "last_error": db.last_error,
            }
        ready = self.bot.is_ready() and self.bot.user is not None
        payload = {
            "ok": ready and db_ok,
            "discord": {"ready": ready, "guilds": len(self.bot.guilds)},
            "database": database,
            "backup": self.bot.db_backups.status() if self.bot.db_backups is not None else {"enabled": False},
            "latency_ms": round(self.bot.latency * 1000) if self.bot.latency >= 0 else None,
            "cogs": len(self.bot.cogs),
            "voice_clients": len(self.bot.voice_clients),
            "version": self.bot.config.version,
        }
        return self._json(payload, status=200 if payload["ok"] else 503)

    async def _api_metrics(self, request: web.Request) -> web.Response:
        """Диагностические метрики API и панели для owner/admin."""
        return self._json(
            {
                "ok": True,
                "api_clients": ApiClient.snapshots(),
                "panel": {
                    "active_sessions": len(self._sessions),
                    "rate_limited_ips": sum(1 for hits in self._rate_hits.values() if hits),
                    "analytics_clients": len(self._analytics_clients),
                },
            }
        )

    async def _prometheus_metrics(self, request: web.Request) -> web.Response:
        """Отдаёт компактный Prometheus text exposition через ту же авторизацию."""
        lines = [
            "# HELP megabot_api_requests_total Total external API requests.",
            "# TYPE megabot_api_requests_total counter",
            "# HELP megabot_api_successes_total Successful external API requests.",
            "# TYPE megabot_api_successes_total counter",
            "# HELP megabot_api_failures_total Circuit-worthy external API failures.",
            "# TYPE megabot_api_failures_total counter",
            "# HELP megabot_api_retries_total External API retries.",
            "# TYPE megabot_api_retries_total counter",
            "# HELP megabot_api_circuit_open Whether an API circuit is open.",
            "# TYPE megabot_api_circuit_open gauge",
        ]
        for item in ApiClient.snapshots():
            service = re.sub(r"[^a-zA-Z0-9_]", "_", str(item["service"]).lower()).strip("_") or "unknown"
            labels = f'service="{service}"'
            lines.extend(
                (
                    f"megabot_api_requests_total{{{labels}}} {item['requests']}",
                    f"megabot_api_successes_total{{{labels}}} {item['successes']}",
                    f"megabot_api_failures_total{{{labels}}} {item['failures']}",
                    f"megabot_api_retries_total{{{labels}}} {item['retries']}",
                    f"megabot_api_circuit_open{{{labels}}} {1 if item['circuit_open'] else 0}",
                )
            )
        lines.extend(
            (
                "# HELP megabot_panel_sessions_active Active panel sessions.",
                "# TYPE megabot_panel_sessions_active gauge",
                f"megabot_panel_sessions_active {len(self._sessions)}",
                "# HELP megabot_panel_analytics_clients Active analytics WebSocket clients.",
                "# TYPE megabot_panel_analytics_clients gauge",
                f"megabot_panel_analytics_clients {len(self._analytics_clients)}",
            )
        )
        return web.Response(
            text="\n".join(lines) + "\n",
            content_type="text/plain",
            charset="utf-8",
            headers={"Cache-Control": "no-store"},
        )

    async def _api_bot_channels(self, request: web.Request) -> web.Response:
        return self._json({"ok": True, "channels": self._channel_options()})

    # --- API: админка (обзор / настройки) ---

    @staticmethod
    def _human_uptime(seconds: int) -> str:
        days, rem = divmod(max(seconds, 0), 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        if days:
            return f"{days} д {hours} ч {minutes} мин"
        if hours:
            return f"{hours} ч {minutes} мин"
        return f"{minutes} мин"

    def _primary_guild(self) -> discord.Guild | None:
        configured_id = self.bot.config.guild_id
        if configured_id is not None:
            return self.bot.get_guild(configured_id)
        return self.bot.guilds[0] if self.bot.guilds else None

    def _channel_options(self) -> list[dict[str, Any]]:
        channels: list[dict[str, Any]] = []
        for guild in self.bot.guilds:
            me = guild.me
            for channel in guild.text_channels:
                if me is not None and not channel.permissions_for(me).send_messages:
                    continue
                channels.append(
                    {
                        "id": str(channel.id),
                        "name": channel.name,
                        "category": channel.category.name if channel.category else "",
                        "nsfw": channel.nsfw,
                    }
                )
        channels.sort(key=lambda item: (item["category"], item["name"]))
        return channels

    def _category_options(self) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = []
        for guild in self.bot.guilds:
            for category in guild.categories:
                options.append({"id": str(category.id), "name": category.name})
        options.sort(key=lambda item: item["name"])
        return options

    def _role_options(self) -> list[dict[str, Any]]:
        guild = self._primary_guild()
        if guild is None:
            return []
        roles = []
        for role in guild.roles:
            if role.is_default():
                continue
            roles.append({"id": str(role.id), "name": role.name})
        roles.sort(key=lambda item: item["name"])
        return roles

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

    async def _api_overview(self, request: web.Request) -> web.Response:
        bot = self.bot
        online = bot.is_ready() and bot.user is not None
        data: dict[str, Any] = {"ok": True, "bot_online": online}
        if online and bot.user is not None:
            data["bot_name"] = bot.user.name
        seconds = int(bot.uptime.total_seconds())
        data["uptime_seconds"] = seconds
        data["uptime"] = self._human_uptime(seconds)
        latency = bot.latency
        data["latency_ms"] = round(latency * 1000) if latency and latency > 0 else 0
        if tracemalloc.is_tracing():
            current, peak = tracemalloc.get_traced_memory()
            data["mem_mb"] = round(current / 1024 / 1024, 1)
            data["mem_peak_mb"] = round(peak / 1024 / 1024, 1)
        else:
            data["mem_mb"] = round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
        guild = self._primary_guild()
        if guild is not None:
            data["guild"] = {
                "id": str(guild.id),
                "name": guild.name,
                "members": guild.member_count or len(guild.members),
                "online": sum(1 for member in guild.members if member.status is not discord.Status.offline),
                "channels": len(guild.channels),
                "roles": len(guild.roles),
            }
        self._record_metrics(data)
        return self._json(data)

    def _record_metrics(self, data: dict[str, Any]) -> None:
        """Копит сэмплы для мини-графиков на дашборде (максимум 90 точек)."""
        now = datetime.now(UTC).isoformat()
        if "latency_ms" in data:
            self._lat.append({"t": now, "v": data.get("latency_ms", 0)})
        if "mem_mb" in data:
            self._mem.append({"t": now, "v": data["mem_mb"]})
        guild = data.get("guild") or {}
        if guild.get("online") is not None:
            self._online.append({"t": now, "v": guild.get("online", 0)})

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

    # --- API: загрузка изображений для эмбедов ---

    async def _api_upload(self, request: web.Request) -> web.Response:
        reader = await request.multipart()
        field = await reader.next()
        if field is None:
            return self._json({"ok": False, "error": "Файл не передан"}, status=400)
        ext = Path(field.filename or "").suffix.lower()
        if ext not in _UPLOAD_EXTS:
            return self._json(
                {"ok": False, "error": "Допустимы только PNG, JPG, GIF, WEBP"}, status=400
            )
        data = b""
        while len(data) <= _MAX_UPLOAD_BYTES:
            chunk = await field.read_chunk()
            if not chunk:
                break
            data += chunk
        if not data:
            return self._json({"ok": False, "error": "Пустой файл"}, status=400)
        if len(data) > _MAX_UPLOAD_BYTES:
            return self._json({"ok": False, "error": "Файл больше 8 МБ"}, status=400)
        signatures = _MAGIC.get(ext, ())
        if not signatures or not any(data[: len(sig)] == sig for sig in signatures):
            return self._json({"ok": False, "error": "Содержимое не соответствует типу файла"}, status=400)
        if ext == ".webp" and data[8:12] != b"WEBP":
            return self._json({"ok": False, "error": "Содержимое не соответствует типу файла"}, status=400)
        self._uploads_dir.mkdir(parents=True, exist_ok=True)
        name = uuid.uuid4().hex + ext
        (self._uploads_dir / name).write_bytes(data)
        base = self._public_base(request)
        return self._json({"ok": True, "name": name, "url": f"/uploads/{name}", "absolute_url": f"{base}/uploads/{name}"})

    async def _api_uploads_list(self, request: web.Request) -> web.Response:
        files: list[dict[str, Any]] = []
        if self._uploads_dir.is_dir():
            for path in sorted(self._uploads_dir.iterdir(), key=lambda p: p.stat().st_mtime if p.is_file() else 0, reverse=True):
                if not path.is_file() or _UPLOAD_NAME_RE.match(path.name) is None:
                    continue
                size = path.stat().st_size
                files.append(
                    {
                        "name": path.name,
                        "url": f"/uploads/{path.name}",
                        "size": self._human_size(size),
                        "bytes": size,
                    }
                )
        return self._json({"ok": True, "count": len(files), "files": files})

    async def _api_uploads_delete(self, request: web.Request) -> web.Response:
        name = request.match_info.get("name", "")
        if _UPLOAD_NAME_RE.match(name) is None:
            return self._json({"ok": False, "error": "Некорректное имя файла"}, status=400)
        path = self._uploads_dir / name
        if not path.is_file():
            return self._json({"ok": False, "error": "Файл не найден"}, status=404)
        path.unlink(missing_ok=True)
        return self._json({"ok": True})

    @staticmethod
    def _human_size(size: int) -> str:
        if size < 1024:
            return f"{size} Б"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} КБ"
        return f"{size / 1024 / 1024:.1f} МБ"

    @staticmethod
    def _public_base(request: web.Request) -> str:
        proto = request.headers.get("X-Forwarded-Proto") or request.scheme
        return f"{proto}://{request.host}"

    # --- API: отправка через бота ---

    def _resolve_channel(self, channel_id: Any) -> discord.TextChannel | None:
        try:
            channel = self.bot.get_channel(int(channel_id))
        except (TypeError, ValueError):
            return None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _api_bot_send(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        channel = self._resolve_channel(payload.get("channel_id") or "")
        if channel is None:
            return self._json({"ok": False, "error": "Канал не найден"}, status=400)
        try:
            message = await channel.send(
                content=str(payload.get("content") or "")[:2000] or None,
                embeds=[_embed_from_dict(item) for item in (payload.get("embeds") or [])[:_MAX_EMBEDS] if isinstance(item, dict)],
                view=_view_from_components(payload.get("components")),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.HTTPException, discord.Forbidden) as exc:
            return self._json({"ok": False, "error": str(exc)}, status=400)
        return self._json({"ok": True, "message_id": str(message.id)})

    async def _api_bot_edit(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        channel = self._resolve_channel(payload.get("channel_id") or "")
        message_id = self._parse_id(payload.get("message_id"))
        if channel is None or message_id is None:
            return self._json({"ok": False, "error": "Канал или ID сообщения неверны"}, status=400)
        try:
            message = await channel.fetch_message(message_id)
        except discord.HTTPException:
            return self._json({"ok": False, "error": "Сообщение не найдено"}, status=404)
        try:
            await message.edit(
                content=str(payload.get("content") or "")[:2000] or None,
                embeds=[_embed_from_dict(item) for item in (payload.get("embeds") or [])[:_MAX_EMBEDS] if isinstance(item, dict)],
                view=_view_from_components(payload.get("components")),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.HTTPException, discord.Forbidden) as exc:
            return self._json({"ok": False, "error": str(exc)}, status=400)
        return self._json({"ok": True})

    async def _api_bot_fetch(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        channel = self._resolve_channel(payload.get("channel_id") or "")
        message_id = self._parse_id(payload.get("message_id"))
        if channel is None or message_id is None:
            return self._json({"ok": False, "error": "Канал или ID сообщения неверны"}, status=400)
        try:
            message = await channel.fetch_message(message_id)
        except discord.HTTPException:
            return self._json({"ok": False, "error": "Сообщение не найдено"}, status=404)
        return self._json({"ok": True, "data": _message_to_client(message)})

    # --- API: мониторинг, сервер, модерация, розыгрыши, планировщик, бэкап ---

    # --- сбор сообщений для /api/stats (паттерн add_listener как в donations.py) ---

    async def _on_message_hook(self, message: discord.Message) -> None:
        """Корутина дяди discord.py: add_listener требует async-функцию, не обёртку."""
        await self._msg_counter(message)

    async def _msg_counter(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        now = datetime.now(UTC)
        hour_key = now.replace(minute=0, second=0, microsecond=0)
        day_key = now.date().isoformat()
        self._msg_total += 1
        if self._msg_by_hour and self._msg_by_hour[-1]["t"] == hour_key.timestamp():
            self._msg_by_hour[-1]["n"] += 1
        else:
            self._msg_by_hour.append({"t": hour_key.timestamp(), "n": 1})
        if self._msg_by_day and self._msg_by_day[-1].get("d") == day_key:
            self._msg_by_day[-1]["n"] += 1
        else:
            self._msg_by_day.append({"d": day_key, "n": 1})
        self._pending_activity[(message.guild.id, hour_key.isoformat())] += 1

    async def _analytics_flush_loop(self) -> None:
        while True:
            await asyncio.sleep(10)
            await self._flush_activity()

    async def _flush_activity(self) -> None:
        if self.bot.db is None or not self._pending_activity:
            return
        pending = self._pending_activity
        self._pending_activity = defaultdict(int)
        for (guild_id, bucket), amount in pending.items():
            try:
                await self.bot.db.increment_activity(guild_id, bucket, amount)
            except Exception:
                self._pending_activity[(guild_id, bucket)] += amount
                logger.exception("Не удалось сохранить activity metric")
        if self._analytics_clients:
            payload = await self._analytics_payload()
            dead: list[web.WebSocketResponse] = []
            for websocket in self._analytics_clients:
                try:
                    await websocket.send_json({"type": "analytics", "data": payload})
                except (ConnectionResetError, RuntimeError, aiohttp.ClientConnectionError):
                    dead.append(websocket)
            for websocket in dead:
                self._analytics_clients.discard(websocket)

    async def _analytics_payload(self) -> dict[str, Any]:
        guild = self._primary_guild()
        if guild is None or self.bot.db is None:
            return {"guild_id": None, "rows": []}
        rows = await self.bot.db.list_activity(guild.id, 1000)
        return {"guild_id": str(guild.id), "rows": rows}

    async def _api_analytics(self, request: web.Request) -> web.Response:
        await self._flush_activity()
        return self._json({"ok": True, **(await self._analytics_payload())})

    async def _api_analytics_export(self, request: web.Request) -> web.Response:
        await self._flush_activity()
        payload = await self._analytics_payload()
        rows = payload["rows"]
        if request.query.get("format", "json").lower() == "csv":
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=["bucket", "messages"])
            writer.writeheader()
            writer.writerows(rows)
            return web.Response(
                text=output.getvalue(),
                content_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=activity.csv"},
            )
        return self._json({"ok": True, **payload})

    async def _api_streams_archive_csv(self, request: web.Request) -> web.Response:
        """Экспорт архива завершённых эфиров всех настроенных каналов (CSV; BOM, разделитель ;)."""
        config = self.bot.config
        services = self.services
        sources: list[tuple[str, str, Any]] = []
        for login in config.twitch_channels:
            sources.append(("twitch", login, services.twitch.archive_store(login)))
        if config.kick_channel_slug:
            sources.append(("kick", config.kick_channel_slug, services.kick.archive_store(config.kick_channel_slug)))
        if config.vk_channel_slug:
            sources.append(("vk_video", config.vk_channel_slug, services.vk_video.archive_store(config.vk_channel_slug)))

        rows: list[list[Any]] = []
        for platform, name, store in sources:
            for entry in await store.list():
                rows.append(
                    [
                        platform,
                        name,
                        entry.get("title") or "",
                        entry.get("category") or "",
                        entry.get("url") or "",
                        entry.get("vod") or "",
                        entry.get("started_at") or "",
                        entry.get("ended_at") or "",
                        int(entry.get("seconds") or 0) // 60,
                        int(entry.get("peak") or 0),
                    ]
                )
        rows.sort(key=lambda row: str(row[7]), reverse=True)

        output = io.StringIO()
        writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
        writer.writerow(
            ["платформа", "канал", "название", "категория", "ссылка", "запись", "начало", "конец", "минуты", "пик"]
        )
        writer.writerows(rows)
        filename = f"streams-archive-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.csv"
        return web.Response(
            text="\ufeff" + output.getvalue(),
            content_type="text/csv",
            charset="utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    async def _ws_analytics(self, request: web.Request) -> web.StreamResponse:
        if not self._rate_ok(request) or not self._allowed_origin(request):
            return self._json({"ok": False, "error": "Unauthorized"}, status=401)
        websocket = web.WebSocketResponse(heartbeat=30)
        await websocket.prepare(request)
        try:
            first = await websocket.receive(timeout=5)
        except TimeoutError:
            await websocket.close(code=4401, message=b"Unauthorized")
            return websocket
        token = ""
        if first.type == web.WSMsgType.TEXT:
            try:
                token = str(json.loads(first.data).get("token") or "")
            except (TypeError, ValueError):
                token = ""
        role = self._check_token_value(token)
        if role is None or self._role_rank(role) < self._role_rank("viewer"):
            await websocket.close(code=4401, message=b"Unauthorized")
            return websocket
        self._analytics_clients.add(websocket)
        try:
            await websocket.send_json({"type": "analytics", "data": await self._analytics_payload()})
            async for message in websocket:
                if message.type in (web.WSMsgType.CLOSE, web.WSMsgType.ERROR):
                    break
        finally:
            self._analytics_clients.discard(websocket)
        return websocket

    def _on_ring_record(self, entry: dict[str, str]) -> None:
        """WARNING+ и аудит-записи уходят в шину живой ленты (из любого потока)."""
        if entry.get("audit") != "1" and entry.get("level") not in ("WARNING", "ERROR", "CRITICAL"):
            return
        services = getattr(self.bot, "services", None)
        events = getattr(services, "events", None) if services is not None else None
        if events is None:
            return
        events.publish(
            "log",
            {
                "level": entry.get("level", "INFO"),
                "msg": entry.get("msg", ""),
                "cat": entry.get("cat", "sys"),
                "t": entry.get("t", ""),
            },
        )

    async def _events_loop(self) -> None:
        """Раздаёт события шины подключённым ws-клиентам живой ленты."""
        while True:
            await asyncio.sleep(0.4)
            try:
                services = getattr(self.bot, "services", None)
                events = getattr(services, "events", None) if services is not None else None
                if events is None:
                    continue
                if not self._event_clients:
                    # клиентов нет — не копим буфер, новое только после подключения
                    self._events_seq = events.seq
                    continue
                batch = events.drain(self._events_seq)
                if not batch:
                    continue
                self._events_seq = batch[-1]["seq"]
                for queue in tuple(self._event_clients):
                    for event in batch:
                        if queue.full():
                            try:
                                queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                        try:
                            queue.put_nowait(event)
                        except asyncio.QueueFull:
                            pass
            except asyncio.CancelledError:
                return
            except Exception:
                logger.debug("Живая лента: сбой рассылки событий", exc_info=True)

    async def _ws_events(self, request: web.Request) -> web.StreamResponse:
        if not self._rate_ok(request) or not self._allowed_origin(request):
            return self._json({"ok": False, "error": "Unauthorized"}, status=401)
        websocket = web.WebSocketResponse(heartbeat=30)
        await websocket.prepare(request)
        try:
            first = await websocket.receive(timeout=5)
        except TimeoutError:
            await websocket.close(code=4401, message=b"Unauthorized")
            return websocket
        token = ""
        if first.type == web.WSMsgType.TEXT:
            try:
                token = str(json.loads(first.data).get("token") or "")
            except (TypeError, ValueError):
                token = ""
        role = self._check_token_value(token)
        if role is None or self._role_rank(role) < self._role_rank("viewer"):
            await websocket.close(code=4401, message=b"Unauthorized")
            return websocket
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._event_clients.add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    if websocket.closed:
                        break
                    await websocket.send_json({"type": "ping"})
                    continue
                await websocket.send_json(event)
        except (ConnectionResetError, ConnectionError, RuntimeError):
            pass
        finally:
            self._event_clients.discard(queue)
        return websocket

    async def _api_monitor(self, request: web.Request) -> web.Response:
        sample = await self._live_sample()
        self._record_metrics(sample)
        return self._json(
            {
                "ok": True,
                "latency": list(self._lat),
                "mem": list(self._mem),
                "online": list(self._online),
                **sample,
            }
        )

    async def _api_stats(self, request: web.Request) -> web.Response:
        sample = await self._live_sample()
        self._record_metrics(sample)
        return self._json(
            {
                "ok": True,
                "by_hour": list(self._msg_by_hour),
                "by_day": list(self._msg_by_day),
                "total": self._msg_total,
                "latency": list(self._lat),
                "mem": list(self._mem),
                "online": list(self._online),
                **sample,
            }
        )

    async def _live_sample(self) -> dict[str, Any]:
        """Снимает актуальный срез латентности/памяти/онлайна для мониторинга."""
        bot = self.bot
        sample: dict[str, Any] = {}
        latency = bot.latency
        sample["latency_ms"] = round(latency * 1000) if latency and latency > 0 else 0
        sample["mem_mb"] = round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
        guild = self._primary_guild()
        if guild is not None:
            sample["guild"] = {
                "online": sum(1 for member in guild.members if member.status is not discord.Status.offline)
            }
        return sample
