"""Тест маршрутизации уведомлений о донатах.

Регрессия: донат без персонального VIP-кода не привязан к гильде, и код
раньше молча уходил в DONATION_NOTIFY_CHANNEL_ID — то есть в канал с
кнопкой «Поддержать», а не в канал донатов из настроек сервера.
"""
from __future__ import annotations

from types import SimpleNamespace

import discord
import pytest

from app.cogs.donations.donations import DonationsCog

GUILD_ID = 1524743223866556456
DONATION_CHANNEL = 1550271635045490688
BUTTON_CHANNEL = 1547376296378507304


class _FakeSettings:
    def __init__(self, channel_id):
        self._channel_id = channel_id
        self.requested: list[int] = []

    async def get(self, guild_id):
        self.requested.append(guild_id)
        return {"donation_channel_id": self._channel_id}


class _FakeChannel(discord.TextChannel):
    def __init__(self, channel_id):
        self.id = channel_id


def _make_bot(*, db_channel=DONATION_CHANNEL, notify_channel=BUTTON_CHANNEL, guild_id=GUILD_ID):
    channels = {
        DONATION_CHANNEL: _FakeChannel(DONATION_CHANNEL),
        BUTTON_CHANNEL: _FakeChannel(BUTTON_CHANNEL),
    }
    settings = _FakeSettings(db_channel)
    bot = SimpleNamespace(
        config=SimpleNamespace(
            guild_id=guild_id,
            donation_notify_channel_id=notify_channel,
        ),
        services=SimpleNamespace(settings=settings),
        guilds=[],
        get_channel=lambda cid: channels.get(int(cid or 0)),
    )
    return bot, settings


def _cog(bot):
    return DonationsCog(bot, donations=None)


@pytest.mark.asyncio
async def test_donation_without_code_goes_to_guild_setting():
    """Донат без кода (guild_id=None) обязан попасть в канал из настроек гильды."""
    bot, settings = _make_bot()
    cog = _cog(bot)

    channel = await cog._donation_channel(None)

    assert channel is not None, "канал донатов не найден"
    assert channel.id == DONATION_CHANNEL, (
        f"донат ушёл в {channel.id}, ожидался канал донатов {DONATION_CHANNEL}"
    )
    assert settings.requested == [GUILD_ID], "настройки основной гильды должны запрашиваться"


@pytest.mark.asyncio
async def test_donation_without_code_never_falls_into_button_channel():
    """Прямая проверка исходного бага: канал с кнопкой — не точка назначения."""
    bot, _ = _make_bot()
    cog = _cog(bot)

    channel = await cog._donation_channel(None)

    assert channel.id != BUTTON_CHANNEL, "донат не должен идти в канал с кнопкой «Поддержать»"


@pytest.mark.asyncio
async def test_donation_with_code_still_wins_by_link_guild():
    """С кодом привязка к гильде из ссылки остаётся приоритетной."""
    bot, settings = _make_bot()
    cog = _cog(bot)

    channel = await cog._donation_channel(GUILD_ID)

    assert channel.id == DONATION_CHANNEL
    assert settings.requested == [GUILD_ID]


@pytest.mark.asyncio
async def test_falls_back_to_env_when_guild_has_no_channel():
    """Если в настройках гильды канал не задан — работает DONATION_NOTIFY_CHANNEL_ID."""
    bot, _ = _make_bot(db_channel=None, notify_channel=999)
    cog = _cog(bot)
    bot.get_channel = lambda cid: _FakeChannel(999) if int(cid or 0) == 999 else None

    channel = await cog._donation_channel(None)

    assert channel is not None and channel.id == 999
