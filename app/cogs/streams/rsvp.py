"""Команда /stream_rsvp: кто откликнулся на старт-анонс стрима (реакция 🔔)."""
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.streams.stream_announce import rsvp_users
from app.core import embeds

if TYPE_CHECKING:
    from app.core.bot import MegaBot
    from app.services.kick_service import KickService
    from app.services.twitch_service import TwitchService
    from app.services.vk_video_service import VkVideoService

_PLATFORM_NAMES = {"twitch": "Twitch", "kick": "Kick", "vk_video": "VK Видео"}


class StreamRsvp(commands.Cog):
    """Список откликнувшихся 🔔 на пост «Стрим начался»."""

    def __init__(
        self,
        bot: MegaBot,
        twitch: TwitchService,
        kick: KickService,
        vk_video: VkVideoService,
    ) -> None:
        self.bot = bot
        self.twitch = twitch
        self.kick = kick
        self.vk_video = vk_video

    def _targets(self) -> list[tuple[str, int, object]]:
        """(название платформы, id канала уведомлений, rsvp-store) для настроенных стримов."""
        config = self.bot.config
        targets: list[tuple[str, int, object]] = []
        if config.twitch_channels and config.twitch_notify_channel_id:
            store = self.twitch.rsvp_store(config.twitch_channels[0])
            targets.append(("Twitch", config.twitch_notify_channel_id, store))
        if config.kick_channel_slug and config.kick_notify_channel_id:
            targets.append(("Kick", config.kick_notify_channel_id, self.kick.rsvp_store()))
        if config.vk_channel_slug and config.vk_notify_channel_id:
            targets.append(("VK Видео", config.vk_notify_channel_id, self.vk_video.rsvp_store()))
        return targets

    def _notify_channel(self, channel_id: int) -> discord.TextChannel | None:
        for guild in self.bot.guilds:
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                return channel
        return None

    @app_commands.command(name="stream_rsvp", description="Кто откликнулся на анонс стрима (реакция 🔔)")
    @app_commands.describe(platform="Платформа стрима (по умолчанию — все настроенные)")
    @app_commands.choices(
        platform=[
            app_commands.Choice(name="Twitch", value="twitch"),
            app_commands.Choice(name="Kick", value="kick"),
            app_commands.Choice(name="VK Видео", value="vk_video"),
        ]
    )
    @app_commands.guild_only()
    async def stream_rsvp(self, interaction: discord.Interaction, platform: str | None = None) -> None:
        targets = self._targets()
        if platform:
            name = _PLATFORM_NAMES.get(platform)
            targets = [t for t in targets if t[0] == name]
        if not targets:
            await interaction.response.send_message(
                embed=embeds.error("Нет данных", "Стримы с каналом уведомлений не настроены."),
                ephemeral=True,
            )
            return
        embed = discord.Embed(title="🔔 Кто откликнулся на стрим", color=0x5865F2)
        for name, channel_id, store in targets:
            channel = self._notify_channel(channel_id)
            if channel is None:
                embed.add_field(name=name, value="канал уведомлений не найден", inline=False)
                continue
            users = await rsvp_users(channel, store=store)  # type: ignore[arg-type]
            if users is None:
                embed.add_field(name=name, value="анонс ещё не публиковался", inline=False)
                continue
            lines = [f"{user.mention} ({user.display_name})" for user in users]
            value = "\n".join(lines) if lines else "пока никто не откликнулся"
            embed.add_field(name=f"{name} • {len(users)}", value=value, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)
