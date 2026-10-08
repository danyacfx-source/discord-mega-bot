"""Вебпанель конструктора эмбедов: браузерный редактор, отправка через бота и прокси вебхуков."""
from __future__ import annotations

import asyncio
import html
import logging
import re
import secrets
from collections import defaultdict, deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiohttp
from aiohttp import web
from argon2 import PasswordHasher

from app.core.secrets import attach_redaction
from app.core.webpanel.auth import _AuthMixin
from app.core.webpanel.community_api import _CommunityApiMixin
from app.core.webpanel.core_api import _CoreApiMixin
from app.core.webpanel.guild_api import _GuildApiMixin
from app.core.webpanel.log_ring import RingBufferHandler
from app.core.webpanel.media_api import _MediaApiMixin
from app.core.webpanel.payload import (
    _AUDIT_PAGE_PATH,
    _DIST_INDEX_PATH,
    _LOCAL_HOSTS,
    _LOG_RING_SIZE,
    _LOGS_PAGE_PATH,
    _MAX_REQUEST_BYTES,
    _TOKEN_FILE,
    _UPLOAD_DIRNAME,
    _PanelSession,
)
from app.core.webpanel.payload import (
    overlay_url_base as overlay_url_base,
)
from app.core.webpanel.profiles_api import _ProfilesApiMixin
from app.core.webpanel.routes import register_routes
from app.core.webpanel.showcase_api import _ShowcaseApiMixin
from app.core.webpanel.tools_api import _ToolsApiMixin
from app.services.wardogs_service import WardogsService, WardogsUnavailable

if TYPE_CHECKING:
    from app.core.bot import MegaBot
    from app.services import Services

logger = logging.getLogger("bot.webpanel")



