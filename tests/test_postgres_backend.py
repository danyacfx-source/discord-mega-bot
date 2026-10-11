"""Проверки PostgreSQL-адаптера без обязательного запущенного PostgreSQL."""
from __future__ import annotations

from app.db.postgres_database import _translate_sql
from app.db.schema import POSTGRES_SCHEMA, postgres_index_names, postgres_table_names


def test_postgres_translates_placeholders_and_generated_id() -> None:
    query, key = _translate_sql("INSERT INTO reminders (user_id, message) VALUES (?, ?)")
    assert query.endswith("RETURNING id")
    assert "$1" in query and "$2" in query
    assert key == "id"


def test_postgres_translates_sqlite_ignore_and_replace() -> None:
    ignore, ignore_key = _translate_sql("INSERT OR IGNORE INTO kv(key, value) VALUES (?, ?)")
    replace, replace_key = _translate_sql(
        "INSERT OR REPLACE INTO poll_votes (poll_id, user_id, option) VALUES (?, ?, ?)"
    )
    assert "INSERT OR IGNORE" not in ignore.upper()
    assert "ON CONFLICT DO NOTHING" in ignore.upper()
    assert ignore_key is None
    assert "EXCLUDED.OPTION" in replace.upper()
    assert replace_key is None


def test_postgres_schema_defines_chat_coins() -> None:
    """Регрессия: chat_coins был только в миграциях SQLite, не в PG-схеме."""
    tables = postgres_table_names(POSTGRES_SCHEMA)
    assert "chat_coins" in tables
    indexes = postgres_index_names(POSTGRES_SCHEMA)
    assert "idx_chat_coins_top" in indexes
