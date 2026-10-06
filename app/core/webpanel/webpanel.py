"""Вебпанель конструктора эмбедов: браузерный редактор, отправка через бота и прокси вебхуков."""
from __future__ import annotations

import logging
import re
import secrets
import time
import tracemalloc
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import aiohttp
import discord
from aiohttp import web

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.webpanel")

_INDEX_PATH = Path(__file__).parent / "index.html"
_WEBHOOK_RE = re.compile(r"^https://(?:discord\.com|discordapp\.com)/api/webhooks/(\d+)/([A-Za-z0-9_\-]+)$")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}
_MAX_EMBEDS = 10
_LOGIN_WINDOW = 60.0
_LOGIN_LIMIT = 5
_SESSION_TTL = 24 * 3600
_TOKEN_FILE = ".panel-token"
_UPLOAD_DIRNAME = "uploads"
_UPLOAD_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024
_WARDOGS_CATEGORY_ID = 1534711415883956284
_WARDOGS_ROLE_NAME = "Wardogs"
_EDITABLE_PERMISSION_NAMES = (
    "view_channel",
    "send_messages",
    "read_message_history",
    "connect",
    "speak",
    "attach_files",
    "embed_links",
    "add_reactions",
    "send_messages_in_threads",
)
_SETTING_COLUMNS = (
    "welcome_channel_id",
    "farewell_channel_id",
    "log_channel_id",
    "ticket_category_id",
    "member_log_channel_id",
    "message_log_channel_id",
    "voice_log_channel_id",
    "mod_log_channel_id",
    "bot_log_channel_id",
    "donation_channel_id",
)


def _trim_embeds(raw: Any) -> list[dict[str, Any]]:
    """Обрезает эмбеды до лимитов Discord для отправки (webhook-режим)."""
    trimmed: list[dict[str, Any]] = []
    for item in (raw or [])[:_MAX_EMBEDS]:
        if not isinstance(item, dict):
            continue
        entry: dict[str, Any] = {}
        if item.get("title"):
            entry["title"] = str(item["title"])[:256]
        if item.get("description"):
            entry["description"] = str(item["description"])[:4000]
        color = item.get("color")
        if color is not None:
            try:
                entry["color"] = int(color) & 0xFFFFFF
            except (TypeError, ValueError):
                pass
        author = item.get("author")
        if isinstance(author, dict) and author.get("name"):
            author_entry: dict[str, Any] = {"name": str(author["name"])[:256]}
            if author.get("icon_url"):
                author_entry["icon_url"] = str(author["icon_url"])[:2048]
            if author.get("url"):
                author_entry["url"] = str(author["url"])[:2048]
            entry["author"] = author_entry
        footer = item.get("footer")
        if isinstance(footer, dict) and footer.get("text"):
            footer_entry: dict[str, Any] = {"text": str(footer["text"])[:2048]}
            if footer.get("icon_url"):
                footer_entry["icon_url"] = str(footer["icon_url"])[:2048]
            entry["footer"] = footer_entry
        if item.get("thumbnail"):
            entry["thumbnail"] = {"url": str(item["thumbnail"].get("url", ""))[:2048]}
        if item.get("image"):
            entry["image"] = {"url": str(item["image"].get("url", ""))[:2048]}
        timestamp = item.get("timestamp")
        if timestamp:
            entry["timestamp"] = str(timestamp)[:64]
        fields = []
        for field in (item.get("fields") or [])[:25]:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            fields.append(
                {
                    "name": str(field["name"])[:256],
                    "value": str(field.get("value") or "")[:1024],
                    "inline": bool(field.get("inline", False)),
                }
            )
        if fields:
            entry["fields"] = fields
        if entry:
            trimmed.append(entry)
    return trimmed


def _embed_from_dict(data: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed()
    if data.get("title"):
        embed.title = str(data["title"])[:256]
    if data.get("description"):
        embed.description = str(data["description"])[:4000]
    color = data.get("color")
    if color is not None:
        try:
            embed.color = int(color) & 0xFFFFFF
        except (TypeError, ValueError):
            pass
    author = data.get("author")
    if isinstance(author, dict) and author.get("name"):
        embed.set_author(
            name=str(author["name"])[:256],
            url=str(author.get("url") or "")[:2048] or None,
            icon_url=str(author.get("icon_url") or "")[:2048] or None,
        )
    footer = data.get("footer")
    if isinstance(footer, dict) and footer.get("text"):
        embed.set_footer(
            text=str(footer["text"])[:2048],
            icon_url=str(footer.get("icon_url") or "")[:2048] or None,
        )
    if data.get("thumbnail"):
        embed.set_thumbnail(url=str(data["thumbnail"].get("url", ""))[:2048])
    if data.get("image"):
        embed.set_image(url=str(data["image"].get("url", ""))[:2048])
    timestamp = data.get("timestamp")
    if timestamp:
        try:
            embed.timestamp = datetime.fromisoformat(str(timestamp)[:64].replace("Z", "+00:00"))
        except ValueError:
            embed.timestamp = datetime.now(UTC)
    for field in (data.get("fields") or [])[:25]:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "")[:256]
        if not name:
            continue
        embed.add_field(name=name, value=str(field.get("value") or "")[:1024], inline=bool(field.get("inline", False)))
    return embed


