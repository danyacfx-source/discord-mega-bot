"""Сессии, CSRF, OAuth, rate-limit и авторизация запросов веб-панели."""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from base64 import b64encode
from hashlib import sha256
from typing import Any
from urllib.parse import urlencode

import discord
from aiohttp import web
from argon2.exceptions import VerificationError

from app.core.shield import is_scanner_path, is_scanner_ua
from app.core.totp import verify as verify_totp
from app.core.webpanel.base_api import RATE_LIMIT_KEY, _BaseApi
from app.core.webpanel.payload import (
    _CSP,
    _CSP_REST,
    _LOGIN_LIMIT,
    _LOGIN_LOCK_SECONDS,
    _LOGIN_WINDOW,
    _PANEL_ROLE_KEY,
    _SCAN_BAN_SECONDS,
    _SCAN_LIMIT,
    _SCAN_PERMANENT_AFTER,
    _SCAN_WINDOW,
    _SESSION_MAX,
    _SESSION_TTL,
    _token_key,
)
from app.db.admin_audit_repository import AdminAuditRepository
from app.db.panel_login_lock_repository import PanelLoginLockRepository
from app.db.panel_session_repository import PanelSessionRepository
from app.features.scan_bans.repository import PanelScanRepository

logger = logging.getLogger("bot.webpanel")

#: Инлайн-скрипты ищем только в HTML; внешние src= в хэш не берём.
_INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\ssrc=)[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)


