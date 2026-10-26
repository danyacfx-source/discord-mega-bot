"""PostgreSQL backend with the same small API as the SQLite Database wrapper.

The repositories deliberately depend on this narrow API instead of a concrete
driver. SQLite remains the default; PostgreSQL is enabled by using a
``postgresql://`` database URL.
"""
from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from app.db.schema import POSTGRES_SCHEMA

_INSERT_PRIMARY_KEYS = {
    "warns": "id",
    "tickets": "ticket_id",
    "reminders": "id",
    "polls": "id",
    "giveaways": "id",
    "scheduled_messages": "id",
    "moderation_cases": "case_id",
}
_PARAM_RE = re.compile(r"\?")
_TABLE_RE = re.compile(r"\bINSERT\s+INTO\s+([a-z_]+)\b", re.IGNORECASE)


@dataclass(slots=True)
class PostgresCursor:
    rowcount: int = 0
    lastrowid: int | None = None




def _translate_sql(sql: str) -> tuple[str, str | None]:
    """Переводит небольшой SQLite-диалект репозиториев в PostgreSQL."""
    normalized = sql.replace("datetime('now')", "CURRENT_TIMESTAMP::text")
    insert_ignore = bool(re.search(r"\bINSERT\s+OR\s+IGNORE\b", normalized, re.IGNORECASE))
    normalized = re.sub(r"\bINSERT\s+OR\s+IGNORE\b", "INSERT", normalized, flags=re.IGNORECASE)
    if insert_ignore and "ON CONFLICT" not in normalized.upper():
        normalized = normalized.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    if re.search(r"\bINSERT\s+OR\s+REPLACE\b", normalized, re.IGNORECASE):
        normalized = re.sub(r"\bINSERT\s+OR\s+REPLACE\b", "INSERT", normalized, flags=re.IGNORECASE)
        normalized = normalized.rstrip().rstrip(";") + (
            " ON CONFLICT (poll_id, user_id) DO UPDATE SET option = EXCLUDED.option"
        )
    table_match = _TABLE_RE.search(normalized)
    table = table_match.group(1).lower() if table_match else None
    primary_key = _INSERT_PRIMARY_KEYS.get(table or "")
    has_returning = "RETURNING" in normalized.upper()
    if primary_key and not has_returning:
        normalized = normalized.rstrip().rstrip(";") + f" RETURNING {primary_key}"
    index = 0

    def replace(_match: re.Match[str]) -> str:
        nonlocal index
        index += 1
        return f"${index}"

    return _PARAM_RE.sub(replace, normalized), primary_key if primary_key and not has_returning else None


