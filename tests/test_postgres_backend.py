"""Проверки PostgreSQL-адаптера без обязательного запущенного PostgreSQL."""
from __future__ import annotations

import pytest

from app.db import reminders_repository, scheduled_repository
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


def test_postgres_replace_does_not_double_append_conflict() -> None:
    """Уже имеющийся ON CONFLICT не должен задваиваться."""
    query, _ = _translate_sql(
        "INSERT OR REPLACE INTO poll_votes (poll_id, user_id, option) VALUES (?, ?, ?) "
        "ON CONFLICT (poll_id, user_id) DO UPDATE SET option = EXCLUDED.option"
    )
    assert query.upper().count("ON CONFLICT") == 1


def test_postgres_replace_rejects_unknown_table() -> None:
    """Чужой conflict target молча сломал бы запрос — лучше падать сразу."""
    with pytest.raises(ValueError, match="_REPLACE_CONFLICTS"):
        _translate_sql("INSERT OR REPLACE INTO kv(key, value) VALUES (?, ?)")


def test_claim_rechecks_lease_on_outer_row() -> None:
    """Аренда должна быть на внешней строке UPDATE, а не только в подзапросе.

    На PostgreSQL результат некоррелированного подзапроса с LIMIT кэшируется в
    InitPlan, и EPQ-recheck после коммита конкурента пере-проверяет лишь
    внешний qual. Пока предикат аренды жил только внутри подзапроса, два
    инстанса брали одну и ту же строку — напоминание или отложенное сообщение
    уходило дважды.
    """
    for sql in (reminders_repository._CLAIM_DUE_SQL, scheduled_repository._CLAIM_DUE_SQL):
        after_limit = sql.split("LIMIT 1", 1)[1]
        assert after_limit.count("processing_until IS NULL OR processing_until <= ?") == 1
        assert sql.count("processing_until IS NULL OR processing_until <= ?") == 2


def test_postgres_schema_defines_chat_coins() -> None:
    """Регрессия: chat_coins был только в миграциях SQLite, не в PG-схеме."""
    tables = postgres_table_names(POSTGRES_SCHEMA)
    assert "chat_coins" in tables
    indexes = postgres_index_names(POSTGRES_SCHEMA)
    assert "idx_chat_coins_top" in indexes


def test_postgres_schema_defines_media_files() -> None:
    """Регрессия: файлы панели переехали в БД — таблица и сид версий 11."""
    tables = postgres_table_names(POSTGRES_SCHEMA)
    assert "media_files" in tables
    assert "generate_series(1, 11)" in POSTGRES_SCHEMA
