"""Файлы загрузок и медиатеки в БД.

Хранение в БД, а не в data/uploads: контейнер при редеплое удаляется целиком,
и файлы на файловой системе контейнера не переживали пересоздание.
"""
from __future__ import annotations

from typing import Any

from app.db.base_repository import BaseRepository


class MediaFilesRepository(BaseRepository):
    async def put(self, name: str, data: bytes, mime: str, size: int, created_at: str) -> None:
        await self.db.execute(
            "INSERT INTO media_files (name, bytes, mime, size, created_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET bytes = excluded.bytes, mime = excluded.mime, "
            "size = excluded.size, created_at = excluded.created_at",
            (name, data, mime, size, created_at),
        )

    async def get(self, name: str) -> tuple[bytes, str] | None:
        row = await self.db.fetchone("SELECT bytes, mime FROM media_files WHERE name = ?", (name,))
        if row is None:
            return None
        data: Any = row["bytes"]
        # asyncpg отдаёт bytea как memoryview — aiohttp нужен bytes.
        if isinstance(data, memoryview):
            data = bytes(data)
        return bytes(data), str(row["mime"])

    async def delete(self, name: str) -> bool:
        cursor = await self.db.execute("DELETE FROM media_files WHERE name = ?", (name,))
        return cursor.rowcount > 0

    async def list_all(self) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT name, size, created_at FROM media_files ORDER BY created_at DESC"
        )
        return [{"name": str(r["name"]), "size": int(r["size"])} for r in rows]
