"""Сессии, CSRF, OAuth, rate-limit и авторизация запросов веб-панели."""
from __future__ import annotations

import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode, urlparse

from aiohttp import web
from argon2.exceptions import VerificationError

from app.core.webpanel.payload import (
    _CSP,
    _LOCAL_HOSTS,
    _LOGIN_LIMIT,
    _LOGIN_WINDOW,
    _PANEL_ROLE_KEY,
    _RATE_LIMIT_MAX,
    _RATE_LIMIT_WINDOW,
    _SESSION_MAX,
    _SESSION_TTL,
    _PanelSession,
)

logger = logging.getLogger("bot.webpanel")


class _AuthMixin:
    """Сессии, CSRF, OAuth, rate-limit и авторизация запросов веб-панели."""

    # --- авторизация, origin и безопасность ---

    @web.middleware
    async def _security_middleware(self, request: web.Request, handler: Any) -> web.Response:
        # Страницы, статика и прочие не-API маршруты не проходят через
        # _authorized, поэтому лимит считаем здесь. /api и /ws учитываются
        # в своих обработчиках, чтобы не считать дважды.
        if not request.path.startswith(("/api/", "/ws/")) and not self._rate_ok(request):
            return self._json({"ok": False, "error": "Слишком много запросов"}, status=429)
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            response = web.Response(status=exc.status, headers=exc.headers, text=exc.text)
        except Exception:
            logger.exception("Необработанная ошибка HTTP %s %s", request.method, request.path)
            response = self._json({"ok": False, "error": "Внутренняя ошибка сервера"}, status=500)
        headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=(), usb=(), payment=()",
            "Cross-Origin-Opener-Policy": "same-origin",
            "Content-Security-Policy": _CSP,
            "Cache-Control": "no-store",
        }
        proto = request.headers.get("X-Forwarded-Proto") or request.scheme
        if proto == "https":
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers.update(headers)
        return response

    @staticmethod
    def _role_rank(role: str) -> int:
        return {"viewer": 10, "moderator": 20, "admin": 30, "owner": 40}.get(role, 0)

    def _required_role(self, request: web.Request) -> str:
        if request.method == "GET":
            if request.path in {"/api/backup", "/api/backup/db", "/api/metrics"}:
                return "admin"
            return "viewer"
        if request.path in {
            "/api/settings",
            "/api/automod",
            "/api/tickets/panel",
            "/api/server/members/roles",
        } or request.path.startswith(("/api/upload", "/api/webhook", "/api/bot", "/api/automod/")):
            return "admin"
        return "moderator"

    async def _record_admin_audit(self, request: web.Request, role: str, response: web.Response) -> None:
        if request.method == "GET" or response.status >= 400 or self.bot.db is None:
            return
        try:
            await self.bot.db.record_admin_audit(
                role,
                "panel request",
                request.method,
                request.path,
                request.remote or "",
            )
        except Exception:
            logger.exception("Не удалось записать аудит веб-панели")

    def _authorized(self, handler, required_role: str | None = None):
        async def wrapped(request: web.Request) -> web.Response:
            if not self._rate_ok(request) or not self._allowed_origin(request):
                return self._json({"ok": False, "error": "Unauthorized"}, status=401)
            role = self._check_token(request)
            required = required_role or self._required_role(request)
            if role is None or self._role_rank(role) < self._role_rank(required):
                return self._json({"ok": False, "error": "Недостаточно прав"}, status=403 if role else 401)
            if request.method != "GET" and self._password_auth:
                token = request.headers.get("X-Panel-Token", "")
                expected_csrf = self._csrf_for_token(token)
                provided_csrf = request.headers.get("X-Panel-CSRF", "")
                if not expected_csrf or not provided_csrf or not secrets.compare_digest(expected_csrf, provided_csrf):
                    return self._json({"ok": False, "error": "Некорректный CSRF-токен"}, status=403)
            request[_PANEL_ROLE_KEY] = role
            response = await handler(request)
            await self._record_admin_audit(request, role, response)
            return response

        return wrapped

    def _bridge_or_authorized(self, handler, required_role: str | None = None):
        authorized = self._authorized(handler, required_role)

        async def wrapped(request: web.Request) -> web.Response:
            supplied = request.headers.get("X-Bridge-Token", "")
            if (
                self._bridge_token
                and supplied
                and self._rate_ok(request)
                and secrets.compare_digest(supplied, self._bridge_token)
            ):
                return await handler(request)
            return await authorized(request)

        return wrapped

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

    def _allowed_origin(self, request: web.Request) -> bool:
        origin = request.headers.get("Origin") or request.headers.get("Referer")
        if not origin:
            return True
        parsed = urlparse(origin)
        host = parsed.hostname
        if not host:
            return False
        if host == self.host or host in _LOCAL_HOSTS:
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

    def _check_token(self, request: web.Request) -> str | None:
        return self._check_token_value(request.headers.get("X-Panel-Token", ""))

    def _csrf_for_token(self, token: str) -> str | None:
        session = self._sessions.get(token)
        if session is None or session["expires"] <= time.time():
            return None
        return session["csrf"]

    def _check_token_value(self, token: str) -> str | None:
        if not token:
            return None
        if not self._password_auth:
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

    async def _api_logout(self, request: web.Request) -> web.Response:
        token = request.headers.get("X-Panel-Token", "")
        self._sessions.pop(token, None)
        return self._json({"ok": True})

    async def _api_session(self, request: web.Request) -> web.Response:
        role = request.get(_PANEL_ROLE_KEY, "viewer")
        token = request.headers.get("X-Panel-Token", "")
        return self._json(
            {
                "ok": True,
                "role": role,
                "csrf": self._csrf_for_token(token),
                "permissions": {
                    "read": True,
                    "moderate": self._role_rank(role) >= self._role_rank("moderator"),
                    "admin": self._role_rank(role) >= self._role_rank("admin"),
                    "owner": role == "owner",
                },
            }
        )

    async def _oauth_start(self, request: web.Request) -> web.Response:
        if not self._oauth_enabled:
            raise web.HTTPNotFound(text="Discord OAuth2 не настроен")
        now = time.time()
        self._oauth_states = {key: expires for key, expires in self._oauth_states.items() if expires > now}
        state = secrets.token_urlsafe(32)
        self._oauth_states[state] = now + 300
        query = urlencode(
            {
                "client_id": self._oauth_client_id,
                "response_type": "code",
                "redirect_uri": self._oauth_redirect_url,
                "scope": "identify guilds",
                "state": state,
            }
        )
        return web.Response(status=302, headers={"Location": f"https://discord.com/oauth2/authorize?{query}"})

    async def _oauth_callback(self, request: web.Request) -> web.Response:
        state = request.query.get("state", "")
        if not self._oauth_enabled or not state or self._oauth_states.pop(state, 0) <= time.time():
            raise web.HTTPBadRequest(text="OAuth2 state истёк или недействителен")
        if request.query.get("error"):
            raise web.HTTPUnauthorized(text="Discord OAuth2 отклонил авторизацию")
        code = request.query.get("code", "")
        if not code or self._http is None:
            raise web.HTTPBadRequest(text="Discord OAuth2 не вернул code")

        async with self._http.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": self._oauth_client_id,
                "client_secret": self._oauth_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._oauth_redirect_url,
            },
        ) as token_response:
            if token_response.status != 200:
                raise web.HTTPUnauthorized(text="Не удалось обменять OAuth2 code")
            token_data = await token_response.json()
        access_token = token_data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise web.HTTPUnauthorized(text="Discord не вернул access token")

        headers = {"Authorization": f"Bearer {access_token}"}
        async with self._http.get("https://discord.com/api/users/@me", headers=headers) as user_response:
            if user_response.status != 200:
                raise web.HTTPUnauthorized(text="Не удалось получить Discord-профиль")
            user_data = await user_response.json()
        try:
            user_id = int(user_data["id"])
        except (KeyError, TypeError, ValueError):
            raise web.HTTPUnauthorized(text="Некорректный Discord-профиль")

        async with self._http.get("https://discord.com/api/users/@me/guilds", headers=headers) as guilds_response:
            if guilds_response.status != 200:
                raise web.HTTPUnauthorized(text="Не удалось получить список серверов")
            guilds = await guilds_response.json()
        if not isinstance(guilds, list):
            raise web.HTTPUnauthorized(text="Discord вернул некорректный список серверов")
        primary_guild = self._primary_guild()
        target_guild = self.bot.config.guild_id or (primary_guild.id if primary_guild else None)
        member_guild = next(
            (item for item in guilds if isinstance(item, dict) and str(item.get("id")) == str(target_guild)),
            None,
        )
        if member_guild is None:
            raise web.HTTPForbidden(text="У Discord-пользователя нет доступа к серверу бота")

        try:
            permissions = int(str(member_guild.get("permissions") or 0))
        except (TypeError, ValueError):
            raise web.HTTPUnauthorized(text="Discord вернул некорректные права пользователя")
        if self.bot.config.owner_id == user_id or bool(member_guild.get("owner")):
            role = "owner"
        elif permissions & (1 << 3) or permissions & (1 << 5):
            role = "admin"
        elif permissions & (1 << 13):
            role = "moderator"
        else:
            role = "viewer"

        session_token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        self._sessions[session_token] = {"expires": time.time() + _SESSION_TTL, "role": role, "csrf": csrf}
        if len(self._sessions) > _SESSION_MAX:
            self._sessions = dict(sorted(self._sessions.items(), key=lambda item: item[1]["expires"])[:_SESSION_MAX])
        # Токен уходит во fragment: он не попадает ни в access-log сервера,
        # ни в историю запросов, в отличие от query-строки.
        query = urlencode({"oauth_token": session_token, "oauth_csrf": csrf})
        return web.Response(status=302, headers={"Location": f"/admin#{query}"})

    async def _api_login(self, request: web.Request) -> web.Response:
        if not self._password_auth:
            return self._json({"ok": False, "error": "Пароль не настроен"}, status=400)
        if not self._allowed_origin(request):
            return self._json({"ok": False, "error": "Unauthorized"}, status=401)
        ip = request.remote or "?"
        now = time.time()
        attempts = self._login_attempts[ip]
        while attempts and attempts[0] < now - _LOGIN_WINDOW:
            attempts.popleft()
        if len(attempts) >= _LOGIN_LIMIT:
            return self._json({"ok": False, "error": "Слишком много попыток. Подождите минуту."}, status=429)
        try:
            payload = await request.json()
        except Exception:
            return self._json({"ok": False, "error": "Некорректный JSON"}, status=400)
        password = str(payload.get("password") or "")
        role = next(
            (
                candidate
                for candidate, configured in self._panel_passwords.items()
                if secrets.compare_digest(password, configured)
            ),
            None,
        )
        if role is None:
            for candidate, configured in self._panel_password_hashes.items():
                try:
                    if self._password_hasher.verify(configured, password):
                        role = candidate
                        break
                except VerificationError:
                    continue
        if role is None:
            attempts.append(now)
            return self._json({"ok": False, "error": "Неверный пароль"}, status=401)
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        self._sessions[token] = {"expires": now + _SESSION_TTL, "role": role, "csrf": csrf}
        if len(self._sessions) > _SESSION_MAX:
            self._sessions = dict(sorted(self._sessions.items(), key=lambda item: item[1]["expires"])[:_SESSION_MAX])
        return self._json({"ok": True, "token": token, "role": role, "csrf": csrf})
