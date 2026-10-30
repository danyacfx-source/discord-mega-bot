"""Статус, health, метрики, обзор, мониторинг и статистика."""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

import discord
import psutil
from aiohttp import web

from app.core.api_client import ApiClient
from app.core.webpanel.base_api import _BaseApi

logger = logging.getLogger("bot.webpanel")


class _StatusApiMixin(_BaseApi):
    """Статус, health, метрики, обзор, мониторинг и статистика."""

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
        tasks_status = self.bot.background_task_status()
        payload = {
            "ok": ready and db_ok and not tasks_status["failed"],
            "discord": {"ready": ready, "guilds": len(self.bot.guilds)},
            "database": database,
            "backup": self.bot.db_backups.status() if self.bot.db_backups is not None else {"enabled": False},
            "latency_ms": round(self.bot.latency * 1000) if self.bot.latency >= 0 else None,
            "cogs": len(self.bot.cogs),
            "voice_clients": len(self.bot.voice_clients),
            "background_tasks": tasks_status,
            "version": self.bot.config.version,
        }
        return self._json(payload, status=200 if payload["ok"] else 503)

    async def _api_preflight(self, request: web.Request) -> web.Response:
        """Human-readable readiness check for the minutes before a stream."""
        checks: list[dict[str, str]] = []

        def add(name: str, state: str, detail: str) -> None:
            checks.append({"name": name, "state": state, "detail": detail})

        ready = self.bot.is_ready() and self.bot.user is not None
        add("Discord", "ok" if ready else "error", "бот подключён" if ready else "бот ещё не подключён")

        db = self.bot.db
        try:
            db_ok = db is not None and db.available and await db.integrity_check() == "ok"
        except Exception:
            logger.debug("Preflight: database check failed", exc_info=True)
            db_ok = False
        add("База данных", "ok" if db_ok else "error", "целостность подтверждена" if db_ok else "проверьте подключение или логи")

        failed = self.bot.background_task_status()["failed"]
        add("Фоновые задачи", "ok" if not failed else "error", "все задачи работают" if not failed else ", ".join(failed[:4]))

        if self.bot.config.twitch_channels:
            chat = self.bot.get_cog("StreamChat")
            control = await chat.twitch_control_status() if chat is not None else {"state": "starting", "can_write": False}
            state = str(control.get("state") or "unknown")
            level = "ok" if state == "connected" and control.get("can_write") else "warn"
            add("Twitch-чат", level, "подключён и может писать" if level == "ok" else f"режим: {state}")

        if self.bot.config.overlay_port is not None:
            overlay_ok = self.bot.overlay is not None
            add("OBS-оверлей", "ok" if overlay_ok else "error", "сервер оверлея запущен" if overlay_ok else "сервер не запущен")

        backup = self.bot.db_backups.status() if self.bot.db_backups is not None else {"enabled": False}
        if backup.get("enabled"):
            backup_detail = "последний: " + str(backup.get("last_backup") or "ещё не создан")
            add("Автобэкапы", "ok" if backup.get("last_backup") else "warn", backup_detail)
        else:
            add("Автобэкапы", "warn", "автоматические копии выключены")

        return self._json({"ok": not any(item["state"] == "error" for item in checks), "checks": checks})

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
