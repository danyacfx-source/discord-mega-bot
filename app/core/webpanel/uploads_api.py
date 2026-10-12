"""Загрузка, список и удаление изображений.

Хранилище — таблица media_files в БД: контейнер при редеплое Bothost удаляется
целиком, поэтому файлы на FS контейнера не переживали пересоздание. FS-каталог
data/uploads остаётся только read-fallback'ом для файлов, загруженных до
перехода (импорт в БД происходит при первом же запросе).
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
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
from app.db.media_files_repository import MediaFilesRepository

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
_CACHE_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


class _UploadsApiMixin(_BaseApi):
    """Загрузка, список и удаление изображений для эмбедов."""

    def _media_repo(self) -> MediaFilesRepository | None:
        if self.bot.db is None:
            return None
        return MediaFilesRepository(self.bot.db)

    async def _api_upload(self, request: web.Request) -> web.Response:
        repo = self._media_repo()
        if repo is None:
            return self._json({"ok": False, "error": "Хранилище недоступно"}, status=503)
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
        name = uuid.uuid4().hex + ext
        mime = _MIME_BY_EXT.get(ext, "application/octet-stream")
        await repo.put(name, data, mime, len(data), datetime.now(UTC).isoformat(timespec="microseconds"))
        base = self._public_base(request)
        return self._json({"ok": True, "name": name, "url": f"/uploads/{name}", "absolute_url": f"{base}/uploads/{name}"})

    async def _api_uploads_list(self, request: web.Request) -> web.Response:
        repo = self._media_repo()
        if repo is None:
            return self._json({"ok": False, "error": "Хранилище недоступно"}, status=503)
        files: list[dict[str, Any]] = [
            {
                "name": item["name"],
                "url": f"/uploads/{item['name']}",
                "size": self._human_size(item["size"]),
                "bytes": item["size"],
            }
            for item in await repo.list_all()
        ]
        return self._json({"ok": True, "count": len(files), "files": files})

    async def _api_uploads_delete(self, request: web.Request) -> web.Response:
        name = request.match_info.get("name", "")
        if _UPLOAD_NAME_RE.match(name) is None:
            return self._json({"ok": False, "error": "Некорректное имя файла"}, status=400)
        repo = self._media_repo()
        if repo is None:
            return self._json({"ok": False, "error": "Хранилище недоступно"}, status=503)
        deleted = await repo.delete(name)
        # Копия в FS убирается тоже: иначе fallback воскресит её при следующем GET.
        (self._uploads_dir / name).unlink(missing_ok=True)
        if not deleted:
            return self._json({"ok": False, "error": "Файл не найден"}, status=404)
        return self._json({"ok": True})

    async def _serve_upload(self, request: web.Request) -> web.Response:
        """Отдаёт файл из БД; промах — read-fallback в data/uploads (импорт в БД)."""
        name = request.match_info.get("name", "")
        if _UPLOAD_NAME_RE.match(name) is None:
            return web.Response(status=404, text="Not Found")
        repo = self._media_repo()
        if repo is None:
            return web.Response(status=503, text="Storage unavailable")
        stored = await repo.get(name)
        if stored is None:
            path = self._uploads_dir / name
            if not path.is_file():
                return web.Response(status=404, text="Not Found")
            data = path.read_bytes()
            mime = _MIME_BY_EXT.get(Path(name).suffix.lower(), "application/octet-stream")
            await repo.put(name, data, mime, len(data), datetime.now(UTC).isoformat(timespec="microseconds"))
        else:
            data, mime = stored
        return web.Response(body=data, content_type=mime, headers=_CACHE_HEADERS)

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
