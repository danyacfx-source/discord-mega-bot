"""Живая лента вебпанели: шина событий, кольцевой лог-хук, ws /ws/events."""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.config import Config
from app.core.bot import MegaBot
from app.core.webpanel.log_ring import RingBufferHandler
from app.core.webpanel.webpanel import WebPanel
from app.services.event_bus import EventBus


def _panel(tmp_path, port: int = 17892) -> tuple[MegaBot, WebPanel, EventBus]:
    config = Config(
        token="x",
        prefix="!",
        db_path=str(tmp_path / "bot.db"),
        log_level="ERROR",
        status_activity="s",
        owner_id=None,
        panel_port=port,
    )
    bot = MegaBot(config)
    bus = EventBus()
    bot.services = SimpleNamespace(events=bus)  # type: ignore[assignment]
    return bot, WebPanel(bot), bus


def test_event_bus_publish_drain_seq():
    bus = EventBus()
    first = bus.publish("stream", {"status": "live"})
    second = bus.publish("donation", {"amount": 5})
    assert first["seq"] == 1
    assert second["seq"] == 2
    assert second["type"] == "donation"
    assert second["ts"]
    fresh = bus.drain(0)
    assert [e["type"] for e in fresh] == ["stream", "donation"]
    assert [e["type"] for e in bus.drain(1)] == ["donation"]
    assert bus.drain(2) == []
    assert bus.seq == 2


def test_event_bus_rotates_buffer():
    bus = EventBus(maxlen=3)
    for i in range(5):
        bus.publish("log", {"i": i})
    kept = bus.drain(0)
    assert [e["data"]["i"] for e in kept] == [2, 3, 4]


def test_ring_on_record_callback():
    seen: list[dict] = []
    handler = RingBufferHandler(capacity=10, on_record=seen.append)
    record = logging.LogRecord("bot.services.audit.member_join", logging.INFO, "f", 1, "Вошёл", (), None)
    handler.emit(record)
    assert len(seen) == 1
    assert seen[0]["audit"] == "1"
    assert seen[0]["cat"] == "member_join"
    assert seen[0]["msg"] == "Вошёл"
    assert handler.snapshot(10)[0]["msg"] == "Вошёл"


def test_on_ring_record_filters_and_publishes(tmp_path):
    _, panel, bus = _panel(tmp_path)
    panel._on_ring_record({"level": "INFO", "msg": "тихое", "cat": "sys", "t": "", "audit": "0"})
    assert bus.drain(0) == []
    panel._on_ring_record({"level": "WARNING", "msg": "громкое", "cat": "sys", "t": "", "audit": "0"})
    panel._on_ring_record({"level": "INFO", "msg": "вошёл", "cat": "member_join", "t": "", "audit": "1"})
    types = [e["type"] for e in bus.drain(0)]
    assert types == ["log", "log"]
    assert bus.drain(0)[1]["data"]["cat"] == "member_join"


@pytest.mark.asyncio
async def test_ws_events_rejects_bad_token(tmp_path):
    _, panel, _bus = _panel(tmp_path)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            ws = await client.ws_connect("/ws/events")
            await ws.send_json({"token": "mud"})
            message = await ws.receive(timeout=5)
            assert message.type == web.WSMsgType.CLOSE
            assert message.data == 4401


@pytest.mark.asyncio
async def test_ws_events_delivers_published_event(tmp_path):
    _, panel, bus = _panel(tmp_path)
    loop_task = asyncio.create_task(panel._events_loop())
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                ws = await client.ws_connect("/ws/events")
                await ws.send_json({"token": panel._static_token})
                for _ in range(50):
                    if panel._event_clients:
                        break
                    await asyncio.sleep(0.05)
                assert panel._event_clients, "клиент не зарегистрировался"
                bus.publish("stream", {"platform": "kick", "status": "live", "title": "т"})
                event = await ws.receive_json(timeout=5)
                assert event["type"] == "stream"
                assert event["data"]["title"] == "т"
                assert event["seq"] >= 1
                await ws.close()
    finally:
        loop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop_task


@pytest.mark.asyncio
async def test_events_loop_skips_when_no_clients(tmp_path):
    """Без клиентов шина не должна разгонять seq впустую на старых событиях."""
    _, panel, bus = _panel(tmp_path)
    bus.publish("stream", {"status": "live"})
    loop_task = asyncio.create_task(panel._events_loop())
    try:
        await asyncio.sleep(1.0)
        assert panel._events_seq == bus.seq
        assert not panel._event_clients
    finally:
        loop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop_task
