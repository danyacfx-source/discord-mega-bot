"""Подключение к PostgreSQL: единственный бэкенд хранилища."""
from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from app.db.postgres_database import PostgresCursor, PostgresDatabase

logger = logging.getLogger("bot.db")

#: Схемы URL, которые принимает PostgreSQL-бэкенд.
POSTGRES_URL_PREFIXES = ("postgresql://", "postgres://")

#: Ошибки, которые говорят о сбое хранилища, а не о плохом запросе.
#: Нарушения целостности и ошибки SQL здесь намеренно нет: конфликт данных —
#: это живая БД, пометить её «недоступной» из-за дубля ключа нельзя.
_AVAILABILITY_ERRORS = (
    asyncpg.PostgresConnectionError,
    asyncpg.CannotConnectNowError,
    asyncpg.ConnectionDoesNotExistError,
    asyncpg.InterfaceError,
    asyncpg.InsufficientResourcesError,
    asyncpg.OperatorInterventionError,
    ConnectionError,
    OSError,
    TimeoutError,
)
#: Сбоев подряд, после которых хранилище считается недоступным.
_UNAVAILABLE_AFTER = 3


def is_postgres_url(url: str | None) -> bool:
    return bool(url) and str(url).startswith(POSTGRES_URL_PREFIXES)


def _is_availability_error(exc: BaseException) -> bool:
    if isinstance(exc, asyncpg.IntegrityConstraintViolationError):
        return False
    return isinstance(exc, _AVAILABILITY_ERRORS)


def _tracked(method: Any) -> Any:
    """Считает сбои хранилища вокруг execute/fetchone/fetchall."""

    @functools.wraps(method)
    async def wrapper(self: Database, *args: Any, **kwargs: Any) -> Any:
        try:
            result = await method(self, *args, **kwargs)
        except Exception as exc:
            self._note_failure(exc)
            raise
        self._note_success()
        return result

    return wrapper


class Database:
    """Тонкая обёртка над PostgresDatabase: учёт доступности и транзакции."""

    def __init__(self, url: str) -> None:
        if not is_postgres_url(url):
            raise ValueError("DATABASE_URL должен начинаться с postgresql:// или postgres://")
        self.url = url
        self._postgres: PostgresDatabase | None = None
        # Сериализует явные транзакции: конкурирующие записи ждут,
        # а не вливаются в чужую транзакцию.
        self._tx_lock = asyncio.Lock()
        self._tx_owner: asyncio.Task[Any] | None = None
        # Состояние деградации: доступность считают execute/fetchone/fetchall.
        self._db_failures = 0
        self._db_available = True
        self._db_last_error: str | None = None

    @property
    def available(self) -> bool:
        """Хранилище отвечает на запросы (после порога сбоев подряд)."""
        return self._db_available

    @property
    def consecutive_failures(self) -> int:
        """Сбоев подряд; сбрасывается первым успешным запросом."""
        return self._db_failures

    @property
    def last_error(self) -> str | None:
        """Последняя ошибка доступности, или ``None`` после восстановления."""
        return self._db_last_error

    def _note_success(self) -> None:
        if not self._db_available:
            logger.warning("Хранилище снова отвечает: восстановление после %d сбоев", self._db_failures)
        self._db_failures = 0
        self._db_available = True
        self._db_last_error = None

    def _note_failure(self, exc: BaseException) -> None:
        if not _is_availability_error(exc):
            return
        self._db_failures += 1
        self._db_last_error = f"{type(exc).__name__}: {exc}"[:500]
        if self._db_failures >= _UNAVAILABLE_AFTER and self._db_available:
            self._db_available = False
            logger.error(
                "Хранилище недоступно (%d сбоев подряд), бот переходит в degraded: %s",
                self._db_failures,
                self._db_last_error,
            )

    @property
    def pg(self) -> PostgresDatabase:
        if self._postgres is None:
            raise RuntimeError("БД не подключена")
        return self._postgres

    async def connect(self) -> None:
        postgres = PostgresDatabase(self.url)
        await postgres.connect()
        self._postgres = postgres
        integrity = await self.integrity_check()
        if integrity != "ok":
            raise RuntimeError(f"Проверка целостности PostgreSQL не пройдена: {integrity}")

    async def integrity_check(self) -> str:
        return await self.pg.integrity_check()

    async def execute_returning(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        return await self.pg.execute_returning(sql, params)

    async def backup(self, destination: str | Path) -> Path:
        """Создаёт backup через pg_dump (custom format)."""
        return await self.pg.backup(destination)

    async def close(self) -> None:
        if self._postgres is not None:
            await self._postgres.close()
            self._postgres = None

    @_tracked
    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> PostgresCursor:
        return await self.pg.execute(sql, params)

    @_tracked
    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        return await self.pg.fetchone(sql, params)

    @_tracked
    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return await self.pg.fetchall(sql, params)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """Атомарная группа операций (BEGIN/COMMIT/ROLLBACK).

        Пока транзакция открыта, чужие транзакции ждут её завершения. Запросы
        внутри блока идут через соединение транзакции. Вложенность
        не поддерживается.
        """
        if self._tx_owner is asyncio.current_task():
            raise RuntimeError("Вложенная транзакция не поддерживается")
        async with self._tx_lock:
            self._tx_owner = asyncio.current_task()
            try:
                async with self.pg.transaction():
                    yield
            finally:
                self._tx_owner = None
