"""Twitch: уведомления о стримах (sticky-сообщение, пинг роли, статус бота) и /twitch_status."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import tasks

from app.core import embeds
from app.core.base import MegaCog
from app.core.stream_state import stream_activity
from app.services.twitch_service import TwitchService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")


class TwitchCog(MegaCog, name="TwitchStatus"):
    def __init__(self, bot: MegaBot, twitch: TwitchService) -> None:
        super().__init__(bot)
        self.twitch = twitch

    async def cog_load(self) -> None:
        if self.bot.config.twitch_channels:
            self.poll_loop.change_interval(seconds=self.bot.config.twitch_poll_seconds)
            self.poll_loop.start()

    async def cog_unload(self) -> None:
        self.poll_loop.cancel()
        await self.twitch.aclose()

    @tasks.loop(seconds=300.0)
    async def poll_loop(self) -> None:
        live: dict[str, dict] = {}
        for channel in self.bot.config.twitch_channels:
            try:
                status = await self._check(channel)
                if status is not None:
                    live[channel] = status
            except Exception:
                logger.exception("Twitch: ошибка проверки канала %s", channel)
        if live:
            status = next(iter(live.values()))
            await self._set_presence(status["title"], int(status.get("viewers") or 0))
        else:
            try:
                await self.bot.change_presence(activity=stream_activity(None))
            except Exception:
                logger.debug("Twitch: не удалось сменить присутствие", exc_info=True)

    @poll_loop.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()

    async def _check(self, channel: str) -> dict | None:
        status = await self.twitch.channel_status(channel)
        if status is not None:
            await self._sticky_live(status)
            return status
        await self._sticky_offline(channel)
        return None

    async def _sticky_live(self, status: dict) -> None:
        config = self.bot.config
        channel = self._notify_channel()
        if channel is None:
            return
        embed = self._status_embed(status)
        message_id = await self.twitch.sticky_message_id(status["login"])
        if message_id is not None:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed)
                return
            except discord.HTTPException:
                pass
        content = ""
        if config.twitch_ping_role_id:
            role = channel.guild.get_role(config.twitch_ping_role_id)
            if role is not None:
                content = role.mention
        message = await channel.send(content, embed=embed)
        await self.twitch.set_sticky_message(status["login"], message.id)

    async def _sticky_offline(self, channel_name: str) -> None:
        channel = self._notify_channel()
        message_id = await self.twitch.sticky_message_id(channel_name)
        if channel is None or message_id is None:
            return
        try:
            message = await channel.fetch_message(message_id)
            embed = embeds.info("Стрим завершён", f"Канал `{channel_name}` офлайн. Спасибо за просмотр!")
            await message.edit(embed=embed, content="")
        except discord.HTTPException:
            pass
        await self.twitch.clear_sticky_message(channel_name)

    def _notify_channel(self) -> discord.TextChannel | None:
        channel_id = self.bot.config.twitch_notify_channel_id
        if not channel_id:
            return None
        for guild in self.bot.guilds:
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                return channel
        return None

    async def _set_presence(self, title: str | None, viewers: int = 0) -> None:
        try:
            await self.bot.change_presence(activity=stream_activity(title, viewers))
        except Exception:
            logger.debug("Twitch: не удалось сменить присутствие", exc_info=True)

    @staticmethod
    def _status_embed(status: dict) -> discord.Embed:
        embed = embeds.info("🔴 Twitch: стрим начался", f"**[{status['title']}](https://www.twitch.tv/{status['login']})**")
        embed.set_thumbnail(url=status["thumbnail"])
        embed.add_field(name="Зрители", value=str(status["viewers"]), inline=True)
        embed.add_field(name="Категория", value=status["category"], inline=True)
        return embed

    @app_commands.command(name="twitch_status", description="Статус Twitch-канала")
    @app_commands.describe(channel="Ник канала (по умолчанию из конфигурации)")
    @app_commands.guild_only()
    async def twitch_status(self, interaction: discord.Interaction, channel: str | None = None) -> None:
        login = channel or (self.bot.config.twitch_channels[0] if self.bot.config.twitch_channels else None)
        if not login:
            await interaction.response.send_message(
                embed=embeds.error("Не настроено", "Укажите канал или настройте TWITCH_CHANNELS."),
                ephemeral=True,
            )
            return
        try:
            status = await self.twitch.channel_status(login)
        except Exception as exc:
            await interaction.response.send_message(
                embed=embeds.error("Не удалось получить статус", f"{type(exc).__name__}: {exc}"),
                ephemeral=True,
            )
            return
        if status is None:
            embed = embeds.info(f"Twitch: {login}", "Канал сейчас **офлайн**.")
        else:
            embed = self._status_embed(status)
        await interaction.response.send_message(embed=embed)
