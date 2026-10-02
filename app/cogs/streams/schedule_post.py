"""Авто-пост нового расписания Twitch в закреплённый канал.

Канал — TWITCH_SCHEDULE_CHANNEL_ID (не задан — выкл). Каждый сегмент
анонсируется ровно один раз: дедуп по ключу `schedpost:{login}:{start_iso}`
в KV. SCHEDULE_POST_HOUR (0..23) ограничивает публикацию часом; -1 —
проверка на каждом тике (дедуп всё равно защитит от дублей).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from app.cogs.streams.quiet import resolve_tz
from app.cogs.streams.stats import _segment_line
from app.services.kv_service import KvService
from app.services.twitch_service import TwitchService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")

_TWITCH_PURPLE = 0x9146FF


class SchedulePostCog(commands.Cog, name="SchedulePost"):
    def __init__(
        self,
        bot: MegaBot,
        twitch: TwitchService,
        kv: KvService,
    ) -> None:
        self.bot = bot
        self.twitch = twitch
        self.kv = kv

    async def cog_load(self) -> None:
        config = self.bot.config
        if config.twitch_schedule_channel_id and config.twitch_channels:
            self.post_loop.start()
            logger.info(
                "SchedulePost: канал %s, час %s, каналы Twitch: %d",
                config.twitch_schedule_channel_id,
                config.schedule_post_hour,
                len(config.twitch_channels),
            )

    async def cog_unload(self) -> None:
        self.post_loop.cancel()

    def _key(self, login: str, start: datetime) -> str:
        return f"schedpost:{login}:{start.isoformat()}"

    @tasks.loop(minutes=30)
    async def post_loop(self) -> None:
        await self._tick()

    @post_loop.before_loop
    async def _before_post(self) -> None:
        try:
            await self.bot.wait_until_ready()
        except RuntimeError:
            self.post_loop.stop()  # клиент вне логина (тесты) — выходим без ошибок

    async def _tick(self) -> None:
        config = self.bot.config
        channel_id = config.twitch_schedule_channel_id
        if not channel_id or not config.twitch_channels:
            return
        hour = config.schedule_post_hour
        if hour >= 0 and datetime.now(resolve_tz(config.stream_quiet_tz)).hour != hour:
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None or not hasattr(channel, "send"):
            return
        for login in config.twitch_channels:
            try:
                segments = await self.twitch.schedule(login)
            except Exception:
                logger.warning("SchedulePost: расписание %s недоступно", login, exc_info=True)
                continue
            if not segments:
                continue
            fresh = [s for s in segments if not await self.kv.get(self._key(login, s["start_time"]))]
            if not fresh:
                continue
            await self._post(channel, login, fresh)
            for segment in fresh:
                await self.kv.set(self._key(login, segment["start_time"]), "1")

    async def _post(self, channel, login: str, segments: list[dict]) -> None:
        tz = resolve_tz(self.bot.config.stream_quiet_tz)
        lines = [_segment_line(segment, tz) for segment in segments]
        lines.append(f"[Открыть расписание](https://www.twitch.tv/{login}/schedule)")
        embed = discord.Embed(
            title="📅 Новое в расписании Twitch",
            description="\n".join(lines),
            color=_TWITCH_PURPLE,
        )
        embed.set_footer(text=f"{login} • {self.bot.config.stream_quiet_tz}")
        embed.timestamp = datetime.now(resolve_tz(self.bot.config.stream_quiet_tz))
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.warning("SchedulePost: не удалось отправить расписание", exc_info=True)
