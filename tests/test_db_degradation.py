"""Graceful degradation: счётчик сбоев хранилища и fallback настроек.

Проверяет, что лежащая БД переводит бота в degraded-режим, а не роняет
каждую команду, и что /api/health на этом основании умеет отдать 503.
"""
from __future__ import annotations

import time
from typing import Any

import asyncpg

from app.db.database import Database, _is_availability_error
from app.services.settings_service import SettingsService

_URL = "postgresql://u:p@localhost:5432/x"


def test_storage_error_is_availability_error() -> None:
    assert _is_availability_error(ConnectionError("connection refused"))
    assert _is_availability_error(TimeoutError("timeout"))
    assert _is_availability_error(OSError("network unreachable"))
    assert _is_availability_error(asyncpg.CannotConnectNowError("starting up"))
    assert _is_availability_error(asyncpg.ConnectionDoesNotExistError("closed"))


def test_sql_error_is_not_availability_error() -> None:
    assert not _is_availability_error(asyncpg.UndefinedTableError("relation foo does not exist"))
    assert not _is_availability_error(asyncpg.PostgresSyntaxError("syntax error"))
    assert not _is_availability_error(asyncpg.UniqueViolationError("duplicate key"))
    assert not _is_availability_error(ValueError("БД не подключена"))


def test_three_storage_failures_mark_database_unavailable() -> None:
    db = Database(_URL)
    assert db.available

    for _ in range(3):
        db._note_failure(ConnectionError("connection refused"))

    assert not db.available
    assert db.consecutive_failures == 3
    assert db.last_error is not None and "connection refused" in db.last_error


def test_sql_errors_never_mark_database_unavailable() -> None:
    db = Database(_URL)
    for _ in range(10):
        db._note_failure(asyncpg.UndefinedTableError("relation settings does not exist"))

    assert db.available
    assert db.consecutive_failures == 0


async def test_successful_query_recovers_state(pg_url: str) -> None:
    db = Database(pg_url)
    await db.connect()
    for _ in range(3):
        db._note_failure(ConnectionError("connection refused"))
    assert not db.available

    row = await db.fetchone("SELECT 1 AS one")
    assert row is not None
    assert db.available
    assert db.consecutive_failures == 0
    assert db.last_error is None
    await db.close()


async def test_queries_still_work_while_degraded(pg_url: str) -> None:
    """Degraded — это сигнал для health, а не блокировка работы."""
    db = Database(pg_url)
    await db.connect()
    for _ in range(3):
        db._note_failure(ConnectionError("connection refused"))
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
            raise ConnectionError("connection refused")
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
    except ConnectionError:
        pass
    else:
        raise AssertionError("без кеша ошибка должна пройти наружу")
