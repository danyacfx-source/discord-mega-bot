"""VK Видео: уведомления о LIVE-трансляциях (sticky-сообщение, пинг роли) и /vk_status."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import tasks

from app.cogs.streams.abort_alert import abort_alert
from app.cogs.streams.archive import needs_seal, seal_archive
from app.cogs.streams.poll_guard import PollGuard
from app.cogs.streams.quiet import is_quiet
from app.cogs.streams.stream_announce import pin_sticky, post_rsvp, unpin_sticky
from app.cogs.streams.stream_cards import live_card, offline_card
from app.cogs.streams.stream_role import update_stream_role
from app.core import embeds
from app.core.base import MegaCog, wait_ready_or_stop
from app.core.stream_state import stream_activity
from app.services.vk_video_service import VkVideoService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")


class VkVideoCog(MegaCog, name="VkVideo"):
    def __init__(self, bot: MegaBot, vk_video: VkVideoService) -> None:
        super().__init__(bot)
        self.vk_video = vk_video
        self._guard = PollGuard()

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
                # Табло живёт быстрее базового поллинга, пока стрим идёт.
                self.poll_loop.change_interval(seconds=self.bot.config.stream_sticky_poll_seconds)
            else:
                await self._sticky_offline(slug)
                await self._set_presence(None, 0)
                self.poll_loop.change_interval(seconds=self.bot.config.vk_poll_seconds)
            self._guard.ok("vk_video")
        except Exception:
            self._guard.fail("vk_video", f"VK Видео: ошибка проверки трансляции {slug}")

    @poll_loop.before_loop
    async def _before_poll(self) -> None:
        await wait_ready_or_stop(self.bot, self.poll_loop)

    async def _set_presence(self, title: str | None, viewers: int = 0) -> None:
        try:
            await self.bot.change_presence(activity=stream_activity(title, viewers))
        except Exception:
            logger.debug("VK Видео: не удалось сменить присутствие", exc_info=True)

    async def _sticky_live(self, status: dict[str, Any]) -> None:
        await update_stream_role(self.bot, enable=True)
        config = self.bot.config
        channel = self._notify_channel()
        if channel is None:
            return
        slug = str(status["slug"])
        url = str(status.get("url") or f"https://live.vkvideo.ru/{slug}")
        session = await self.vk_video.session_store(slug).capture(status, url=url)
        embed = live_card("vk_video", url=url, status=status, session=session)
        message_id = await self.vk_video.sticky_message_id()
        if message_id is not None:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed)
                return
            except discord.HTTPException:
                pass
        content = ""
        if config.vk_ping_role_id and not is_quiet(config):  # ночью — без пинга
            role = channel.guild.get_role(config.vk_ping_role_id)
            if role is not None:
                content = role.mention
        message = await channel.send(content, embed=embed)
        await self.vk_video.set_sticky_message(message.id)
        await pin_sticky(message)
        await post_rsvp(
            channel,
            store=self.vk_video.rsvp_store(),
            title=str(status.get("title") or ""),
            url=url,
        )

    async def _sticky_offline(self, slug: str) -> None:
        await update_stream_role(self.bot, enable=False)
        store = self.vk_video.session_store(slug)
        session = await store.load()
        url = (session or {}).get("url") or f"https://live.vkvideo.ru/{slug}"
        vod_url = f"https://vkvideo.ru/@{slug}"
        archive = self.vk_video.archive_store(slug)
        if await needs_seal(archive, session):
            await seal_archive(
                archive,
                session,
                platform="vk_video",
                url=str(url),
                vod_url=vod_url,
                max_age_days=self.bot.config.stream_archive_days,
            )
        channel = self._notify_channel()
        message_id = await self.vk_video.sticky_message_id()
        if channel is None or message_id is None:
            return
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(embed=offline_card("vk_video", url=url, session=session, vod_url=vod_url), content="")
            await unpin_sticky(message)
        except discord.HTTPException:
            pass
        await self.vk_video.clear_sticky_message()
        # Сессию не чистим — это «последний эфир» для карточек и оверлея.
        await abort_alert(
            channel,
            session=session,
            label="VK Видео",
            url=url,
            threshold_minutes=self.bot.config.stream_abort_alert_minutes,
        )

    def _notify_channel(self) -> discord.TextChannel | None:
        channel_id = self.bot.config.vk_notify_channel_id
        if not channel_id:
            return None
        for guild in self.bot.guilds:
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                return channel
        return None

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
        store = self.vk_video.session_store(slug)
        session = await store.load()
        if status is None or not status.get("live"):
            url = (session or {}).get("url") or f"https://live.vkvideo.ru/{slug}"
            embed = offline_card("vk_video", url=url, session=session, vod_url=f"https://vkvideo.ru/@{slug}")
        else:
            url = str(status.get("url") or f"https://live.vkvideo.ru/{slug}")
            embed = live_card("vk_video", url=url, status=status, session=session)
        await interaction.response.send_message(embed=embed)
