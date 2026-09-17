"""Управление подключением к SQLite через aiosqlite."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import aiosqlite

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
    automod_enabled     INTEGER NOT NULL DEFAULT 1,
    blocked_words       TEXT    NOT NULL DEFAULT '[]'
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
    closed_at  TEXT
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
"""


class Database:
    """Дефолтная обёртка над aiosqlite."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("БД не подключена")
        return self._conn

    async def connect(self) -> None:
        parent = Path(self.path).parent
        parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(_SCHEMA)
        cursor = await self._conn.execute("PRAGMA table_info(guild_settings)")
        rows = await cursor.fetchall()
        columns = {row["name"] for row in rows}
        for column in (
            "member_log_channel_id",
            "message_log_channel_id",
            "voice_log_channel_id",
            "mod_log_channel_id",
            "bot_log_channel_id",
        ):
            if column not in columns:
                await self._conn.execute(f"ALTER TABLE guild_settings ADD COLUMN {column} INTEGER")
        gv_cursor = await self._conn.execute("PRAGMA table_info(giveaways)")
        gv_columns = {row["name"] for row in await gv_cursor.fetchall()}
        if "min_days" not in gv_columns:
            await self._conn.execute("ALTER TABLE giveaways ADD COLUMN min_days INTEGER NOT NULL DEFAULT 0")
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Cursor:
        cursor = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cursor

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        cursor = await self.conn.execute(sql, params)
        return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        cursor = await self.conn.execute(sql, params)
        return await cursor.fetchall()
