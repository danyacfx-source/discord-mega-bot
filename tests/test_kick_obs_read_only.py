"""Regression: public Kick OBS chat must not depend on moderation OAuth."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.cogs.streams.kick import KickCog


@pytest.mark.asyncio
async def test_kick_starts_read_only_chat_watcher_without_access_token() -> None:
    config = SimpleNamespace(
        kick_channel_slug="dendosich",
        kick_access_token="",
        kick_mod_channel_id=None,
        kick_poll_seconds=300,
        chat_commands_enabled=False,
    )
    bot = SimpleNamespace(
        config=config,
        loop=asyncio.get_running_loop(),
        wait_until_ready=AsyncMock(side_effect=RuntimeError("not logged in")),
    )
    kick = SimpleNamespace(aclose=AsyncMock())
    chat = SimpleNamespace(register_platform=MagicMock(), unregister_platform=MagicMock())
    cog = KickCog(bot, kick, chat)  # type: ignore[arg-type]
    cog._chat_watcher = AsyncMock()

    await cog.cog_load()
    try:
        assert cog._chat_task is not None, "read-only Pusher connection must be launched without a token"
        await cog._chat_task
        cog._chat_watcher.assert_awaited_once_with()
        chat.register_platform.assert_not_called()
    finally:
        await cog.cog_unload()


@pytest.mark.asyncio
async def test_kick_chat_read_only_delivers_messages_to_command_feed() -> None:
    chat = SimpleNamespace(handle=AsyncMock())
    kick = SimpleNamespace(
        viewer_store=lambda: SimpleNamespace(touch=AsyncMock()),
    )
    bot = SimpleNamespace(config=SimpleNamespace(kick_ban_words=()))
    cog = KickCog(bot, kick, chat)  # type: ignore[arg-type]

    await cog._handle_chat_message({
        "sender": {"username": "Guest", "identity": {}},
        "content": "Тестовый чат в OBS",
    })
    assert chat.handle.await_count == 1
    message = chat.handle.await_args.args[0]
    assert message.platform == "kick"
    assert message.content == "Тестовый чат в OBS"
