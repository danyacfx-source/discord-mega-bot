"""Интеграционные тесты репозиториев (SQLite в памяти/файл)."""
import os

import pytest

from app.db.database import Database
from app.db.settings_repository import SettingsRepository
from app.db.tickets_repository import TicketsRepository
from app.db.warns_repository import WarnsRepository


@pytest.fixture
async def db(tmp_path):
    database = Database(os.path.join(tmp_path, "test.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_settings_repository(db):
    repo = SettingsRepository(db)
    data = await repo.get(111)
    assert data["automod_enabled"] == 1
    assert data["welcome_channel_id"] is None
    assert data["member_log_channel_id"] is None
    assert data["message_log_channel_id"] is None
    assert data["voice_log_channel_id"] is None
    assert data["mod_log_channel_id"] is None
    assert data["bot_log_channel_id"] is None

    await repo.set(111, "welcome_channel_id", 555)
    await repo.set(111, "mod_log_channel_id", 666)
    updated = await repo.get(111)
    assert updated["welcome_channel_id"] == 555
    assert updated["mod_log_channel_id"] == 666


@pytest.mark.asyncio
async def test_warns_repository(db):
    repo = WarnsRepository(db)
    warning_id = await repo.add(111, 222, 333, "спам", "2026-01-01T10:00:00+00:00")
    assert warning_id > 0
    assert await repo.count_for_user(111, 222) == 1
    assert await repo.total_for_guild(111) == 1

    await repo.add(111, 222, 333, "реклама", "2026-01-02T10:00:00+00:00")
    warns = await repo.list_for_user(111, 222)
    assert len(warns) == 2
    assert warns[0]["reason"] == "реклама"

    assert await repo.clear_for_user(111, 222) == 2
    assert await repo.count_for_user(111, 222) == 0


@pytest.mark.asyncio
async def test_tickets_repository(db):
    from datetime import UTC, datetime

    repo = TicketsRepository(db)
    ticket_id = await repo.create(111, 777, 222, datetime.now(UTC))
    assert ticket_id > 0

    ticket = await repo.by_channel(777)
    assert ticket is not None
    assert ticket["status"] == "open"
    assert await repo.has_open_by_creator(111, 222) is True

    await repo.close(ticket_id, datetime.now(UTC))
    assert await repo.has_open_by_creator(111, 222) is False
