"""Persistent presentation options for the standalone OBS chat overlay.

The overlay token and Browser Source URL stay unchanged. Settings are stored
in the existing KV repository (PostgreSQL in production).
"""
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.kv_service import KvService

CHAT_SETTINGS_KEY = "overlay:chat:settings"
CHAT_PAUSED_KEY = "overlay:chat:paused"
DEFAULT_CHAT_SETTINGS: dict[str, Any] = {
    "size": 17,
    "limit": 15,
    "idle": 10,
    "gap": 6,
    "padding": 12,
    "opacity": 82,
    "theme": "minimal",
    "font": "system",
    "text_color": "#f7f5ee",
    "accent_color": "#b9a47a",
    "show_platform": False,
    "enabled_platforms": ["twitch", "kick", "youtube"],
    "hidden_users": [],
    "blocked_words": [],
}
_HEX = re.compile(r"#[0-9a-fA-F]{6}\Z")
_THEMES = frozenset({"minimal", "radio", "glass"})
_FONTS = frozenset({"system", "mono"})
_PLATFORMS = ("twitch", "kick", "youtube")


def _number(value: Any, lo: int, hi: int, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        number = int(value)
    except (ValueError, TypeError, OverflowError):
        return fallback
    return min(hi, max(lo, number))


def _color(value: Any, fallback: str) -> str:
    return value.lower() if isinstance(value, str) and _HEX.fullmatch(value) else fallback


def _terms(value: Any, *, max_len: int) -> list[str]:
    """Normalize small literal blocklists; never interpret as patterns."""
    if isinstance(value, str):
        items = re.split(r"[,;\\n]", value)
    elif isinstance(value, list):
        items = value
    else:
        return []
    result: list[str] = []
    for entry in items[:60]:
        if not isinstance(entry, str):
            continue
        term = " ".join(entry.split()).casefold()[:max_len]
        if term and term not in result:
            result.append(term)
            if len(result) >= 20:
                break
    return result


def _enabled_platforms(value: Any) -> list[str]:
    if not isinstance(value, list):
        return list(_PLATFORMS)
    return [platform for platform in _PLATFORMS if platform in value]


def filter_chat_messages(
    messages: Sequence[dict[str, Any]],
    settings: dict[str, Any] | None,
    *,
    paused: bool = False,
) -> list[dict[str, Any]]:
    """Overlay-only safety filters; Twitch and Kick messages are untouched."""
    if paused:
        return []
    if settings is None:
        return list(messages)
    enabled = set(settings.get("enabled_platforms", _PLATFORMS))
    hidden = set(settings.get("hidden_users", []))
    blocked = settings.get("blocked_words", [])
    return [
        item
        for item in messages
        if item.get("platform") in enabled
        and str(item.get("name") or "").casefold() not in hidden
        and not any(word in str(item.get("text") or "").casefold() for word in blocked)
    ]


async def get_chat_paused(kv: KvService) -> bool:
    return await kv.get(CHAT_PAUSED_KEY) == "1"


async def set_chat_paused(kv: KvService, paused: bool) -> None:
    await kv.set(CHAT_PAUSED_KEY, "1" if paused else "0")


def sanitize_chat_settings(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    defaults = DEFAULT_CHAT_SETTINGS
    theme = data.get("theme")
    font = data.get("font")
    platform = data.get("show_platform")
    return {
        "size": _number(data.get("size"), 11, 44, defaults["size"]),
        "limit": _number(data.get("limit"), 1, 80, defaults["limit"]),
        "idle": _number(data.get("idle"), 0, 600, defaults["idle"]),
        "gap": _number(data.get("gap"), 0, 20, defaults["gap"]),
        "padding": _number(data.get("padding"), 0, 32, defaults["padding"]),
        "opacity": _number(data.get("opacity"), 0, 100, defaults["opacity"]),
        "theme": theme if theme in _THEMES else defaults["theme"],
        "font": font if font in _FONTS else defaults["font"],
        "text_color": _color(data.get("text_color"), defaults["text_color"]),
        "accent_color": _color(data.get("accent_color"), defaults["accent_color"]),
        "show_platform": platform if isinstance(platform, bool) else defaults["show_platform"],
        "enabled_platforms": _enabled_platforms(data.get("enabled_platforms")),
        "hidden_users": _terms(data.get("hidden_users"), max_len=32),
        "blocked_words": _terms(data.get("blocked_words"), max_len=40),
    }


async def load_chat_settings(kv: KvService) -> dict[str, Any] | None:
    """None means no saved settings: old ?size/limit/idle URLs remain effective."""
    raw = await kv.get(CHAT_SETTINGS_KEY)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return sanitize_chat_settings(parsed)


async def save_chat_settings(kv: KvService, data: Any) -> dict[str, Any]:
    clean = sanitize_chat_settings(data)
    await kv.set(CHAT_SETTINGS_KEY, json.dumps(clean, ensure_ascii=False, separators=(",", ":")))
    return clean
