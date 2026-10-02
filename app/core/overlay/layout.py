"""Раскладки оверлея: схема, валидация и хранение в KV (конструктор в вебпанели).

KV-ключи:
    overlay:layouts      — индекс [{id, name}, ...]
    overlay:layout:{id}  — тело раскладки {id, name, width, height, widgets: [...]}
"""
from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.kv_service import KvService

LAYOUTS_KEY = "overlay:layouts"
_PREFIX = "overlay:layout:"

WIDGET_TYPES = ("stream", "goal", "donation", "slots", "poll", "chat_top", "chat", "countdown", "text", "image")
CANVAS_PRESETS: tuple[tuple[int, int], ...] = ((1920, 1080), (1280, 720), (800, 600), (420, 720))
MAX_WIDGETS = 30

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_SAFE_ID = re.compile(r"^[a-z0-9_-]{1,32}$")
_ALIGNS = ("left", "center", "right")

_DEFAULT_TITLES = {
    "donation": "Последний донат",
    "slots": "Последний выигрыш",
    "poll": "Последний опрос",
    "goal": "Донат-цель",
    "chat_top": "Топ чата",
}


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def _hex(value: object, default: str = "") -> str:
    return value if isinstance(value, str) and _HEX.match(value) else default


def _text(value: object, default: str, limit: int) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()[:limit]
    return default


def _num(value: object, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _props(widget_type: str, raw: object) -> dict[str, Any]:
    """Белый список свойств виджета: мусор молча деградирует к дефолтам."""
    data = raw if isinstance(raw, dict) else {}
    base: dict[str, Any] = {"bg": _hex(data.get("bg")), "radius": _num(data.get("radius"), 0, 48, 14)}
    if widget_type == "text":
        align = data.get("align")
        return {
            **base,
            "text": _text(data.get("text"), "Новый текст", 300),
            "size": _num(data.get("size"), 10, 120, 36),
            "color": _hex(data.get("color"), "#ffffff"),
            "align": align if align in _ALIGNS else "left",
            "bold": bool(data.get("bold")),
        }
    if widget_type == "image":
        url = data.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://", "/uploads/", "/overlay")):
            url = ""
        return {**base, "url": url[:500]}
    if widget_type == "countdown":
        return {
            **base,
            "label": _text(data.get("label"), "До стрима", 80),
            "date": _text(data.get("date"), "", 40),
            "color": _hex(data.get("color"), "#ff5a36"),
        }
    if widget_type == "chat_top":
        return {**base, "title": _text(data.get("title"), _DEFAULT_TITLES["chat_top"], 80), "limit": _num(data.get("limit"), 1, 10, 3)}
    if widget_type == "chat":
        return {**base, "title": _text(data.get("title"), "Лента чата", 80), "limit": _num(data.get("limit"), 1, 25, 10)}
    if widget_type == "stream":
        return {**base, "title": _text(data.get("title"), "", 80)}
    if widget_type in _DEFAULT_TITLES:
        return {**base, "title": _text(data.get("title"), _DEFAULT_TITLES[widget_type], 80)}
    return base


def sanitize_layout(raw: object, *, layout_id: str | None = None) -> dict[str, Any]:
    """Нормализует присланный JSON к безопасной схеме раскладки."""
    data = raw if isinstance(raw, dict) else {}
    width = _num(data.get("width"), 320, 3840, 1920)
    height = _num(data.get("height"), 240, 2160, 1080)
    identifier = layout_id or ""
    if not _SAFE_ID.match(str(data.get("id") or "")):
        identifier = identifier or new_id()
    else:
        identifier = str(data["id"]) if not identifier else identifier
    widgets_raw = data.get("widgets")
    widgets: list[dict[str, Any]] = []
    if isinstance(widgets_raw, list):
        for item in widgets_raw[:MAX_WIDGETS]:
            if not isinstance(item, dict) or item.get("type") not in WIDGET_TYPES:
                continue
            widget_id = item.get("id")
            widget_id = str(widget_id) if isinstance(widget_id, str) and _SAFE_ID.match(str(widget_id)) else new_id()
            box_w = _num(item.get("w"), 40, width, 320)
            box_h = _num(item.get("h"), 30, height, 140)
            x = _num(item.get("x"), 0, max(0, width - box_w), 0)
            y = _num(item.get("y"), 0, max(0, height - box_h), 0)
            widgets.append(
                {
                    "id": widget_id,
                    "type": item["type"],
                    "x": x,
                    "y": y,
                    "w": box_w,
                    "h": box_h,
                    "props": _props(str(item["type"]), item.get("props")),
                }
            )
    return {
        "id": identifier,
        "name": _text(data.get("name"), "Раскладка", 60),
        "width": width,
        "height": height,
        "widgets": widgets,
    }


def default_layout(layout_id: str) -> dict[str, Any]:
    """Стартовая раскладка для нового оверлея: стрим, цель, донат, топ чата."""
    return sanitize_layout(
        {
            "id": layout_id,
            "name": "Основная",
            "widgets": [
                {"id": "stream", "type": "stream", "x": 40, "y": 40, "w": 560, "h": 190},
                {"id": "goal", "type": "goal", "x": 40, "y": 250, "w": 560, "h": 150},
                {"id": "donation", "type": "donation", "x": 40, "y": 420, "w": 270, "h": 150},
                {"id": "chat_top", "type": "chat_top", "x": 330, "y": 420, "w": 270, "h": 150},
            ],
        },
        layout_id=layout_id,
    )


# ------------------------------------------------------------------ KV-доступ

async def list_layouts(kv: KvService) -> list[dict[str, str]]:
    try:

        raw = await kv.get(LAYOUTS_KEY)
        parsed = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        parsed = []
    if not isinstance(parsed, list):
        return []
    return [
        {"id": str(item["id"]), "name": str(item.get("name") or item["id"])[:60]}
        for item in parsed
        if isinstance(item, dict) and _SAFE_ID.match(str(item.get("id") or ""))
    ]


async def save_layouts(kv: KvService, layouts: list[dict[str, str]]) -> None:

    await kv.set(LAYOUTS_KEY, json.dumps(layouts, ensure_ascii=False))


async def load_layout(kv: KvService, layout_id: str) -> dict[str, Any] | None:
    if not _SAFE_ID.match(layout_id):
        return None
    try:

        raw = await kv.get(_PREFIX + layout_id)
        if not raw:
            return None
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return sanitize_layout(parsed, layout_id=layout_id)


async def save_layout(kv: KvService, layout: dict[str, Any]) -> dict[str, Any]:

    clean = sanitize_layout(layout, layout_id=str(layout.get("id") or ""))
    await kv.set(_PREFIX + clean["id"], json.dumps(clean, ensure_ascii=False))
    return clean


async def delete_layout(kv: KvService, layout_id: str) -> bool:
    if not _SAFE_ID.match(layout_id):
        return False
    layouts = await list_layouts(kv)
    remaining = [item for item in layouts if item["id"] != layout_id]
    if len(remaining) == len(layouts):
        return False
    await save_layouts(kv, remaining)
    await kv.delete(_PREFIX + layout_id)
    return True