def _embed_to_client(embed: discord.Embed) -> dict[str, Any]:
    author = {"name": embed.author.name, "icon_url": embed.author.icon_url, "url": embed.author.url} if embed.author.name else {}
    footer = {"text": embed.footer.text, "icon_url": embed.footer.icon_url} if embed.footer.text else {}
    return {
        "title": embed.title or "",
        "description": embed.description or "",
        "color": embed.color.value if getattr(embed.color, "value", None) is not None else None,
        "author": author,
        "footer": footer,
        "thumbnail": {"url": embed.thumbnail.url} if embed.thumbnail else {},
        "image": {"url": embed.image.url} if embed.image else {},
        "timestamp": embed.timestamp.isoformat() if embed.timestamp else None,
        "fields": [{"name": f.name, "value": f.value, "inline": f.inline} for f in embed.fields[:25]],
    }


def _message_to_client(message: discord.Message) -> dict[str, Any]:
    return {
        "content": message.content or "",
        "embeds": [_embed_to_client(embed) for embed in message.embeds[:_MAX_EMBEDS]],
    }


def _raw_to_client(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": raw.get("content") or "",
        "embeds": [_raw_embed_to_client(embed) for embed in (raw.get("embeds") or [])[:_MAX_EMBEDS]],
    }


def _raw_embed_to_client(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": entry.get("title") or "",
        "description": entry.get("description") or "",
        "color": entry.get("color"),
        "author": entry.get("author") or {},
        "footer": entry.get("footer") or {},
        "thumbnail": entry.get("thumbnail") or {},
        "image": entry.get("image") or {},
        "timestamp": entry.get("timestamp"),
        "fields": [
            {"name": field.get("name") or "", "value": field.get("value") or "", "inline": bool(field.get("inline"))}
            for field in (entry.get("fields") or [])[:25]
        ],
    }