class PostgresDatabase:
    """Async PostgreSQL implementation used behind the Database facade."""

    #: Фиксированный признак бэкенда для фасада Database и веб-панели.
    is_postgres = True

    def __init__(self, url: str) -> None:
        self.url = url
        self.pool: asyncpg.Pool | None = None
        self._tx_connection: asyncpg.Connection | None = None
        #: Владелец открытой транзакции — задача asyncio; чужие запросы не
        #: должны попадать в чужое соединение (иначе теряются/откатываются).
        self._tx_task: asyncio.Task[Any] | None = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(
            self.url,
            min_size=1,
            max_size=max(2, int(os.getenv("POSTGRES_POOL_SIZE", "8"))),
            command_timeout=30,
        )
        async with self.pool.acquire() as connection:
            await connection.execute(POSTGRES_SCHEMA)
            # Миграция 10: дни рождения получают guild_id. Старые строки
            # переносятся с guild_id=0 (скрыты от гильдий, нужен re-set).
            has_old = await connection.fetchval(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'birthdays' AND column_name = 'user_id' "
                "AND is_nullable = 'NO' AND column_default IS NULL "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM information_schema.columns "
                "  WHERE table_name = 'birthdays' AND column_name = 'guild_id'"
                ")"
            )
            if has_old:
                await connection.execute(
                    """
                    ALTER TABLE birthdays RENAME TO birthdays_old;
                    CREATE TABLE birthdays (
                        user_id  BIGINT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        month    INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
                        day      INTEGER NOT NULL CHECK (day BETWEEN 1 AND 31),
                        PRIMARY KEY (user_id, guild_id)
                    );
                    INSERT INTO birthdays (user_id, guild_id, month, day)
                        SELECT user_id, 0, month, day FROM birthdays_old;
                    DROP TABLE birthdays_old;
                    CREATE INDEX IF NOT EXISTS idx_birthdays_date ON birthdays(month, day);
                    """
                )

    def _require_pool(self) -> asyncpg.Pool:
        if self.pool is None:
            raise RuntimeError("PostgreSQL не подключён")
        return self.pool

    @asynccontextmanager
    async def _acquire(self) -> AsyncIterator[asyncpg.Connection]:
        """Соединение для запроса: внутри транзакции — её собственное."""
        if self._tx_connection is not None and self._tx_task is asyncio.current_task():
            yield self._tx_connection
            return
        async with self._require_pool().acquire() as connection:
            yield connection

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """Выделяет соединение и держит транзакцию открытой на время блока."""
        async with self._require_pool().acquire() as connection:
            async with connection.transaction():
                self._tx_connection = connection
                self._tx_task = asyncio.current_task()
                try:
                    yield
                finally:
                    self._tx_connection = None
                    self._tx_task = None

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> PostgresCursor:
        query, generated_key = _translate_sql(sql)
        async with self._acquire() as connection:
            if generated_key:
                rows = await connection.fetch(query, *params)
                lastrowid = int(rows[0][generated_key]) if rows else None
                return PostgresCursor(rowcount=len(rows), lastrowid=lastrowid)
            status = await connection.execute(query, *params)
        return PostgresCursor(rowcount=_command_rowcount(status))

    async def execute_returning(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        query, _ = _translate_sql(sql)
        async with self._acquire() as connection:
            row = await connection.fetchrow(query, *params)
        return dict(row) if row is not None else None

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        query, _ = _translate_sql(sql)
        async with self._acquire() as connection:
            row = await connection.fetchrow(query, *params)
        return dict(row) if row is not None else None

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        query, _ = _translate_sql(sql)
        async with self._acquire() as connection:
            rows = await connection.fetch(query, *params)
        return [dict(row) for row in rows]

    async def integrity_check(self) -> str:
        row = await self.fetchone("SELECT 1 AS result")
        return "ok" if row and row["result"] == 1 else "error"

    async def backup(self, destination: str | Path) -> Path:
        """Делает PostgreSQL backup через pg_dump в custom format."""
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.tmp")
        env = self._pg_env()
        try:
            process = await asyncio.create_subprocess_exec(
                "pg_dump",
                "--format=custom",
                "--no-owner",
                "--file",
                str(temp),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("pg_dump не найден: установите postgresql-client (pg_dump) в PATH") from exc
        try:
            _, stderr = await process.communicate()
        except asyncio.CancelledError:
            temp.unlink(missing_ok=True)
            raise
        if process.returncode != 0:
            temp.unlink(missing_ok=True)
            detail = (stderr or b"").decode("utf-8", errors="replace").strip()[:500]
            raise RuntimeError(f"pg_dump завершился с кодом {process.returncode}: {detail or 'без описания'}")
        os.replace(temp, target)
        return target

    def _pg_env(self) -> dict[str, str]:
        """Параметры подключения для pg_dump через переменные окружения.

        DSN не передаётся в argv: пароль не должен быть виден в `ps`.
        """
        from urllib.parse import unquote, urlparse

        parsed = urlparse(self.url)
        env = dict(os.environ)
        if parsed.hostname:
            env["PGHOST"] = parsed.hostname
        if parsed.port:
            env["PGPORT"] = str(parsed.port)
        if parsed.username:
            env["PGUSER"] = unquote(parsed.username)
        if parsed.password:
            env["PGPASSWORD"] = unquote(parsed.password)
        database = parsed.path.lstrip("/")
        if database:
            env["PGDATABASE"] = unquote(database)
        return env

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None


def _command_rowcount(status: str) -> int:
    match = re.search(r"\b(\d+)$", status)
    return int(match.group(1)) if match else 0
