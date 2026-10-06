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
from app.services.stream_session import session_is_live

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
        """(ключ платформы, id канала уведомлений, rsvp-store) для настроенных стримов."""
        config = self.bot.config
        targets: list[tuple[str, int, StreamRsvpStore]] = []
        if config.twitch_channels and config.twitch_notify_channel_id:
            store = self.twitch.rsvp_store(config.twitch_channels[0])
            targets.append(("twitch", config.twitch_notify_channel_id, store))
        if config.kick_channel_slug and config.kick_notify_channel_id:
            targets.append(("kick", config.kick_notify_channel_id, self.kick.rsvp_store()))
        if config.vk_channel_slug and config.vk_notify_channel_id:
            targets.append(("vk_video", config.vk_notify_channel_id, self.vk_video.rsvp_store()))
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

    async def _announce_target(self, guild_id: int, message_id: int) -> tuple[str, StreamRsvpStore] | None:
        """(ключ платформы, rsvp-store), чей старт-анонс совпал с сообщением этого guild."""
        for platform, channel_id, store in self._targets():
            if await store.message_id() != message_id:
                continue
            channel = self.bot.get_channel(channel_id)
            guild = getattr(channel, "guild", None)
            if guild is None or guild.id != guild_id:
                continue
            return platform, store
        return None

    async def _stream_live(self, platform: str) -> bool:
        """Стрим реально идёт: поллинг дописывает session-store только во время эфира."""
        config = self.bot.config
        if platform == "twitch":
            if not config.twitch_channels:
                return False
            session = await self.twitch.session_store(config.twitch_channels[0]).load()
            poll = config.twitch_poll_seconds
        elif platform == "kick":
            if not config.kick_channel_slug:
                return False
            session = await self.kick.session_store(config.kick_channel_slug).load()
            poll = config.kick_poll_seconds
        elif platform == "vk_video":
            if not config.vk_channel_slug:
                return False
            session = await self.vk_video.session_store(config.vk_channel_slug).load()
            poll = config.vk_poll_seconds
        else:
            return False
        return session_is_live(
            session,
            poll_seconds=poll,
            sticky_seconds=config.stream_sticky_poll_seconds,
        )

    async def _rsvp_role(self, payload: discord.RawReactionActionEvent, *, remove: bool) -> None:
        """Выдаёт или снимает роль «На стриме» по реакции 🔔 под старт-анонсом.

        raw-события — сообщение может не быть в кэше (рестарт). Роль ищется по
        ``STREAM_RSVP_ROLE_ID``, иначе по имени «На стриме»; не нашли — варн раз на guild.
        Выдача — только пока стрим идёт (свежий session-store): поздний 🔔 вне эфира
        роль не добавляет, снятие работает всегда.
        """
        if payload.guild_id is None or str(payload.emoji) != RSVP_EMOJI:
            return
        if self.bot.user is not None and payload.user_id == self.bot.user.id:
            return
        target = await self._announce_target(payload.guild_id, payload.message_id)
        if target is None:
            return
        platform, store = target
        if not remove and not await self._stream_live(platform):
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
            targets = [t for t in targets if t[0] == platform]
        if not targets:
            await interaction.response.send_message(
                embed=embeds.error("Нет данных", "Стримы с каналом уведомлений не настроены."),
                ephemeral=True,
            )
            return
        embed = discord.Embed(title="🔔 Кто откликнулся на стрим", color=0x5865F2)
        for target_platform, channel_id, store in targets:
            name = _PLATFORM_NAMES[target_platform]
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