class WebPanel:
    def __init__(self, bot: MegaBot) -> None:
        self.bot = bot
        config = bot.config
        assert config.panel_port is not None
        self.host = config.panel_host or "127.0.0.1"
        self.port = config.panel_port
        self.password = config.panel_password
        self.public_url = config.panel_public_url
        self._uploads_dir = Path(config.db_path).parent / _UPLOAD_DIRNAME
        self._index_html = _INDEX_PATH.read_text(encoding="utf-8")
        self._static_token: str | None = None if self.password else self._load_static_token()
        self._sessions: dict[str, float] = {}
        self._login_attempts: dict[str, deque[float]] = defaultdict(deque)
        self._runner: web.AppRunner | None = None
        self._http: aiohttp.ClientSession | None = None

    # --- жизненный цикл ---

    def _load_static_token(self) -> str:
        path = Path(self.bot.config.db_path).parent / _TOKEN_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
        token = secrets.token_urlsafe(32)
        path.write_text(token, encoding="utf-8")
        return token

    def _create_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self._redirect_index)
        app.router.add_get("/admin", self._serve_index)
        app.router.add_get("/admin/", self._serve_index)
        app.router.add_get("/admin/embed-constructor", self._serve_index)
        app.router.add_post("/api/login", self._api_login)
        app.router.add_get("/api/status", self._authorized(self._api_status))
        app.router.add_get("/api/overview", self._authorized(self._api_overview))
        app.router.add_get("/api/settings", self._authorized(self._api_settings_get))
        app.router.add_post("/api/settings", self._authorized(self._api_settings_post))
        app.router.add_get("/api/server", self._authorized(self._api_server_get))
        app.router.add_post("/api/server/permissions", self._authorized(self._api_permissions_post))
        app.router.add_post("/api/server/wardogs", self._authorized(self._api_wardogs_post))
        app.router.add_post("/api/upload", self._authorized(self._api_upload))
        self._uploads_dir.mkdir(parents=True, exist_ok=True)
        app.router.add_static("/uploads", str(self._uploads_dir), show_index=False)
        app.router.add_get("/api/bot/channels", self._authorized(self._api_bot_channels))
        app.router.add_post("/api/bot/send", self._authorized(self._api_bot_send))
        app.router.add_post("/api/bot/edit", self._authorized(self._api_bot_edit))
        app.router.add_post("/api/bot/fetch", self._authorized(self._api_bot_fetch))
        app.router.add_post("/api/webhook/send", self._authorized(self._api_webhook_send))
        app.router.add_post("/api/webhook/edit", self._authorized(self._api_webhook_edit))
        app.router.add_post("/api/webhook/fetch", self._authorized(self._api_webhook_fetch))
        return app

    async def start(self) -> None:
        if self._runner is not None:
            return
        self._http = aiohttp.ClientSession()
        runner = web.AppRunner(self._create_app())
        await runner.setup()
        await web.TCPSite(runner, self.host, self.port).start()
        self._runner = runner
        logger.info("Вебпанель запущена: http://%s:%d/admin", self.host, self.port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        if self._http is not None:
            await self._http.close()
            self._http = None

    # --- авторизация и origin ---

    def _authorized(self, handler):
        async def wrapped(request: web.Request) -> web.Response:
            if not self._allowed_origin(request) or not self._check_token(request):
                return self._json({"ok": False, "error": "Unauthorized"}, status=401)
            return await handler(request)

        return wrapped

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

    def _check_token(self, request: web.Request) -> bool:
        token = request.headers.get("X-Panel-Token", "")
        if not token:
            return False
        if self.password is None:
            return bool(self._static_token) and token == self._static_token
        now = time.time()
        self._sessions = {saved: expires for saved, expires in self._sessions.items() if expires > now}
        return token in self._sessions

    @staticmethod
    def _json(data: dict[str, Any], status: int = 200) -> web.Response:
        return web.json_response(data, status=status)

    # --- страницы ---

    async def _redirect_index(self, request: web.Request) -> web.Response:
        raise web.HTTPFound("/admin")

    async def _serve_index(self, request: web.Request) -> web.Response:
        html = self._index_html
        if self.password:
            html = html.replace("__PANEL_TOKEN__", "").replace("__PANEL_LOGIN__", "true")
        else:
            html = html.replace("__PANEL_TOKEN__", self._static_token or "").replace("__PANEL_LOGIN__", "false")
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    # --- API: login / status / channels ---

    async def _api_login(self, request: web.Request) -> web.Response:
        if not self.password:
            return self._json({"ok": False, "error": "Пароль не настроен"}, status=400)
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
        if payload.get("password") != self.password:
            attempts.append(now)
            return self._json({"ok": False, "error": "Неверный пароль"}, status=401)
        token = secrets.token_urlsafe(32)
        self._sessions[token] = now + _SESSION_TTL
        return self._json({"ok": True, "token": token})

    async def _api_status(self, request: web.Request) -> web.Response:
        online = self.bot.is_ready() and self.bot.user is not None
        data: dict[str, Any] = {"bot_online": online}
        if online:
            data["bot_name"] = self.bot.user.name  # type: ignore[union-attr]
        if self.bot.guilds:
            data["guild_name"] = self.bot.guilds[0].name
        return self._json(data)

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

    def _role_options(self, guild: discord.Guild) -> list[dict[str, Any]]:
        """Возвращает только роли, которыми бот может управлять."""
        me = guild.me
        top_position = me.top_role.position if me is not None else 0
        roles = [
            role
            for role in guild.roles
            if not role.is_default() and role.position < top_position
        ]
        roles.sort(key=lambda role: (-role.position, role.name.casefold()))
        return [
            {
                "id": str(role.id),
                "name": role.name,
                "position": role.position,
                "color": str(role.color),
                "mentionable": role.mentionable,
            }
            for role in roles
        ]

    def _server_categories(self, guild: discord.Guild) -> list[dict[str, Any]]:
        categories: list[dict[str, Any]] = []
        for category in sorted(guild.categories, key=lambda item: item.name.casefold()):
            categories.append(
                {
                    "id": str(category.id),
                    "name": category.name,
                    "position": category.position,
                    "channels": [
                        {
                            "id": str(channel.id),
                            "name": channel.name,
                            "type": "voice" if isinstance(channel, discord.VoiceChannel) else "text",
                        }
                        for channel in sorted(category.channels, key=lambda item: item.position)
                    ],
                }
            )
        return categories

    @staticmethod
    def _permission_state(overwrite: discord.PermissionOverwrite) -> dict[str, bool | None]:
        return {name: getattr(overwrite, name) for name in _EDITABLE_PERMISSION_NAMES}

    def _role_overwrite(self, category: discord.CategoryChannel, role: discord.Role) -> dict[str, bool | None]:
        overwrite = category.overwrites_for(role)
        return self._permission_state(overwrite)

    def _resolve_editable_role(self, guild: discord.Guild, role_id: Any) -> discord.Role | None:
        try:
            role = guild.get_role(int(role_id))
        except (TypeError, ValueError):
            return None
        me = guild.me
        if role is None or role.is_default() or me is None or role.position >= me.top_role.position:
            return None
        return role

    def _resolve_category(self, guild: discord.Guild, category_id: Any) -> discord.CategoryChannel | None:
        try:
            channel = guild.get_channel(int(category_id))
        except (TypeError, ValueError):
            return None
        return channel if isinstance(channel, discord.CategoryChannel) else None

    async def _api_overview(self, request: web.Request) -> web.Response:
        bot = self.bot
        online = bot.is_ready() and bot.user is not None
        data: dict[str, Any] = {"ok": True, "bot_online": online}
        if online:
            data["bot_name"] = bot.user.name  # type: ignore[union-attr]
        seconds = int(bot.uptime.total_seconds())
        data["uptime_seconds"] = seconds
        data["uptime"] = self._human_uptime(seconds)
        latency = bot.latency
        data["latency_ms"] = round(latency * 1000) if latency and latency > 0 else 0
        if tracemalloc.is_tracing():
            current, peak = tracemalloc.get_traced_memory()
            data["mem_mb"] = round(current / 1024 / 1024, 1)
            data["mem_peak_mb"] = round(peak / 1024 / 1024, 1)
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
        return self._json(data)

    async def _api_settings_get(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        service = self.bot.services.settings  # type: ignore[union-attr]
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
            }
        )

    async def _api_settings_post(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        payload = await self._read_json(request)
        service = self.bot.services.settings  # type: ignore[union-attr]
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

    async def _api_server_get(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        wardogs_role = discord.utils.get(guild.roles, name=_WARDOGS_ROLE_NAME)
        wardogs_category = guild.get_channel(_WARDOGS_CATEGORY_ID)
        roles = self._role_options(guild)
        editable_roles = [guild.get_role(int(role["id"])) for role in roles]
        categories = self._server_categories(guild)
        for category_data in categories:
            category = self._resolve_category(guild, category_data["id"])
            if category is not None:
                category_data["permission_overwrites"] = {
                    role_data["id"]: self._role_overwrite(category, role)
                    for role_data, role in zip(roles, editable_roles)
                    if role is not None
                }
        return self._json(
            {
                "ok": True,
                "guild": {"id": str(guild.id), "name": guild.name},
                "roles": roles,
                "categories": categories,
                "wardogs": {
                    "role_id": str(wardogs_role.id) if wardogs_role else None,
                    "role_name": _WARDOGS_ROLE_NAME,
                    "category_id": str(_WARDOGS_CATEGORY_ID),
                    "category_name": wardogs_category.name if isinstance(wardogs_category, discord.CategoryChannel) else None,
                    "available": bool(wardogs_role and isinstance(wardogs_category, discord.CategoryChannel)),
                    "permissions": self._role_overwrite(wardogs_category, wardogs_role)
                    if wardogs_role and isinstance(wardogs_category, discord.CategoryChannel)
                    else {},
                },
                "permission_names": list(_EDITABLE_PERMISSION_NAMES),
            }
        )

    async def _set_category_permissions(
        self, guild: discord.Guild, category: discord.CategoryChannel, role: discord.Role, raw_permissions: Any
    ) -> None:
        if not isinstance(raw_permissions, dict):
            raise ValueError("permissions должен быть объектом")
        overwrite = discord.PermissionOverwrite()
        for name in _EDITABLE_PERMISSION_NAMES:
            value = raw_permissions.get(name)
            if value is None:
                value = None
            elif isinstance(value, bool):
                pass
            else:
                raise ValueError(f"Некорректное значение права: {name}")
            setattr(overwrite, name, value)
        await category.set_permissions(role, overwrite=overwrite, reason="Настройка прав через веб-админку")

    async def _api_permissions_post(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        payload = await self._read_json(request)
        role = self._resolve_editable_role(guild, payload.get("role_id"))
        category = self._resolve_category(guild, payload.get("category_id"))
        if role is None:
            return self._json({"ok": False, "error": "Роль не найдена или находится выше роли бота"}, status=400)
        if category is None:
            return self._json({"ok": False, "error": "Категория не найдена"}, status=400)
        me = guild.me
        if me is None or not category.permissions_for(me).manage_channels:
            return self._json({"ok": False, "error": "Боту нужно право Manage Channels в этой категории"}, status=403)
        try:
            await self._set_category_permissions(guild, category, role, payload.get("permissions"))
        except (ValueError, discord.Forbidden, discord.HTTPException) as exc:
            return self._json({"ok": False, "error": str(exc)}, status=400)
        return self._json({"ok": True, "category_id": str(category.id), "role_id": str(role.id)})

    async def _api_wardogs_post(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        role = discord.utils.get(guild.roles, name=_WARDOGS_ROLE_NAME)
        category = self._resolve_category(guild, _WARDOGS_CATEGORY_ID)
        if role is None:
            return self._json({"ok": False, "error": f"Роль «{_WARDOGS_ROLE_NAME}» не найдена"}, status=404)
        if category is None:
            return self._json({"ok": False, "error": f"Категория {_WARDOGS_CATEGORY_ID} не найдена"}, status=404)
        if self._resolve_editable_role(guild, role.id) is None:
            return self._json({"ok": False, "error": "Роль Wardogs находится выше роли бота"}, status=403)
        me = guild.me
        if me is None or not category.permissions_for(me).manage_channels:
            return self._json({"ok": False, "error": "Боту нужно право Manage Channels в этой категории"}, status=403)
        permissions = {
            "view_channel": True,
            "send_messages": True,
            "read_message_history": True,
            "connect": True,
            "speak": True,
            "attach_files": True,
            "embed_links": True,
            "add_reactions": True,
            "send_messages_in_threads": True,
        }
        try:
            await self._set_category_permissions(guild, category, role, permissions)
        except (discord.Forbidden, discord.HTTPException) as exc:
            return self._json({"ok": False, "error": str(exc)}, status=400)
        return self._json({"ok": True, "role": _WARDOGS_ROLE_NAME, "category_id": str(category.id), "permissions": permissions})

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
        self._uploads_dir.mkdir(parents=True, exist_ok=True)
        name = uuid.uuid4().hex + ext
        (self._uploads_dir / name).write_bytes(data)
        base = self._public_base(request)
        return self._json({"ok": True, "name": name, "url": f"/uploads/{name}", "absolute_url": f"{base}/uploads/{name}"})

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

    # --- API: прокси вебхуков ---

    @staticmethod
    def _parse_id(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _webhook_base(self, url: Any) -> str | None:
        match = _WEBHOOK_RE.match(str(url or ""))
        if match is None:
            return None
        return f"https://discord.com/api/webhooks/{match.group(1)}/{match.group(2)}"

    async def _read_json(self, request: web.Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _webhook_body(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "content": str(payload.get("content") or "")[:2000] or "",
            "embeds": _trim_embeds(payload.get("embeds")),
            "allowed_mentions": {"parse": []},
        }

    async def _api_webhook_send(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        base = self._webhook_base(payload.get("webhook_url"))
        if base is None:
            return self._json({"ok": False, "error": "Неверный Webhook URL"}, status=400)
        async with self._require_http().post(f"{base}?wait=true", json=self._webhook_body(payload)) as response:
            data = await response.json()
            if response.status >= 400:
                return self._json({"ok": False, "error": data.get("message") or str(response.status), "data": data}, status=response.status)
            return self._json({"ok": True, "data": {"id": str(data.get("id"))}})

    async def _api_webhook_edit(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        base = self._webhook_base(payload.get("webhook_url"))
        message_id = self._parse_id(payload.get("message_id"))
        if base is None or message_id is None:
            return self._json({"ok": False, "error": "Неверный Webhook URL или ID сообщения"}, status=400)
        async with self._require_http().patch(f"{base}/messages/{message_id}", json=self._webhook_body(payload)) as response:
            data = await response.json()
            if response.status >= 400:
                return self._json({"ok": False, "error": data.get("message") or str(response.status), "data": data}, status=response.status)
            return self._json({"ok": True, "data": {"id": str(data.get("id"))}})

    async def _api_webhook_fetch(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        base = self._webhook_base(payload.get("webhook_url"))
        message_id = self._parse_id(payload.get("message_id"))
        if base is None or message_id is None:
            return self._json({"ok": False, "error": "Неверный Webhook URL или ID сообщения"}, status=400)
        async with self._require_http().get(f"{base}/messages/{message_id}") as response:
            data = await response.json()
            if response.status >= 400:
                return self._json({"ok": False, "error": data.get("message") or str(response.status), "data": data}, status=response.status)
            return self._json({"ok": True, "data": _raw_to_client(data)})

    def _require_http(self) -> aiohttp.ClientSession:
        if self._http is None:
            self._http = aiohttp.ClientSession()
        return self._http
