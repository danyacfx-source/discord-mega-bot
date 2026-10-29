"""Настройки и ручная отправка Twitch-промо."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.cogs.streams.chat_commands import StreamChatCog
from app.core.composition import assemble
from app.core.webpanel.webpanel import WebPanel
from app.db.database import Database
from app.services.twitch_promo import (
    load_twitch_promo_settings,
    normalize_promo_interval,
)


def test_promo_interval_is_clamped() -> None:
    assert normalize_promo_interval(None) == 30
    assert normalize_promo_interval("2") == 5
    assert normalize_promo_interval(45) == 45
    assert normalize_promo_interval(999) == 180


@pytest.mark.asyncio
async def test_promo_settings_use_twitch_discord_url() -> None:
    kv = SimpleNamespace(get=AsyncMock(return_value="{}"))
    config = SimpleNamespace(
        twitch_discord_url="https://discord.gg/twitch",
        socials_discord="https://discord.gg/general",
    )
    settings = await load_twitch_promo_settings(kv, config)
    assert settings == {
        "enabled": True,
        "text": "https://discord.gg/twitch проект спонсор данного стрима",
        "interval_minutes": 30,
    }


@pytest.mark.asyncio
async def test_webpanel_saves_interval_and_sends_promo(make_panel_bot, monkeypatch) -> None:
    bot = make_panel_bot(
        twitch_channels=("alice", "bob"),
        twitch_discord_url="https://discord.gg/twitch",
    )
    database = Database(bot.config.db_path)
    await database.connect()
    assemble(config=bot.config, db=database, bot=bot)
    panel = WebPanel(bot)
    applied: list[int] = []
    send_now = AsyncMock(
        return_value={
            "sent": ["alice"],
            "offline": ["bob"],
            "failed": [],
            "disabled": False,
            "irc_ready": True,
        }
    )
    cog = SimpleNamespace(set_promo_interval=applied.append, send_promo_now=send_now)
    monkeypatch.setattr(bot, "get_cog", lambda name: cog if name == "StreamChat" else None)
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                headers = {"X-Panel-Token": panel._static_token or ""}
                saved = await client.post(
                    "/api/twitch/promo",
                    headers=headers,
                    json={"enabled": True, "text": "  Реклама   здесь  ", "interval_minutes": 2},
                )
                assert saved.status == 200
                saved_body = await saved.json()
                assert saved_body["promo"] == {
                    "enabled": True,
                    "text": "Реклама здесь",
                    "interval_minutes": 5,
                }
                assert applied == [5]
                stored = json.loads(await bot.services.kv.get("panel.twitch.promo"))
                assert stored["interval_minutes"] == 5

                sent = await client.post(
                    "/api/twitch/promo/send",
                    headers=headers,
                    json={"text": "  Отправить   сейчас  "},
                )
                assert sent.status == 200
                sent_body = await sent.json()
                assert sent_body["sent"] == ["alice"]
                assert sent_body["offline"] == ["bob"]
                send_now.assert_awaited_once_with("Отправить сейчас")
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_manual_promo_only_sends_to_live_channels() -> None:
    config = SimpleNamespace(
        twitch_channels=("alice", "bob"),
        twitch_discord_url="https://discord.gg/twitch",
        socials_discord="",
    )
    kv = SimpleNamespace(
        get=AsyncMock(
            return_value=json.dumps(
                {"enabled": False, "text": "Сохранённый текст", "interval_minutes": 30}
            )
        )
    )
    bot = SimpleNamespace(config=config, services=SimpleNamespace(kv=kv))
    twitch = SimpleNamespace(channel_status=AsyncMock(side_effect=[{"live": True}, None]))
    cog = StreamChatCog(bot, SimpleNamespace(), twitch)

    class FakeIrc:
        can_write = True
        _token = "secret"

        def __init__(self) -> None:
            self.messages: list[tuple[str, str]] = []

        async def send(self, channel: str, text: str) -> bool:
            self.messages.append((channel, text))
            return True

    irc = FakeIrc()
    cog._irc = irc  # type: ignore[assignment]
    result = await cog.send_promo_now("Ручной текст")

    assert result["sent"] == ["alice"]
    assert result["offline"] == ["bob"]
    assert irc.messages == [("alice", "Ручной текст")]
