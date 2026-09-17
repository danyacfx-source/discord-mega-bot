"""Overlay для OBS: статус стрима, каналы, донат-цель. Порт Node ``overlay.js``."""
from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.overlay")

_PAGE_FILE = Path(__file__).resolve().parent / "page.html"


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
    def _create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/overlay", self._page_handler)
        app.router.add_get("/overlay/api", self._api_handler)
        app.router.add_get("/overlay/health", self._health_handler)
        return app

    def _valid_auth(self, request: web.Request) -> bool:
        token = request.headers.get("X-Overlay-Token") or request.query.get("token") or ""
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
        if not self._valid_auth(request):
            return self._unauthorized()
        return web.json_response(await self._payload())

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
            return self._base_stream("twitch", None)
        if config.kick_channel_slug:
            try:
                status = await services.kick.channel_status(config.kick_channel_slug)
            except Exception:
                logger.debug("Overlay: ошибка опроса Kick %s", config.kick_channel_slug, exc_info=True)
                status = None
            base = self._base_stream("kick", f"https://kick.com/{config.kick_channel_slug}")
            if status is not None:
                viewers = status.get("viewers") or 0
                return {
                    **base,
                    "live": True,
                    "viewers": viewers,
                    "peak": viewers,
                    "title": str(status.get("title") or "")[:200],
                    "category": str(status.get("category") or "")[:100],
                    "startedAt": status.get("started_at"),
                }
            if not config.twitch_channels:
                return base
        login = config.twitch_channels[0]
        base = self._base_stream("twitch", f"https://www.twitch.tv/{login}")
        try:
            status = await services.twitch.channel_status(login)
        except Exception:
            logger.debug("Overlay: ошибка опроса стрима %s", login, exc_info=True)
            return base
        if status is None:
            return base
        return {
            **base,
            "live": True,
            "viewers": status.get("viewers") or 0,
            "title": str(status.get("title") or "")[:200],
            "category": str(status.get("category") or "")[:100],
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
