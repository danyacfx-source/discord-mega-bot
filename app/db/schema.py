"""Единый источник схемы: базовые DDL для SQLite и PostgreSQL.

Дрейф диалектов ловит ``tests/test_schema_parity.py``: таблицы и индексы
актуальной SQLite-базы сверяются с ``POSTGRES_SCHEMA``. Новая таблица или
индекс добавляются в оба диалекта (или в миграции SQLite + схему PG).
"""
from __future__ import annotations

import re

#: Базовая схема SQLite. Версионные дополнения — в ``app.db.migrations``.
SQLITE_SCHEMA = """
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
    user_id  INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    month    INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    day      INTEGER NOT NULL CHECK (day BETWEEN 1 AND 31),
    PRIMARY KEY (user_id, guild_id)
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

#: DDL PostgreSQL. Должен покрывать финальное состояние SQLite (схема + все
#: миграции): сверка — в tests/test_schema_parity.py.
POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id BIGINT PRIMARY KEY,
    welcome_channel_id BIGINT, farewell_channel_id BIGINT, log_channel_id BIGINT,
    ticket_category_id BIGINT, member_log_channel_id BIGINT, message_log_channel_id BIGINT,
    voice_log_channel_id BIGINT, mod_log_channel_id BIGINT, bot_log_channel_id BIGINT,
    donation_channel_id BIGINT, automod_enabled INTEGER NOT NULL DEFAULT 1,
    blocked_words TEXT NOT NULL DEFAULT '[]',
    ticket_panel_title TEXT NOT NULL DEFAULT 'Поддержка',
    ticket_panel_description TEXT NOT NULL DEFAULT 'Нажмите на кнопку, чтобы открыть тикет.',
    ticket_panel_footer TEXT NOT NULL DEFAULT 'Тикеты помогают решать личные вопросы без шума в каналах.',
    ticket_open_label TEXT NOT NULL DEFAULT 'Открыть тикет', ticket_open_emoji TEXT NOT NULL DEFAULT '🎫',
    ticket_intro_title TEXT NOT NULL DEFAULT 'Новый тикет',
    ticket_intro_description TEXT NOT NULL DEFAULT 'Опишите свою проблему, {member}.',
    ticket_intro_footer TEXT NOT NULL DEFAULT 'Нажмите кнопку ниже, чтобы закрыть тикет по завершении.',
    ticket_close_label TEXT NOT NULL DEFAULT 'Закрыть тикет', ticket_close_emoji TEXT NOT NULL DEFAULT '🔒',
    ticket_channel_prefix TEXT NOT NULL DEFAULT 'ticket'
);
CREATE TABLE IF NOT EXISTS warns (
    id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
    moderator_id BIGINT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, channel_id BIGINT NOT NULL UNIQUE,
    creator_id BIGINT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL,
    closed_at TEXT, transcript TEXT
);
CREATE TABLE IF NOT EXISTS reminders (
    id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL, guild_id BIGINT, channel_id BIGINT,
    message TEXT NOT NULL, remind_at TEXT NOT NULL, created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1, processing_until TEXT
);
CREATE TABLE IF NOT EXISTS polls (
    id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, channel_id BIGINT NOT NULL,
    message_id BIGINT, author_id BIGINT NOT NULL, question TEXT NOT NULL, options TEXT NOT NULL,
    created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS poll_votes (
    poll_id BIGINT NOT NULL, user_id BIGINT NOT NULL, option INTEGER NOT NULL,
    PRIMARY KEY (poll_id, user_id), FOREIGN KEY (poll_id) REFERENCES polls(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS giveaways (
    id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, channel_id BIGINT NOT NULL,
    message_id BIGINT, author_id BIGINT NOT NULL, prize TEXT NOT NULL,
    winners INTEGER NOT NULL DEFAULT 1, ends_at TEXT NOT NULL, created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1, processing_until TEXT, min_days INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS giveaway_entries (
    giveaway_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
    PRIMARY KEY (giveaway_id, user_id), FOREIGN KEY (giveaway_id) REFERENCES giveaways(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reaction_roles (
    id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, channel_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL, role_id BIGINT NOT NULL, emoji TEXT NOT NULL,
    UNIQUE (message_id, emoji)
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS donations (
    da_id BIGINT PRIMARY KEY, user_name TEXT NOT NULL, user_id BIGINT, amount DOUBLE PRECISION NOT NULL,
    currency TEXT NOT NULL DEFAULT '', message TEXT NOT NULL DEFAULT '', vip INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS temp_voices (
    owner_id BIGINT PRIMARY KEY, channel_id BIGINT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS birthdays (
    user_id BIGINT NOT NULL, guild_id BIGINT NOT NULL,
    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    day INTEGER NOT NULL CHECK (day BETWEEN 1 AND 31),
    PRIMARY KEY (user_id, guild_id)
);
CREATE TABLE IF NOT EXISTS season_points (
    user_id BIGINT NOT NULL, guild_id BIGINT NOT NULL, points INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, guild_id)
);
CREATE TABLE IF NOT EXISTS scheduled_messages (
    id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, channel_id BIGINT NOT NULL,
    author_id BIGINT NOT NULL, content TEXT NOT NULL DEFAULT '', embed_json TEXT NOT NULL DEFAULT '{}',
    send_at TEXT NOT NULL, created_at TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
    processing_until TEXT
);
CREATE TABLE IF NOT EXISTS moderation_cases (
    case_id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
    moderator_id BIGINT NOT NULL, action TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL, expires_at TEXT, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS admin_audit (
    id BIGSERIAL PRIMARY KEY, actor_role TEXT NOT NULL, action TEXT NOT NULL,
    method TEXT NOT NULL, path TEXT NOT NULL, remote TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS music_playlists (
    guild_id BIGINT NOT NULL, name TEXT NOT NULL, created_by BIGINT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY (guild_id, name)
);
CREATE TABLE IF NOT EXISTS music_playlist_tracks (
    guild_id BIGINT NOT NULL, playlist_name TEXT NOT NULL, position INTEGER NOT NULL,
    title TEXT NOT NULL, url TEXT NOT NULL, stream_url TEXT NOT NULL DEFAULT '', duration INTEGER,
    uploader TEXT, thumbnail TEXT, PRIMARY KEY (guild_id, playlist_name, position),
    FOREIGN KEY (guild_id, playlist_name) REFERENCES music_playlists(guild_id, name) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS music_queue (
    guild_id BIGINT NOT NULL, position INTEGER NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
    stream_url TEXT NOT NULL DEFAULT '', duration INTEGER, uploader TEXT, thumbnail TEXT,
    PRIMARY KEY (guild_id, position)
);
CREATE TABLE IF NOT EXISTS activity_hourly (
    guild_id BIGINT NOT NULL, bucket TEXT NOT NULL, messages INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, bucket)
);
CREATE TABLE IF NOT EXISTS music_history (
    id BIGSERIAL PRIMARY KEY, guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
    title TEXT NOT NULL, url TEXT NOT NULL, duration INTEGER, played_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_coins (
    platform TEXT NOT NULL, username TEXT NOT NULL, display_name TEXT NOT NULL,
    coins INTEGER NOT NULL DEFAULT 0, messages INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
    PRIMARY KEY (platform, username)
);
CREATE TABLE IF NOT EXISTS media_files (
    name TEXT PRIMARY KEY, bytes BYTEA NOT NULL, mime TEXT NOT NULL,
    size INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(active, remind_at);
CREATE INDEX IF NOT EXISTS idx_scheduled_due ON scheduled_messages(done, send_at);
CREATE INDEX IF NOT EXISTS idx_giveaways_due ON giveaways(active, ends_at);
CREATE INDEX IF NOT EXISTS idx_warns_guild_user ON warns(guild_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tickets_guild_status ON tickets(guild_id, status);
CREATE INDEX IF NOT EXISTS idx_reminders_processing ON reminders(active, processing_until);
CREATE INDEX IF NOT EXISTS idx_scheduled_processing ON scheduled_messages(done, processing_until);
CREATE INDEX IF NOT EXISTS idx_giveaways_processing ON giveaways(active, processing_until);
CREATE INDEX IF NOT EXISTS idx_cases_guild_user ON moderation_cases(guild_id, user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_music_playlist_tracks ON music_playlist_tracks(guild_id, playlist_name, position);
CREATE INDEX IF NOT EXISTS idx_music_queue_guild ON music_queue(guild_id, position);
CREATE INDEX IF NOT EXISTS idx_activity_hourly_bucket ON activity_hourly(guild_id, bucket);
CREATE INDEX IF NOT EXISTS idx_music_history_guild ON music_history(guild_id, played_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_coins_top ON chat_coins(platform, coins DESC);
CREATE INDEX IF NOT EXISTS idx_birthdays_date ON birthdays(month, day);
INSERT INTO schema_migrations(version, applied_at)
SELECT version, CURRENT_TIMESTAMP::text FROM generate_series(1, 11) AS version
ON CONFLICT (version) DO NOTHING;
"""

_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", re.IGNORECASE)
_INDEX_RE = re.compile(r"CREATE INDEX IF NOT EXISTS\s+(\w+)\s+ON\s+(\w+)", re.IGNORECASE)


def postgres_table_names(ddl: str = POSTGRES_SCHEMA) -> set[str]:
    """Имена таблиц, которые создаёт PG-DDL."""
    return {match.group(1).lower() for match in _TABLE_RE.finditer(ddl)}


def postgres_index_names(ddl: str = POSTGRES_SCHEMA) -> set[str]:
    """Имена индексов, которые создаёт PG-DDL."""
    return {match.group(1).lower() for match in _INDEX_RE.finditer(ddl)}
