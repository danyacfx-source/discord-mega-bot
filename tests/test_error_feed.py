"""Ошибки бота уходят эмбедом в канал модерации (и в веб-ленту /audit)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from app.core.bot import MegaBot
from app.services.logging_service import LoggingService


@pytest.mark.asyncio
async def test_notify_error_feed_posts_mod_embed() -> None:
    bot = MegaBot.__new__(MegaBot)
    bot.services = SimpleNamespace(logging=AsyncMock())
    await bot._notify_error_feed(None, "Событие on_message: ValueError: boom")

    send = bot.services.logging.send_embed
    send.assert_awaited_once()
    args = send.await_args
    assert args.kwargs.get("category") == "mod"
    embed = args.args[1]
    assert isinstance(embed, discord.Embed)
    assert "ValueError: boom" in (embed.description or "")


@pytest.mark.asyncio
async def test_notify_error_feed_without_services_is_noop() -> None:
    bot = MegaBot.__new__(MegaBot)
    bot.services = None
    await bot._notify_error_feed(None, "text")  # не должно упасть


@pytest.mark.asyncio
async def test_logging_send_embed_survives_guildless_error() -> None:
    """guild=None (ЛС/DM) — emit в фид проходит, пост в канал пропускается."""
    settings = SimpleNamespace(get=AsyncMock(return_value={}))
    logging_service = LoggingService(settings, SimpleNamespace(config=SimpleNamespace()))
    await logging_service.send_embed(None, discord.Embed(title="t"), category="mod")
    settings.get.assert_not_awaited()
