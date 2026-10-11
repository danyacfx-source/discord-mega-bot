"""Загрузка, список и удаление изображений для эмбедов."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from aiohttp import web

from app.core.webpanel.base_api import _BaseApi
from app.core.webpanel.payload import (
    _MAGIC,
    _MAX_UPLOAD_BYTES,
    _UPLOAD_EXTS,
    _UPLOAD_NAME_RE,
)


class _UploadsApiMixin(_BaseApi):
    """Загрузка, список и удаление изображений для эмбедов."""

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
        signatures = _MAGIC.get(ext, ())
        if not signatures or not any(data[: len(sig)] == sig for sig in signatures):
            return self._json({"ok": False, "error": "Содержимое не соответствует типу файла"}, status=400)
        if ext == ".webp" and data[8:12] != b"WEBP":
            return self._json({"ok": False, "error": "Содержимое не соответствует типу файла"}, status=400)
        self._uploads_dir.mkdir(parents=True, exist_ok=True)
        name = uuid.uuid4().hex + ext
        (self._uploads_dir / name).write_bytes(data)
        base = self._public_base(request)
        return self._json({"ok": True, "name": name, "url": f"/uploads/{name}", "absolute_url": f"{base}/uploads/{name}"})

    async def _api_uploads_list(self, request: web.Request) -> web.Response:
        files: list[dict[str, Any]] = []
        if self._uploads_dir.is_dir():
            for path in sorted(self._uploads_dir.iterdir(), key=lambda p: p.stat().st_mtime if p.is_file() else 0, reverse=True):
                if not path.is_file() or _UPLOAD_NAME_RE.match(path.name) is None:
                    continue
                size = path.stat().st_size
                files.append(
                    {
                        "name": path.name,
                        "url": f"/uploads/{path.name}",
                        "size": self._human_size(size),
                        "bytes": size,
                    }
                )
        return self._json({"ok": True, "count": len(files), "files": files})

    async def _api_uploads_delete(self, request: web.Request) -> web.Response:
        name = request.match_info.get("name", "")
        if _UPLOAD_NAME_RE.match(name) is None:
            return self._json({"ok": False, "error": "Некорректное имя файла"}, status=400)
        path = self._uploads_dir / name
        if not path.is_file():
            return self._json({"ok": False, "error": "Файл не найден"}, status=404)
        path.unlink(missing_ok=True)
        return self._json({"ok": True})

    @staticmethod
    def _human_size(size: int) -> str:
        if size < 1024:
            return f"{size} Б"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} КБ"
        return f"{size / 1024 / 1024:.1f} МБ"

    @staticmethod
    def _public_base(request: web.Request) -> str:
        proto = request.headers.get("X-Forwarded-Proto") or request.scheme
        return f"{proto}://{request.host}"
