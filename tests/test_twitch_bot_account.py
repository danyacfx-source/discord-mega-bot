"""Twitch bot-account wiring and RADIO SILENCE chat commands."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.cogs.streams.chat_commands import TwitchIrc, _safe_auth_reason
from app.services.chat_commands_service import ChatCommandsService, ChatMessage
from app.services.twitch_bot_auth import TwitchBotAuth


def _msg(command: str) -> ChatMessage:
    return ChatMessage(platform="twitch", username="viewer", display_name="Viewer", content=command)


@pytest.mark.asyncio
async def test_twitch_brand_commands_are_centralized() -> None:
    config = SimpleNamespace(
        chat_commands_enabled=True,
        chat_command_prefix="!",
        chat_cmd_cooldown=0.0,
        chat_coin_reward=0,
        socials_discord="https://discord.gg/example",
        socials_youtube="https://www.youtube.com/@Dendosich",
        twitch_channels=("streamer",),
        kick_channel_slug=None,
        socials_donate=None,
    )
    coins = SimpleNamespace()
    kv = SimpleNamespace(set=AsyncMock())
    chat = ChatCommandsService(config, coins, kv)
    replies: list[str] = []

    async def reply(_channel: str, message: str) -> None:
        replies.append(message)

    async def live() -> dict[str, str]:
        return {"category": "Arma Reforger"}

    chat.register_platform("twitch", reply=reply, live=live)
    for cmd in ("!discord", "!youtube", "!игра", "!сигналы", "!награды", "!позывной"):
        await chat.handle(_msg(cmd))

    assert len(replies) == 6
    assert "discord.gg" in replies[0]
    assert "@Dendosich" in replies[1]
    assert "Arma Reforger" in replies[2]
    assert "баллы канала Twitch" in replies[3]
    assert "5000" in replies[4]
    assert "позывной" in replies[5]


@pytest.mark.asyncio
async def test_irc_does_not_echo_bot_commands() -> None:
    irc = TwitchIrc(nick="unused", token="token", channels=("streamer",), write_login="radiobot")
    collected: list[ChatMessage] = []

    async def on_message(m: ChatMessage) -> None:
        collected.append(m)

    line = ":radiobot!radiobot@radiobot.tmi.twitch.tv PRIVMSG #streamer :!help"
    assert not await irc._dispatch(line, SimpleNamespace(), on_message)
    assert collected and collected[0].is_bot


def test_bot_auth_does_not_load_cache_for_other_user(tmp_path) -> None:
    p = tmp_path / "oauth.json"
    p.write_text('{"login":"attacker","client_id":"client","refresh_token":"wrong"}')
    auth = TwitchBotAuth(
        login="radiobot", client_id="client", client_secret="secret",
        refresh_token="safe", cache_file=str(p),
    )
    assert auth._refresh == "safe"


@pytest.mark.asyncio
async def test_anonymous_chat_keeps_broadcaster_commands() -> None:
    irc = TwitchIrc(nick="justinfan12345", token="", channels=("streamer",), write_login="streamer")
    collected: list[ChatMessage] = []

    async def on_message(m: ChatMessage) -> None:
        collected.append(m)

    line = ":streamer!streamer@streamer.tmi.twitch.tv PRIVMSG #streamer :!help"
    assert not await irc._dispatch(line, SimpleNamespace(), on_message)
    assert collected and collected[0].is_bot is False



@pytest.mark.asyncio
async def test_manual_chat_token_does_not_need_same_app_client_id(monkeypatch, tmp_path) -> None:
    """External IRC bot token works even when Twitch stream API uses another app."""
    from app.services import twitch_bot_auth as auth_module

    session = MagicMock()
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value={
        "login": "radiobot",
        "client_id": "external_chat_token_app",
        "scopes": ["chat:read", "chat:edit"],
        "expires_in": 3600,
    })
    session.get.return_value.__aenter__.return_value = response
    session.__aenter__.return_value = session
    monkeypatch.setattr(auth_module.aiohttp, "ClientSession", lambda: session)

    auth = TwitchBotAuth(
        login="radiobot",
        client_id="stream_api_app",
        client_secret="",
        refresh_token="",
        access_token="oauth:manual_chat_token",
        cache_file=str(tmp_path / "not-present.json"),
    )
    assert await auth.token() == "manual_chat_token"


@pytest.mark.asyncio
async def test_managed_refresh_token_still_checks_app_client_id(monkeypatch, tmp_path) -> None:
    """Protect app-owned refresh tokens against accepting the wrong OAuth app."""
    from app.services import twitch_bot_auth as auth_module

    session = MagicMock()
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value={
        "login": "radiobot",
        "client_id": "incorrect_app",
        "scopes": ["chat:read", "chat:edit"],
        "expires_in": 3600,
    })
    session.get.return_value.__aenter__.return_value = response
    session.__aenter__.return_value = session
    monkeypatch.setattr(auth_module.aiohttp, "ClientSession", lambda: session)

    auth = TwitchBotAuth(
        login="radiobot", client_id="managed_app", client_secret="secret",
        refresh_token="managed_refresh", access_token="managed_access",
        cache_file=str(tmp_path / "not-present.json"),
    )
    auth._expires = time.time() + 3600
    with pytest.raises(RuntimeError, match="client_id mismatch"):
        await auth.token()



@pytest.mark.asyncio
async def test_ttg_refresh_rotates_access_and_refresh_persistently(monkeypatch, tmp_path) -> None:
    from app.services import twitch_bot_auth as auth_module

    client_id = "generator_application"
    session = MagicMock()
    session.__aenter__.return_value = session
    urls: list[str] = []

    def fake_get(url: str, **kwargs):
        urls.append(url)
        cm = MagicMock()
        response = MagicMock(status=200)
        if url.startswith("https://twitchtokengenerator.com/api/refresh/"):
            assert kwargs["allow_redirects"] is False
            response.json = AsyncMock(return_value={
                "success": True,
                "client_id": client_id,
                "token": "new_access",
                "refresh": "new_refresh",
            })
        else:
            assert url == "https://id.twitch.tv/oauth2/validate"
            response.json = AsyncMock(return_value={
                "login": "radiobot",
                "client_id": client_id,
                "scopes": ["chat:read", "chat:edit"],
                "expires_in": 14400,
            })
        cm.__aenter__.return_value = response
        return cm

    session.get.side_effect = fake_get
    monkeypatch.setattr(auth_module.aiohttp, "ClientSession", lambda: session)
    cache = tmp_path / "ttg_secrets.json"
    auth = TwitchBotAuth(
        login="radiobot", client_id=client_id, client_secret="",
        refresh_token="old_refresh", access_token="old_access",
        refresh_provider="ttg", cache_file=str(cache),
    )
    assert await auth.token() == "new_access"
    assert urls == [
        "https://twitchtokengenerator.com/api/refresh/old_refresh",
        "https://id.twitch.tv/oauth2/validate",
    ]
    saved = json.loads(cache.read_text())
    assert saved["provider"] == "ttg"
    assert saved["access_token"] == "new_access"
    assert saved["refresh_token"] == "new_refresh"
    assert auth.seconds_until_refresh() is not None
    assert auth.seconds_until_refresh() > 10000

    # Restart: prefer the rotated credentials in cache over stale environment.
    second = TwitchBotAuth(
        login="radiobot", client_id=client_id, client_secret="",
        refresh_token="old_refresh", access_token="old_access",
        refresh_provider="ttg", cache_file=str(cache),
    )
    assert second._refresh == "new_refresh"
    assert second._access == "new_access"
    urls.clear()
    assert await second.token() == "new_access"
    assert urls == ["https://id.twitch.tv/oauth2/validate"]


@pytest.mark.asyncio
async def test_ttg_refuses_wrong_generator_client_id(monkeypatch, tmp_path) -> None:
    from app.services import twitch_bot_auth as auth_module

    session = MagicMock()
    session.__aenter__.return_value = session
    cm = MagicMock()
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value={
        "success": True, "client_id": "someone_elses_app",
        "token": "new_access", "refresh": "new_refresh",
    })
    cm.__aenter__.return_value = response
    session.get.return_value = cm
    monkeypatch.setattr(auth_module.aiohttp, "ClientSession", lambda: session)

    cache = tmp_path / "oauth.json"
    auth = TwitchBotAuth(
        login="radiobot", client_id="expected_app", client_secret="",
        refresh_token="old_refresh", access_token="old_access",
        refresh_provider="ttg", cache_file=str(cache),
    )
    with pytest.raises(RuntimeError, match="client ID mismatch"):
        await auth.token()
    assert not cache.exists()


@pytest.mark.asyncio
async def test_ttg_does_not_follow_redirects_or_log_tokens(monkeypatch, tmp_path) -> None:
    from app.services import twitch_bot_auth as auth_module

    session = MagicMock()
    session.__aenter__.return_value = session
    cm = MagicMock()
    response = MagicMock(status=302)
    cm.__aenter__.return_value = response
    session.get.return_value = cm
    monkeypatch.setattr(auth_module.aiohttp, "ClientSession", lambda: session)
    auth = TwitchBotAuth(
        login="radiobot", client_id="app", client_secret="",
        refresh_token="sensitive/token?&=", access_token="access",
        refresh_provider="ttg", cache_file=str(tmp_path / "oauth.json"),
    )
    with pytest.raises(RuntimeError) as exc:
        await auth.token()
    assert "sensitive" not in str(exc.value)
    args, kwargs = session.get.call_args
    assert kwargs["allow_redirects"] is False
    assert args[0].endswith("sensitive%2Ftoken%3F%26%3D")


def test_ttg_cache_isolated_from_other_oauth_providers(tmp_path) -> None:
    cache = tmp_path / "oauth.json"
    cache.write_text(json.dumps({
        "login": "radiobot", "client_id": "app",
        "provider": "twitch", "refresh_token": "old_app_refresh",
    }))
    auth = TwitchBotAuth(
        login="radiobot", client_id="app", client_secret="",
        refresh_token="ttg_refresh", refresh_provider="ttg",
        cache_file=str(cache),
    )
    assert auth._refresh == "ttg_refresh"
