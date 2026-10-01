"""Команда /stream_stats: история завершённых эфиров из архива KV."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.streams.quiet import resolve_tz
from app.core import embeds
from app.core.embeds import BOT_NAME, NEUTRAL
from app.services.stream_archive import parse_dt
from app.utils.format import truncate

if TYPE_CHECKING:
    from app.core.bot import MegaBot
    from app.services.kick_service import KickService
    from app.services.stream_archive import StreamArchiveStore
    from app.services.stream_session import StreamSessionStore
    from app.services.twitch_service import TwitchService
    from app.services.vk_video_service import VkVideoService

_PLATFORM_NAMES = {"twitch": "Twitch", "kick": "Kick", "vk_video": "VK Видео"}
_MAX_LINES = 10
_WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


@dataclass
class _Target:
    platform: str
    label: str
    name: str
    url: str
    archive: StreamArchiveStore
    session: StreamSessionStore


def _count(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _fmt_minutes(seconds: int) -> str:
    minutes = max(0, seconds) // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} ч {minutes:02d} мин"
    return f"{minutes} мин"


def _summary(entries: list[dict[str, Any]]) -> str:
    """Агрегаты по всему архиву: число эфиров, средний/лучший пик, суммарное время."""
    if not entries:
        return "Завершённых эфиров пока нет."
    peaks = [int(entry.get("peak") or 0) for entry in entries]
    total_seconds = sum(int(entry.get("seconds") or 0) for entry in entries)
    avg = sum(peaks) / len(peaks)
    return (
        f"Всего эфиров: **{len(entries)}** · Средний пик: **{avg:.0f}** · "
        f"Лучший пик: **{_count(max(peaks))}** · Суммарно в эфире: **{total_seconds // 3600} ч**"
    )


def _entry_line(entry: dict[str, Any], tz: Any) -> str:
    platform = str(entry.get("platform") or "")
    label = _PLATFORM_NAMES.get(platform, platform)
    ended = parse_dt(entry.get("ended_at"))
    date = ended.astimezone(tz).strftime("%d.%m %H:%M") if ended else "??.??"
    title = truncate(str(entry.get("title") or "Без названия"), 60)
    url = entry.get("url")
    head = f"[{title}]({url})" if url else title
    parts = [f"**{date}** · {label} · **{head}**"]
    peak = int(entry.get("peak") or 0)
    if peak:
        parts.append(f"📈 {_count(peak)}")
    seconds = int(entry.get("seconds") or 0)
    if seconds:
        parts.append(f"⏱ {_fmt_minutes(seconds)}")
    vod = entry.get("vod")
    if vod:
        parts.append(f"[📼]({vod})")
    return " · ".join(parts)


def _is_fresh(session: dict[str, Any] | None, window_seconds: int) -> bool:
    """True, если сессия писалась недавно — стрим считается идущим."""
    if not session or not session.get("started_at"):
        return False
    captured = parse_dt(session.get("captured_at"))
    if captured is None:
        return False
    return datetime.now(UTC) - captured <= timedelta(seconds=window_seconds)


def _live_line(target: _Target, session: dict[str, Any]) -> str:
    title = truncate(str(session.get("title") or "Без названия"), 60)
    url = session.get("url") or target.url
    viewers = int(session.get("viewers") or 0)
    peak = int(session.get("peak") or 0)
    started = parse_dt(session.get("started_at"))
    in_air = ""
    if started is not None:
        minutes = max(0, int((datetime.now(UTC) - started).total_seconds())) // 60
        in_air = f", в эфире {minutes} мин"
    return f"🔴 {target.label} · **[{title}]({url})** — 👁 {_count(viewers)}, пик {_count(peak)}{in_air}"


def _segment_line(segment: dict[str, Any], tz: Any) -> str:
    """Строка расписания: «Сб 03.10 21:00 · **Название** · 🎮 · ⏱» в локали tz."""
    start = segment["start_time"].astimezone(tz)
    stamp = f"{_WEEKDAYS[start.weekday()]} {start.strftime('%d.%m %H:%M')}"
    title = truncate(str(segment.get("title") or "Без названия"), 60)
    url = segment.get("url")
    head = f"[{title}]({url})" if url else title
    parts = [f"**{stamp}**", f"**{head}**"]
    category = str(segment.get("category") or "")
    if category:
        parts.append(f"🎮 {truncate(category, 40)}")
    end = segment.get("end_time")
    if end is not None:
        minutes = int((end - segment["start_time"]).total_seconds()) // 60
        if minutes > 0:
            parts.append(f"⏱ {_fmt_minutes(minutes * 60)}")
    return " · ".join(parts)


class StreamStats(commands.Cog):
    """История завершённых стримов: пики, длительность, ссылки на записи."""

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

    def _targets(self, platform: str | None) -> list[_Target]:
        """Архив+сессия для каждого настроенного канала (фильтр по платформе)."""
        config = self.bot.config
        targets: list[_Target] = []
        for login in config.twitch_channels:
            targets.append(
                _Target(
                    platform="twitch",
                    label="Twitch",
                    name=login,
                    url=f"https://www.twitch.tv/{login}",
                    archive=self.twitch.archive_store(login),
                    session=self.twitch.session_store(login),
                )
            )
        if config.kick_channel_slug:
            slug = config.kick_channel_slug
            targets.append(
                _Target(
                    platform="kick",
                    label="Kick",
                    name=slug,
                    url=f"https://kick.com/{slug}",
                    archive=self.kick.archive_store(slug),
                    session=self.kick.session_store(slug),
                )
            )
        if config.vk_channel_slug:
            slug = config.vk_channel_slug
            targets.append(
                _Target(
                    platform="vk_video",
                    label="VK Видео",
                    name=slug,
                    url=f"https://live.vkvideo.ru/{slug}",
                    archive=self.vk_video.archive_store(slug),
                    session=self.vk_video.session_store(slug),
                )
            )
        if platform:
            targets = [t for t in targets if t.platform == platform]
        return targets

    @app_commands.command(name="stream_stats", description="История завершённых стримов: пики, длительность, записи")
    @app_commands.describe(platform="Платформа (по умолчанию — все настроенные)")
    @app_commands.choices(
        platform=[
            app_commands.Choice(name="Twitch", value="twitch"),
            app_commands.Choice(name="Kick", value="kick"),
            app_commands.Choice(name="VK Видео", value="vk_video"),
        ]
    )
    @app_commands.guild_only()
    async def stream_stats(self, interaction: discord.Interaction, platform: str | None = None) -> None:
        targets = self._targets(platform)
        if not targets:
            await interaction.response.send_message(
                embed=embeds.error("Не настроено", "Стримы не настроены (TWITCH_CHANNELS/KICK_CHANNEL_SLUG/VK_CHANNEL_SLUG)."),
                ephemeral=True,
            )
            return
        config = self.bot.config
        live_window = max(int(config.stream_sticky_poll_seconds), 60) * 3
        all_entries: list[dict[str, Any]] = []
        live_lines: list[str] = []
        for target in targets:
            await target.archive.trim(max_age_days=config.stream_archive_days)
            all_entries.extend(await target.archive.list())
            session = await target.session.load()
            if _is_fresh(session, live_window):
                live_lines.append(_live_line(target, session))
        all_entries.sort(key=lambda entry: str(entry.get("ended_at") or ""), reverse=True)
        shown = all_entries[:_MAX_LINES]

        tz = resolve_tz(config.stream_quiet_tz)
        lines: list[str] = []
        if live_lines:
            lines.extend(live_lines)
            lines.append("")
        lines.append(_summary(all_entries))
        if shown:
            lines.append("")
            lines.extend(_entry_line(entry, tz) for entry in shown)

        embed = discord.Embed(title="📊 Статистика стримов", description="\n".join(lines), color=NEUTRAL)
        embed.set_footer(text=f"Показаны {len(shown)} из {len(all_entries)} • {BOT_NAME}")
        embed.timestamp = datetime.now(UTC)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="stream_schedule", description="Ближайшие эфиры по расписанию Twitch")
    @app_commands.describe(channel="Ник канала (по умолчанию из конфигурации)")
    @app_commands.guild_only()
    async def stream_schedule(self, interaction: discord.Interaction, channel: str | None = None) -> None:
        login = channel or (self.bot.config.twitch_channels[0] if self.bot.config.twitch_channels else None)
        if not login:
            await interaction.response.send_message(
                embed=embeds.error("Не настроено", "Укажите канал или настройте TWITCH_CHANNELS."),
                ephemeral=True,
            )
            return
        try:
            segments = await self.twitch.schedule(login)
        except Exception as exc:
            await interaction.response.send_message(
                embed=embeds.error("Не удалось получить расписание", f"{type(exc).__name__}: {exc}"),
                ephemeral=True,
            )
            return
        if segments is None:
            await interaction.response.send_message(
                embed=embeds.error(
                    "Расписание недоступно",
                    "Нужны TWITCH_CLIENT_ID и TWITCH_CLIENT_SECRET, либо Twitch вернул ошибку.",
                ),
                ephemeral=True,
            )
            return
        schedule_url = f"https://www.twitch.tv/{login}/schedule"
        if not segments:
            embed = discord.Embed(
                title="📅 Расписание Twitch",
                description=f"На канале **{login}** нет запланированных эфиров.\n[Открыть расписание]({schedule_url})",
                color=NEUTRAL,
            )
            await interaction.response.send_message(embed=embed)
            return
        tz = resolve_tz(self.bot.config.stream_quiet_tz)
        lines = [_segment_line(segment, tz) for segment in segments]
        lines.append(f"[Полное расписание]({schedule_url})")
        embed = discord.Embed(title="📅 Ближайшие эфиры Twitch", description="\n".join(lines), color=0x9146FF)
        embed.set_footer(text=f"{login} • {self.bot.config.stream_quiet_tz} • {BOT_NAME}")
        embed.timestamp = datetime.now(UTC)
        await interaction.response.send_message(embed=embed)
