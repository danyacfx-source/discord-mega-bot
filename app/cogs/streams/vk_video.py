"""VK Видео: уведомления о LIVE-трансляциях (sticky-сообщение, пинг роли) и /vk_status."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import tasks

from app.core import embeds
from app.core.base import MegaCog
from app.core.stream_state import stream_activity
from app.services.vk_video_service import VkVideoService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")


class VkVideoCog(MegaCog, name="VkVideo"):
    def __init__(self, bot: MegaBot, vk_video: VkVideoService) -> None:
        super().__init__(bot)
        self.vk_video = vk_video

    async def cog_load(self) -> None:
        if self.bot.config.vk_channel_slug:
            self.poll_loop.change_interval(seconds=self.bot.config.vk_poll_seconds)
            self.poll_loop.start()

    async def cog_unload(self) -> None:
        self.poll_loop.cancel()
        await self.vk_video.aclose()

    # ---------------------------------------------------------------- стримы

    @tasks.loop(seconds=300.0)
    async def poll_loop(self) -> None:
        slug = self.bot.config.vk_channel_slug
        if not slug:
            return
        try:
            status = await self.vk_video.channel_status(slug)
            if status is not None and status.get("live"):
                await self._sticky_live(status)
                await self._set_presence(status["title"], 0)
            else:
                await self._sticky_offline(slug)
                await self._set_presence(None, 0)
        except Exception:
            logger.exception("VK Видео: ошибка проверки трансляции %s", slug)

    @poll_loop.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()

    async def _set_presence(self, title: str | None, viewers: int = 0) -> None:
        try:
            await self.bot.change_presence(activity=stream_activity(title, viewers))
        except Exception:
            logger.debug("VK Видео: не удалось сменить присутствие", exc_info=True)

    async def _sticky_live(self, status: dict) -> None:
        config = self.bot.config
        channel = self._notify_channel()
        if channel is None:
            return
        embed = self._status_embed(status)
        message_id = await self.vk_video.sticky_message_id()
        if message_id is not None:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed)
                return
            except discord.HTTPException:
                pass
        content = ""
        if config.vk_ping_role_id:
            role = channel.guild.get_role(config.vk_ping_role_id)
            if role is not None:
                content = role.mention
        message = await channel.send(content, embed=embed)
        await self.vk_video.set_sticky_message(message.id)

    async def _sticky_offline(self, slug: str) -> None:
        channel = self._notify_channel()
        message_id = await self.vk_video.sticky_message_id()
        if channel is None or message_id is None:
            return
        try:
            message = await channel.fetch_message(message_id)
            embed = embeds.info("Трансляция завершена", f"Канал `{slug}` офлайн. Спасибо за просмотр!")
            await message.edit(embed=embed, content="")
        except discord.HTTPException:
            pass
        await self.vk_video.clear_sticky_message()

    def _notify_channel(self) -> discord.TextChannel | None:
        channel_id = self.bot.config.vk_notify_channel_id
        if not channel_id:
            return None
        for guild in self.bot.guilds:
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                return channel
        return None

    @staticmethod
    def _status_embed(status: dict) -> discord.Embed:
        embed = embeds.info("🔴 VK Видео: трансляция идёт", f"**[{status['title']}]({status['url']})**")
        if status.get("description"):
            embed.add_field(name="Описание", value=status["description"][:1024], inline=False)
        return embed

    @app_commands.command(name="vk_status", description="Статус LIVE-трансляции VK Видео")
    @app_commands.guild_only()
    async def vk_status(self, interaction: discord.Interaction) -> None:
        slug = self.bot.config.vk_channel_slug
        if not slug:
            await interaction.response.send_message(
                embed=embeds.error("Не настроено", "Укажите VK_CHANNEL_SLUG в конфигурации."),
                ephemeral=True,
            )
            return
        status = await self.vk_video.channel_status(slug)
        if status is None:
            embed = embeds.info(f"VK Видео: {slug}", "Канал сейчас **офлайн**.")
        elif status.get("live"):
            embed = self._status_embed(status)
        else:
            embed = embeds.info(f"VK Видео: {status['title']}", "Трансляция сейчас **не идёт**.")
        await interaction.response.send_message(embed=embed)
