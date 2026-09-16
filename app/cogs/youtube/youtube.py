"""YouTube: статистика канала (/yt_stats) и рост (/yt_growth), как в Node youtube.js/youtube_growth.js.

Состояние роста (известные Shorts, премьеры, дата последней аналитики) хранится
в KvRepository и переживает рестарты. Циклы запускаются, если модуль включён
и задан API-ключ (как в Node) — уведомления зависят от notify-канала.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

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
_SHORTS_LIMIT = 60
_ANALYTICS_PERIOD = timedelta(days=7)
_MSC_OFFSET = timedelta(hours=3)


def _msk(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + _MSC_OFFSET


class YouTubeCog(MegaCog, name="YouTube"):
    def __init__(self, bot: MegaBot, youtube: YouTubeService) -> None:
        super().__init__(bot)
        self.youtube = youtube
        self._known_video_ids: set[str] = set()
        self._video_seeded = False

    async def cog_load(self) -> None:
        if not self.youtube.enabled:
            logger.info("YouTube: модуль отключён (youtube.enabled=false)")
            return
        if not self.youtube.api_key:
            logger.error("YouTube: включён, но не задан YOUTUBE_API_KEY — циклы не запущены")
            return
        await self.youtube.load_state()
        self.video_check_loop.start()
        self.growth_loop.start()
        logger.info("YouTube: модуль запущен: @%s", self.youtube.handle)

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

    @staticmethod
    def _small_embed(title: str, url: str, thumbnail: str | None, footer: str | None = None) -> discord.Embed:
        embed = discord.Embed(title=title, url=url, color=discord.Color(_YOUTUBE_COLOR))
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        if footer:
            embed.set_footer(text=footer)
        return embed

    async def _send_notify(self, channel: discord.TextChannel, embed: discord.Embed) -> None:
        if channel is None:
            return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.debug("YouTube: не удалось отправить уведомление", exc_info=True)

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
                title = snippet.get("title") or "?"
                embed = self._small_embed(
                    f"📹 Новое видео: {title}",
                    f"https://www.youtube.com/watch?v={vid}",
                    (snippet.get("thumbnails") or {}).get("high", {}).get("url"),
                )
                await self._send_notify(channel, embed)
        if not self._video_seeded:
            self._video_seeded = True
            logger.info("YouTube: инициализировано %d известных видео", len(self._known_video_ids))

    @tasks.loop(seconds=600.0)
    async def growth_loop(self) -> None:
        try:
            await self._check_shorts()
            await self._check_premieres()
            await self._post_weekly_analytics()
        except Exception:
            logger.exception("YouTubeGrowth: ошибка цикла")

    async def _check_shorts(self) -> None:
        channel = self._notify_channel()
        if channel is None:
            return
        state = await self.youtube.load_state()
        known = list(state.get("known_shorts") or [])
        known_set = set(known)
        videos = await self.youtube.recent_videos(10)
        for item in videos:
            vid = (item.get("id") or {}).get("videoId")
            if not vid or vid in known_set:
                continue
            details = await self.youtube.video_details([vid])
            if not details:
                continue
            content = (details[0].get("contentDetails") or {}).get("duration") or ""
            snippet = details[0].get("snippet") or {}
            if not (content.startswith("PT") and parse_duration_seconds(content) <= _SHORTS_LIMIT):
                continue
            known.append(vid)
            state["known_shorts"] = known[-200:]
            title = snippet.get("title") or "?"
            embed = self._small_embed(
                f"📱 Новый YouTube Short: {title}",
                f"https://www.youtube.com/shorts/{vid}",
                (snippet.get("thumbnails") or {}).get("high", {}).get("url"),
                footer="YouTube Shorts",
            )
            await self._send_notify(channel, embed)
        await self.youtube.save_state()

    async def _check_premieres(self) -> None:
        channel = self._notify_channel()
        if channel is None:
            return
        channel_id = await self.youtube.resolve_channel_id()
        if not channel_id:
            return
        state = await self.youtube.load_state()
        videos = await self.youtube.recent_videos(5)
        for item in videos:
            vid = (item.get("id") or {}).get("videoId")
            if not vid:
                continue
            key = f"premiere:{vid}"
            if state.get(key):
                continue
            snippet = item.get("snippet") or {}
            if snippet.get("liveBroadcastContent") != "upcoming":
                continue
            state[key] = True
            title = snippet.get("title") or "?"
            embed = self._small_embed(
                f"🎬 Премьера: {title}",
                f"https://www.youtube.com/watch?v={vid}",
                (snippet.get("thumbnails") or {}).get("high", {}).get("url"),
                footer="Добавь в календарь!",
            )
            embed.description = "Скоро на YouTube! Не пропусти."
            published = snippet.get("publishedAt")
            if published:
                try:
                    ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    embed.add_field(name="Старт", value=f"<t:{int(ts.timestamp())}:R>")
                except ValueError:
                    pass
            await self._send_notify(channel, embed)
        await self.youtube.save_state()

    async def _post_weekly_analytics(self) -> None:
        channel = self._notify_channel()
        if channel is None:
            return
        state = await self.youtube.load_state()
        last = state.get("last_analytics_post")
        if last and datetime.now(UTC) - datetime.fromtimestamp(last, tz=UTC) < _ANALYTICS_PERIOD:
            return
        item = await self.youtube.channel_stats()
        if not item:
            return
        stats = item.get("statistics") or {}
        snippet = item.get("snippet") or {}
        subs = int(stats.get("subscriberCount") or 0)
        views = int(stats.get("viewCount") or 0)
        videos_count = int(stats.get("videoCount") or 0)

        embed = embeds.info(f"📈 YouTube аналитика: {snippet.get('title') or '?'}")
        embed.color = discord.Color(_YOUTUBE_COLOR)
        embed.add_field(name="Подписчики", value=format_number(subs), inline=True)
        embed.add_field(name="Просмотры", value=format_number(views), inline=True)
        embed.add_field(name="Видео", value=str(videos_count), inline=True)

        try:
            videos = await self.youtube.recent_videos(5)
            ids = [(v.get("id") or {}).get("videoId") for v in videos if (v.get("id") or {}).get("videoId")]
            if ids:
                lines: list[str] = []
                for item_v in await self.youtube.video_details(ids[:5]):
                    stats_v = item_v.get("statistics") or {}
                    title = (item_v.get("snippet") or {}).get("title") or "?"
                    vc = int(stats_v.get("viewCount") or 0)
                    lk = int(stats_v.get("likeCount") or 0)
                    lines.append(f"**{title[:40]}** — 👁 {format_number(vc)} · 👍 {format_number(lk)}")
                if lines:
                    embed.add_field(name="Последние видео", value="\n".join(lines), inline=False)
        except Exception:
            logger.debug("YouTubeGrowth: не удалось собрать последние видео для аналитики", exc_info=True)

        embed.set_footer(text=f"Обновлено {_msk().strftime('%Y-%m-%d %H:%M')} МСК")
        await self._send_notify(channel, embed)
        state["last_analytics_post"] = int(datetime.now(UTC).timestamp())
        await self.youtube.save_state()

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
        embed.set_footer(text=f"Обновлено {_msk().strftime('%H:%M')} МСК")
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
        state = await self.youtube.load_state()
        known_shorts = len(state.get("known_shorts") or [])
        embed = embeds.info(
            "📈 YouTube Growth",
            f"Модуль работает в режиме **API-ключа** (только чтение).\n"
            f"Канал: @{self.youtube.handle}\n"
            f"Известно Shorts: {known_shorts}\n"
            f"Функции: уведомления о Shorts, премьеры, еженедельная аналитика.",
        )
        embed.color = discord.Color(_YOUTUBE_COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)
