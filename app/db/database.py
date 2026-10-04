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

_SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id            INTEGER PRIMARY KEY,
    welcome_channel_id  INTEGER,
    farewell_channel_id INTEGER,
    log_channel_id      INTEGER,
    ticket_category_id  INTEGER,
    member_log_channel_id  INTEGER,
    message_log_channel_id INTEGER,
    voice_log_channel_id   INTEGER,
    mod_log_channel_id     INTEGER,
    bot_log_channel_id     INTEGER,
    donation_channel_id    INTEGER,
    automod_enabled     INTEGER NOT NULL DEFAULT 1,
    blocked_words       TEXT    NOT NULL DEFAULT '[]',
    ticket_panel_title       TEXT NOT NULL DEFAULT 'Поддержка',
    ticket_panel_description TEXT NOT NULL DEFAULT 'Нажмите на кнопку, чтобы открыть тикет.',
    ticket_panel_footer      TEXT NOT NULL DEFAULT 'Тикеты помогают решать личные вопросы без шума в каналах.',
    ticket_open_label        TEXT NOT NULL DEFAULT 'Открыть тикет',
    ticket_open_emoji        TEXT NOT NULL DEFAULT '🎫',
    ticket_intro_title       TEXT NOT NULL DEFAULT 'Новый тикет',
    ticket_intro_description TEXT NOT NULL DEFAULT 'Опишите свою проблему, {member}.',
    ticket_intro_footer      TEXT NOT NULL DEFAULT 'Нажмите кнопку ниже, чтобы закрыть тикет по завершении.',
    ticket_close_label       TEXT NOT NULL DEFAULT 'Закрыть тикет',
    ticket_close_emoji       TEXT NOT NULL DEFAULT '🔒',
    ticket_channel_prefix    TEXT NOT NULL DEFAULT 'ticket'
);

CREATE TABLE IF NOT EXISTS warns (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    reason       TEXT    NOT NULL,
    created_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL UNIQUE,
    creator_id INTEGER NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'open',
    created_at TEXT    NOT NULL,
    closed_at  TEXT,
    transcript TEXT
);

CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    guild_id   INTEGER,
    channel_id INTEGER,
    message    TEXT    NOT NULL,
    remind_at  TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS polls (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    author_id  INTEGER NOT NULL,
    question   TEXT    NOT NULL,
    options    TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS poll_votes (
    poll_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    option  INTEGER NOT NULL,
    PRIMARY KEY (poll_id, user_id),
    FOREIGN KEY (poll_id) REFERENCES polls(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS giveaways (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    author_id  INTEGER NOT NULL,
    prize      TEXT    NOT NULL,
    winners    INTEGER NOT NULL DEFAULT 1,
    ends_at    TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS giveaway_entries (
    giveaway_id INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    PRIMARY KEY (giveaway_id, user_id),
    FOREIGN KEY (giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reaction_roles (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    role_id    INTEGER NOT NULL,
    emoji      TEXT    NOT NULL,
    UNIQUE (message_id, emoji)
);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS donations (
    da_id      INTEGER PRIMARY KEY,
    user_name  TEXT    NOT NULL,
    user_id    INTEGER,
    amount     REAL    NOT NULL,
    currency   TEXT    NOT NULL DEFAULT '',
    message    TEXT    NOT NULL DEFAULT '',
    vip        INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS temp_voices (
    owner_id   INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL UNIQUE,
    created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS birthdays (
    user_id INTEGER PRIMARY KEY,
    month   INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    day     INTEGER NOT NULL CHECK (day BETWEEN 1 AND 31)
);

CREATE TABLE IF NOT EXISTS season_points (
    user_id    INTEGER NOT NULL,
    guild_id   INTEGER NOT NULL,
    points     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS scheduled_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id     INTEGER NOT NULL,
    channel_id   INTEGER NOT NULL,
    author_id    INTEGER NOT NULL,
    content      TEXT    NOT NULL DEFAULT '',
    embed_json   TEXT    NOT NULL DEFAULT '{}',
    send_at      TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,
    done         INTEGER NOT NULL DEFAULT 0
);
"""


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
        await self._conn.executescript(_SCHEMA)
        await self._run_migrations()
        # Обновляет статистику query planner без тяжёлого полного ANALYZE.
        await self._conn.execute("PRAGMA optimize")
        integrity = await self.integrity_check()
        if integrity != "ok":
            raise RuntimeError(f"Проверка целостности SQLite не пройдена: {integrity}")
        await self._conn.commit()

    async def _run_migrations(self) -> None:
        """Применяет идемпотентные миграции поверх базовой схемы."""
        conn = self.conn
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied_rows = await conn.execute_fetchall("SELECT version FROM schema_migrations")
        applied = {int(row[0]) for row in applied_rows}

        if 1 not in applied:
            await conn.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(active, remind_at);
                CREATE INDEX IF NOT EXISTS idx_scheduled_due ON scheduled_messages(done, send_at);
                CREATE INDEX IF NOT EXISTS idx_giveaways_due ON giveaways(active, ends_at);
                CREATE INDEX IF NOT EXISTS idx_warns_guild_user ON warns(guild_id, user_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_tickets_guild_status ON tickets(guild_id, status);
                """
            )
            await conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (1, datetime('now'))"
            )

        if 2 not in applied:
            for table in ("reminders", "scheduled_messages", "giveaways"):
                columns = await conn.execute_fetchall(f"PRAGMA table_info({table})")
                if "processing_until" not in {row[1] for row in columns}:
                    await conn.execute(f"ALTER TABLE {table} ADD COLUMN processing_until TEXT")
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_processing ON reminders(active, processing_until)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_scheduled_processing ON scheduled_messages(done, processing_until)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_giveaways_processing ON giveaways(active, processing_until)"
            )
            await conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (2, datetime('now'))"
            )

        if 3 not in applied:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS moderation_cases (
                    case_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cases_guild_user ON moderation_cases(guild_id, user_id, created_at)"
            )
            await conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (3, datetime('now'))"
            )
        if 4 not in applied:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_role TEXT NOT NULL,
                    action TEXT NOT NULL,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    remote TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit(created_at DESC)"
            )
            await conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (4, datetime('now'))"
            )
        if 5 not in applied:
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS music_playlists (
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    created_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, name)
                );
                CREATE TABLE IF NOT EXISTS music_playlist_tracks (
                    guild_id INTEGER NOT NULL,
                    playlist_name TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    stream_url TEXT NOT NULL DEFAULT '',
                    duration INTEGER,
                    uploader TEXT,
                    thumbnail TEXT,
                    PRIMARY KEY (guild_id, playlist_name, position),
                    FOREIGN KEY (guild_id, playlist_name)
                        REFERENCES music_playlists(guild_id, name) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_music_playlist_tracks
                    ON music_playlist_tracks(guild_id, playlist_name, position);
                """
            )
            await conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (5, datetime('now'))"
            )
        if 6 not in applied:
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS music_queue (
                    guild_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    stream_url TEXT NOT NULL DEFAULT '',
                    duration INTEGER,
                    uploader TEXT,
                    thumbnail TEXT,
                    PRIMARY KEY (guild_id, position)
                );
                CREATE INDEX IF NOT EXISTS idx_music_queue_guild ON music_queue(guild_id, position);
                """
            )
            await conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (6, datetime('now'))"
            )
        if 7 not in applied:
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS activity_hourly (
                    guild_id INTEGER NOT NULL,
                    bucket TEXT NOT NULL,
                    messages INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, bucket)
                );
                CREATE INDEX IF NOT EXISTS idx_activity_hourly_bucket
                    ON activity_hourly(guild_id, bucket);
                """
            )
            await conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (7, datetime('now'))"
            )
        if 8 not in applied:
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS music_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    duration INTEGER,
                    played_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_music_history_guild
                    ON music_history(guild_id, played_at DESC);
                """
            )
            await conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (8, datetime('now'))"
            )
        if 9 not in applied:
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS chat_coins (
                    platform TEXT NOT NULL,
                    username TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    coins INTEGER NOT NULL DEFAULT 0,
                    messages INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (platform, username)
                );
                CREATE INDEX IF NOT EXISTS idx_chat_coins_top ON chat_coins(platform, coins DESC);
                """
            )
            await conn.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (9, datetime('now'))"
            )
        conn = self.conn
        cursor = await conn.execute("PRAGMA table_info(guild_settings)")
        rows = await cursor.fetchall()
        columns = {row["name"] for row in rows}
        for column in (
            "member_log_channel_id",
            "message_log_channel_id",
            "voice_log_channel_id",
            "mod_log_channel_id",
            "bot_log_channel_id",
            "donation_channel_id",
        ):
            if column not in columns:
                await conn.execute(f"ALTER TABLE guild_settings ADD COLUMN {column} INTEGER")
        for column in (
            "ticket_panel_title",
            "ticket_panel_description",
            "ticket_panel_footer",
            "ticket_open_label",
            "ticket_open_emoji",
            "ticket_intro_title",
            "ticket_intro_description",
            "ticket_intro_footer",
            "ticket_close_label",
            "ticket_close_emoji",
            "ticket_channel_prefix",
        ):
            if column not in columns:
                await conn.execute(f"ALTER TABLE guild_settings ADD COLUMN {column} TEXT")
        gv_cursor = await conn.execute("PRAGMA table_info(giveaways)")
        gv_columns = {row["name"] for row in await gv_cursor.fetchall()}
        if "min_days" not in gv_columns:
            await conn.execute("ALTER TABLE giveaways ADD COLUMN min_days INTEGER NOT NULL DEFAULT 0")
        tk_cursor = await conn.execute("PRAGMA table_info(tickets)")
        tk_columns = {row["name"] for row in await tk_cursor.fetchall()}
        if "transcript" not in tk_columns:
            await conn.execute("ALTER TABLE tickets ADD COLUMN transcript TEXT")
        await conn.commit()

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

    async def record_admin_audit(
        self,
        actor_role: str,
        action: str,
        method: str,
        path: str,
        remote: str = "",
    ) -> None:
        await self.execute(
            """
            INSERT INTO admin_audit(actor_role, action, method, path, remote, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (actor_role, action[:200], method[:16], path[:500], remote[:120]),
        )

    async def list_admin_audit(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            """
            SELECT id, actor_role, action, method, path, remote, created_at
            FROM admin_audit
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 1000)),),
        )
        return [dict(row) for row in rows]

    async def increment_activity(self, guild_id: int, bucket: str, amount: int = 1) -> None:
        await self.execute(
            """
            INSERT INTO activity_hourly(guild_id, bucket, messages)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, bucket) DO UPDATE SET
                messages = activity_hourly.messages + excluded.messages
            """,
            (guild_id, bucket, max(1, amount)),
        )

    async def list_activity(self, guild_id: int, limit: int = 1000) -> list[dict[str, Any]]:
        rows = await self.fetchall(
            """
            SELECT bucket, messages
            FROM activity_hourly
            WHERE guild_id = ?
            ORDER BY bucket DESC
            LIMIT ?
            """,
            (guild_id, max(1, min(limit, 5000))),
        )
        return [dict(row) for row in rows]

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
