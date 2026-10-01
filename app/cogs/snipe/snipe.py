"""Snipe: показывает последние удалённые и изменённые сообщения."""
from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.core import embeds
from app.core.base import MegaCog
from app.utils.format import relative

if TYPE_CHECKING:
    from app.core.bot import MegaBot

_MAX_ENTRIES = 10
_MAX_TRACKED_CHANNELS = 400
_STALE_SECONDS = 7200.0


class SnipeCog(MegaCog, name="Snipe"):
    def __init__(self, bot: MegaBot) -> None:
        super().__init__(bot)
        self._deleted: dict[tuple[int, int], deque[discord.Message]] = {}
        self._edited: dict[tuple[int, int], deque[discord.Message]] = {}
        self._last_touch: dict[tuple[int, int], float] = {}

    def _record(
        self, store: dict[tuple[int, int], deque[discord.Message]], key: tuple[int, int], message: discord.Message
    ) -> None:
        now = time.monotonic()
        store.setdefault(key, deque(maxlen=_MAX_ENTRIES)).append(message)
        self._last_touch[key] = now
        if len(self._last_touch) <= _MAX_TRACKED_CHANNELS:
            return
        cutoff = now - _STALE_SECONDS
        for stale in [k for k, touched in self._last_touch.items() if touched < cutoff]:
            self._drop(stale)
        overflow = len(self._last_touch) - _MAX_TRACKED_CHANNELS
        if overflow > 0:
            oldest = sorted(self._last_touch.items(), key=lambda item: item[1])[:overflow]
            for key_evict, _ in oldest:
                self._drop(key_evict)

    def _drop(self, key: tuple[int, int]) -> None:
        self._last_touch.pop(key, None)
        self._deleted.pop(key, None)
        self._edited.pop(key, None)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        self._record(self._deleted, (message.guild.id, message.channel.id), message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.author.bot or before.guild is None:
            return
        if before.content == after.content:
            return
        self._record(self._edited, (before.guild.id, before.channel.id), before)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        guild = getattr(channel, "guild", None)
        if guild is None:
            return
        self._drop((guild.id, channel.id))

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        for key in [k for k in self._last_touch if k[0] == guild.id]:
            self._drop(key)

    @staticmethod
    def _mention_author(message: discord.Message) -> str:
        return f"{message.author.mention} ({message.author.display_name})"

    def _embed(self, message: discord.Message) -> discord.Embed:
        content = message.content or "*нет текста, только вложение*"
        embed = embeds.info(f"✏️ Изменённое сообщение: {message.author}", content[:1000])
        embed.add_field(name="Когда", value=relative(message.created_at), inline=True)
        if message.attachments:
            embed.add_field(name="Вложения", value="\n".join(a.url for a in message.attachments), inline=False)
        return embed

    @app_commands.command(name="snipe", description="Показать последние удалённые сообщения в канале")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def snipe(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                embed=embeds.error("Недоступно", "Команда работает только в текстовом канале сервера."),
                ephemeral=True,
            )
            return
        messages = self._deleted.get((interaction.guild.id, interaction.channel.id))
        if not messages:
            await interaction.response.send_message(embed=embeds.info("Пусто", "Удалённых сообщений в этом канале нет."), ephemeral=True)
            return
        latest = messages[-1]
        embed = embeds.warning("🗑️ Удалённое сообщение", latest.content or "*нет текста*")
        embed.add_field(name="Автор", value=self._mention_author(latest), inline=True)
        embed.add_field(name="Когда", value=relative(latest.created_at), inline=True)
        if latest.attachments:
            embed.add_field(name="Вложения", value="\n".join(a.url for a in latest.attachments), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="editsnipe", description="Показать последние изменённые сообщения в канале")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def editsnipe(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                embed=embeds.error("Недоступно", "Команда работает только в текстовом канале сервера."),
                ephemeral=True,
            )
            return
        messages = self._edited.get((interaction.guild.id, interaction.channel.id))
        if not messages:
            await interaction.response.send_message(embed=embeds.info("Пусто", "Изменённых сообщений в этом канале нет."), ephemeral=True)
            return
        latest = messages[-1]
        embed = self._embed(latest)
        embed.add_field(name="Автор", value=self._mention_author(latest), inline=True)
        await interaction.response.send_message(embed=embed)
