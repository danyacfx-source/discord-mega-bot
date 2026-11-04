"""Тесты integrity check, транзакций и backup PostgreSQL (pg_dump)."""

import asyncio
import contextlib
import os
import time
from pathlib import Path

import pytest

from app.db.backup_manager import DatabaseBackupManager
from app.db.database import Database
from app.db.postgres_database import PostgresDatabase


async def test_schema_integrity_and_backup(pg_url: str, tmp_path: Path) -> None:
    database = Database(pg_url)
    await database.connect()
    await database.execute("INSERT INTO kv(key, value) VALUES (?, ?)", ("health", "ok"))
    assert await database.integrity_check() == "ok"
    migrations = await database.fetchall("SELECT version FROM schema_migrations ORDER BY version")
    assert [row["version"] for row in migrations] == list(range(1, 15))
    backup = await database.backup(tmp_path / "backup.dump")
    assert backup.is_file() and backup.stat().st_size > 0
    await database.close()


async def test_backup_is_atomic_and_replaces_previous_copy(pg_url: str, tmp_path: Path) -> None:
    target = tmp_path / "nested" / "backup.dump"
    database = Database(pg_url)
    await database.connect()
    await database.backup(target)
    await database.execute("INSERT INTO kv(key, value) VALUES ('marker', 'second')")
    await database.backup(target)
    await database.close()

    assert target.is_file()
    assert not list(target.parent.glob(".*.tmp"))


async def test_backup_manager_keeps_only_configured_retention(pg_url: str, tmp_path: Path) -> None:
    database = Database(pg_url)
    await database.connect()
    manager = DatabaseBackupManager(database, tmp_path / "backups", interval_hours=1, retention=2)

    await manager.backup_now()
    await manager.backup_now()
    await manager.backup_now()

    backups = sorted((tmp_path / "backups").glob("bot-*.dump"))
    assert len(backups) == 2
    assert manager.status()["last_backup"] is not None
    assert manager.status()["last_error"] is None
    await database.close()


async def test_backup_manager_posts_to_external_sink(pg_url: str, tmp_path: Path) -> None:
    """Каждый backup уходит в sink (Discord-канал): внешняя копия переживает хост."""
    database = Database(pg_url)
    await database.connect()
    seen: list[Path] = []

    async def sink(path: Path) -> None:
        seen.append(path)

    manager = DatabaseBackupManager(database, tmp_path / "backups", interval_hours=1, retention=1, on_backup=sink)
    result = await manager.backup_now()
    assert seen == [result]
    await database.close()


async def test_backup_manager_sink_error_does_not_fail_backup(pg_url: str, tmp_path: Path) -> None:
    """Ошибка внешнего sink не проваливает сам backup."""
    database = Database(pg_url)
    await database.connect()

    async def boom(path: Path) -> None:
        raise RuntimeError("discord down")

    manager = DatabaseBackupManager(database, tmp_path / "backups", interval_hours=1, retention=1, on_backup=boom)
    result = await manager.backup_now()
    assert result.is_file()
    assert manager.status()["last_error"] is None
    await database.close()


def test_backup_manager_prunes_orphan_temp_files(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    stale = backups / ".bot-20260101-000000.dump.abc123.tmp"
    stale.write_bytes(b"")
    old = time.time() - 7200
    os.utime(stale, (old, old))
    fresh = backups / ".bot-20260102-000000.dump.def456.tmp"
    fresh.write_bytes(b"")
    regular = backups / "bot-20260101-000000.dump"
    regular.write_bytes(b"db")

    manager = DatabaseBackupManager(Database("postgresql://u:p@localhost/x"), backups, interval_hours=1, retention=1)
    manager._prune()

    assert not stale.exists()
    assert fresh.exists()
    assert regular.exists()


def test_pg_env_keeps_password_out_of_process_args() -> None:
    db = PostgresDatabase("postgresql://panel:s3cret@dbhost:5432/megabot")
    env = db._pg_env()
    assert env["PGHOST"] == "dbhost"
    assert env["PGPORT"] == "5432"
    assert env["PGUSER"] == "panel"
    assert env["PGPASSWORD"] == "s3cret"
    assert env["PGDATABASE"] == "megabot"


def test_pg_env_reads_unix_socket_from_query() -> None:
    db = PostgresDatabase("postgresql://panel:@/megabot?host=/run/postgresql&port=5433")
    env = db._pg_env()
    assert env["PGHOST"] == "/run/postgresql"
    assert env["PGPORT"] == "5433"
    assert env["PGDATABASE"] == "megabot"


def test_database_rejects_non_postgres_url() -> None:
    with pytest.raises(ValueError):
        Database("data/bot.db")
    with pytest.raises(ValueError):
        Database("")


async def test_transaction_commits_atomically_and_rolls_back(pg_url: str) -> None:
    database = Database(pg_url)
    await database.connect()

    async with database.transaction():
        await database.execute("INSERT INTO kv(key, value) VALUES (?, ?)", ("committed", "yes"))
        await database.execute("INSERT INTO kv(key, value) VALUES (?, ?)", ("atomic", "pair"))
        row = await database.fetchone("SELECT value FROM kv WHERE key = ?", ("committed",))
        assert row is not None and row["value"] == "yes"

    with pytest.raises(RuntimeError, match="boom"):
        async with database.transaction():
            await database.execute("INSERT INTO kv(key, value) VALUES (?, ?)", ("rolled", "back"))
            raise RuntimeError("boom")

    assert await database.fetchone("SELECT value FROM kv WHERE key = ?", ("committed",)) is not None
    assert await database.fetchone("SELECT value FROM kv WHERE key = ?", ("atomic",)) is not None
    assert await database.fetchone("SELECT value FROM kv WHERE key = ?", ("rolled",)) is None

    await database.execute("INSERT INTO kv(key, value) VALUES (?, ?)", ("after", "tx"))
    assert await database.fetchone("SELECT value FROM kv WHERE key = ?", ("after",)) is not None
    await database.close()


async def test_transactions_are_serialized(pg_url: str) -> None:
    """Вторая транзакция ждёт завершения первой (обычные запросы идут через другие соединения пула)."""
    database = Database(pg_url)
    await database.connect()
    order: list[str] = []

    async def second() -> None:
        async with database.transaction():
            order.append("second")
            await database.execute("INSERT INTO kv(key, value) VALUES (?, ?)", ("waiting", "v"))

    async with database.transaction():
        await database.execute("INSERT INTO kv(key, value) VALUES (?, ?)", ("inside", "1"))
        waiter = asyncio.create_task(second())
        await asyncio.sleep(0.05)
        assert not waiter.done()
        order.append("first")
    await waiter

    assert order == ["first", "second"]
    assert await database.fetchone("SELECT value FROM kv WHERE key = ?", ("waiting",)) is not None
    await database.close()


async def test_cancelled_backup_leaves_connection_healthy(pg_url: str, tmp_path: Path) -> None:
    """Отмена backup посреди pg_dump не ломает соединение."""
    database = Database(pg_url)
    await database.connect()
    await database.execute("INSERT INTO kv(key, value) VALUES (?, ?)", ("marker", "alive"))

    for index in range(5):
        task = asyncio.create_task(database.backup(tmp_path / f"out-{index}.dump"))
        await asyncio.sleep(0.001)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    row = await database.fetchone("SELECT value FROM kv WHERE key = ?", ("marker",))
    assert row is not None and row["value"] == "alive"
    await database.close()
