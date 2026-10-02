"""Лента чата (ChatFeed): кольцо сообщений и питание из диспетчера команд."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Config
from app.db.chat_coins_repository import ChatCoinsRepository
from app.db.database import Database
from app.services.chat_coins_service import ChatCoinsService
from app.services.chat_commands_service import ChatCommandsService, ChatMessage
from app.services.chat_feed import ChatFeed


@pytest.fixture
async def db(tmp_path):
    database = Database(os.path.join(tmp_path, "feed.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


def test_feed_keeps_tail_and_limits() -> None:
    feed = ChatFeed(maxlen=3)
    for i in range(5):
        feed.push("kick", f"user{i}", f"msg{i}", is_mod=(i == 4))

    items = feed.recent()
    assert [item["name"] for item in items] == ["user2", "user3", "user4"], "maxlen держит только хвост"
    assert items[-1]["mod"] is True
    assert feed.recent(limit=1)[-1]["text"] == "msg4"
    assert feed.recent(limit=0) == []
    assert feed.recent(limit=-5) == []


def test_feed_clamps_long_fields() -> None:
    feed = ChatFeed()
    feed.push("twitch", "n" * 100, "т" * 700)
    item = feed.recent()[0]
    assert len(item["name"]) == 64
    assert len(item["text"]) == 500
    assert item["platform"] == "twitch" and item["mod"] is False
    assert item["ts"] > 0


@pytest.mark.asyncio
async def test_dispatch_feeds_chat_feed(db, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "x")
    config = Config.from_env(tmp_path / "absent.env")
    coins = ChatCoinsService(ChatCoinsRepository(db))
    kv = SimpleNamespace(set=AsyncMock(), get=AsyncMock(return_value=None), delete=AsyncMock())
    feed = ChatFeed()
    service = ChatCommandsService(config, coins, kv, feed)
    service.register_platform("kick", reply=AsyncMock())

    # обычное сообщение кормит ленту
    await service.handle(
        ChatMessage(platform="kick", username="alice", display_name="Alice", content="привет!", is_mod=True)
    )
    # сообщение бота — не кормит
    await service.handle(
        ChatMessage(platform="kick", username="bot1", display_name="Bot", content="spam", is_bot=True)
    )
    # пустое — тоже нет
    await service.handle(ChatMessage(platform="kick", username="alice", display_name="Alice", content="   "))

    items = feed.recent()
    assert len(items) == 1
    assert items[0]["name"] == "Alice" and items[0]["text"] == "привет!" and items[0]["mod"] is True

    # сервис без ленты (default) — не падает
    bare = ChatCommandsService(config, coins, kv)
    bare.register_platform("kick", reply=AsyncMock())
    await bare.handle(ChatMessage(platform="kick", username="a", display_name="A", content="x"))
