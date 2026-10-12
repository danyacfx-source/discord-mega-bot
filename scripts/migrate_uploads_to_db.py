#!/usr/bin/env python3
"""Переносит файлы data/uploads в таблицу media_files (разовый запуск).

Запускается на хосте ДО редеплоя, пока файлы ещё живы в текущем контейнере:

    docker cp scripts/migrate_uploads_to_db.py <container>:/app/
    docker exec <container> python migrate_uploads_to_db.py

Скрипт сам создаёт таблицу (в старом контейнере миграции v11 ещё нет) и
идемпотентен — повторный запуск просто перезапишет те же строки. В конце
печатает записи галереи, чьи файлы не нашлись ни в БД, ни в FS.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

for candidate in (Path(__file__).resolve().parent, Path(__file__).resolve().parent.parent):
    sys.path.insert(0, str(candidate))

from app.db.database import Database  # noqa: E402

_NAME_RE = re.compile(r"^[0-9a-fA-F]{32}\.(?:png|jpg|jpeg|gif|webp)$")
_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
_GALLERY_KEY = "panel.media.gallery"


def _uploads_dir() -> Path:
    db_path = os.getenv("DB_PATH", "data/bot.db")
    return Path(db_path).parent / "uploads"


async def main() -> int:
    database_url = os.getenv("DATABASE_URL", "")
    db_path = os.getenv("DB_PATH", "data/bot.db")
    db = Database(database_url or db_path)
    await db.connect()
    try:
        blob = "BYTEA" if db.is_postgres else "BLOB"
        await db.execute(
            f"CREATE TABLE IF NOT EXISTS media_files ("
            f"name TEXT PRIMARY KEY, bytes {blob} NOT NULL, mime TEXT NOT NULL, "
            f"size INTEGER NOT NULL, created_at TEXT NOT NULL)"
        )

        uploads = _uploads_dir()
        migrated = 0
        if uploads.is_dir():
            for path in sorted(uploads.iterdir()):
                if not path.is_file() or _NAME_RE.match(path.name) is None:
                    continue
                data = path.read_bytes()
                mime = _MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream")
                await db.execute(
                    "INSERT INTO media_files (name, bytes, mime, size, created_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET bytes = excluded.bytes, "
                    "mime = excluded.mime, size = excluded.size, created_at = excluded.created_at",
                    (path.name, data, mime, len(data), datetime.now(UTC).isoformat(timespec="microseconds")),
                )
                migrated += 1

        total_row = await db.fetchone("SELECT COUNT(*) AS n FROM media_files")
        total = int(total_row["n"]) if total_row else 0
        print(f"[migrate] файлов перенесено: {migrated}, всего в БД: {total}")

        kv_row = await db.fetchone("SELECT value FROM kv WHERE key = ?", (_GALLERY_KEY,))
        missing: list[str] = []
        if kv_row:
            try:
                items = json.loads(kv_row["value"] or "[]")
            except (TypeError, ValueError):
                items = []
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "")
                if not url.startswith("/uploads/"):
                    continue
                name = url.removeprefix("/uploads/")
                exists = await db.fetchone("SELECT 1 AS x FROM media_files WHERE name = ?", (name,))
                if not exists and not (_uploads_dir() / name).is_file():
                    missing.append(str(item.get("title") or name))
        if missing:
            print(f"[migrate] записей галереи без файла: {len(missing)} — удалите их вручную в панели:")
            for title in missing:
                print(f"  - {title}")
        else:
            print("[migrate] у всех записей галереи файлы на месте")
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
