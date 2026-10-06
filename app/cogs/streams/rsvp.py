"""Команда /stream_rsvp и роль «На стриме» за реакцию 🔔 на старт-анонсе."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.streams.stream_announce import RSVP_EMOJI, rsvp_users
from app.core import embeds
from app.services.stream_rsvp import RSVP_ROLE_NAME, StreamRsvpStore, resolve_rsvp_role

if TYPE_CHECKING:
    from app.core.bot import MegaBot
    from app.services.kick_service import KickService
    from app.services.twitch_service import TwitchService
    from app.services.vk_video_service import VkVideoService

logger = logging.getLogger("bot.cogs")

_PLATFORM_NAMES = {"twitch": "Twitch", "kick": "Kick", "vk_video": "VK Видео"}


class StreamRsvp(commands.Cog):
    """Список откликнувшихся 🔔 на пост «Стрим начался» + выдача роли «На стриме»."""

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
        self._missing_role_warned: set[int] = set()
        self._perm_warned: set[int] = set()

    def _targets(self) -> list[tuple[str, int, StreamRsvpStore]]:
        """(название платформы, id канала уведомлений, rsvp-store) для настроенных стримов."""
        config = self.bot.config
        targets: list[tuple[str, int, StreamRsvpStore]] = []
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

    # -------------------------------------------------- роль «На стриме» за 🔔
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self._rsvp_role(payload, remove=False)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self._rsvp_role(payload, remove=True)

    async def _announce_store(self, guild_id: int, message_id: int) -> StreamRsvpStore | None:
        """rsvp-store, чей старт-анонс совпал с сообщением этого guild (иначе None)."""
        for _name, channel_id, store in self._targets():
            if await store.message_id() != message_id:
                continue
            channel = self.bot.get_channel(channel_id)
            guild = getattr(channel, "guild", None)
            if guild is None or guild.id != guild_id:
                continue
            return store
        return None

    async def _rsvp_role(self, payload: discord.RawReactionActionEvent, *, remove: bool) -> None:
        """Выдаёт или снимает роль «На стриме» по реакции 🔔 под старт-анонсом.

        raw-события — сообщение может не быть в кэше (рестарт). Роль ищется по
        ``STREAM_RSVP_ROLE_ID``, иначе по имени «На стриме»; не нашли — варн раз на guild.
        """
        if payload.guild_id is None or str(payload.emoji) != RSVP_EMOJI:
            return
        if self.bot.user is not None and payload.user_id == self.bot.user.id:
            return
        store = await self._announce_store(payload.guild_id, payload.message_id)
        if store is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        role = resolve_rsvp_role(guild, self.bot.config.stream_rsvp_role_id)
        if role is None:
            if guild.id not in self._missing_role_warned:
                self._missing_role_warned.add(guild.id)
                logger.warning(
                    "RSVP: роль «%s» не найдена — создайте её или задайте STREAM_RSVP_ROLE_ID",
                    RSVP_ROLE_NAME,
                )
            return
        member = guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except discord.HTTPException:
                return
        try:
            if remove:
                await member.remove_roles(role, reason="Снята реакция 🔔 под старт-анонсом")
            else:
                await member.add_roles(role, reason="Реакция 🔔 — пойду смотреть стрим")
        except (discord.Forbidden, discord.HTTPException):
            if guild.id not in self._perm_warned:
                self._perm_warned.add(guild.id)
                logger.warning(
                    "RSVP: не удалось изменить роль «%s» — проверьте Manage Roles и иерархию ролей",
                    role.name,
                    exc_info=True,
                )
            return
        if not remove:
            try:
                await store.add_granted(payload.user_id)
            except Exception:
                logger.debug("Не удалось запомнить выданную роль RSVP", exc_info=True)

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
