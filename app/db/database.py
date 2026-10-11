"""Управление подключением к SQLite через aiosqlite."""
from __future__ import annotations

import asyncio
import functools
import logging
import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import aiosqlite

from app.db.migrations import run_migrations
from app.db.schema import SQLITE_SCHEMA

logger = logging.getLogger("bot.db")

#: Ошибки, которые говорят о сбое хранилища, а не о плохом запросе.
#: IntegrityError здесь намеренно нет: конфликт данных — это живая БД,
#: пометить её «недоступной» из-за дубля первичного ключа нельзя.
_AVAILABILITY_ERRORS = (sqlite3.DatabaseError, ConnectionError, OSError, TimeoutError)
#: Сбоев подряд, после которых хранилище считается недоступным.
_UNAVAILABLE_AFTER = 3
#: Слова, по которым sqlite-ошибка опознаётся как отказ диска или блокировки,
#: а не как ошибка самого SQL. Без них упавший «no such table» пометил бы БД
#: недоступной, и /api/health начал бы отдавать 503 из-за бага в запросе.
_STORAGE_MARKERS = ("disk", "locked", "malformed", "not a database", "unable to open", "readonly", "full")


def _is_availability_error(exc: BaseException) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return False
    if not isinstance(exc, _AVAILABILITY_ERRORS):
        return False
    if not isinstance(exc, sqlite3.DatabaseError):
        return True
    message = str(exc).lower()
    return any(marker in message for marker in _STORAGE_MARKERS)


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
    """Дефолтная обёртка над aiosqlite."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._postgres: Any | None = None
        # Сериализует явные транзакции: одна запись в БД на процесс,
        # конкурирующие записи ждут, а не вливаются в чужой BEGIN.
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

    @property
    def is_postgres(self) -> bool:
        """True, если бэкенд — PostgreSQL (а не SQLite)."""
        return self.path.startswith(("postgresql://", "postgres://"))

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
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("БД не подключена")
        return self._conn

    async def connect(self) -> None:
        if self.path.startswith(("postgresql://", "postgres://")):
            from app.db.postgres_database import PostgresDatabase

            self._postgres = PostgresDatabase(self.path)
            await self._postgres.connect()
            return
        parent = Path(self.path).parent
        parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA temp_store=MEMORY")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SQLITE_SCHEMA)
        await run_migrations(self._conn)
        # Обновляет статистику query planner без тяжёлого полного ANALYZE.
        await self._conn.execute("PRAGMA optimize")
        integrity = await self.integrity_check()
        if integrity != "ok":
            raise RuntimeError(f"Проверка целостности SQLite не пройдена: {integrity}")
        await self._conn.commit()

    async def integrity_check(self) -> str:
        if self._postgres is not None:
            return await self._postgres.integrity_check()
        cursor = await self.conn.execute("PRAGMA integrity_check")
        row = await cursor.fetchone()
        return str(row[0]) if row else "unknown"

    async def execute_returning(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> aiosqlite.Row | None:
        if self._postgres is not None:
            return await self._postgres.execute_returning(sql, params)
        if self._tx_owner is asyncio.current_task():
            cursor = await self.conn.execute(sql, params)
            return await cursor.fetchone()
        async with self._tx_lock:
            cursor = await self.conn.execute(sql, params)
            row = await cursor.fetchone()
            await self.conn.commit()
            return row

    async def backup(self, destination: str | Path) -> Path:
        """Создаёт консистентный backup через SQLite backup API.

        Запись идёт во временный файл с последующей атомарной заменой. Так
        процесс, который в этот момент читает backup, никогда не увидит
        полуготовую SQLite-базу после сбоя или остановки контейнера.
        """
        if self._postgres is not None:
            return await self._postgres.backup(destination)
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with NamedTemporaryFile(
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
            if temp_path is None:
                raise RuntimeError("Не удалось подготовить временный файл SQLite backup")
            # Под тем же локом, что и execute(): backup на общем коннекте ждёт
            # освобождения незакоммиченной записи, а коммит стоял бы в очереди
            # аiosqlite позади backup'а — получался дедлок.
            async with self._tx_lock:
                # connect не должен прерываться отменой: Task.cancel() отменяет
                # и то, на чём повисла корутина, — дочерний connect-таск тоже
                # встал бы под отмену, аiosqlite успел бы открыть файл в своём
                # рабочем потоке и объект остался бы никому не нужен: закрыть
                # его нечем, а Windows не отдаст хэндл. shield гасит отмену на
                # этом await, сам таск мы закроем в finally.
                connect = asyncio.ensure_future(aiosqlite.connect(temp_path))
                backup_conn: aiosqlite.Connection | None = None
                cancelled: asyncio.CancelledError | None = None
                try:
                    backup_conn = await asyncio.shield(connect)
                    await self.conn.backup(backup_conn)
                    cursor = await backup_conn.execute("PRAGMA integrity_check")
                    row = await cursor.fetchone()
                    if not row or str(row[0]).lower() != "ok":
                        raise RuntimeError(f"Проверка backup SQLite не пройдена: {row[0] if row else 'unknown'}")
                except asyncio.CancelledError as exc:
                    cancelled = exc
                finally:
                    if backup_conn is None:
                        try:
                            backup_conn = await connect
                        except Exception:
                            backup_conn = None
                    if backup_conn is not None:
                        # Отмена backup-таска прерывает только await: sqlite3
                        # backup уже передан в рабочий поток source-соединения
                        # и продолжает писать в backup_conn. Закрыть его сразу
                        # — два потока на одном sqlite3-объекте и access
                        # violation на Windows. SELECT встаёт в ту же очередь
                        # позади backup-коллбека и возвращается после него.
                        try:
                            await self._drain_source_queue()
                        finally:
                            await backup_conn.close()
                if cancelled is not None:
                    raise cancelled
            os.replace(temp_path, target)
            temp_path = None
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    # Windows держит temp-файл открытым, пока aiosqlite worker
                    # дочищает отменённую операцию. Не перекрываем CancelledError
                    # периодического backup-таска этой ошибкой.
                    logger.debug("Не удалось удалить временный SQLite backup: %s", temp_path)
        return target

    async def _drain_source_queue(self) -> None:
        """Дожидается конца операции, уже переданной в рабочий поток aiosqlite.

        Нужен только в путях отмены: ``Connection.backup`` ставит коллбек в
        очередь source-соединения и ждёт его через await, но отмена снимает
        лишь ожидающую корутину — сама операция в потоке продолжается.
        """
        conn = self._conn
        if conn is None:
            return
        try:
            await conn.execute("SELECT 1")
        except Exception:
            logger.debug("Очередь source-соединения не дождалась drain", exc_info=True)

    async def close(self) -> None:
        if self._postgres is not None:
            await self._postgres.close()
            self._postgres = None
            return
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @_tracked
    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Cursor:
        if self._postgres is not None:
            return await self._postgres.execute(sql, params)
        if self._tx_owner is asyncio.current_task():
            # Собственная транзакция: коммит сделает transaction().
            return await self.conn.execute(sql, params)
        async with self._tx_lock:
            cursor = await self.conn.execute(sql, params)
            await self.conn.commit()
            return cursor

    @_tracked
    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        if self._postgres is not None:
            return await self._postgres.fetchone(sql, params)
        cursor = await self.conn.execute(sql, params)
        return await cursor.fetchone()

    @_tracked
    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        if self._postgres is not None:
            return await self._postgres.fetchall(sql, params)
        cursor = await self.conn.execute(sql, params)
        return list(await cursor.fetchall())

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """Атомарная группа операций (BEGIN/COMMIT/ROLLBACK).

        Пока транзакция открыта, чужие записи ждут её завершения, а свои
        запросы внутри блока не коммитятся по отдельности. Вложенность
        не поддерживается.
        """
        if self._tx_owner is asyncio.current_task():
            raise RuntimeError("Вложенная транзакция не поддерживается")
        async with self._tx_lock:
            self._tx_owner = asyncio.current_task()
            try:
                if self._postgres is not None:
                    async with self._postgres.transaction():
                        yield
                    return
                await self.conn.execute("BEGIN")
                try:
                    yield
                except BaseException:
                    await self.conn.rollback()
                    raise
                else:
                    await self.conn.commit()
            finally:
                self._tx_owner = None
