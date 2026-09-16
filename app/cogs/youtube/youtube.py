"""YouTube: статистика канала (/yt_stats) и статус роста (/yt_growth), как в Node youtube.js/youtube_growth.js."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import tasks

from app.core import embeds
from app.core.base import MegaCog
from app.services.youtube_service import YouTubeService, format_number, parse_duration_seconds

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")

_YOUTUBE_COLOR = 0xFF0000
_GROWTH_STATE_KEY = "youtube:growth"
_SHORTS_LIMIT = 60


class YouTubeCog(MegaCog, name="YouTube"):
    def __init__(self, bot: MegaBot, youtube: YouTubeService) -> None:
        super().__init__(bot)
        self.youtube = youtube
        self._known_video_ids: set[str] = set()
        self._video_seeded = False
        self._growth_state: dict[str, Any] = {}

    async def cog_load(self) -> None:
        if not self.youtube.enabled:
            return
        if self.bot.config.youtube_notify_channel_id:
            self.video_check_loop.start()
            self.growth_loop.start()

    async def cog_unload(self) -> None:
        self.video_check_loop.cancel()
        self.growth_loop.cancel()
        await self.youtube.aclose()

    # ------------------------------------------------------------- helpers

    def _notify_channel(self) -> discord.TextChannel | None:
        channel_id = self.bot.config.youtube_notify_channel_id
        if not channel_id:
            return None
        for guild in self.bot.guilds:
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                return channel
        return None

    # ------------------------------------------------------------- loops

    @tasks.loop(seconds=300.0)
    async def video_check_loop(self) -> None:
        try:
            videos = await self.youtube.recent_videos(10)
        except Exception:
            logger.exception("YouTube: ошибка проверки видео")
            return
        channel = self._notify_channel()
        for video in reversed(videos):
            vid = (video.get("id") or {}).get("videoId")
            snippet = video.get("snippet") or {}
            if not vid or snippet.get("liveBroadcastContent") == "live":
                continue
            if not self._video_seeded:
                self._known_video_ids.add(vid)
                continue
            if vid in self._known_video_ids:
                continue
            self._known_video_ids.add(vid)
            if len(self._known_video_ids) > 200:
                self._known_video_ids.pop()
            if channel is not None:
                embed = embeds.info("📹 Новое видео", f"**{snippet.get('title') or '?'}**")
                embed.url = f"https://www.youtube.com/watch?v={vid}"
                embed.color = discord.Color(_YOUTUBE_COLOR)
                thumb = (snippet.get("thumbnails") or {}).get("high", {}).get("url")
                if thumb:
                    embed.set_thumbnail(url=thumb)
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    logger.debug("YouTube: не удалось отправить уведомление о видео", exc_info=True)
        if not self._video_seeded:
            self._video_seeded = True
            logger.info("YouTube: инициализировано %d известных видео", len(self._known_video_ids))

    @tasks.loop(seconds=600.0)
    async def growth_loop(self) -> None:
        try:
            await self._check_shorts()
            await self._check_premieres()
        except Exception:
            logger.exception("YouTubeGrowth: ошибка цикла")

    async def _check_shorts(self) -> None:
        channel = self._notify_channel()
        if channel is None:
            return
        videos = await self.youtube.recent_videos(10)
        known = set(self._growth_state.get("known_shorts", []))
        for item in videos:
            vid = (item.get("id") or {}).get("videoId")
            if not vid or vid in known:
                continue
            details = await self.youtube.video_details([vid])
            if not details:
                continue
            content = (details[0].get("contentDetails") or {}).get("duration") or ""
            snippet = details[0].get("snippet") or {}
            if not (content.startswith("PT") and parse_duration_seconds(content) <= _SHORTS_LIMIT):
                continue
            known.add(vid)
            self._growth_state["known_shorts"] = list(known)[-200:]
            embed = embeds.info("📱 Новый YouTube Short", f"**{snippet.get('title') or '?'}**")
            embed.url = f"https://www.youtube.com/shorts/{vid}"
            embed.color = discord.Color(_YOUTUBE_COLOR)
            thumb = (snippet.get("thumbnails") or {}).get("high", {}).get("url")
            if thumb:
                embed.set_thumbnail(url=thumb)
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                logger.debug("YouTubeGrowth: не удалось опубликовать Short", exc_info=True)

    async def _check_premieres(self) -> None:
        channel = self._notify_channel()
        if channel is None:
            return
        channel_id = await self.youtube.resolve_channel_id()
        if not channel_id:
            return
        # поиск upcoming промо-видео нет в сервисе, проверяем через video_details свежих
        videos = await self.youtube.recent_videos(5)
        for item in videos:
            vid = (item.get("id") or {}).get("videoId")
            if not vid:
                continue
            key = f"premiere:{vid}"
            if self._growth_state.get(key):
                continue
            snippet = item.get("snippet") or {}
            if snippet.get("liveBroadcastContent") != "upcoming":
                continue
            self._growth_state[key] = True
            embed = embeds.info("🎬 Премьера", f"**{snippet.get('title') or '?'}**\nСкоро на YouTube! Не пропусти.")
            embed.url = f"https://www.youtube.com/watch?v={vid}"
            embed.color = discord.Color(_YOUTUBE_COLOR)
            published = snippet.get("publishedAt")
            if published:
                try:
                    ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    embed.add_field(name="Старт", value=f"<t:{int(ts.timestamp())}:R>")
                except ValueError:
                    pass
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                logger.debug("YouTubeGrowth: не удалось опубликовать премьеру", exc_info=True)

    # ------------------------------------------------------------- commands

    @app_commands.command(name="yt_stats", description="Статистика YouTube канала")
    @app_commands.guild_only()
    async def yt_stats(self, interaction: discord.Interaction) -> None:
        if not self.config.youtube_enabled:
            await interaction.response.send_message("YouTube-модуль отключён (youtube.enabled=false).", ephemeral=True)
            return
        if not self.config.youtube_api_key:
            await interaction.response.send_message("YouTube-модуль отключён: не задан API ключ.", ephemeral=True)
            return
        await interaction.response.defer()
        try:
            item = await self.youtube.channel_stats()
        except Exception as exc:
            await interaction.followup.send(f"Ошибка: {exc}", ephemeral=True)
            return
        if not item:
            await interaction.followup.send("Канал не найден.", ephemeral=True)
            return
        snippet = item.get("snippet") or {}
        stats = item.get("statistics") or {}
        title = snippet.get("title") or self.youtube.handle
        subs = int(stats.get("subscriberCount") or 0)
        views = int(stats.get("viewCount") or 0)
        videos_count = int(stats.get("videoCount") or 0)

        embed = embeds.info(f"📊 {title}", (snippet.get("description") or "Нет описания")[:200])
        embed.url = f"https://www.youtube.com/@{self.youtube.handle}"
        embed.color = discord.Color(_YOUTUBE_COLOR)
        embed.add_field(name="Подписчики", value=format_number(subs), inline=True)
        embed.add_field(name="Просмотры", value=format_number(views), inline=True)
        embed.add_field(name="Видео", value=str(videos_count), inline=True)
        thumb = (snippet.get("thumbnails") or {}).get("high", {}).get("url")
        if thumb:
            embed.set_thumbnail(url=thumb)
        try:
            videos = await self.youtube.recent_videos(3)
            lines = []
            for video in videos:
                snippet_v = video.get("snippet") or {}
                vid = (video.get("id") or {}).get("videoId")
                if snippet_v.get("title") and vid:
                    lines.append(f"**{snippet_v['title'][:40]}**\n<https://www.youtube.com/watch?v={vid}>")
            if lines:
                embed.add_field(name="Последние видео", value="\n\n".join(lines), inline=False)
        except Exception:
            logger.debug("YouTube: не удалось получить последние видео", exc_info=True)
        embed.set_footer(text=f"Обновлено {(datetime.now(UTC) + timedelta(hours=3)).strftime('%H:%M')} МСК")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="yt_growth", description="Статус YouTube-Growth модуля")
    @app_commands.guild_only()
    async def yt_growth(self, interaction: discord.Interaction) -> None:
        if not self.config.youtube_enabled:
            await interaction.response.send_message("YouTubeGrowth: модуль отключён (youtube.enabled=false).", ephemeral=True)
            return
        if not self.config.youtube_api_key:
            await interaction.response.send_message("YouTubeGrowth: отключён — не задан YOUTUBE_API_KEY.", ephemeral=True)
            return
        known_shorts = len(self._growth_state.get("known_shorts", []))
        embed = embeds.info(
            "📈 YouTube Growth",
            f"Модуль работает в режиме **API-ключа** (только чтение).\n"
            f"Канал: @{self.youtube.handle}\n"
            f"Известно Shorts: {known_shorts}\n"
            f"Функции: уведомления о Shorts, премьеры.",
        )
        embed.color = discord.Color(_YOUTUBE_COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)
