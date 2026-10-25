"""Keep Twitch OBS chat ingestion independent from chat-bot OAuth and commands."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.cogs.streams import chat_commands as chat_module
from app.cogs.streams.chat_commands import StreamChatCog
from app.services.chat_commands_service import ChatCommandsService, ChatMessage
from app.services.chat_feed import ChatFeed


def _config(*, commands: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        chat_commands_enabled=commands,
        twitch_channels=("streamer",),
        twitch_bot_login="broken_bot",
        twitch_bot_client_id="client",
        twitch_client_id="client",
        twitch_client_secret="",
        twitch_bot_refresh_token="expired",
        twitch_chat_token="expired_access",
        twitch_bot_refresh_provider="ttg",
    )


@pytest.mark.asyncio
async def test_twitch_irc_starts_for_obs_even_when_commands_disabled() -> None:
    bot = SimpleNamespace(config=_config(commands=False), loop=asyncio.get_running_loop())
    chat = SimpleNamespace(register_platform=MagicMock(), unregister_platform=MagicMock())
    cog = StreamChatCog(bot, chat, SimpleNamespace())  # type: ignore[arg-type]
    cog._irc_runner = AsyncMock()

    await cog.cog_load()
    try:
        assert cog._irc_task is not None
        await cog._irc_task
        cog._irc_runner.assert_awaited_once_with()
        chat.register_platform.assert_not_called()
    finally:
        await cog.cog_unload()


@pytest.mark.asyncio
async def test_twitch_feed_receives_messages_without_chat_commands() -> None:
    feed = ChatFeed()
    service = ChatCommandsService(
        SimpleNamespace(chat_commands_enabled=False),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        feed,
    )
    await service.handle(
        ChatMessage(platform="twitch", username="guest", display_name="Guest", content="Привет в эфир!")
    )
    assert [(row["platform"], row["text"]) for row in feed.recent()] == [
        ("twitch", "Привет в эфир!")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["oauth", "irc"])
async def test_twitch_bad_bot_auth_falls_back_to_anonymous_obs_feed(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    config = _config()
    bot = SimpleNamespace(config=config)
    cog = StreamChatCog(bot, SimpleNamespace(), SimpleNamespace())  # type: ignore[arg-type]
    monkeypatch.setattr(chat_module, "wait_ready_or_stop", AsyncMock(return_value=True))

    auth = SimpleNamespace(
        token=AsyncMock(
            side_effect=RuntimeError("Twitch OAuth: missing chat:read / chat:edit scopes")
            if failure == "oauth"
            else None,
            return_value="expired_access",
        ),
        seconds_until_refresh=lambda: None,
    )
    monkeypatch.setattr(chat_module, "TwitchBotAuth", lambda **kwargs: auth)

    used_tokens: list[str] = []

    class FakeIrc:
        def __init__(self, *, token: str, **kwargs: object) -> None:
            used_tokens.append(token)
            self.auth_failed = False

        async def run(self, on_message: object) -> None:
            if used_tokens[-1] and failure == "irc":
                self.auth_failed = True
                return
            raise asyncio.CancelledError()

    monkeypatch.setattr(chat_module, "TwitchIrc", FakeIrc)
    await cog._irc_runner()

    assert used_tokens[-1] == "", "OAuth must not block the read-only OBS chat"
    if failure == "irc":
        assert used_tokens == ["expired_access", ""]
    else:
        assert used_tokens == [""]
