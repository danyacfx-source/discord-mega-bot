"""Private persistent editorial/work dashboard for the DENDICH command center.

Items are stored in the bot's KV repository so they survive container restarts.
Read access: moderator+. Writes: admin+ (enforced in routes, including CSRF).
No user supplied text is forwarded to Discord automatically.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from aiohttp import web

from app.core.webpanel.base_api import _BaseApi

logger = logging.getLogger("bot.webpanel")
_BOARD_KEY = "panel.command_center.workboard.v1"
_MAX_ITEMS = 120
_TYPES = {"task", "idea"}
_STATUSES = {"task": {"todo", "doing", "done"}, "idea": {"draft", "ready", "published"}}
_PRIORITIES = {"normal", "high"}


def _clean_text(raw: Any, limit: int) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    return value if 0 < len(value) <= limit else None


def _read_items(raw: str | None) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError):
        logger.warning("Workboard: unreadable stored data")
        return []
    if not isinstance(data, list):
        return []
    return [
        item for item in data[:_MAX_ITEMS]
        if isinstance(item, dict) and item.get("type") in _TYPES
        and isinstance(item.get("id"), str) and isinstance(item.get("title"), str)
    ]


class _WorkboardApiMixin(_BaseApi):
    """CRUD for shared planning notes; no public endpoints."""

    async def _workboard_items(self) -> list[dict[str, Any]]:
        raw = await self.services.kv.get(_BOARD_KEY, "[]")
        return _read_items(raw)

    async def _api_workboard_get(self, request: web.Request) -> web.Response:
        items = await self._workboard_items()
        return self._json({"ok": True, "items": items, "limit": _MAX_ITEMS},
                          status=200)

    async def _api_workboard_write(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        action = payload.get("action")
        if action not in ("create", "update", "delete"):
            return self._json({"ok": False, "error": "Неизвестная операция"}, status=400)

        # Protect read-modify-write from two admins clicking at once.
        async with self._workboard_lock:
            items = await self._workboard_items()
            now = datetime.now(UTC).isoformat(timespec="seconds")
            if action == "create":
                kind = payload.get("type")
                title = _clean_text(payload.get("title"), 120)
                note = payload.get("note", "")
                priority = payload.get("priority", "normal")
                if kind not in _TYPES or title is None:
                    return self._json({"ok": False, "error": "Укажи тип и название (до 120 символов)"}, status=400)
                if not isinstance(note, str) or len(note) > 2000:
                    return self._json({"ok": False, "error": "Описание не должно превышать 2000 символов"}, status=400)
                if priority not in _PRIORITIES:
                    return self._json({"ok": False, "error": "Некорректный приоритет"}, status=400)
                if len(items) >= _MAX_ITEMS:
                    return self._json({"ok": False, "error": "Достигнут лимит записей"}, status=409)
                item: dict[str, Any] = {
                    "id": uuid4().hex, "type": kind, "title": title,
                    "note": note.strip(), "status": "todo" if kind == "task" else "draft",
                    "priority": priority, "created_at": now, "updated_at": now,
                }
                items.insert(0, item)
            else:
                item_id = payload.get("id")
                if not isinstance(item_id, str) or len(item_id) != 32:
                    return self._json({"ok": False, "error": "Неверный ID записи"}, status=400)
                idx = next((i for i, row in enumerate(items) if row["id"] == item_id), -1)
                if idx < 0:
                    return self._json({"ok": False, "error": "Запись не найдена"}, status=404)
                if action == "delete":
                    items.pop(idx)
                else:
                    row = dict(items[idx])
                    if "title" in payload:
                        title = _clean_text(payload["title"], 120)
                        if title is None:
                            return self._json({"ok": False, "error": "Название должно быть от 1 до 120 символов"}, status=400)
                        row["title"] = title
                    if "note" in payload:
                        note = payload["note"]
                        if not isinstance(note, str) or len(note) > 2000:
                            return self._json({"ok": False, "error": "Слишком длинное описание"}, status=400)
                        row["note"] = note.strip()
                    if "status" in payload:
                        if payload["status"] not in _STATUSES[row["type"]]:
                            return self._json({"ok": False, "error": "Некорректный статус"}, status=400)
                        row["status"] = payload["status"]
                    if "priority" in payload:
                        if payload["priority"] not in _PRIORITIES:
                            return self._json({"ok": False, "error": "Некорректный приоритет"}, status=400)
                        row["priority"] = payload["priority"]
                    row["updated_at"] = now
                    items[idx] = row
            await self.services.kv.set(_BOARD_KEY, json.dumps(items, ensure_ascii=False))
            return self._json({"ok": True, "items": items, "limit": _MAX_ITEMS})
