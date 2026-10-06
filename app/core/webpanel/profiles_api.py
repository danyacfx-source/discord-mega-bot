"""Стримы, дни рождения, temp-voice, AI, карточки и приветствия."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import discord
from aiohttp import web

from app.core.webpanel.payload import (
    _STREAM_CARDS_KEY,
    _WELCOME_PRESET_KEY,
    _clean_cards_preset,
)
from app.services.stream_rsvp import resolve_rsvp_role
from app.services.stream_session import session_is_live
from app.services.viewer_sessions import ViewerSessionStore
from app.utils.stream_history import trend
from app.utils.welcome_card import WelcomePreset, make_placeholder_avatar, render_welcome_card

logger = logging.getLogger("bot.webpanel")

class _ProfilesApiMixin:
    """Стримы, дни рождения, temp-voice, AI, карточки и приветствия."""

    def _stream_is_live(self, session: dict[str, Any] | None, poll_seconds: float) -> bool:
        """Эфир идёт, пока session-store дописывается поллингом (свежий captured_at)."""
        return session_is_live(
            session,
            poll_seconds=poll_seconds,
            sticky_seconds=self.bot.config.stream_sticky_poll_seconds,
        )

    async def _api_streams_get(self, request: web.Request) -> web.Response:
        """Стримы (Twitch/Kick/VK): конфигурация и данные сессии из KV.

        Статус берётся из session-store (обновляется поллингом) — без
        запросов к внешним API на каждый клик в панели.
        """
        config = self.bot.config
        streams: list[dict[str, Any]] = []

        def item(platform: str, label: str, url: str, notify_id: int | None, poll: float) -> dict[str, Any]:
            return {
                "platform": platform,
                "label": label,
                "url": url,
                "notify_channel_id": str(notify_id or ""),
                "poll_seconds": poll,
                "session": None,
                "live": False,
                "trend": None,
            }

        if config.twitch_channels:
            for login in config.twitch_channels:
                entry = item(
                    "twitch",
                    f"Twitch · {login}",
                    f"https://www.twitch.tv/{login}",
                    config.twitch_notify_channel_id,
                    config.twitch_poll_seconds,
                )
                entry["session"] = await self.services.twitch.session_store(login).load()
                streams.append(entry)
        if config.kick_channel_slug:
            slug = config.kick_channel_slug
            entry = item(
                "kick",
                f"Kick · {slug}",
                f"https://kick.com/{slug}",
                config.kick_notify_channel_id,
                config.kick_poll_seconds,
            )
            entry["session"] = await self.services.kick.session_store(slug).load()
            streams.append(entry)
        if config.vk_channel_slug:
            slug = config.vk_channel_slug
            entry = item(
                "vk_video",
                f"VK Видео · {slug}",
                f"https://live.vkvideo.ru/{slug}",
                config.vk_notify_channel_id,
                config.vk_poll_seconds,
            )
            entry["session"] = await self.services.vk_video.session_store(slug).load()
            streams.append(entry)

        for entry in streams:
            entry["live"] = self._stream_is_live(entry["session"], entry["poll_seconds"])
            if entry["live"]:
                entry["trend"] = trend((entry["session"] or {}).get("history"))

        quiet = config.stream_quiet_hours
        guild = self._primary_guild()
        rsvp_role = resolve_rsvp_role(guild, config.stream_rsvp_role_id) if guild is not None else None
        return self._json(
            {
                "ok": True,
                "streams": streams,
                "role_id": str(config.stream_role_id or ""),
                "role_user_ids": [str(uid) for uid in config.stream_role_user_ids],
                "rsvp_role_id": str(rsvp_role.id) if rsvp_role else "",
                "rsvp_role_name": rsvp_role.name if rsvp_role else "",
                "quiet_hours": f"{quiet[0]}-{quiet[1]}" if quiet else "",
                "sticky_poll_seconds": config.stream_sticky_poll_seconds,
            }
        )

    async def _watchers_block(self, store: ViewerSessionStore, *, enabled: bool) -> dict[str, Any]:
        """Активные в чате и топ говорящих за эфир из KV viewer-sessions."""
        active = await store.active()
        top = await store.top_talkers(limit=10)
        rows: list[dict[str, Any]] = []
        for session in active.values():
            if not isinstance(session, dict):
                continue
            try:
                messages = int(session.get("messages") or 0)
            except (TypeError, ValueError):
                messages = 0
            rows.append(
                {
                    "name": str(session.get("name") or ""),
                    "messages": messages,
                    "last_seen": str(session.get("last_seen") or ""),
                }
            )
        rows.sort(key=lambda row: row["last_seen"], reverse=True)
        return {"enabled": enabled, "active": rows, "top": top}

    async def _api_streams_watchers(self, request: web.Request) -> web.Response:
        """Кто сейчас в чате и топ говорящих за эфир — по каждой платформе.

        Kick слушает Pusher, Twitch — IRC; у VK чата нет, блок отдаётся
        выключенным (фронт покажет «не отслеживается»). Поля ``kick_enabled``/
        ``active``/``top`` наверху — легаси-срез по Kick.
        """
        config = self.bot.config
        twitch = await self._watchers_block(
            self.services.twitch.viewer_store(), enabled=bool(config.twitch_channels)
        )
        kick = await self._watchers_block(
            self.services.kick.viewer_store(), enabled=bool(config.kick_channel_slug)
        )
        return self._json(
            {
                "ok": True,
                "kick_enabled": kick["enabled"],
                "twitch_enabled": twitch["enabled"],
                "active": kick["active"],
                "top": kick["top"],
                "platforms": {
                    "twitch": twitch,
                    "kick": kick,
                    "vk_video": {"enabled": False, "active": [], "top": []},
                },
            }
        )

    async def _api_birthdays_get(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        service = self.services.birthdays
        rows = await service.all()
        items = [
            {
                "user_id": str(row["user_id"]),
                "name": self._member_name(guild, row["user_id"]),
                "month": row["month"],
                "day": row["day"],
            }
            for row in rows
        ]
        settings = await self.services.settings.get(guild.id)
        return self._json(
            {
                "ok": True,
                "birthdays": items,
                "members": self._member_options(guild, 400),
                "channel_id": str(settings.get("birthday_channel_id") or self.bot.config.birthday_channel_id or ""),
            }
        )

    async def _api_birthdays_post(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        payload = await self._read_json(request)
        user_id = self._parse_id(payload.get("member_id"))
        if user_id is None or guild.get_member(user_id) is None:
            return self._json({"ok": False, "error": "Участник не найден на сервере"}, status=400)
        month = self._parse_id(payload.get("month"))
        day = self._parse_id(payload.get("day"))
        if month is None or day is None:
            return self._json({"ok": False, "error": "Некорректная дата: месяц 1–12, день 1–31"}, status=400)
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return self._json({"ok": False, "error": "Некорректная дата: месяц 1–12, день 1–31"}, status=400)
        try:
            datetime(2000, month, day)
        except ValueError:
            return self._json({"ok": False, "error": "Некорректная дата"}, status=400)
        service = self.services.birthdays
        await service.set(user_id, month, day)
        return self._json({"ok": True, "name": self._member_name(guild, user_id)})

    async def _api_birthdays_remove(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        user_id = self._parse_id(request.match_info.get("user_id"))
        if user_id is None or not await self.services.birthdays.remove(user_id):
            return self._json({"ok": False, "error": "День рождения не найден"}, status=404)
        return self._json({"ok": True})

    # --- API: временные голосовые ---

    async def _api_tempvoice_get(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        service = self.services.tempvoice
        rooms: list[dict[str, Any]] = []
        for row in await service.all():
            channel = guild.get_channel(row["channel_id"])
            rooms.append(
                {
                    "channel_id": str(row["channel_id"]),
                    "name": channel.name if channel else None,
                    "owner_id": str(row["owner_id"]),
                    "owner_name": self._member_name(guild, row["owner_id"]),
                    "created_at": row["created_at"],
                    "members": [
                        {
                            "id": str(member.id),
                            "name": member.display_name,
                            "bot": member.bot,
                        }
                        for member in (channel.members if isinstance(channel, discord.VoiceChannel) else [])
                    ],
                }
            )
        config = self.bot.config
        triggers = [
            {"id": str(cid), "name": self._channel_name(guild, cid)}
            for cid in config.temp_voice_trigger_ids
        ]
        category = guild.get_channel(config.temp_voice_category_id) if config.temp_voice_category_id else None
        return self._json(
            {
                "ok": True,
                "rooms": rooms,
                "triggers": triggers,
                "category_id": str(config.temp_voice_category_id) if config.temp_voice_category_id else "",
                "category_name": category.name if category else None,
                "members": self._member_options(guild, 400),
            }
        )

    async def _api_tempvoice_delete(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        channel_id = self._parse_id(request.match_info.get("channel_id"))
        if channel_id is None:
            return self._json({"ok": False, "error": "Неверный ID канала"}, status=400)
        service = self.services.tempvoice
        if not await service.owner_of(channel_id):
            return self._json({"ok": False, "error": "Комната не найдена"}, status=404)
        await service.delete(channel_id)
        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.VoiceChannel):
            try:
                await channel.delete(reason="Удаление комнаты из веб-панели")
            except (discord.HTTPException, discord.Forbidden):
                pass
        return self._json({"ok": True})

    async def _api_tempvoice_transfer(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        channel_id = self._parse_id(request.match_info.get("channel_id"))
        payload = await self._read_json(request)
        new_owner_id = self._parse_id(payload.get("owner_id"))
        if channel_id is None or new_owner_id is None:
            return self._json({"ok": False, "error": "Неверные параметры"}, status=400)
        service = self.services.tempvoice
        if not await service.owner_of(channel_id):
            return self._json({"ok": False, "error": "Комната не найдена"}, status=404)
        if guild.get_member(new_owner_id) is None:
            return self._json({"ok": False, "error": "Новый владелец не найден на сервере"}, status=400)
        await service.transfer(channel_id, new_owner_id)
        return self._json({"ok": True, "owner_name": self._member_name(guild, new_owner_id)})

    # --- API: AI-чат ---

    async def _api_ai_get(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        config = self.bot.config
        cog = self.bot.cogs.get("ChatAI")
        paused = bool(getattr(cog, "_paused", False))
        channels = []
        for cid in config.ai_channels:
            channel = self.bot.get_channel(cid)
            channels.append({"id": str(cid), "name": channel.name if channel else str(cid)})
        return self._json(
            {
                "ok": True,
                "guild_name": guild.name if guild else None,
                "enabled": bool(config.ai_enabled and config.ai_api_key and config.ai_channels),
                "paused": paused,
                "has_key": bool(config.ai_api_key),
                "has_channels": bool(config.ai_channels),
                "model": config.ai_model,
                "channels": channels,
                "temperature": config.ai_temperature,
                "max_tokens": config.ai_max_tokens,
                "history_size": config.ai_history_size,
                "cooldown_seconds": config.ai_cooldown_seconds,
                "timeout_seconds": config.ai_timeout_seconds,
                "system_prompt": config.ai_system_prompt or "",
                "proxy": config.ai_proxy or None,
            }
        )

    async def _api_ai_post(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        cog = self.bot.cogs.get("ChatAI")
        if cog is None:
            return self._json({"ok": False, "error": "Ког AI-чата не найден"}, status=500)
        changed = False
        if "paused" in payload:
            cog._paused = bool(payload.get("paused"))
            changed = True
        if not changed:
            return self._json({"ok": False, "error": "Нечего обновить"}, status=400)
        return self._json({"ok": True, "paused": bool(cog._paused)})

    async def _api_stream_cards_get(self, request: web.Request) -> web.Response:
        raw = await self.services.kv.get(_STREAM_CARDS_KEY)
        try:
            preset = json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            preset = {}
        if not isinstance(preset, dict):
            preset = {}
        return self._json({"ok": True, "preset": preset})

    async def _api_stream_cards_post(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        if payload.get("reset"):
            await self.services.kv.delete(_STREAM_CARDS_KEY)
            return self._json({"ok": True, "preset": {}, "custom": False})
        preset = _clean_cards_preset(payload.get("preset") if isinstance(payload.get("preset"), dict) else {})
        await self.services.kv.set(_STREAM_CARDS_KEY, json.dumps(preset, ensure_ascii=False))
        return self._json({"ok": True, "preset": preset, "custom": True})

    async def _api_welcome_get(self, request: web.Request) -> web.Response:
        raw = await self.services.kv.get(_WELCOME_PRESET_KEY)
        preset = WelcomePreset.from_json(raw)
        return self._json(
            {
                "ok": True,
                "preset": preset.to_json(),
                "custom": bool(raw),
                "card_enabled": bool(self.bot.config.welcome_card),
            }
        )

    async def _api_welcome_post(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        if payload.get("reset"):
            await self.services.kv.delete(_WELCOME_PRESET_KEY)
            preset = WelcomePreset()
        else:
            preset = WelcomePreset.from_json(payload.get("preset") if isinstance(payload.get("preset"), dict) else payload)
            await self.services.kv.set(_WELCOME_PRESET_KEY, json.dumps(preset.to_json(), ensure_ascii=False))
        return self._json({"ok": True, "preset": preset.to_json(), "custom": not payload.get("reset")})

    async def _api_welcome_preview(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        preset = WelcomePreset.from_json(payload.get("preset") if isinstance(payload.get("preset"), dict) else {})
        name = str(payload.get("name") or "Алиса")[:32]
        guild = str(payload.get("guild") or "Тестовый сервер")[:32]
        try:
            count = max(1, int(payload.get("count") or 42))
        except (TypeError, ValueError):
            count = 42
        try:
            avatar = make_placeholder_avatar(name, bg=preset.bg_bottom)
            png = render_welcome_card(
                avatar_png=avatar,
                display_name=name,
                member_count=count,
                guild_name=guild,
                preset=preset,
            )
        except Exception:
            logger.debug("Превью welcome-карточки не построено", exc_info=True)
            return self._json({"ok": False, "error": "Не удалось построить превью"}, status=500)
        return web.Response(body=png, content_type="image/png")

    # ------------------------------------------------------ оверлей (раскладки)
