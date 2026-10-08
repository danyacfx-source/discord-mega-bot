"""Преобразование payload'ов Discord <-> клиентский JSON для веб-панели.

Бессостоятельный модуль: константы и чистые функции, вынесенные из
``webpanel.py``, чтобы сервис панели не превращался в монолит.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import discord
from aiohttp import web


class _PanelSession(TypedDict):
    expires: float
    role: str
    csrf: str


_PANEL_ROLE_KEY = web.RequestKey("panel_role", str)

_DIST_INDEX_PATH = Path(__file__).parent / "dist" / "index.html"
_LOGS_PAGE_PATH = Path(__file__).parent / "logs.html"
_AUDIT_PAGE_PATH = Path(__file__).parent / "audit.html"
_WEBHOOK_RE = re.compile(r"^https://(?:discord\.com|discordapp\.com)/api/webhooks/(\d+)/([A-Za-z0-9_\-]+)$")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}
_MAX_EMBEDS = 10
_LOGIN_WINDOW = 60.0
_LOGIN_LIMIT = 5
_SESSION_TTL = 24 * 3600
_SESSION_MAX = 2000
_RATE_LIMIT_MAX = 600
_RATE_LIMIT_WINDOW = 60.0
_TOKEN_FILE = ".panel-token"
_UPLOAD_DIRNAME = "uploads"
_UPLOAD_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024
_MAX_REQUEST_BYTES = _MAX_UPLOAD_BYTES + 256 * 1024
_UPLOAD_NAME_RE = re.compile(r"^[0-9a-fA-F]{32}\.(?:png|jpg|jpeg|gif|webp)$")
_MAGIC: dict[str, tuple[bytes, ...]] = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),
}
_CSP_SCRIPT_SRC = "script-src 'self' 'unsafe-inline'"
_CSP_SCRIPT_ATTR = "script-src-attr 'unsafe-inline'"
_CSP_REST = (
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "img-src 'self' data: blob: https: http:; "
    "connect-src 'self'; "
    "font-src 'self' https://fonts.gstatic.com; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)
_CSP = f"default-src 'self'; {_CSP_SCRIPT_SRC}; {_CSP_REST}"
_LOG_RING_SIZE = 2000
_WELCOME_PRESET_KEY = "welcome_preset"

#: Пресеты карточек стримов (см. app.cogs.streams.stream_cards.CARDS_KEY).
_STREAM_CARDS_KEY = "stream:cards"
_CARD_PLATFORMS = ("twitch", "kick", "vk_video")
_CARD_HEX_RE = re.compile(r"#?[0-9a-fA-F]{6}\Z")
_CARD_FIELDS_LIVE = ("viewers", "peak", "duration", "trend", "category", "description")
_CARD_FIELDS_OFFLINE = ("vod", "peak", "duration", "category", "talkers")


def _clean_cards_str(value: Any, limit: int = 200) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:limit]


def _clean_cards_hex(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not _CARD_HEX_RE.fullmatch(text):
        return ""
    return text if text.startswith("#") else f"#{text}"


def _clean_cards_section(raw: Any, field_keys: tuple[str, ...]) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    titles = data.get("titles") if isinstance(data.get("titles"), dict) else {}
    colors = data.get("colors") if isinstance(data.get("colors"), dict) else {}
    fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
    return {
        "titles": {p: t for p in _CARD_PLATFORMS if (t := _clean_cards_str(titles.get(p), 256))},
        "colors": {p: c for p in _CARD_PLATFORMS if (c := _clean_cards_hex(colors.get(p)))},
        "footer": _clean_cards_str(data.get("footer"), 100),
        "fields": {k: v for k in field_keys if (v := _clean_cards_str(fields.get(k), 120))},
    }


def _clean_cards_preset(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "live": _clean_cards_section(raw.get("live"), _CARD_FIELDS_LIVE),
        "offline": _clean_cards_section(raw.get("offline"), _CARD_FIELDS_OFFLINE),
    }
_MAX_COMPONENT_ROWS = 5
_MAX_COMPONENT_PER_ROW = 5
_MAX_BUTTON_LABEL = 80
_BUTTON_STYLES = {1, 2, 3, 4, 5}
_BUTTON_STYLE_BY_INT = {
    1: discord.ButtonStyle.primary,
    2: discord.ButtonStyle.secondary,
    3: discord.ButtonStyle.success,
    4: discord.ButtonStyle.danger,
    5: discord.ButtonStyle.link,
}
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

_TICKET_TEXT_FIELDS = (
    "ticket_panel_title",
    "ticket_panel_description",
    "ticket_panel_footer",
    "ticket_open_label",
    "ticket_open_emoji",
    "ticket_intro_title",
    "ticket_intro_description",
    "ticket_intro_footer",
    "ticket_close_label",
    "ticket_close_emoji",
    "ticket_channel_prefix",
)

_TICKET_DEFAULTS = {
    "ticket_panel_title": "Поддержка",
    "ticket_panel_description": "Нажмите на кнопку, чтобы открыть тикет.",
    "ticket_panel_footer": "Тикеты помогают решать личные вопросы без шума в каналах.",
    "ticket_open_label": "Открыть тикет",
    "ticket_open_emoji": "🎫",
    "ticket_intro_title": "Новый тикет",
    "ticket_intro_description": "Опишите свою проблему, {member}.",
    "ticket_intro_footer": "Нажмите кнопку ниже, чтобы закрыть тикет по завершении.",
    "ticket_close_label": "Закрыть тикет",
    "ticket_close_emoji": "🔒",
    "ticket_channel_prefix": "ticket",
}


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


def _trim_components(raw: Any) -> list[dict[str, Any]]:
    """Нормализует кнопки (components) до формата Discord webhook. Возвращает список ActionRow."""
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for row in (raw or [])[:_MAX_COMPONENT_ROWS]:
        if not isinstance(row, list):
            continue
        buttons: list[dict[str, Any]] = []
        for item in (row or [])[:_MAX_COMPONENT_PER_ROW]:
            if not isinstance(item, dict):
                continue
            try:
                style = int(item.get("style") or 1)
            except (TypeError, ValueError):
                style = 1
            if style not in _BUTTON_STYLES:
                style = 1
            label = str(item.get("label") or "")[:_MAX_BUTTON_LABEL]
            if not label:
                continue
            url = str(item.get("url") or "")[:2048]
            if style == 5:
                if not url.startswith(("https://", "http://")):
                    continue
            else:
                url = ""
            buttons.append({"type": 2, "label": label, "style": style, "url": url})
        if buttons:
            rows.append({"type": 1, "components": buttons})
    return rows


def _view_from_components(raw: Any) -> discord.ui.View | None:
    """Собирает View для отправки через бота. ``None`` — кнопки не трогаем."""
    if raw is None:
        return None
    view = discord.ui.View()
    for row in _trim_components(raw):
        for component in row.get("components", [])[:_MAX_COMPONENT_PER_ROW]:
            style = _BUTTON_STYLE_BY_INT.get(component["style"], discord.ButtonStyle.secondary)
            view.add_item(
                discord.ui.Button(label=component["label"], style=style, url=component.get("url") or None)
            )
    return view


def _components_from_message(message: discord.Message) -> list[list[dict[str, Any]]]:
    rows: list[list[dict[str, Any]]] = []
    for message_view in getattr(message, "components", []) or []:
        row: list[dict[str, Any]] = []
        for component in getattr(message_view, "children", []) or []:
            if isinstance(component, discord.Button):
                row.append(
                    {
                        "label": component.label or "",
                        "style": str(component.style.value if component.style else 1),
                        "url": str(getattr(component, "url", "") or ""),
                    }
                )
        if row:
            rows.append(row)
    return rows


def _components_from_raw(raw: Any) -> list[list[dict[str, Any]]]:
    rows: list[list[dict[str, Any]]] = []
    for action in (raw or [])[:_MAX_COMPONENT_ROWS]:
        if not isinstance(action, dict):
            continue
        row: list[dict[str, Any]] = []
        for component in (action.get("components") or [])[:_MAX_COMPONENT_PER_ROW]:
            if not isinstance(component, dict) or component.get("type") != 2:
                continue
            row.append(
                {
                    "label": str(component.get("label") or ""),
                    "style": str(component.get("style") or 1),
                    "url": str(component.get("url") or ""),
                }
            )
        if row:
            rows.append(row)
    return rows


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
        "components": _components_from_message(message),
    }


def _raw_to_client(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": raw.get("content") or "",
        "embeds": [_raw_embed_to_client(embed) for embed in (raw.get("embeds") or [])[:_MAX_EMBEDS]],
        "components": _components_from_raw(raw.get("components")),
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


def overlay_url_base(config: Any) -> str:
    """База ссылки для OBS: публичный URL (Traefik, без порта) или прямой хост:порт."""
    if not config.overlay_port:
        return ""
    public = (config.overlay_public_url or "").strip().rstrip("/")
    if public:
        return public
    host = (config.overlay_host or "").strip()
    if host in ("", "0.0.0.0", "::"):
        return ""
    return f"http://{host}:{config.overlay_port}"

