"""Тесты welcome-карточки: рендер PNG, отправка файлом, фолбэк без Pillow-ошибок."""
from __future__ import annotations

import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from app.cogs.administration.greetings import GreetingsCog
from app.config import Config
from app.utils.welcome_card import render_welcome_card


def _config(**overrides) -> Config:
    config = Config(
        token="x",
        prefix="!",
        db_path="bot.db",
        log_level="ERROR",
        status_activity="s",
        owner_id=None,
    )
    for key, value in overrides.items():
        object.__setattr__(config, key, value)
    return config


def _avatar_png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (256, 256), (90, 120, 200)).save(buffer, "PNG")
    return buffer.getvalue()


def test_render_welcome_card_returns_png() -> None:
    out = render_welcome_card(
        avatar_png=_avatar_png(),
        display_name="Длинное имя участника что точно не влезет",
        member_count=1234,
        guild_name="Тестовый сервер",
    )
    assert out[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(out) > 5000


def test_render_handles_broken_avatar_gracefully() -> None:
    with pytest.raises(Exception):
        render_welcome_card(
            avatar_png=b"\x00\x01not-a-png\x02",
            display_name="x",
            member_count=1,
            guild_name="g",
        )


class _Avatar:
    url = "https://cdn.example/avatar.png"

    def __init__(self, data: bytes | Exception) -> None:
        self._data = data

    def with_format(self, fmt: str) -> _Avatar:
        return self

    def with_size(self, size: int) -> _Avatar:
        return self

    async def read(self) -> bytes:
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


class _CaptureChannel(discord.TextChannel):
    def __init__(self) -> None:
        self.id = 555
        self.name = "welcome"
        self.sent: list = []

    async def send(self, *args, **kwargs):  # type: ignore[method-assign,override]
        self.sent.append((args, kwargs))
        return SimpleNamespace(id=1)


def _cog(config: Config) -> tuple[GreetingsCog, _CaptureChannel, SimpleNamespace]:
    settings = SimpleNamespace(get=AsyncMock(return_value={"welcome_channel_id": None}))
    channel = _CaptureChannel()
    guild = SimpleNamespace(
        id=1,
        get_channel=lambda cid: channel if cid == 555 else None,
        member_count=42,
        rules_channel=None,
        name="Тестовый",
    )
    bot = SimpleNamespace(config=config)
    return GreetingsCog(bot, settings), channel, guild  # type: ignore[arg-type]


def _member(guild, avatar: _Avatar) -> SimpleNamespace:
    return SimpleNamespace(
        display_avatar=avatar,
        display_name="Алиса",
        mention="<@111>",
        id=111,
        guild=guild,
    )


@pytest.mark.asyncio
async def test_public_join_sends_card_as_file() -> None:
    cog, channel, guild = _cog(_config(welcome_card=True, welcome_channel_id=555))
    member = _member(guild, _Avatar(_avatar_png()))

    await cog._public_join(member)  # type: ignore[arg-type]

    assert len(channel.sent) == 1
    _, kwargs = channel.sent[0]
    assert "file" in kwargs
    assert isinstance(kwargs["file"], discord.File)
    assert kwargs["embed"].image.url == "attachment://welcome.png"
    # файл действительно PNG
    kwargs["file"].fp.seek(0)
    assert kwargs["file"].fp.read(8) == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_public_join_without_card_is_plain_embed() -> None:
    cog, channel, guild = _cog(_config(welcome_card=False, welcome_channel_id=555))
    member = _member(guild, _Avatar(_avatar_png()))

    await cog._public_join(member)  # type: ignore[arg-type]

    _, kwargs = channel.sent[0]
    assert "file" not in kwargs
    assert kwargs["embed"].image.url is None


@pytest.mark.asyncio
async def test_public_join_falls_back_when_card_fails() -> None:
    cog, channel, guild = _cog(_config(welcome_card=True, welcome_channel_id=555))
    member = _member(guild, _Avatar(RuntimeError("аватар недоступен")))

    await cog._public_join(member)  # type: ignore[arg-type]

    assert len(channel.sent) == 1
    _, kwargs = channel.sent[0]
    assert "file" not in kwargs
    assert kwargs["embed"].title  # эмбед ушёл как обычно


def test_welcome_card_env_flag(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("WELCOME_CARD", "1")
    assert Config.from_env(tmp_path / "absent.env").welcome_card is True
    monkeypatch.setenv("WELCOME_CARD", "0")
    assert Config.from_env(tmp_path / "absent.env").welcome_card is False
