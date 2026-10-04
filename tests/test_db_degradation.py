"""Graceful degradation: счётчик сбоев хранилища и fallback настроек.

Проверяет, что лежащая БД переводит бота в degraded-режим, а не роняет
каждую команду, и что /api/health на этом основании умеет отдать 503.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from app.db.database import Database, _is_availability_error
from app.services.settings_service import SettingsService


def test_storage_error_is_availability_error() -> None:
    assert _is_availability_error(sqlite3.OperationalError("database is locked"))
    assert _is_availability_error(sqlite3.OperationalError("disk I/O error"))
    assert _is_availability_error(sqlite3.DatabaseError("database disk image is malformed"))
    assert _is_availability_error(ConnectionError("connection refused"))


def test_sql_error_is_not_availability_error() -> None:
    assert not _is_availability_error(sqlite3.OperationalError("no such table: foo"))
    assert not _is_availability_error(sqlite3.OperationalError("near 'SELCT': syntax error"))
    assert not _is_availability_error(sqlite3.IntegrityError("UNIQUE constraint failed: kv.key"))
    assert not _is_availability_error(ValueError("БД не подключена"))


def test_three_storage_failures_mark_database_unavailable() -> None:
    db = Database("unused.db")
    assert db.available

    for _ in range(3):
        db._note_failure(sqlite3.OperationalError("database is locked"))

    assert not db.available
    assert db.consecutive_failures == 3
    assert db.last_error is not None and "database is locked" in db.last_error


def test_sql_errors_never_mark_database_unavailable() -> None:
    db = Database("unused.db")
    for _ in range(10):
        db._note_failure(sqlite3.OperationalError("no such table: settings"))

    assert db.available
    assert db.consecutive_failures == 0


async def test_successful_query_recovers_state(tmp_path: Path) -> None:
    db = Database(str(tmp_path / "recovery.db"))
    await db.connect()
    for _ in range(3):
        db._note_failure(sqlite3.OperationalError("database is locked"))
    assert not db.available

    row = await db.fetchone("SELECT 1")
    assert row is not None
    assert db.available
    assert db.consecutive_failures == 0
    assert db.last_error is None
    await db.close()


async def test_queries_still_work_while_degraded(tmp_path: Path) -> None:
    """Degraded — это сигнал для health, а не блокировка работы."""
    db = Database(str(tmp_path / "degraded.db"))
    await db.connect()
    for _ in range(3):
        db._note_failure(sqlite3.OperationalError("database is locked"))
    assert not db.available

    await db.execute("INSERT INTO kv(key, value) VALUES (?, ?)", ("k", "v"))
    row = await db.fetchone("SELECT value FROM kv WHERE key = ?", ("k",))
    assert row is not None and row["value"] == "v"
    assert db.available
    await db.close()


class _FlakyRepo:
    """Репозиторий настроек, у которого можно сломать чтение."""

    def __init__(self) -> None:
        self.broken = False
        self.calls = 0

    async def get(self, guild_id: int) -> dict[str, Any]:
        self.calls += 1
        if self.broken:
            raise sqlite3.OperationalError("database is locked")
        return {"prefix": "!", "automod_enabled": 1, "blocked_words": None}


async def test_settings_fall_back_to_last_known_values() -> None:
    repo = _FlakyRepo()
    service = SettingsService(repo)  # type: ignore[arg-type]

    fresh = await service.get(1)
    assert fresh["prefix"] == "!"

    # Кеш протухает — без fallback команда упала бы вместе с БД.
    repo.broken = True
    service._cache[1] = (time.monotonic() - 1.0, dict(fresh))
    stale = await service.get(1)
    assert stale["prefix"] == "!"
    assert service._degraded

    # Восстановление: как только БД отвечает, сервис возвращается к ней.
    repo.broken = False
    service._cache[1] = (time.monotonic() - 1.0, dict(fresh))
    recovered = await service.get(1)
    assert recovered["prefix"] == "!"
    assert not service._degraded


async def test_settings_without_cache_still_raise() -> None:
    """Единственный шанс — известное значение; глушить ошибку смысла нет."""
    repo = _FlakyRepo()
    service = SettingsService(repo)  # type: ignore[arg-type]
    repo.broken = True

    try:
        await service.get(42)
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError("без кеша ошибка должна пройти наружу")
