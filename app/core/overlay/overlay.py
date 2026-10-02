"""Overlay для OBS: статус стрима, каналы, донат-цель. Порт Node ``overlay.js``."""
from __future__ import annotations

import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web

from app.core.overlay.layout import load_layout
from app.utils.stream_history import sparkline, trend

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.overlay")

_PAGE_FILE = Path(__file__).resolve().parent / "page.html"
_LAYOUT_PAGE_FILE = Path(__file__).resolve().parent / "layout.html"

#: OBS опрашивает оверлей каждые 5 с — статус стрима кэшируем, чтобы не
#: долбить Twitch/Kick API на каждый запрос страницы.
_STATUS_CACHE_TTL = 60.0

_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)


def _read_page() -> str:
    return _PAGE_FILE.read_text(encoding="utf-8")


class Overlay:
    """aiohttp-сервер оверлея: токен из env или ``data/.overlay-token``."""

    def __init__(self, bot: MegaBot) -> None:
        self.bot = bot
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._token = self._resolve_token()
        self._page = _read_page().replace("__TOKEN__", self._token)
        self._layout_page = _LAYOUT_PAGE_FILE.read_text(encoding="utf-8").replace("__TOKEN__", self._token)
        self._status_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}

    @property
    def token(self) -> str:
        """Токен доступа (вебпанель отдаёт его admin'у для ссылки в OBS)."""
        return self._token

    # ------------------------------------------------------------------ токен
    def _resolve_token(self) -> str:
        config = self.bot.config
        data_dir = Path(config.db_path).parent
        env_token = (config.overlay_token or "").strip()
        if env_token and len(env_token) < 16:
            logger.warning("OVERLAY_TOKEN too short (<16) — ignoring insecure token")
            env_token = ""
        if env_token:
            return env_token

        token_file = data_dir / ".overlay-token"
        file_token = ""
        try:
            if token_file.exists():
                file_token = token_file.read_text(encoding="utf-8").strip()
        except OSError:
            pass
        if len(file_token) >= 16:
            logger.warning("Используется сохранённый токен из файла (OVERLAY_TOKEN не задан)")
            return file_token

        generated = secrets.token_urlsafe(32)
        try:
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(generated + "\n", encoding="utf-8")
            try:
                token_file.chmod(0o600)
            except (OSError, NotImplementedError):
                pass
            logger.warning(
                "Сгенерирован и сохранён OVERLAY_TOKEN в %s — установите OVERLAY_TOKEN в .env для постоянства",
                token_file,
            )
        except OSError:
            logger.warning(
                "OVERLAY_TOKEN не задан — сгенерирован временный токен (перезапуск сменит токен, установите OVERLAY_TOKEN в .env)"
            )
        return generated

    # ------------------------------------------------------------------ HTTP
    @web.middleware
    async def _security_middleware(self, request: web.Request, handler: Any) -> web.Response:
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            response = exc
        headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "SAMEORIGIN",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=(), usb=()",
            "Cross-Origin-Opener-Policy": "same-origin",
            "Content-Security-Policy": _CSP,
            "Cache-Control": "no-store",
        }
        response.headers.update(headers)
        return response

    def _create_app(self) -> web.Application:
        app = web.Application(middlewares=[self._security_middleware])
        app.router.add_get("/overlay", self._page_handler)
        app.router.add_get("/overlay/api", self._api_handler)
        app.router.add_get("/overlay/health", self._health_handler)
        app.router.add_get("/overlay/api/{layout_id}", self._layout_api_handler)
        app.router.add_get("/overlay/{layout_id}", self._layout_page_handler)
        return app

    def _valid_auth(self, request: web.Request) -> bool:
        token = request.headers.get("X-Overlay-Token") or request.query.get("token") or ""
        return secrets.compare_digest(str(token), self._token)

    def _valid_api_auth(self, request: web.Request) -> bool:
        # API принимает только заголовок: query-строка оседает в access-log
        # и истории запросов браузера, в отличие от заголовка.
        token = request.headers.get("X-Overlay-Token", "")
        return secrets.compare_digest(str(token), self._token)

    def _unauthorized(self) -> web.Response:
        return web.json_response({"error": "unauthorized"}, status=401)

    async def _page_handler(self, request: web.Request) -> web.Response:
        if not self._valid_auth(request):
            return self._unauthorized()
        return web.Response(text=self._page, content_type="text/html", charset="utf-8")

    async def _health_handler(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def _api_handler(self, request: web.Request) -> web.Response:
        if not self._valid_api_auth(request):
            return self._unauthorized()
        return web.json_response(await self._payload())

    # ------------------------------------------------------- раскладки (KV)

    async def _layout_page_handler(self, request: web.Request) -> web.Response:
        if not self._valid_auth(request):
            return self._unauthorized()
        layout = await self._load_layout(request.match_info["layout_id"])
        if layout is None:
            return web.json_response({"error": "layout not found"}, status=404)
        return web.Response(text=self._layout_page, content_type="text/html", charset="utf-8")

    async def _layout_api_handler(self, request: web.Request) -> web.Response:
        if not self._valid_api_auth(request):
            return self._unauthorized()
        layout = await self._load_layout(request.match_info["layout_id"])
        if layout is None:
            return web.json_response({"error": "layout not found"}, status=404)
        data = await self._payload()
        data["last_donation"] = await self._kv_json("overlay:last_donation")
        data["last_slot"] = await self._kv_json("overlay:last_slot")
        data["last_poll"] = await self._kv_json("overlay:last_poll")
        data["chat_top"] = await self._chat_top()
        data["chat"] = self._feed_recent()
        return web.json_response({"layout": layout, "data": data})

    async def _load_layout(self, layout_id: str) -> dict[str, Any] | None:
        services = self.bot.services
        if services is None:
            return None
        try:
            return await load_layout(services.kv, layout_id)
        except Exception:
            logger.debug("Overlay: раскладка %s не прочитана", layout_id, exc_info=True)
            return None

    async def _kv_json(self, key: str) -> dict[str, Any] | None:
        services = self.bot.services
        if services is None:
            return None
        try:
            raw = await services.kv.get(key)
            if not raw:
                return None

            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def _feed_recent(self) -> list[dict[str, Any]]:
        services = self.bot.services
        if services is None:
            return []
        try:
            return services.chat_feed.recent(limit=80)
        except Exception:
            logger.debug("Overlay: лента чата не прочитана", exc_info=True)
            return []

    async def _chat_top(self) -> list[dict[str, Any]]:
        services = self.bot.services
        config = self.bot.config
        if services is None:
            return []
        platform = "kick" if config.kick_channel_slug else ("twitch" if config.twitch_channels else "")
        if not platform:
            return []
        try:
            rows = await services.chat_coins.top(platform, limit=3)
        except Exception:
            logger.debug("Overlay: топ чата не прочитан", exc_info=True)
            return []
        return [
            {
                "name": str(row.get("display_name") or row.get("username") or "?")[:32],
                "messages": int(row.get("messages") or 0),
                "coins": int(row.get("coins") or 0),
            }
            for row in rows[:3]
        ]

    async def _payload(self) -> dict[str, Any]:
        return {
            "stream": await self._stream_payload(),
            "channels": self._safe_channels(),
            "counters": [],
            "donation_goal": self._donation_goal(),
        }

    def _safe_channels(self) -> dict[str, str]:
        channels = self.bot.config.twitch_channels
        result: dict[str, str] = {}
        if channels:
            result["twitch"] = str(channels[0])[:64]
        return result

    def _donation_goal(self) -> dict[str, Any]:
        config = self.bot.config
        if not config.overlay_donation_goal_enabled:
            return {"enabled": False}
        return {
            "enabled": True,
            "target": config.overlay_donation_goal_target,
            "currency": str(config.overlay_donation_goal_currency)[:8],
            "label": str(config.overlay_donation_goal_label)[:64],
            "current": config.overlay_donation_goal_current,
        }

    async def _stream_payload(self) -> dict[str, Any] | None:
        config = self.bot.config
        if not config.twitch_channels and not config.kick_channel_slug:
            return None
        services = self.bot.services
        if services is None:
            return {**self._base_stream("twitch", None), "last": None}

        # Приоритет как раньше: Kick, если настроен, иначе Twitch.
        if config.kick_channel_slug:
            slug = config.kick_channel_slug
            platform = "kick"
            url = f"https://kick.com/{slug}"
            session = await services.kick.session_store(slug).load()
            status = await self._cached_status(platform, lambda: services.kick.channel_status(slug))
        elif config.twitch_channels:
            login = config.twitch_channels[0]
            platform = "twitch"
            url = f"https://www.twitch.tv/{login}"
            session = await services.twitch.session_store(login).load()
            status = await self._cached_status(platform, lambda: services.twitch.channel_status(login))
        else:
            return None

        # Сессия «последнего эфира» может быть от другого стрима — для live-блока
        # берём её только если started_at совпадает с текущим статусом.
        if status is not None and session and session.get("started_at") != status.get("started_at"):
            session = None
        last = self._last_block(session) if status is None else None

        base = self._base_stream(platform, url)
        if status is None:
            return {**base, "last": last}
        viewers = int(status.get("viewers") or 0)
        return {
            **base,
            "live": True,
            "viewers": viewers,
            "peak": max(viewers, int((session or {}).get("peak") or 0)),
            "title": str(status.get("title") or "")[:200],
            "category": str(status.get("category") or "")[:100],
            "startedAt": status.get("started_at") or (session or {}).get("started_at"),
            "trend": trend((session or {}).get("history")),
            "spark": sparkline((session or {}).get("history")),
            "last": last,
        }

    async def _cached_status(
        self, key: str, fetch: Callable[[], Awaitable[dict[str, Any] | None]]
    ) -> dict[str, Any] | None:
        """Статус стрима не чаще раза в ``_STATUS_CACHE_TTL`` секунд.

        ``fetch`` — корутина-фабрика (вызывается только при промахе кэша, чтобы
        не плодить не-awaited корутины). Ошибка тоже кэшируется: при забитом
        API оверлей не ретраит каждые 5 секунд.
        """
        now = time.monotonic()
        hit = self._status_cache.get(key)
        if hit is not None and now - hit[0] < _STATUS_CACHE_TTL:
            return hit[1]
        try:
            result = await fetch()
        except Exception:
            logger.debug("Overlay: ошибка опроса стрима %s", key, exc_info=True)
            result = None
        self._status_cache[key] = (now, result)
        return result

    @staticmethod
    def _last_block(session: dict[str, Any] | None) -> dict[str, Any] | None:
        """Данные последнего завершённого эфира для офлайн-карточки оверлея."""
        if not session or not session.get("title"):
            return None
        return {
            "title": str(session.get("title"))[:200],
            "peak": int(session.get("peak") or 0),
            "category": str(session.get("category") or "")[:100],
            "startedAt": session.get("started_at"),
            "capturedAt": session.get("captured_at"),
            "spark": sparkline(session.get("history")),
        }

    @staticmethod
    def _base_stream(platform: str, url: str | None) -> dict[str, Any]:
        return {
            "platform": platform,
            "live": False,
            "viewers": 0,
            "peak": 0,
            "title": None,
            "category": None,
            "startedAt": None,
            "url": url,
        }

    # ------------------------------------------------------------------ жизнь
    async def start(self) -> None:
        if self._runner is not None:
            return
        config = self.bot.config
        host = config.overlay_host
        port = config.overlay_port or 8765
        runner = web.AppRunner(self._create_app())
        await runner.setup()
        try:
            site = web.TCPSite(runner, host, port)
            await site.start()
        except OSError:
            logger.error("Порт %s уже занят — оверлей не запущен", port)
            await runner.cleanup()
            return
        self._runner = runner
        self._site = site
        logger.info("Сервер запущен на http://%s:%s/overlay", host, port)

    async def stop(self) -> None:
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
