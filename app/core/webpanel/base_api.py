"""Общий базовый класс миксинов веб-панели.

Содержит методы, которые используются несколькими миксинами: JSON-ответы,
резолв гильдий/каналов, rate-limit, origin-проверка, чтение payload'ов.
Без этого модуля связанность была бы неявной (375 вызовов ``self._X``
между файлами без статической связи).
"""
from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import discord
from aiohttp import web

from app.core.webpanel.payload import (
    _LOCAL_HOSTS,
    _RATE_LIMIT_MAX,
    _RATE_LIMIT_WINDOW,
    _SESSION_MAX,
    _PanelSession,
)

if TYPE_CHECKING:
    from app.core.bot import MegaBot
    from app.services import Services


class _BaseApi:
    """Общие методы для всех миксинов веб-панели.

    Состояние (bot, sessions, rate-hits и пр.) инициализируется
    в ``WebPanel.__init__`` — миксины только читают/пишут через ``self``.
    """

    bot: MegaBot

    @property
    def services(self) -> Services:
        services = self.bot.services
        if services is None:
            raise RuntimeError("Сервисы недоступны до запуска вебпанели")
        return services

    @property
    def _oauth_enabled(self) -> bool:
        return bool(
            getattr(self, "_oauth_client_id", None)
            and getattr(self, "_oauth_client_secret", None)
            and getattr(self, "_oauth_redirect_url", None)
        )

    @staticmethod
    def _json(data: dict[str, Any], status: int = 200) -> web.Response:
        return web.json_response(data, status=status)

    async def _read_json(self, request: web.Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _primary_guild(self) -> discord.Guild | None:
        configured_id = self.bot.config.guild_id
        if configured_id is not None:
            return self.bot.get_guild(configured_id)
        return self.bot.guilds[0] if self.bot.guilds else None

    def _resolve_channel(self, channel_id: Any) -> discord.TextChannel | None:
        # Резолвим только внутри основной гильдии — иначе panel-admin одной
        # гильдии пишет/читает каналы чужих гильдий (H1).
        guild = self._primary_guild()
        if guild is None:
            return None
        try:
            channel = guild.get_channel(int(channel_id))
        except (TypeError, ValueError):
            return None
        return channel if isinstance(channel, discord.TextChannel) else None

    # --- rate-limit ---

    def _rate_key(self, request: web.Request) -> str:
        # Адрес соединения — единственный ключ, который нельзя подделать
        # извне. X-Forwarded-For учитывается только за доверенным прокси.
        if self._trusted_proxy:
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                return forwarded.split(",")[0].strip() or (request.remote or "?")
        return request.remote or "?"

    def _rate_ok(self, request: web.Request) -> bool:
        key = self._rate_key(request)
        now = time.time()
        hits = self._rate_hits[key]
        while hits and hits[0] < now - _RATE_LIMIT_WINDOW:
            hits.popleft()
        if len(hits) >= _RATE_LIMIT_MAX:
            return False
        hits.append(now)
        self._rate_gc += 1
        if self._rate_gc % 500 == 0:
            self._prune_rate_hits(now)
        return True

    def _prune_rate_hits(self, now: float) -> None:
        """Удаляет протухшие ключи, чтобы словарь не рос бесконечно."""
        cutoff = now - _RATE_LIMIT_WINDOW
        expired = [key for key, hits in self._rate_hits.items() if not hits or hits[-1] < cutoff]
        for key in expired:
            self._rate_hits.pop(key, None)

    # --- origin ---

    def _allowed_origin(self, request: web.Request) -> bool:
        origin = request.headers.get("Origin") or request.headers.get("Referer")
        if not origin:
            return True
        parsed = urlparse(origin)
        host = parsed.hostname
        if not host:
            return False
        if host == self.host:
            return True
        # localhost-Origin доверяем только если сама панель локальная —
        # иначе любой локальный приложение сможет слать кросс-ориджин-запросы
        # к публичной панели (M6).
        if host in _LOCAL_HOSTS and self.host in _LOCAL_HOSTS:
            return True
        if host == (request.host or "").split(":")[0]:
            return True
        for entry in (self.public_url or "").split(","):
            entry = entry.strip()
            if not entry:
                continue
            candidate = urlparse(entry).hostname if "://" in entry else entry.split("/")[0].split(":")[0]
            if candidate == host:
                return True
        return False

    # --- токены ---

    @staticmethod
    def _role_rank(role: str) -> int:
        return {"viewer": 10, "moderator": 20, "admin": 30, "owner": 40}.get(role, 0)

    def _check_token_value(self, token: str) -> str | None:
        if not token:
            return None
        # Статик-режим: только localhost без пароля и без OAuth.
        # В OAuth-режиме _static_token = None, поэтому сессии проверяются ниже.
        if not self._password_auth and not self._oauth_enabled:
            return "owner" if self._static_token and secrets.compare_digest(token, self._static_token) else None
        now = time.time()
        active: dict[str, _PanelSession] = {}
        role: str | None = None
        for saved, session in self._sessions.items():
            if session["expires"] > now:
                active[saved] = session
                if secrets.compare_digest(token, saved):
                    role = session["role"]
        self._sessions = active
        if len(self._sessions) > _SESSION_MAX:
            self._sessions = dict(sorted(self._sessions.items(), key=lambda item: item[1]["expires"])[:_SESSION_MAX])
        return role
