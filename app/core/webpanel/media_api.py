"""Медиатека веб-панели: галерея изображений в KV (добавление, лайки, витрина)."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from aiohttp import web

from app.core.webpanel.payload import _PANEL_ROLE_KEY

_MEDIA_KEY = "panel.media.gallery"
_MEDIA_MAX = 500
_TITLE_MAX = 100
_TAGS_MAX = 6
_TAG_RE = re.compile(r"^[\wА-Яа-яЁё №+./-]{1,24}$")


class _MediaApiMixin:
    """Галерея медиатеки хранится одним JSON-документом в KV."""

    async def _gallery_load(self) -> list[dict[str, Any]]:
        raw = await self.services.kv.get(_MEDIA_KEY, "[]")
        try:
            data = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [
            item
            for item in data
            if isinstance(item, dict) and item.get("id") and item.get("url") and item.get("title")
        ]

    async def _gallery_save(self, items: list[dict[str, Any]]) -> None:
        await self.services.kv.set(_MEDIA_KEY, json.dumps(items, ensure_ascii=False))

    @staticmethod
    def _media_type(url: str) -> str:
        clean = url.split("?")[0].lower()
        return "gif" if clean.endswith(".gif") else "image"

    @staticmethod
    def _media_like_key(request: web.Request) -> str:
        token = request.headers.get("X-Panel-Token", "")
        return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _media_tags(raw: Any) -> list[str]:
        if isinstance(raw, str):
            raw = re.split(r"[,\n]+", raw)
        if not isinstance(raw, list):
            return []
        tags: list[str] = []
        for value in raw:
            tag = str(value).strip()
            if _TAG_RE.match(tag) and tag not in tags:
                tags.append(tag)
            if len(tags) >= _TAGS_MAX:
                break
        return tags

    @staticmethod
    def _media_row(item: dict[str, Any], like_key: str) -> dict[str, Any]:
        likers = [str(x) for x in item.get("likers", []) if isinstance(x, str)]
        url = str(item.get("url") or "")
        return {
            "id": str(item.get("id") or ""),
            "title": str(item.get("title") or ""),
            "url": url,
            "type": _MediaApiMixin._media_type(url),
            "tags": [str(t) for t in item.get("tags", []) if isinstance(t, str)],
            "public": bool(item.get("public")),
            "author": str(item.get("author") or ""),
            "created_at": str(item.get("created_at") or ""),
            "likes": len(likers),
            "liked": like_key in likers,
        }

    async def _api_media_list(self, request: web.Request) -> web.Response:
        items = await self._gallery_load()
        like_key = self._media_like_key(request)
        rows = [
            self._media_row(item, like_key)
            for item in sorted(items, key=lambda i: str(i.get("created_at") or ""), reverse=True)
        ]
        return self._json({"ok": True, "items": rows, "count": len(rows)})

    async def _api_media_add(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        url = str(payload.get("url") or "").strip()
        if not url.startswith(("/uploads/", "https://", "http://")):
            return self._json({"ok": False, "error": "Сначала загрузите файл или укажите ссылку"}, status=400)
        title = str(payload.get("title") or "").strip()[:_TITLE_MAX] or "Без названия"
        tags = self._media_tags(payload.get("tags"))
        items = await self._gallery_load()
        if len(items) >= _MEDIA_MAX:
            return self._json({"ok": False, "error": "Галерея заполнена (максимум 500)"}, status=400)
        item = {
            "id": uuid.uuid4().hex[:12],
            "title": title,
            "url": url,
            "tags": tags,
            "public": bool(payload.get("public", True)),
            "author": str(request.get(_PANEL_ROLE_KEY) or ""),
            "created_at": datetime.now(UTC).isoformat(timespec="microseconds"),
            "likers": [],
        }
        items.append(item)
        await self._gallery_save(items)
        return self._json({"ok": True, "item": self._media_row(item, self._media_like_key(request))})

    async def _api_media_like(self, request: web.Request) -> web.Response:
        media_id = request.match_info.get("media_id", "")
        items = await self._gallery_load()
        item = next((entry for entry in items if entry.get("id") == media_id), None)
        if item is None:
            return self._json({"ok": False, "error": "Элемент не найден"}, status=404)
        like_key = self._media_like_key(request)
        likers = [str(x) for x in item.get("likers", []) if isinstance(x, str)]
        if like_key in likers:
            likers.remove(like_key)
            liked = False
        else:
            likers.append(like_key)
            liked = True
        item["likers"] = likers
        await self._gallery_save(items)
        return self._json({"ok": True, "likes": len(likers), "liked": liked})

    async def _api_media_delete(self, request: web.Request) -> web.Response:
        media_id = request.match_info.get("media_id", "")
        items = await self._gallery_load()
        kept = [entry for entry in items if entry.get("id") != media_id]
        if len(kept) == len(items):
            return self._json({"ok": False, "error": "Элемент не найден"}, status=404)
        await self._gallery_save(kept)
        return self._json({"ok": True, "id": media_id})
