"""Настройка команд Twitch через KV и веб-панель."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.core.composition import assemble
from app.core.webpanel.webpanel import WebPanel
from app.db.database import Database
from app.services.chat_commands_service import ChatCommandsService, ChatMessage
from app.services.twitch_command_settings import (
    default_twitch_command_settings,
    save_twitch_command_settings,
)


class MemoryKv:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str, default: str | None = None) -> str | None:
        return self.values.get(key, default)

    async def set(self, key: str, value: str) -> None:
        self.values[key] = value


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        chat_commands_enabled=True,
        chat_command_prefix="!",
        chat_cmd_cooldown=0.0,
        chat_coin_reward=0,
        twitch_discord_url="https://discord.gg/test",
        socials_discord="",
        twitch_donate_url="",
        socials_donate="",
        socials_youtube="",
        kick_channel_slug="",
        twitch_channels=("channel",),
    )


def _message(content: str, *, is_mod: bool = False) -> ChatMessage:
    return ChatMessage(
        platform="twitch",
        username="viewer",
        display_name="Viewer",
        content=content,
        is_mod=is_mod,
        reply_to="channel",
    )


@pytest.mark.asyncio
async def test_custom_alias_response_and_permissions() -> None:
    kv = MemoryKv()
    settings = default_twitch_command_settings()
    settings["discord"]["aliases"] = ["штаб"]
    settings["discord"]["response"] = "Для {user}: {default}"
    settings["ping"]["moderator_only"] = True
    saved, error = await save_twitch_command_settings(kv, settings)
    assert error is None
    assert saved["discord"]["aliases"] == ["штаб"]

    service = ChatCommandsService(_config(), SimpleNamespace(), kv)
    replies: list[str] = []

    async def reply(_channel: str, text: str) -> None:
        replies.append(text)

    service.register_platform("twitch", reply=reply)
    await service.handle(_message("!discord"))
    assert replies == []
    await service.handle(_message("!штаб"))
    assert replies == ["Для Viewer: 📡 Штаб в Discord: https://discord.gg/test"]
    await service.handle(_message("!ping"))
    assert len(replies) == 1
    await service.handle(_message("!ping", is_mod=True))
    assert replies[-1].startswith("🏓 pong")
    await service.handle(_message("!help"))
    assert "!штаб" in replies[-1]
    assert "!discord" not in replies[-1]
    assert "!опрос" not in replies[-1]


@pytest.mark.asyncio
async def test_twitch_poll_alias_can_be_changed_and_disabled() -> None:
    kv = MemoryKv()
    settings = default_twitch_command_settings()
    settings["twitch_poll"]["aliases"] = ["голосование"]
    await save_twitch_command_settings(kv, settings)
    service = ChatCommandsService(_config(), SimpleNamespace(), kv)

    assert await service.match_twitch_command(_message("!опрос вопрос", is_mod=True)) is None
    matched = await service.match_twitch_command(
        _message("!голосование Вопрос | Да | Нет", is_mod=True)
    )
    assert matched is not None and matched[0] == "twitch_poll"
    assert matched[1] == "Вопрос | Да | Нет"

    settings["twitch_poll"]["enabled"] = False
    await save_twitch_command_settings(kv, settings)
    service.invalidate_twitch_command_settings()
    assert (
        await service.match_twitch_command(
            _message("!голосование Вопрос | Да | Нет", is_mod=True)
        )
        is None
    )


@pytest.mark.asyncio
async def test_duplicate_alias_is_rejected() -> None:
    kv = MemoryKv()
    settings = default_twitch_command_settings()
    settings["discord"]["aliases"] = ["donate"]
    _, error = await save_twitch_command_settings(kv, settings)
    assert error == "Алиас !donate назначен нескольким командам"


@pytest.mark.asyncio
async def test_twitch_commands_web_api(make_panel_bot) -> None:
    bot = make_panel_bot(twitch_channels=("channel",))
    database = Database(bot.config.db_path)
    await database.connect()
    assemble(config=bot.config, db=database, bot=bot)
    panel = WebPanel(bot)
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                headers = {"X-Panel-Token": panel._static_token or ""}
                loaded = await client.get("/api/twitch/commands", headers=headers)
                assert loaded.status == 200
                commands = (await loaded.json())["commands"]
                assert len(commands) == 20
                assert any(command["id"] == "twitch_poll" for command in commands)

                payload = {
                    command["id"]: {
                        "enabled": command["id"] != "slots",
                        "aliases": command["aliases"],
                        "moderator_only": command["moderator_only"],
                        "response": "выключено" if command["id"] == "slots" else "",
                    }
                    for command in commands
                }
                saved = await client.post(
                    "/api/twitch/commands",
                    headers=headers,
                    json={"commands": payload},
                )
                assert saved.status == 200
                saved_commands = (await saved.json())["commands"]
                slots = next(command for command in saved_commands if command["id"] == "slots")
                assert slots["enabled"] is False
    finally:
        await database.close()
