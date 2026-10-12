"""Идемпотентные миграции SQLite поверх базовой схемы.

Каждая миграция выполняется один раз и фиксируется в ``schema_migrations``.
Без версии остаются только доборы колонок ``guild_settings``/``giveaways``/
``tickets``: они идут после версионных шагов и проверяют состав таблицы
на лету (старые базы могли родиться до появления колонки в базовом DDL).
"""
from __future__ import annotations

from typing import Any


async def run_migrations(conn: Any) -> None:
    """Применяет идемпотентные миграции поверх базовой схемы SQLite."""
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
    if 10 not in applied:
        # Дни рождения: скоуп по гильдии. Старые строки (без guild_id)
        # переносятся с guild_id=0 — они не видны ни одной гильдии,
        # пользователь пере-установит дату командой /birthday set.
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS birthdays_new (
                user_id  INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                month    INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
                day      INTEGER NOT NULL CHECK (day BETWEEN 1 AND 31),
                PRIMARY KEY (user_id, guild_id)
            );
            INSERT INTO birthdays_new (user_id, guild_id, month, day)
                SELECT user_id, 0, month, day FROM birthdays;
            DROP TABLE birthdays;
            ALTER TABLE birthdays_new RENAME TO birthdays;
            CREATE INDEX IF NOT EXISTS idx_birthdays_date ON birthdays(month, day);
            """
        )
        await conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (10, datetime('now'))"
        )
    if 11 not in applied:
        # Файлы медиатеки/загрузок переезжают из FS в БД: контейнер при
        # редеплое удаляется целиком, файлы в data/uploads умирал вместе с ним.
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS media_files (
                name       TEXT PRIMARY KEY,
                bytes      BLOB NOT NULL,
                mime       TEXT NOT NULL,
                size       INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (11, datetime('now'))"
        )
    await _backfill_columns(conn)
    await conn.commit()


async def _backfill_columns(conn: Any) -> None:
    """Добирает колонки, которых могло не хватать в старых базах."""
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