class _AuthMixin(_BaseApi):
    """Сессии, CSRF, OAuth, rate-limit и авторизация запросов веб-панели."""

    # --- авторизация, origin и безопасность ---

    @web.middleware
    async def _security_middleware(self, request: web.Request, handler: Any) -> web.Response:
        # Сканеры глушим до rate-лимита и хендлеров: пустые 404/403 без логов.
        ip = self._rate_key(request)
        now = time.time()
        if self._scan_bans.get(ip, 0.0) > now:
            # Попытки во время бана тоже считаются: эскалация продолжается, пока IP не угомонится.
            await self._note_scan(ip, now, f"во время бана: {request.path}", self._client_location(request))
            return web.Response(status=403)
        if is_scanner_ua(request.headers.get("User-Agent", "")):
            await self._note_scan(ip, now, f"UA: {request.headers.get('User-Agent', '')}", self._client_location(request))
            return web.Response(status=403)
        if is_scanner_path(request.path):
            await self._note_scan(ip, now, f"путь: {request.path}", self._client_location(request))
            return web.Response(status=404, text="Not Found")
        # Страницы, статика и прочие не-API маршруты не проходят через
        # _authorized, поэтому лимит считаем здесь. /api и /ws учитываются
        # в своих обработчиках, чтобы не считать дважды.
        if not request.path.startswith(("/api/", "/ws/")) and not self._rate_ok(request):
            limited = self._json({"ok": False, "error": "Слишком много запросов"}, status=429)
            limited.headers["Retry-After"] = str(request[RATE_LIMIT_KEY]["reset"])
            return limited
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
            "Cross-Origin-Resource-Policy": "same-origin",
            "Content-Security-Policy": self._csp_for(response),
        }
        # Handler мог задать явный кэш (неизменяемые /uploads/*) — не затираем.
        if "Cache-Control" not in response.headers:
            headers["Cache-Control"] = "no-store"
        proto = request.headers.get("X-Forwarded-Proto") or request.scheme
        if proto == "https":
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        rate = request.get(RATE_LIMIT_KEY)
        if rate:
            headers["X-RateLimit-Limit"] = str(rate["limit"])
            headers["X-RateLimit-Remaining"] = str(rate["remaining"])
            headers["X-RateLimit-Reset"] = str(rate["reset"])
        response.headers.update(headers)
        return response

    @staticmethod
    def _csp_for(response: web.Response) -> str:
        """Для HTML считаем sha256 каждого инлайн-скрипта — так CSP можно
        ужать до 'self' + хэшей без unsafe-inline. Не-HTML отдаёт статичный CSP."""
        if "text/html" not in (response.headers.get("Content-Type") or ""):
            return _CSP
        if isinstance(response, web.FileResponse):
            return _CSP
        try:
            body = response.text or ""
        except Exception:
            return _CSP
        hashes = [
            f"'sha256-{b64encode(sha256(match.group(1).encode('utf-8')).digest()).decode('ascii')}'"
            for match in _INLINE_SCRIPT_RE.finditer(body)
        ]
        script_src = "script-src 'self'" + ("".join(f" {digest}" for digest in hashes) if hashes else "")
        # Инлайн-обработчики (onclick= и т.п.) запрещены: только скрипты с хешами.
        return f"default-src 'self'; {script_src}; script-src-attr 'none'; {_CSP_REST}"

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

    @staticmethod
    def _access_denied_page() -> web.Response:
        body = """<!doctype html><html lang="ru"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Доступ запрещён</title><style>
        body{margin:0;min-height:100vh;display:grid;place-items:center;background:#10170f;color:#e6eee1;font:16px system-ui,sans-serif}
        main{max-width:460px;margin:24px;padding:38px;border:1px solid #6d8b5b;border-radius:18px;background:#1b2619;text-align:center}
        h1{margin:0 0 12px;font-size:28px}p{margin:0;color:#b8c5b1;line-height:1.5}
        </style><main><h1>Доступ запрещён</h1><p>У вас недостаточно прав для входа в веб-админку.</p></main>"""
        return web.Response(text=body, content_type="text/html", charset="utf-8", status=403)

    async def _record_admin_audit(self, request: web.Request, role: str, response: web.Response) -> None:
        if request.method == "GET" or response.status >= 400 or self.bot.db is None:
            return
        try:
            await AdminAuditRepository(self.bot.db).record(
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
            # CSRF обязателен при парольных сессиях и при OAuth-сессиях —
            # иначе OAuth-режим без пароля работал бы без CSRF (C1-класс).
            if request.method != "GET" and (self._password_auth or self._sessions):
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
                # Bridge-запросы идут мимо CSRF и ролей, но не мимо аудита —
                # иначе утечка bridge-токена даёт невидимые деструктивные действия.
                request[_PANEL_ROLE_KEY] = "bridge"
                response = await handler(request)
                await self._record_admin_audit(request, "bridge", response)
                return response
            return await authorized(request)

        return wrapped

    def _check_token(self, request: web.Request) -> str | None:
        return self._check_token_value(request.headers.get("X-Panel-Token", ""))

    def _csrf_for_token(self, token: str) -> str | None:
        session = self._sessions.get(_token_key(token))
        if session is None or session["expires"] <= time.time():
            return None
        return session["csrf"]

    def _session_repo(self) -> PanelSessionRepository | None:
        db = self.bot.db
        return PanelSessionRepository(db) if db is not None else None

    async def _store_session(self, token: str, role: str, csrf: str, expires: float) -> None:
        """Сессия живёт в памяти для быстрых проверок и в БД — переживает рестарт.

        Ошибка БД не валит вход: сессия остаётся в памяти до рестарта.
        """
        key = _token_key(token)
        self._sessions[key] = {"expires": expires, "role": role, "csrf": csrf}
        if len(self._sessions) > _SESSION_MAX:
            self._sessions = dict(sorted(self._sessions.items(), key=lambda item: item[1]["expires"])[:_SESSION_MAX])
        repo = self._session_repo()
        if repo is None:
            return
        try:
            await repo.save(key, role, csrf, expires)
        except Exception:
            logger.warning("Не удалось сохранить сессию панели в БД — только в памяти", exc_info=True)

    async def _drop_session(self, key: str) -> None:
        self._sessions.pop(key, None)
        repo = self._session_repo()
        if repo is None:
            return
        try:
            await repo.delete(key)
        except Exception:
            logger.warning("Не удалось удалить сессию панели из БД", exc_info=True)

    async def _restore_sessions(self) -> None:
        """Поднимает живые сессии из БД после рестарта процесса."""
        repo = self._session_repo()
        if repo is None:
            return
        try:
            rows = await repo.load_active(time.time())
        except Exception:
            logger.warning("Не удалось восстановить сессии панели из БД", exc_info=True)
            return
        for key, role, csrf, expires in rows:
            self._sessions[key] = {"expires": expires, "role": role, "csrf": csrf}
        if rows:
            logger.info("Восстановлено сессий панели из БД: %d", len(rows))

    async def _note_scan(self, ip: str, now: float, detail: str, location: str = "") -> None:
        """Считает попадание сканера; после _SCAN_LIMIT за _SCAN_WINDOW — бан IP.

        Счётчик нарушений не сбрасывается: эскалация идёт по всей истории IP,
        каждый бан пишется в БД и владельцу уходит ЛС. Постоянный бан не пересчитывается.
        """
        if location:
            self._scan_locations[ip] = location
        if self._scan_bans.get(ip) == float("inf"):
            return
        hits = self._scan_hits[ip]
        hits.append(now)
        while hits and hits[0] < now - _SCAN_WINDOW:
            hits.popleft()
        if len(hits) < _SCAN_LIMIT:
            return
        hits.clear()
        count = self._scan_offenses.get(ip, (0, 0.0))[0] + 1
        until = float("inf") if count >= _SCAN_PERMANENT_AFTER else now + _SCAN_BAN_SECONDS * 2 ** (count - 1)
        self._scan_bans[ip] = until
        self._scan_offenses[ip] = (count, until)
        if until == float("inf"):
            logger.warning("Бан IP за сканирование панели навсегда: ip=%s (%s), нарушение %d", ip, location or "локация неизвестна", count)
        else:
            logger.warning(
                "Бан IP за сканирование панели: ip=%s (%s) на %d с, нарушение %d",
                ip, location or "локация неизвестна", int(until - now), count,
            )
        await self._save_scan_ban(ip, count, until, self._scan_locations.get(ip, ""))
        await self._notify_scan_ban(ip, detail, count, until, now)

    async def _save_scan_ban(self, ip: str, count: int, until: float, location: str = "") -> None:
        db = self.bot.db
        if db is None:
            return
        try:
            await PanelScanRepository(db).save(ip, count, until, location)
        except Exception:
            logger.warning("Не удалось сохранить бан сканера в БД — только в памяти", exc_info=True)

    async def _restore_scan_state(self) -> None:
        """Поднимает нарушителей и активные баны из БД после рестарта процесса."""
        db = self.bot.db
        if db is None:
            return
        try:
            rows = await PanelScanRepository(db).load_all()
        except Exception:
            logger.warning("Не удалось восстановить нарушителей сканирования из БД", exc_info=True)
            return
        now = time.time()
        for ip, count, until, location in rows:
            self._scan_offenses[ip] = (count, until)
            if location:
                self._scan_locations[ip] = location
            if until > now:
                self._scan_bans[ip] = until
        if rows:
            logger.info("Восстановлено нарушителей сканирования из БД: %d", len(rows))

    async def _notify_scan_ban(self, ip: str, detail: str, count: int, until: float, now: float) -> None:
        """ЛС владельцу о каждом бане за сканирование; сбой отправки не мешает защите."""
        owner_id = self.bot.config.owner_id
        if not owner_id:
            return
        when = "навсегда" if until == float("inf") else f"на {int(until - now) // 60} мин"
        text = (
            "🚨 **Веб-панель: попытка сканирования**\n"
            f"IP: `{ip}`\n"
            f"Локация: {self._scan_locations.get(ip) or 'неизвестна'}\n"
            f"Нарушение №{count}, бан {when}\n"
            f"Последний запрос: {detail[:200]}"
        )
        try:
            user = self.bot.get_user(owner_id) or await self.bot.fetch_user(owner_id)
            await asyncio.wait_for(user.send(text), timeout=10)
        except Exception:
            logger.warning("Не удалось отправить владельцу ЛС о сканировании ip=%s", ip, exc_info=True)

    async def _prune_auth_state(self, now: float) -> None:
        """Периодическая очистка: протухшие сессии и попытки входа в памяти, сессии и блокировки в БД."""
        for ip in [ip for ip, until in self._scan_bans.items() if until <= now]:
            self._scan_bans.pop(ip, None)
        cutoff_scan = now - _SCAN_WINDOW
        for ip in [ip for ip, hits in self._scan_hits.items() if not hits or hits[-1] < cutoff_scan]:
            self._scan_hits.pop(ip, None)
        for key in [key for key, session in self._sessions.items() if session["expires"] <= now]:
            self._sessions.pop(key, None)
        cutoff = now - _LOGIN_WINDOW
        for key in [key for key, bucket in self._login_attempts.items() if not bucket or bucket[-1] < cutoff]:
            self._login_attempts.pop(key, None)
        repo = self._session_repo()
        if repo is not None:
            try:
                await repo.prune(now)
            except Exception:
                logger.warning("Не удалось очистить протухшие сессии в БД", exc_info=True)
        await self._login_prune(now)

    async def _api_scan_bans_get(self, request: web.Request) -> web.Response:
        """Нарушители сканирования: активные баны сверху, затем история."""
        now = time.time()
        items = [
            {
                "ip": ip,
                "offenses": count,
                "banned": until > now,
                "permanent": until == float("inf"),
                "until": None if until == float("inf") else until,
                "location": self._scan_locations.get(ip, ""),
            }
            for ip, (count, until) in self._scan_offenses.items()
        ]
        items.sort(key=lambda item: (not item["banned"], not item["permanent"], -item["offenses"]))
        return self._json({"ok": True, "items": items[:500], "total": len(items)})

    async def clear_scan_ban(self, ip: str, source: str) -> int | None:
        """Снимает действующий бан IP и возвращает число нарушений; None — IP неизвестен.

        Счётчик нарушений остаётся: эскалация не обнуляется.
        """
        if ip not in self._scan_offenses:
            return None
        count, _ = self._scan_offenses[ip]
        self._scan_bans.pop(ip, None)
        self._scan_hits.pop(ip, None)
        self._scan_offenses[ip] = (count, 0.0)
        await self._save_scan_ban(ip, count, 0.0)
        logger.warning("Бан сканера снят вручную (%s): ip=%s (нарушений всего %d)", source, ip, count)
        return count

    async def _api_scan_ban_clear(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        ip = str(payload.get("ip") or "").strip()
        count = await self.clear_scan_ban(ip, "панель")
        if count is None:
            return self._json({"ok": False, "error": "IP нет среди нарушителей сканирования"}, status=404)
        return self._json({"ok": True, "ip": ip, "offenses": count})

    async def _api_logout(self, request: web.Request) -> web.Response:
        token = request.headers.get("X-Panel-Token", "")
        await self._drop_session(_token_key(token))
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
            return self._access_denied_page()

        try:
            permissions = int(str(member_guild.get("permissions") or 0))
        except (TypeError, ValueError):
            raise web.HTTPUnauthorized(text="Discord вернул некорректные права пользователя")

        # Проверяем роли через бота: PANEL_ADMIN_ROLE_IDS — полный доступ.
        member = None
        guild = self._primary_guild()
        if guild is not None:
            try:
                member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            except (discord.NotFound, discord.HTTPException, ValueError):
                member = None

        panel_admin_role_ids = getattr(self, "_admin_role_ids", set())
        has_admin_role = bool(member and panel_admin_role_ids and any(r.id in panel_admin_role_ids for r in member.roles))

        if self.bot.config.owner_id == user_id or bool(member_guild.get("owner")):
            role = "owner"
        elif has_admin_role or permissions & (1 << 3):
            # Доверенные роли из PANEL_ADMIN_ROLE_IDS или Discord Administrator.
            role = "admin"
        else:
            return self._access_denied_page()

        session_token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        await self._store_session(session_token, role, csrf, time.time() + _SESSION_TTL)
        # Токен уходит во fragment: он не попадает ни в access-log сервера,
        # ни в историю запросов, в отличие от query-строки.
        query = urlencode({"oauth_token": session_token, "oauth_csrf": csrf})
        return web.Response(status=302, headers={"Location": f"/admin#{query}"})

    # --- durable-блокировка входа (переживает рестарт процесса) ---

    def _login_locks(self) -> PanelLoginLockRepository | None:
        """Репозиторий блокировок; None — БД недоступна (деградация в память)."""
        db = self.bot.db
        return PanelLoginLockRepository(db) if db is not None else None

    async def _login_locked_until(self, key: str, now: float) -> float:
        """Момент разблокировки из БД; 0 — блокировки нет.

        Ошибка БД не должна ронять вход: остаётся in-memory лимит
        из ``_api_login`` — это деградация до прежнего уровня, не обход.
        """
        locks = self._login_locks()
        if locks is None:
            return 0.0
        try:
            return await locks.locked_until(key, now)
        except Exception:
            logger.warning("Не удалось прочитать блокировку логина из БД — используется память", exc_info=True)
            return 0.0

    async def _login_note_failure(self, key: str, now: float) -> float:
        """Чинит неудачу; возвращает момент разблокировки (0 — лок не наступил).

        Факт блокировки — единственный сигнал, который пишется в аудит: по одной
        строке на каждый лок, а не на каждую попытку, иначе перебор мог бы
        раздуть таблицу admin_audit.
        """
        locks = self._login_locks()
        if locks is None:
            return 0.0
        try:
            locked_until = await locks.record_failure(
                key,
                now,
                limit=_LOGIN_LIMIT,
                window=_LOGIN_WINDOW,
                lock_seconds=_LOGIN_LOCK_SECONDS,
            )
        except Exception:
            logger.warning("Не удалось сохранить неудачу логина в БД", exc_info=True)
            return 0.0
        if locked_until:
            logger.warning(
                "Вход в панель заблокирован: ip=%s до %d (перебор пароля/2FA)",
                key,
                int(locked_until),
            )
            db = self.bot.db
            if db is not None:
                try:
                    await AdminAuditRepository(db).record(
                        "anonymous", "login lockout", "POST", "/api/login", key
                    )
                except Exception:
                    logger.debug("Не удалось записать блокировку в аудит", exc_info=True)
        return locked_until

    async def _login_unlock(self, key: str) -> None:
        locks = self._login_locks()
        if locks is None:
            return
        try:
            await locks.clear(key)
        except Exception:
            logger.warning("Не удалось сбросить блокировку логина", exc_info=True)

    async def _login_prune(self, now: float) -> None:
        """Протухшие ключи не копятся: сканер порождает множество IP."""
        locks = self._login_locks()
        if locks is None:
            return
        try:
            await locks.prune(now, _LOGIN_WINDOW)
        except Exception:
            logger.debug("Не удалось почистить таблицу блокировок логина", exc_info=True)

    async def _api_login(self, request: web.Request) -> web.Response:
        if not self._password_auth:
            return self._json({"ok": False, "error": "Пароль не настроен"}, status=400)
        if not self._rate_ok(request):
            return self._json({"ok": False, "error": "Слишком много запросов"}, status=429)
        if not self._allowed_origin(request):
            return self._json({"ok": False, "error": "Unauthorized"}, status=401)
        # Ключ — реальный клиент: за прокси request.remote общий, и чужие
        # неудачи блокировали бы вход для всех сразу.
        ip = self._rate_key(request)
        now = time.time()
        # Durable-блокировка первым делом: она живёт в БД, поэтому рестарт
        # контейнера брутфорсу не помогает (раньше счётчик был только в памяти).
        locked_until = await self._login_locked_until(ip, now)
        if locked_until:
            return self._json(
                {
                    "ok": False,
                    "error": f"Слишком много попыток. Повторите через {int(locked_until - now) + 1} сек.",
                },
                status=429,
            )
        if len(self._login_attempts) > 1000:
            cutoff = now - _LOGIN_WINDOW
            stale = [key for key, bucket in self._login_attempts.items() if not bucket or bucket[-1] < cutoff]
            for key in stale:
                self._login_attempts.pop(key, None)
        # Таблица блокировок чистится по счётчику вызовов, а не по размеру
        # словаря: память GC-ится на 1000+ ключей, а БД иначе копила бы
        # строки неделями при медленном сканере с разных адресов.
        self._login_gc += 1
        if self._login_gc % 100 == 0:
            await self._login_prune(now)
        attempts = self._login_attempts[ip]
        while attempts and attempts[0] < now - _LOGIN_WINDOW:
            attempts.popleft()
        if len(attempts) >= _LOGIN_LIMIT:
            return self._json({"ok": False, "error": "Слишком много попыток. Подождите минуту."}, status=429)
        try:
            payload = await request.json()
        except Exception:
            return self._json({"ok": False, "error": "Некорректный JSON"}, status=400)

        totp_secret = (getattr(self.bot.config, "panel_totp_secret", None) or "").strip()
        password = str(payload.get("password") or "")
        totp_code = str(payload.get("totp") or "").strip()
        # Фронт не переделывается: при включённой 2FA код дописывается к паролю
        # через двоеточие («пароль:123456») — существующая форма отдаёт его
        # как есть в поле password. Поле totp поддержано для API-клиентов.
        if totp_secret and not totp_code:
            head, separator, tail = password.rpartition(":")
            if separator and len(tail) == 6 and tail.isdigit():
                password, totp_code = head, tail

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
            await self._login_note_failure(ip, now)
            logger.warning("Неудачный вход в панель: ip=%s (неверный пароль)", ip)
            return self._json({"ok": False, "error": "Неверный пароль"}, status=401)
        if self._role_rank(role) < self._role_rank("admin"):
            return self._json({"ok": False, "error": "Доступ запрещён. У вас недостаточно прав"}, status=403)

        # Второй фактор после пароля и проверки роли. Неверный код идёт в тот же
        # счётчик неудач — иначе 6-значный TOTP можно было бы перебирать
        # без последствий, пока не угадается.
        if totp_secret:
            if not verify_totp(totp_secret, totp_code):
                attempts.append(now)
                await self._login_note_failure(ip, now)
                logger.warning("Неудачный вход в панель: ip=%s (неверный код 2FA)", ip)
                return self._json(
                    {"ok": False, "error": "Неверный код 2FA (формат: пароль:123456)"},
                    status=401,
                )

        # Успех сбрасывает счётчик: старые опечатки не должны блокировать вход.
        self._login_attempts.pop(ip, None)
        await self._login_unlock(ip)
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        await self._store_session(token, role, csrf, now + _SESSION_TTL)
        return self._json({"ok": True, "token": token, "role": role, "csrf": csrf})
