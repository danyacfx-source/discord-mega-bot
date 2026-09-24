"""Тесты миграций, integrity check и консистентного backup SQLite."""

from pathlib import Path

from app.db.database import Database
from app.db.restore import restore_backup


async def test_database_migrations_integrity_and_backup(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"

    database = Database(str(source))
    await database.connect()
    await database.execute("INSERT INTO kv(key, value) VALUES (?, ?)", ("health", "ok"))
    assert await database.integrity_check() == "ok"
    await database.backup(backup)
    await database.close()

    restored = Database(str(backup))
    await restored.connect()
    row = await restored.fetchone("SELECT value FROM kv WHERE key = ?", ("health",))
    assert row is not None and row["value"] == "ok"
    migrations = await restored.fetchall("SELECT version FROM schema_migrations ORDER BY version")
    assert [row["version"] for row in migrations] == [1, 2, 3, 4, 5, 6, 7, 8]
    await restored.increment_activity(1, "2026-09-24T00:00:00+00:00")
    activity = await restored.list_activity(1)
    assert activity[0]["messages"] == 1
    await restored.close()


async def test_restore_validates_and_keeps_previous_db(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    first = Database(str(source))
    await first.connect()
    await first.execute("INSERT INTO kv(key, value) VALUES ('marker', 'source')")
    await first.backup(target)
    await first.close()

    replacement = tmp_path / "replacement.db"
    second = Database(str(replacement))
    await second.connect()
    await second.execute("INSERT INTO kv(key, value) VALUES ('marker', 'replacement')")
    await second.close()
    previous = restore_backup(replacement, target)
    assert previous is not None and previous.is_file()
