"""Проверки PostgreSQL-адаптера без обязательного запущенного PostgreSQL."""
from __future__ import annotations

from app.db.postgres_database import _translate_sql
from app.db.schema import POSTGRES_SCHEMA, postgres_index_names, postgres_table_names
from app.features.reminders import repository as reminders_repository
from app.features.scheduler import repository as scheduled_repository


def test_postgres_translates_placeholders_and_generated_id() -> None:
    query, key = _translate_sql("INSERT INTO reminders (user_id, message) VALUES (?, ?)")
    assert query.endswith("RETURNING id")
    assert "$1" in query and "$2" in query
    assert key == "id"


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
    """Регрессия: chat_coins отсутствовал в PG-схеме."""
    tables = postgres_table_names(POSTGRES_SCHEMA)
    assert "chat_coins" in tables
    indexes = postgres_index_names(POSTGRES_SCHEMA)
    assert "idx_chat_coins_top" in indexes


def test_postgres_schema_defines_media_files() -> None:
    """Регрессия: файлы панели переехали в БД — таблица и сид версий 11."""
    tables = postgres_table_names(POSTGRES_SCHEMA)
    assert "media_files" in tables
    assert "generate_series(1, 14)" in POSTGRES_SCHEMA


def test_postgres_schema_defines_panel_tables() -> None:
    """Регрессия: panel_login_attempts (миграция 12) отсутствовала в PG-схеме."""
    tables = postgres_table_names(POSTGRES_SCHEMA)
    assert {"panel_login_attempts", "panel_sessions", "panel_scan_offenses"} <= tables
    assert "ALTER TABLE panel_scan_offenses ADD COLUMN IF NOT EXISTS location" in POSTGRES_SCHEMA
