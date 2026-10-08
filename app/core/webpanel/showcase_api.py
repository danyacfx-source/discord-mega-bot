"""Публичная витрина сообщества: страница /showcase и её настройки.

Витрина доступна без авторизации и отдаёт только безопасные агрегаты:
статус бота, цифры сервера, эфиры, расписание и медиа с флагом public.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import discord
from aiohttp import web

_SHOWCASE_KEY = "panel.showcase.settings"
_SHOWCASE_DEFAULTS = {"hero_title": "", "about": "", "invite_url": "", "avatar_url": "", "donate_url": ""}
_SHOWCASE_MEDIA_LIMIT = 8
_SHOWCASE_SCHEDULE_LIMIT = 5
_SHOWCASE_TEXT_LIMITS = {"hero_title": 120, "about": 600, "invite_url": 300, "avatar_url": 300, "donate_url": 300}


class _ShowcaseApiMixin:
    # --- настройки витрины ---

    async def _showcase_settings(self) -> dict[str, str]:
        raw = await self.services.kv.get(_SHOWCASE_KEY, "{}")
        try:
            data = json.loads(raw or "{}")
        except (TypeError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        settings = dict(_SHOWCASE_DEFAULTS)
        for key, limit in _SHOWCASE_TEXT_LIMITS.items():
            value = data.get(key)
            if isinstance(value, str):
                settings[key] = value[:limit]
        for key in ("invite_url", "avatar_url", "donate_url"):
            if settings[key] and not settings[key].startswith(("https://", "http://")):
                settings[key] = ""
        return settings

    async def _owner_avatar(self) -> str:
        """Аватар владельца: кэш на процесс, чтобы не дёргать Discord на каждый запрос."""
        cached = getattr(self, "_showcase_owner_avatar", None)
        if cached is not None:
            return cached
        owner_id = self.bot.config.owner_id
        url = ""
        if owner_id:
            try:
                user = self.bot.get_user(owner_id)
                if user is None:
                    user = await self.bot.fetch_user(owner_id)
                url = user.display_avatar.url if user else ""
            except Exception:
                url = ""
        self._showcase_owner_avatar = url
        return url

    async def _api_showcase_settings_get(self, request: web.Request) -> web.Response:
        return self._json({"ok": True, "settings": await self._showcase_settings()})

    async def _api_showcase_settings_post(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        settings = await self._showcase_settings()
        for key, limit in _SHOWCASE_TEXT_LIMITS.items():
            if key in payload:
                settings[key] = str(payload.get(key) or "").strip()[:limit]
        for key in ("invite_url", "avatar_url", "donate_url"):
            if settings[key] and not settings[key].startswith(("https://", "http://")):
                return self._json({"ok": False, "error": "Ссылка должна начинаться с http"}, status=400)
        await self.services.kv.set(_SHOWCASE_KEY, json.dumps(settings, ensure_ascii=False))
        return self._json({"ok": True, "settings": settings})

    # --- сборка публичного payload ---

    async def _showcase_streams(self) -> list[dict[str, Any]]:
        config = self.bot.config
        streams: list[dict[str, Any]] = []

        def entry(platform: str, label: str, url: str) -> dict[str, Any]:
            return {"platform": platform, "label": label, "url": url, "live": False}

        for login in config.twitch_channels or []:
            row = entry("twitch", f"Twitch · {login}", f"https://www.twitch.tv/{login}")
            session = await self.services.twitch.session_store(login).load()
            row["live"] = self._stream_is_live(session, config.twitch_poll_seconds)
            streams.append(row)
        if config.kick_channel_slug:
            slug = config.kick_channel_slug
            row = entry("kick", f"Kick · {slug}", f"https://kick.com/{slug}")
            session = await self.services.kick.session_store(slug).load()
            row["live"] = self._stream_is_live(session, config.kick_poll_seconds)
            streams.append(row)
        if config.vk_channel_slug:
            slug = config.vk_channel_slug
            row = entry("vk_video", f"VK · {slug}", f"https://live.vkvideo.ru/{slug}")
            session = await self.services.vk_video.session_store(slug).load()
            row["live"] = self._stream_is_live(session, config.vk_poll_seconds)
            streams.append(row)
        return streams

    async def _showcase_schedule(self) -> list[dict[str, Any]]:
        try:
            rows = await self.services.scheduled.recent(200)
        except Exception:
            return []
        upcoming = [row for row in rows if not row.get("done")]
        upcoming.sort(key=lambda row: str(row.get("send_at") or ""))
        items: list[dict[str, Any]] = []
        for row in upcoming[:_SHOWCASE_SCHEDULE_LIMIT]:
            title = str(row.get("content") or "").strip()[:120]
            try:
                embed = json.loads(row.get("embed_json") or "{}") or {}
            except (TypeError, ValueError):
                embed = {}
            if isinstance(embed, dict) and embed.get("title"):
                title = str(embed.get("title"))[:120]
            items.append({"title": title, "send_at": str(row.get("send_at") or "")})
        return items

    async def _showcase_media(self) -> list[dict[str, Any]]:
        items = await self._gallery_load()
        public = [item for item in items if item.get("public")]
        public.sort(key=lambda i: str(i.get("created_at") or ""), reverse=True)
        return [
            self._media_row(item, "")
            for item in public[:_SHOWCASE_MEDIA_LIMIT]
        ]

    async def _api_public_showcase(self, request: web.Request) -> web.Response:
        if not self._rate_ok(request):
            return self._json({"ok": False, "error": "Слишком много запросов"}, status=429)
        bot = self.bot
        data: dict[str, Any] = {"ok": True, "settings": await self._showcase_settings()}
        if not data["settings"]["donate_url"]:
            data["settings"]["donate_url"] = (
                self.bot.config.donate_url or self.bot.config.socials_donate or ""
            )

        ready = bot.is_ready() and bot.user is not None
        data["bot"] = {
            "online": ready,
            "name": bot.user.name if bot.user else "",
            "avatar": data["settings"]["avatar_url"] or await self._owner_avatar(),
            "uptime_days": int(bot.uptime.total_seconds() // 86400),
        }

        guild = self._primary_guild()
        if guild is not None:
            data["guild"] = {
                "name": guild.name,
                "members": guild.member_count or len(guild.members),
                "online": sum(1 for member in guild.members if member.status is not discord.Status.offline),
            "channels": len(guild.channels),
            "roles": len(guild.roles),
            "created_days": max(0, (datetime.now(UTC) - guild.created_at).days),
            }
        else:
            data["guild"] = None

        data["stats"] = {
            "messages_total": self._msg_total,
            "by_day": list(self._msg_by_day)[-7:],
        }
        data["streams"] = await self._showcase_streams()
        data["schedule"] = await self._showcase_schedule()
        data["media"] = await self._showcase_media()
        return self._json(data)
