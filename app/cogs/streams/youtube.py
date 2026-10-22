"""YouTube LIVE: периодическая проверка + Showcase + Discord-анонсы."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import discord
from discord.ext import tasks
from yt_dlp.utils import UserNotLive

from app.cogs.streams.poll_guard import PollGuard
from app.cogs.streams.quiet import is_quiet
from app.cogs.streams.stream_announce import pin_sticky, unpin_sticky
from app.cogs.streams.stream_cards import card_presets, live_card, offline_card
from app.core.base import MegaCog, wait_ready_or_stop
from app.services.stream_session import StreamSessionStore
from app.services.youtube_data_api import YouTubeDataAPI
from app.services.youtube_live import probe_youtube_live

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")

_CHANNEL = "dendosich"
_DEFAULT_URL = "https://www.youtube.com/@Dendosich"
_SETTINGS = "panel.showcase.settings"
_ACTIVE = "stream:youtube:active"
_ANNOUNCED = "stream:youtube:last_announced"
_STICKY = "stream:youtube:sticky"
_SESSION = "stream:session:youtube:dendosich"


def _safe_channel_url(url: str) -> str:
    """Only permit a direct public YouTube channel path for yt-dlp requests."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        return _DEFAULT_URL
    if not parsed.path.strip("/") or parsed.username or parsed.password or parsed.port not in (None, 443):
        return _DEFAULT_URL
    return f"https://www.youtube.com{parsed.path.rstrip('/')}"


class YouTubeCog(MegaCog, name="YouTubeMonitor"):
    def __init__(self, bot: MegaBot) -> None:
        super().__init__(bot)
        self._guard = PollGuard()
        self._api = YouTubeDataAPI()

    async def cog_load(self) -> None:
        self.poll_loop.change_interval(seconds=self.bot.config.youtube_poll_seconds)
        self.poll_loop.start()

    async def cog_unload(self) -> None:
        self.poll_loop.cancel()

    @tasks.loop(seconds=300.0)
    async def poll_loop(self) -> None:
        try:
            await self.check_once()
            self._guard.ok("youtube")
        except Exception:
            self._guard.fail("youtube", "YouTube: ошибка проверки прямого эфира")

    @poll_loop.before_loop
    async def before_poll(self) -> None:
        await wait_ready_or_stop(self.bot, self.poll_loop)

    async def _channel_url(self) -> str:
        raw = await self.services.kv.get(_SETTINGS)
        try:
            settings = json.loads(raw or "{}")
        except (TypeError, ValueError):
            settings = {}
        url = settings.get("youtube_url", _DEFAULT_URL) if isinstance(settings, dict) else _DEFAULT_URL
        # An explicit blank URL in the admin panel disables monitoring.
        if not url:
            return ""
        return _safe_channel_url(str(url))

    def _notify_channel(self) -> discord.TextChannel | None:
        config = self.bot.config
        # Follow existing Twitch/Kick notification channel unless explicitly overridden.
        channel_id = config.youtube_notify_channel_id or config.twitch_notify_channel_id or config.kick_notify_channel_id
        if not channel_id:
            return None
        for guild in self.bot.guilds:
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                return channel
        return None

    async def check_once(self) -> None:
        url = await self._channel_url()
        if not url:
            await self._offline()
            return
        if self.bot.config.youtube_api_key:
            status = await self._api.channel_status(
                self.bot.config.youtube_api_key,
                active_video_id=str(await self.services.kv.get(_ACTIVE) or ""),
            )
        else:
            try:
                status = await asyncio.to_thread(probe_youtube_live, url)
            except UserNotLive:
                status = None
        # API/yt-dlp failures propagate: a failed request is NOT proof a stream ended.
        if status is None:
            await self._offline()
        else:
            await self._live(status)

    async def _live(self, status: dict[str, Any]) -> None:
        stream_id = str(status["id"])
        url = str(status["url"])
        kv = self.services.kv
        store = StreamSessionStore(kv, _SESSION)
        await store.capture(status, url=url)
        await kv.set(_ACTIVE, stream_id)
        announced = await kv.get(_ANNOUNCED)
        channel = self._notify_channel()
        if announced != stream_id:
            self.publish_event("stream", {"platform": "youtube", "status": "live", "url": url, "title": status["title"]})
        if channel is None:
            return

        embed = live_card("youtube", url=url, status=status, session=await store.load(),
                          preset=await card_presets(kv))
        sticky = await kv.get(_STICKY)
        if announced == stream_id:
            if sticky and sticky.isdigit():
                try:
                    message = await channel.fetch_message(int(sticky))
                    await message.edit(embed=embed)
                except discord.HTTPException:
                    logger.debug("YouTube: не удалось обновить карточку", exc_info=True)
            return

        # New broadcast: only mark announced AFTER successfully sending the message.
        content = ""
        ping_role_id = (
            self.bot.config.youtube_ping_role_id
            or self.bot.config.twitch_ping_role_id
            or self.bot.config.kick_ping_role_id
        )
        if ping_role_id and not is_quiet(self.bot.config):
            role = channel.guild.get_role(ping_role_id)
            if role:
                content = role.mention
        message = await channel.send(content=content, embed=embed)
        await kv.set(_STICKY, str(message.id))
        await kv.set(_ANNOUNCED, stream_id)
        await pin_sticky(message)

    async def _offline(self) -> None:
        kv = self.services.kv
        active = await kv.get(_ACTIVE)
        if not active:
            return
        # Hide LIVE on Showcase immediately, even when the cached session is fresh.
        await kv.delete(_ACTIVE)
        self.publish_event("stream", {"platform": "youtube", "status": "offline", "url": _DEFAULT_URL})
        channel = self._notify_channel()
        sticky = await kv.get(_STICKY)
        if channel is None or not sticky or not sticky.isdigit():
            return
        session = await StreamSessionStore(kv, _SESSION).load()
        try:
            message = await channel.fetch_message(int(sticky))
            await message.edit(
                content="",
                embed=offline_card("youtube", url=_DEFAULT_URL, session=session,
                                   vod_url=f"https://www.youtube.com/watch?v={active}",
                                   preset=await card_presets(kv)),
            )
            await unpin_sticky(message)
        except discord.HTTPException:
            logger.debug("YouTube: не удалось закрыть sticky-карточку", exc_info=True)
        await kv.delete(_STICKY)
