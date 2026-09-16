"""Вебпанель конструктора эмбедов: браузерный редактор, отправка через бота и прокси вебхуков."""
from __future__ import annotations

import logging
import re
import secrets
import time
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
        app.router.add_get("/admin/embed-constructor", self._serve_index)
        app.router.add_post("/api/login", self._api_login)
        app.router.add_get("/api/status", self._authorized(self._api_status))
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
        logger.info("Вебпанель запущена: http://%s:%d/admin/embed-constructor", self.host, self.port)

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
        if self.public_url:
            if urlparse(self.public_url).hostname == host:
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
        raise web.HTTPFound("/admin/embed-constructor")

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
        channels: list[dict[str, Any]] = []
        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                if not channel.permissions_for(guild.me).send_messages:
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
        return self._json({"ok": True, "channels": channels})

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
