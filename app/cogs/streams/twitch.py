"""Twitch: уведомления о стримах (sticky-сообщение, пинг роли, статус бота) и /twitch_status."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import tasks

from app.cogs.streams.abort_alert import abort_alert
from app.cogs.streams.archive import needs_seal, seal_archive
from app.cogs.streams.poll_guard import PollGuard
from app.cogs.streams.quiet import is_quiet
from app.cogs.streams.stream_announce import pin_sticky, post_rsvp, unpin_sticky
from app.cogs.streams.stream_cards import card_presets, live_card, offline_card
from app.cogs.streams.stream_role import update_stream_role
from app.core import embeds
from app.core.base import MegaCog, wait_ready_or_stop
from app.core.embeds import BOT_NAME
from app.core.stream_state import stream_activity
from app.services.twitch_service import TwitchService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")


class TwitchCog(MegaCog, name="TwitchStatus"):
    def __init__(self, bot: MegaBot, twitch: TwitchService) -> None:
        super().__init__(bot)
        self.twitch = twitch
        self._guard = PollGuard()
        self._stream_feed_key: tuple[str, str, str] | None = None

    async def cog_load(self) -> None:
        if self.bot.config.twitch_channels:
            self.poll_loop.change_interval(seconds=self.bot.config.twitch_poll_seconds)
            self.poll_loop.start()

    async def cog_unload(self) -> None:
        self.poll_loop.cancel()
        await self.twitch.aclose()

    @tasks.loop(seconds=300.0)
    async def poll_loop(self) -> None:
        live: dict[str, dict[str, Any]] = {}
        for channel in self.bot.config.twitch_channels:
            try:
                status = await self._check(channel)
                if status is not None:
                    live[channel] = status
                self._guard.ok(f"twitch:{channel}")
            except Exception:
                self._guard.fail(f"twitch:{channel}", f"Twitch: ошибка проверки канала {channel}")
        if live:
            status = next(iter(live.values()))
            await self._set_presence(status["title"], int(status.get("viewers") or 0))
            # Табло живёт быстрее базового поллинга, пока стрим идёт.
            self.poll_loop.change_interval(seconds=self.bot.config.stream_sticky_poll_seconds)
        else:
            self.poll_loop.change_interval(seconds=self.bot.config.twitch_poll_seconds)
            if self.bot.config.kick_channel_slug:
                return
            try:
                await self.bot.change_presence(activity=stream_activity(None))
            except Exception:
                logger.debug("Twitch: не удалось сменить присутствие", exc_info=True)

    @poll_loop.before_loop
    async def _before_poll(self) -> None:
        await wait_ready_or_stop(self.bot, self.poll_loop)

    async def _check(self, channel: str) -> dict[str, Any] | None:
        status = await self.twitch.channel_status(channel)
        self._publish_stream(status, channel)
        if status is not None:
            await self._sticky_live(status)
            return status
        await self._sticky_offline(channel)
        return None

    def _publish_stream(self, status: dict[str, Any] | None, channel: str) -> None:
        """Публикует переход live/offline в живую ленту (не чаще реальных переходов)."""
        state = "live" if status is not None else "offline"
        key = ("twitch", channel, state)
        if key == self._stream_feed_key:
            return
        self._stream_feed_key = key
        data: dict[str, Any] = {"platform": "twitch", "status": state, "url": f"https://www.twitch.tv/{channel}"}
        if status is not None:
            data["title"] = str(status.get("title") or "")
            data["viewers"] = int(status.get("viewers") or 0)
        self.publish_event("stream", data)

    async def _sticky_live(self, status: dict[str, Any]) -> None:
        await update_stream_role(self.bot, enable=True)
        config = self.bot.config
        channel = self._notify_channel()
        if channel is None:
            return
        login = str(status["login"])
        url = f"https://www.twitch.tv/{login}"
        store = self.twitch.session_store(login)
        session = await store.capture(status, url=url)
        embed = live_card("twitch", url=url, status=status, session=session, preset=await card_presets(self.services.kv))
        message_id = await self.twitch.sticky_message_id(login)
        if message_id is not None:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed)
                return
            except discord.HTTPException:
                pass
        content = ""
        if config.twitch_ping_role_id and not is_quiet(config):  # ночью — без пинга
            role = channel.guild.get_role(config.twitch_ping_role_id)
            if role is not None:
                content = role.mention
        message = await channel.send(content, embed=embed)
        await self.twitch.set_sticky_message(login, message.id)
        await pin_sticky(message)
        await post_rsvp(
            channel,
            store=self.twitch.rsvp_store(login),
            title=str(status.get("title") or ""),
            url=url,
        )

    async def _sticky_offline(self, channel_name: str) -> None:
        await update_stream_role(self.bot, enable=False)
        store = self.twitch.session_store(channel_name)
        session = await store.load()
        url = f"https://www.twitch.tv/{channel_name}"
        channel = self._notify_channel()
        message_id = await self.twitch.sticky_message_id(channel_name)
        will_edit = channel is not None and message_id is not None
        archive = self.twitch.archive_store(channel_name)
        will_seal = await needs_seal(archive, session)
        vod_url = await self._vod_url(channel_name, session) if (will_edit or will_seal) else None
        if will_seal:
            await seal_archive(
                archive,
                session,
                platform="twitch",
                url=url,
                vod_url=vod_url,
                max_age_days=self.bot.config.stream_archive_days,
            )
        if not will_edit or channel is None or message_id is None:
            return
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(
                embed=offline_card("twitch", url=url, session=session, vod_url=vod_url,
                                   preset=await card_presets(self.services.kv)),
                content="",
            )
            await unpin_sticky(message)
        except discord.HTTPException:
            pass
        await self.twitch.clear_sticky_message(channel_name)
        # Сессию не чистим: она становится «последним эфиром» для карточек,
        # оверлея и панели; сброс произойдёт при старте нового стрима.
        await abort_alert(
            channel,
            session=session,
            label="Twitch",
            url=url,
            threshold_minutes=self.bot.config.stream_abort_alert_minutes,
        )

    async def _vod_url(self, login: str, session: dict[str, Any] | None) -> str | None:
        """Последний VOD через Helix, иначе страница записей канала."""
        user_id = str((session or {}).get("user_id") or "") or None
        try:
            vod = await self.twitch.latest_vod_url(login, user_id)
        except Exception:
            logger.debug("Twitch: не удалось получить VOD для %s", login, exc_info=True)
            vod = None
        return vod or f"https://www.twitch.tv/{login}/videos"

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

    @app_commands.command(name="twitch_clip", description="Создать клип с текущего Twitch-стрима")
    @app_commands.describe(title="Название клипа (по умолчанию — заголовок стрима)")
    @app_commands.guild_only()
    async def twitch_clip(self, interaction: discord.Interaction, title: str | None = None) -> None:
        config = self.bot.config
        login = config.twitch_channels[0] if config.twitch_channels else None
        if not login:
            await interaction.response.send_message(
                embed=embeds.error("Не настроено", "Укажите TWITCH_CHANNELS."),
                ephemeral=True,
            )
            return
        if not (config.twitch_client_id and config.twitch_client_secret and config.twitch_refresh_token):
            await interaction.response.send_message(
                embed=embeds.error(
                    "Клиппинг не настроен",
                    "Нужны TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET и TWITCH_REFRESH_TOKEN (scope clips:edit).",
                ),
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        status = await self.twitch.channel_status(login)
        if status is None:
            await interaction.followup.send(
                embed=embeds.error("Стрим не идёт", "Клип можно создать только во время эфира."),
                ephemeral=True,
            )
            return
        clip_title = title or str(status.get("title") or "")[:140]
        clip_url = await self.twitch.create_clip(login, title=clip_title)
        if not clip_url:
            await interaction.followup.send(
                embed=embeds.error("Не удалось создать клип", "Проверь TWITCH_REFRESH_TOKEN и scope clips:edit."),
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="🎬 Клип создан",
            url=clip_url,
            description=f"**[{clip_title}]({clip_url})**",
            color=0x9146FF,
        )
        embed.set_footer(text=f"{login} • {BOT_NAME}")
        embed.timestamp = datetime.now(UTC)
        await interaction.followup.send(embed=embed)

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
        url = f"https://www.twitch.tv/{login}"
        store = self.twitch.session_store(login)
        session = await store.load()
        preset = await card_presets(self.services.kv)
        if status is None:
            embed = offline_card("twitch", url=url, session=session, vod_url=await self._vod_url(login, session), preset=preset)
        else:
            embed = live_card("twitch", url=url, status=status, session=session, preset=preset)
        await interaction.response.send_message(embed=embed)
