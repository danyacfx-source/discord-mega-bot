"""Фабрика embed-сообщений: единый стиль для всего бота."""
from __future__ import annotations

from datetime import UTC, datetime

import discord

_SUCCESS = discord.Color.brand_green()
_ERROR = discord.Color.brand_red()
_INFO = discord.Color.blurple()
_WARNING = discord.Color.orange()


def _base(
    color: discord.Color,
    title: str,
    description: str | None = None,
    footer: str | None = None,
    *,
    timestamp: bool = True,
) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    if timestamp:
        embed.timestamp = datetime.now(UTC)
    if footer:
        embed.set_footer(text=footer)
    return embed


def success(title: str, description: str | None = None, footer: str | None = None, *, timestamp: bool = True) -> discord.Embed:
    return _base(_SUCCESS, title, description, footer, timestamp=timestamp)


def error(title: str, description: str | None = None, footer: str | None = None, *, timestamp: bool = True) -> discord.Embed:
    return _base(_ERROR, title, description, footer, timestamp=timestamp)


def info(title: str, description: str | None = None, footer: str | None = None, *, timestamp: bool = True) -> discord.Embed:
    return _base(_INFO, title, description, footer, timestamp=timestamp)


def warning(title: str, description: str | None = None, footer: str | None = None, *, timestamp: bool = True) -> discord.Embed:
    return _base(_WARNING, title, description, footer, timestamp=timestamp)