class WebPanel(
    _AuthMixin,
    _GuildApiMixin,
    _CommunityApiMixin,
    _ProfilesApiMixin,
    _CoreApiMixin,
    _ToolsApiMixin,
    _MediaApiMixin,
    _ShowcaseApiMixin,
):
    def __init__(self, bot: MegaBot) -> None:
        self.bot = bot
        config = bot.config
        if config.panel_port is None:
            raise RuntimeError("Веб-панель включена без PANEL_PORT")
        self.host = config.panel_host or "127.0.0.1"
        self.port = config.panel_port
        self.password = config.panel_password
        self.public_url = config.panel_public_url
        self._oauth_client_id = config.panel_oauth_client_id
        self._oauth_client_secret = config.panel_oauth_client_secret
        self._oauth_redirect_url = config.panel_oauth_redirect_url
        self._bridge_token = config.panel_bridge_token
        self._trusted_proxy = bool(config.panel_trusted_proxy)
        self._uploads_dir = Path(config.db_path).parent / _UPLOAD_DIRNAME
        self._logs_html = _LOGS_PAGE_PATH.read_text(encoding="utf-8") if _LOGS_PAGE_PATH.exists() else ""
        self._audit_html = _AUDIT_PAGE_PATH.read_text(encoding="utf-8") if _AUDIT_PAGE_PATH.exists() else ""
        self._static_token: str | None = None if self.password else self._load_static_token()
        self._sessions: dict[str, _PanelSession] = {}
        self._oauth_states: dict[str, float] = {}
        self._panel_passwords: dict[str, str] = {}
        self._panel_password_hashes: dict[str, str] = {}
        self._password_hasher = PasswordHasher()
        if self.password:
            self._panel_passwords["owner"] = self.password
        for role in ("admin", "moderator", "viewer"):
            value = getattr(config, f"panel_{role}_password", None)
            if value:
                self._panel_passwords[role] = value
        for role in ("owner", "admin", "moderator", "viewer"):
            value = getattr(config, f"panel_{role}_password_hash", None)
            if value:
                self._panel_password_hashes[role] = value
        self._password_auth = bool(self._panel_passwords or self._panel_password_hashes)
        self._rate_hits: dict[str, deque[float]] = defaultdict(deque)
        self._rate_gc: int = 0
        self._login_attempts: dict[str, deque[float]] = defaultdict(deque)
        self._runner: web.AppRunner | None = None
        self._http: aiohttp.ClientSession | None = None
        self._ring: RingBufferHandler | None = None
        self._lat: deque[dict[str, Any]] = deque(maxlen=90)
        self._mem: deque[dict[str, Any]] = deque(maxlen=90)
        self._online: deque[dict[str, Any]] = deque(maxlen=90)
        self._msg_by_hour: deque[dict[str, Any]] = deque(maxlen=24 * 7)
        self._msg_by_day: deque[dict[str, Any]] = deque(maxlen=45)
        self._msg_total: int = 0
        self._msg_unknown_logs: int = 0
        self._listener_registered = False
        self._analytics_task: asyncio.Task[None] | None = None
        self._pending_activity: dict[tuple[int, str], int] = defaultdict(int)
        self._analytics_clients: set[web.WebSocketResponse] = set()
        self._events_task: asyncio.Task[None] | None = None
        self._event_clients: set[asyncio.Queue[dict[str, Any]]] = set()
        self._events_seq: int = 0

    @property
    def services(self) -> Services:
        services = self.bot.services
        if services is None:
            raise RuntimeError("Сервисы недоступны до запуска вебпанели")
        return services

    @property
    def _oauth_enabled(self) -> bool:
        return bool(self._oauth_client_id and self._oauth_client_secret and self._oauth_redirect_url)

    # --- жизненный цикл ---

    def _load_static_token(self) -> str:
        path = Path(self.bot.config.db_path).parent / _TOKEN_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
        token = secrets.token_urlsafe(32)
        path.write_text(token, encoding="utf-8")
        try:
            path.chmod(0o600)
        except (OSError, NotImplementedError):
            pass
        return token

    def _create_app(self) -> web.Application:
        # aiohttp defaults to a 1 MiB request limit. That made the advertised
        # 8 MiB image-upload limit unusable for valid uploads.
        app = web.Application(
            middlewares=[self._security_middleware],
            client_max_size=_MAX_REQUEST_BYTES,
        )
        register_routes(self, app)
        return app

    async def start(self) -> None:
        if self._runner is not None:
            return
        # A static token is embedded into the page when no password is set.
        # That is convenient for localhost, but it would expose full admin
        # access to anyone who can open a public URL. Fail closed instead of
        # relying on a warning that is easy to miss in deployment logs.
        if not (self._password_auth or self._oauth_enabled) and (self.host not in _LOCAL_HOSTS or self.public_url):
            raise RuntimeError(
                "PANEL_PASSWORD обязателен для публичной веб-панели "
                "(задайте пароль или оставьте PANEL_HOST локальным без PANEL_PUBLIC_URL)"
            )
        self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15, connect=5))
        if not (self._password_auth or self._oauth_enabled) and self.host not in _LOCAL_HOSTS:
            logger.warning(
                "Вебпанель без PANEL_PASSWORD слушает %s:%d — страница доступна по статическому токену. "
                "В открытых сетях задайте PANEL_PASSWORD.",
                self.host,
                self.port,
            )
        runner = web.AppRunner(self._create_app())
        try:
            await runner.setup()
            await web.TCPSite(runner, self.host, self.port).start()
        except Exception:
            await runner.cleanup()
            await self._http.close()
            self._http = None
            raise
        self._runner = runner
        if not self._listener_registered:
            self.bot.add_listener(self._on_message_hook, "on_message")
            self._listener_registered = True
        self._analytics_task = asyncio.create_task(self._analytics_flush_loop())
        self._ring = RingBufferHandler(_LOG_RING_SIZE, on_record=self._on_ring_record)
        # Лента «Логи» уходит в браузер тем же каналом, что и консоль: маскируем
        # секреты до emit, иначе токен утек бы в ws-рассылку.
        attach_redaction(self._ring)
        logging.getLogger().addHandler(self._ring)
        self._events_task = asyncio.create_task(self._events_loop())
        logger.info("Вебпанель запущена: http://%s:%d/admin", self.host, self.port)

    async def stop(self) -> None:
        if self._analytics_task is not None:
            self._analytics_task.cancel()
            try:
                await self._analytics_task
            except asyncio.CancelledError:
                pass
            self._analytics_task = None
        if self._events_task is not None:
            self._events_task.cancel()
            try:
                await self._events_task
            except asyncio.CancelledError:
                pass
            self._events_task = None
        self._event_clients.clear()
        await self._flush_activity()
        for websocket in tuple(self._analytics_clients):
            await websocket.close()
        self._analytics_clients.clear()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        if self._ring is not None:
            logging.getLogger().removeHandler(self._ring)
            self._ring = None
        if getattr(self, "_listener_registered", False):
            self.bot.remove_listener(self._on_message_hook, "on_message")
            self._listener_registered = False
        if self._http is not None:
            await self._http.close()
            self._http = None

    # --- авторизация, origin и безопасность ---

    @staticmethod
    def _json(data: dict[str, Any], status: int = 200) -> web.Response:
        return web.json_response(data, status=status)

    # --- страницы ---

    async def _redirect_index(self, request: web.Request) -> web.Response:
        raise web.HTTPFound("/admin")

    def _wardogs_service(self) -> WardogsService:
        return WardogsService(
            server_name=self.bot.config.wardogs_server_name,
            server_id=self.bot.config.wardogs_server_id,
            timeout=self.bot.config.api_timeout_seconds,
        )

    async def _api_wardogs_join_link(self, request: web.Request) -> web.Response:
        """Публичный endpoint для виджетов, Discord и страницы подключения."""
        try:
            server = await self._wardogs_service().get_server()
        except WardogsUnavailable as exc:
            return self._json({"ok": False, "code": "server_unavailable", "error": str(exc)}, status=503)
        custom_url = self.bot.config.wardogs_join_url
        return self._json(
            {
                "ok": True,
                "joinId": server.join_id,
                "url": custom_url if custom_url and custom_url.startswith(("https://", "http://")) else None,
                "server": server.as_dict(),
            }
        )

    async def _wardogs_join_page(self, request: web.Request) -> web.Response:
        try:
            server = await self._wardogs_service().get_server()
        except WardogsUnavailable as exc:
            body = f"<h1>Сервер пока не виден</h1><p>{html.escape(str(exc))}</p><p>Попробуй обновить страницу через пару минут.</p>"
            return web.Response(text=self._wardogs_page_html(body), content_type="text/html", status=503)

        safe_name = html.escape(server.name)
        safe_join_id = html.escape(server.join_id)
        custom_url = self.bot.config.wardogs_join_url
        launch = ""
        if custom_url and custom_url.startswith(("https://", "http://")):
            launch = f'<a class="primary" href="{html.escape(custom_url, quote=True)}">Запустить подключение</a>'
        body = f"""
          <span class="eyebrow">АСУНА ЮКИ · LIVE</span>
          <h1>Заходи в WARDOGS</h1>
          <p class="server">{safe_name}</p>
          <div class="stats">
            <b>{server.players}/{server.max_players}</b>
            <span>{html.escape(server.map_name)}</span>
            <span>{html.escape(server.region)}</span>
          </div>
          <label>JOIN ID</label>
          <button class="code" data-code="{safe_join_id}"
            onclick="navigator.clipboard.writeText(this.dataset.code);
              this.querySelector('small').textContent='Скопировано ✓'">
            <strong>{safe_join_id}</strong><small>Нажми, чтобы скопировать</small>
          </button>
          <div class="actions">{launch}<a href="https://store.steampowered.com/app/1867240/WARDOGS/">Открыть WARDOGS в Steam</a></div>
          <p class="hint">В игре открой браузер серверов → <b>Join By ID</b> → вставь скопированный код.</p>
        """
        return web.Response(text=self._wardogs_page_html(body), content_type="text/html")

    @staticmethod
    def _wardogs_page_html(body: str) -> str:
        return f"""<!doctype html>
        <html lang="ru"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>WARDOGS · Асуна Юки</title><style>
        *{{box-sizing:border-box}}
        body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;
          background:radial-gradient(circle at 20% 10%,#342365 0,transparent 38%),
          radial-gradient(circle at 90% 90%,#173e54 0,transparent 40%),#090a12;
          color:#f7f5ff;font:16px system-ui,sans-serif}}
        main{{width:min(680px,100%);padding:clamp(28px,7vw,64px);border:1px solid #ffffff1d;
          border-radius:30px;background:#11131fd9;box-shadow:0 28px 90px #0008;backdrop-filter:blur(20px)}}
        .eyebrow{{color:#a78bfa;font-size:12px;font-weight:800;letter-spacing:.18em}}
        h1{{margin:12px 0 8px;font-size:clamp(38px,8vw,68px);line-height:.95}}
        p.server{{color:#c8c4d8;font-size:18px}}
        .stats{{display:flex;gap:10px;flex-wrap:wrap;margin:24px 0}}
        .stats>*{{padding:9px 13px;border-radius:999px;background:#ffffff0c;border:1px solid #ffffff12}}
        label{{display:block;margin:28px 0 9px;color:#8d87a3;font-size:12px;font-weight:800;letter-spacing:.14em}}
        button.code{{width:100%;padding:20px;text-align:left;color:#fff;border:1px solid #8b5cf655;
          border-radius:18px;background:#7c3aed1f;cursor:pointer}}
        button.code strong{{display:block;overflow-wrap:anywhere;font:700 clamp(16px,4vw,22px) ui-monospace,monospace}}
        button.code small{{display:block;margin-top:8px;color:#b9acd8}}
        .actions{{display:flex;gap:12px;flex-wrap:wrap;margin-top:18px}}
        a{{padding:13px 17px;border:1px solid #ffffff1d;border-radius:13px;color:#e9e5f5;text-decoration:none}}
        a.primary{{border:0;background:linear-gradient(135deg,#8b5cf6,#5b8cff);font-weight:800}}
        .hint{{margin:24px 0 0;color:#938ca8;line-height:1.55}}
        </style></head><body><main>{body}</main></body></html>"""

    def _inject_panel_bootstrap(self, html: str) -> str:
        token = "" if self._password_auth else (self._static_token or "")
        html = html.replace("__PANEL_TOKEN__", token)
        html = html.replace("__PANEL_LOGIN__", "1" if self._password_auth else "0")
        html = html.replace("__PANEL_OAUTH__", "1" if self._oauth_enabled else "0")
        return html

    def _load_index_html(self) -> str:
        """Читает сборку panel-ui (dist/) на каждый запрос, чтобы пересборка
        фронтенда не требовала перезапуска бота."""
        try:
            return _DIST_INDEX_PATH.read_text(encoding="utf-8")
        except OSError:
            return "<!doctype html><title>Панель</title><p>Сборка panel-ui не найдена (dist/index.html).</p>"

    async def _serve_index(self, request: web.Request) -> web.Response:
        html_text = self._inject_panel_bootstrap(self._load_index_html())
        if request.path == "/showcase":
            meta = await self._showcase_meta_tags(request)
            if meta:
                html_text = re.sub(r"(?i)<title>.*?</title>", "", html_text, count=1)
                html_text = html_text.replace("</head>", f"{meta}\n</head>", 1)
        return web.Response(text=html_text, content_type="text/html", charset="utf-8")

    async def _serve_logs_page(self, request: web.Request) -> web.Response:
        html = self._logs_html or "<h1>/logs</h1><p>Файл logs.html не найден.</p>"
        if self._password_auth:
            html = html.replace("__PANEL_TOKEN__", "")
        else:
            html = html.replace("__PANEL_TOKEN__", self._static_token or "")
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def _serve_audit_page(self, request: web.Request) -> web.Response:
        html = self._audit_html or "<h1>/audit</h1><p>Файл audit.html не найден.</p>"
        if self._password_auth:
            html = html.replace("__PANEL_TOKEN__", "")
        else:
            html = html.replace("__PANEL_TOKEN__", self._static_token or "")
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    # --- API: login / status / channels ---

