"""Команды чата стримов: парсер Twitch IRC, диспетчер команд, монеты, опросы."""
from __future__ import annotations

import os
import time
from typing import Any

import pytest

from app.cogs.streams.chat_commands import parse_privmsg
from app.config import Config
from app.db.chat_coins_repository import ChatCoinsRepository
from app.db.database import Database
from app.services.chat_coins_service import ChatCoinsService
from app.services.chat_commands_service import ChatCommandsService, ChatMessage


@pytest.fixture
async def db(tmp_path):
    database = Database(os.path.join(tmp_path, "chat.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


def _config(tmp_path, monkeypatch, **overrides) -> Config:
    monkeypatch.setenv("BOT_TOKEN", "x")
    for key, value in overrides.items():
        monkeypatch.setenv(key, str(value))
    config = Config.from_env(tmp_path / "absent.env")
    object.__setattr__(config, "chat_cmd_cooldown", 0.0)
    return config


@pytest.fixture
def service(db, tmp_path, monkeypatch) -> ChatCommandsService:
    config = _config(tmp_path, monkeypatch)
    coins = ChatCoinsService(ChatCoinsRepository(db))
    return ChatCommandsService(config, coins)


class _Recorder:
    def __init__(self) -> None:
        self.replies: list[tuple[str, str]] = []

    async def __call__(self, reply_to: str, text: str) -> None:
        self.replies.append((reply_to, text))

    @property
    def last(self) -> str:
        return self.replies[-1][1]


@pytest.fixture
def kick(service: ChatCommandsService) -> tuple[ChatCommandsService, _Recorder]:
    recorder = _Recorder()
    service.register_platform("kick", reply=recorder)
    return service, recorder


def _msg(content: str, *, username: str = "viewer", is_mod: bool = False) -> ChatMessage:
    return ChatMessage(
        platform="kick",
        username=username,
        display_name=username.title(),
        content=content,
        is_mod=is_mod,
    )


# ---------------------------------------------------------------- парсер IRC

def test_parse_privmsg_with_tags() -> None:
    line = (
        "@badge-info=;badges=broadcaster/1;color=#FF0000;display-name=Streamer;mod=1;"
        "room-id=1;subscriber=0;turbo=0;user-type= "
        ":streamer!streamer@streamer.tmi.twitch.tv PRIVMSG #streamer :привет бот"
    )
    parsed = parse_privmsg(line)
    assert parsed is not None
    assert parsed.login == "streamer"
    assert parsed.display_name == "Streamer"
    assert parsed.text == "привет бот"
    assert parsed.channel == "streamer"
    assert parsed.is_mod is True


def test_parse_privmsg_without_tags_and_moderator_badge() -> None:
    line = ":someone!someone@someone.tmi.twitch.tv PRIVMSG #mychan :!ping"
    parsed = parse_privmsg(line)
    assert parsed is not None
    assert parsed.login == "someone"
    assert parsed.is_mod is False
    assert parsed.display_name == "someone"
    assert parsed.text == "!ping"

    mod_line = (
        "@badges=moderator/1;mod=1 :mod!mod@mod.tmi.twitch.tv PRIVMSG #mychan :ok"
    )
    parsed_mod = parse_privmsg(mod_line)
    assert parsed_mod is not None
    assert parsed_mod.is_mod is True


def test_parse_privmsg_ignores_non_privmsg() -> None:
    assert parse_privmsg("PING :tmi.twitch.tv") is None
    assert parse_privmsg(":tmi.twitch.tv 001 welcome") is None
    assert parse_privmsg("@badges= :someone!x@y.tmi.twitch.tv PRIVMSG #c") is None  # без текста


# ---------------------------------------------------------------- диспетчер

@pytest.mark.asyncio
async def test_ping_and_unknown_command(kick) -> None:
    service, recorder = kick
    await service.handle(_msg("!ping"))
    assert "pong" in recorder.last
    await service.handle(_msg("!нет_такой_команды"))
    assert len(recorder.replies) == 1  # неизвестные молчат


@pytest.mark.asyncio
async def test_help_lists_commands(kick) -> None:
    service, recorder = kick
    await service.handle(_msg("!помощь"))
    assert "!слоты" in recorder.last
    assert "!poll" in recorder.last


@pytest.mark.asyncio
async def test_disabled_config_silent(db, tmp_path, monkeypatch) -> None:
    config = _config(tmp_path, monkeypatch, CHAT_COMMANDS_ENABLED="0")
    service = ChatCommandsService(config, ChatCoinsService(ChatCoinsRepository(db)))
    recorder = _Recorder()
    service.register_platform("kick", reply=recorder)
    await service.handle(_msg("!ping"))
    assert recorder.replies == []


@pytest.mark.asyncio
async def test_bot_messages_ignored(kick) -> None:
    service, recorder = kick
    message = _msg("!ping")
    message.is_bot = True
    await service.handle(message)
    assert recorder.replies == []


@pytest.mark.asyncio
async def test_passive_coins_once_per_window(kick) -> None:
    service, recorder = kick
    await service.handle(_msg("просто пишу в чат"))
    await service.handle(_msg("ещё сообщение"))
    row = await service._coins.get("kick", "viewer")
    assert row is not None
    assert row["coins"] == 5
    assert row["messages"] == 1


@pytest.mark.asyncio
async def test_command_cooldown(kick) -> None:
    service, recorder = kick
    object.__setattr__(service._config, "chat_cmd_cooldown", 3.0)
    await service.handle(_msg("!ping"))
    await service.handle(_msg("!ping"))
    assert len(recorder.replies) == 1
    # с чужого ника — можно
    await service.handle(_msg("!ping", username="other"))
    assert len(recorder.replies) == 2


# ---------------------------------------------------------------- монеты/гемблинг

@pytest.mark.asyncio
async def test_slots_jackpot(kick, monkeypatch) -> None:
    service, recorder = kick
    await service._coins.add("kick", "viewer", "Viewer", 100)
    monkeypatch.setattr("app.services.chat_commands_service.random.choice", lambda seq: "7️⃣")
    await service.handle(_msg("!слоты 10"))
    assert "ВЫИГРЫШ" in recorder.last
    row = await service._coins.get("kick", "viewer")
    assert row["coins"] == 190  # 100 - 10 + 100 (x10)


@pytest.mark.asyncio
async def test_slots_insufficient_funds(kick) -> None:
    service, recorder = kick
    await service._coins.add("kick", "viewer", "Viewer", 5)
    await service.handle(_msg("!slots 50"))
    assert "баланса" in recorder.last
    row = await service._coins.get("kick", "viewer")
    assert row["coins"] == 5  # ставка не списана


@pytest.mark.asyncio
async def test_flip_win(kick, monkeypatch) -> None:
    service, recorder = kick
    await service._coins.add("kick", "viewer", "Viewer", 100)
    answers = iter(("heads", "heads"))  # ставка выбрана орлом, выпал орёл
    monkeypatch.setattr("app.services.chat_commands_service.random.choice", lambda seq: next(answers))
    await service.handle(_msg("!монетка 20 орёл"))
    assert "выигрыш" in recorder.last.lower()
    row = await service._coins.get("kick", "viewer")
    assert row["coins"] == 120  # 100 - 20 + 40


@pytest.mark.asyncio
async def test_top_leaderboard(db, tmp_path, monkeypatch) -> None:
    config = _config(tmp_path, monkeypatch)
    service = ChatCommandsService(config, ChatCoinsService(ChatCoinsRepository(db)))
    recorder = _Recorder()
    service.register_platform("kick", reply=recorder)
    await service._coins.add("kick", "alice", "Alice", 500)
    await service._coins.add("kick", "bob", "Bob", 300)
    await service.handle(_msg("!топ"))
    assert "Alice" in recorder.last
    assert recorder.last.index("Alice") < recorder.last.index("Bob")


@pytest.mark.asyncio
async def test_balance_newcomer(kick) -> None:
    service, recorder = kick
    await service.handle(_msg("!баланс"))
    assert "0" in recorder.last


# ---------------------------------------------------------------- опросы

@pytest.mark.asyncio
async def test_poll_flow_and_results(kick) -> None:
    service, recorder = kick
    await service.handle(_msg("!poll Что кушаем?|Пицца|Суши", username="boss", is_mod=True))
    assert "Пицца" in recorder.last and "Суши" in recorder.last

    await service.handle(_msg("2", username="voter1"))
    assert "голос учтён" in recorder.last
    await service.handle(_msg("1", username="voter2"))
    await service.handle(_msg("1", username="voter1"))  # перебил голос

    poll = service._polls["kick"]
    assert poll.votes == {"voter1": 0, "voter2": 0}

    poll.ends = time.monotonic() - 1
    await service.tick()
    assert "Победил: **Пицца**" in recorder.last
    assert "голосов 2" in recorder.last
    assert service.poll_remaining("kick") is None


@pytest.mark.asyncio
async def test_poll_requires_moderator_and_second_poll_blocked(kick) -> None:
    service, recorder = kick
    await service.handle(_msg("!poll Вопрос|А|Б", username="random"))
    assert recorder.replies == []  # не-мод молчит

    await service.handle(_msg("!poll Первый|А|Б", username="boss", is_mod=True))
    await service.handle(_msg("!poll Второй|А|Б", username="boss", is_mod=True))
    assert "уже идёт" in recorder.last


@pytest.mark.asyncio
async def test_poll_bad_usage(kick) -> None:
    service, recorder = kick
    await service.handle(_msg("!poll один вариант", username="boss", is_mod=True))
    assert "Использование" in recorder.last


# ---------------------------------------------------------------- uptime/ссылки

@pytest.mark.asyncio
async def test_uptime_uses_live_provider(kick) -> None:
    service, recorder = kick

    async def offline() -> dict[str, Any] | None:
        return None

    service.register_platform("kick", reply=recorder, live=offline)
    await service.handle(_msg("!uptime"))
    assert "не идёт" in recorder.last

    from datetime import UTC, datetime, timedelta

    started = (datetime.now(UTC) - timedelta(minutes=90)).isoformat()

    async def live_now() -> dict[str, Any] | None:
        return {"started_at": started, "viewers": 7}

    service.register_platform("kick", reply=recorder, live=live_now)
    await service.handle(_msg("!эфир"))
    assert "В эфире" in recorder.last
    assert "👁 7" in recorder.last


@pytest.mark.asyncio
async def test_links_from_config(service, tmp_path, monkeypatch) -> None:
    config = _config(
        tmp_path,
        monkeypatch,
        KICK_CHANNEL_SLUG="mychannel",
        SOCIALS_DISCORD="https://discord.gg/test",
    )
    service = ChatCommandsService(config, service._coins)
    recorder = _Recorder()
    service.register_platform("kick", reply=recorder)
    await service.handle(_msg("!links"))
    assert "kick.com/mychannel" in recorder.last
    assert "discord.gg/test" in recorder.last


# ---------------------------------------------------------------- модераторские

@pytest.mark.asyncio
async def test_so_only_for_mods(kick) -> None:
    service, recorder = kick
    await service.handle(_msg("!so friend", username="random"))
    assert recorder.replies == []
    await service.handle(_msg("!so friend", username="boss", is_mod=True))
    assert "@friend" in recorder.last


# ---------------------------------------------------------------- интеграция Kick

@pytest.mark.asyncio
async def test_kick_dispatch_maps_identity(service, tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    from app.cogs.streams.kick import KickCog

    recorder = _Recorder()
    service.register_platform("kick", reply=recorder)
    bot = SimpleNamespace(config=service._config)  # type: ignore[arg-type]
    cog = KickCog(bot, SimpleNamespace(), service)  # type: ignore[arg-type]

    data = {"sender": {"username": "Vasya", "identity": {"is_moderator": True}}, "content": "!so petr"}
    await cog._dispatch_command(data["sender"], "vasya", data)
    assert "@petr" in recorder.last  # is_mod проброшен из identity Kick

    data2 = {"sender": {"username": "guest", "identity": {}}, "content": "!so petr"}
    await cog._dispatch_command(data2["sender"], "guest", data2)
    assert len(recorder.replies) == 1  # не-мод молчит


# ---------------------------------------------------------------- config env

def test_chat_env_flags(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("CHAT_COMMANDS_ENABLED", "0")
    monkeypatch.setenv("CHAT_COIN_REWARD", "0")
    monkeypatch.setenv("CHAT_COMMAND_PREFIX", "?")
    monkeypatch.setenv("CHAT_POLL_SECONDS", "60")
    config = Config.from_env(tmp_path / "absent.env")
    assert config.chat_commands_enabled is False
    assert config.chat_coin_reward == 0
    assert config.chat_command_prefix == "?"
    assert config.chat_poll_seconds == 60
