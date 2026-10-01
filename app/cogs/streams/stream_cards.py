"""Discord-карточки стримов: живой эфир и завершённый трансляция.

Единый вид для Twitch, Kick и VK Видео: платформенный цвет, превью-картинка,
зрители/пик/длительность во время эфира — итоговые цифры после эфира.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import discord

from app.core.embeds import BOT_NAME, NEUTRAL
from app.utils.format import truncate
from app.utils.stream_history import sparkline, trend

_COLORS = {
    "twitch": discord.Color(0x9146FF),
    "kick": discord.Color(0x53FC18),
    "vk_video": discord.Color(0x0077FF),
}
_LABELS = {
    "twitch": "Twitch",
    "kick": "Kick",
    "vk_video": "VK Видео",
}
_LIVE_TITLES = {
    "twitch": "🔴 Twitch: стрим идёт",
    "kick": "🔴 Kick: стрим идёт",
    "vk_video": "🔴 VK Видео: трансляция идёт",
}
_OFFLINE_TITLES = {
    "twitch": "📺 Twitch: стрим завершён",
    "kick": "📺 Kick: стрим завершён",
    "vk_video": "📺 VK Видео: трансляция завершена",
}


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _duration(started: Any, ended: datetime | None = None) -> str | None:
    """Длительность вида «1:05:09» (или «5:09» без часов); None если нет времени."""
    started_dt = _parse_dt(started)
    if started_dt is None:
        return None
    seconds = int(((ended or datetime.now(UTC)) - started_dt).total_seconds())
    if seconds < 0:
        return None
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _count(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _link(title: str, url: str | None) -> str:
    safe = truncate(title, 250)
    return f"**[{safe}]({url})**" if url else f"**{safe}**"


def live_card(
    platform: str,
    *,
    url: str | None,
    status: dict[str, Any],
    session: dict[str, Any] | None = None,
) -> discord.Embed:
    """Карточка во время эфира: превью, актуальные зрители, пик и таймер."""
    label = _LABELS.get(platform, platform)
    embed = discord.Embed(
        title=_LIVE_TITLES.get(platform, f"🔴 {label}: в эфире"),
        description=_link(str(status.get("title") or "Без названия"), url),
        color=_COLORS.get(platform, NEUTRAL),
    )
    embed.set_footer(text=f"{label} • {BOT_NAME}")
    embed.timestamp = datetime.now(UTC)

    thumbnail = str(status.get("thumbnail") or "")
    if thumbnail:
        embed.set_image(url=thumbnail)

    viewers = int(status.get("viewers") or 0)
    peak = int((session or {}).get("peak") or 0)
    if viewers or peak:
        embed.add_field(name="👁 Зрители", value=_count(max(viewers, 0)), inline=True)
    if peak:
        embed.add_field(name="📈 Пик", value=_count(peak), inline=True)

    duration = _duration(status.get("started_at"))
    if duration:
        embed.add_field(name="⏱ В эфире", value=duration, inline=True)

    delta = trend((session or {}).get("history"))
    spark = sparkline((session or {}).get("history"))
    trend_parts: list[str] = []
    if delta is not None:
        sign = "▲" if delta >= 0 else "▼"
        trend_parts.append(f"{_count(abs(delta))} {sign} за 10 мин")
    if spark:
        trend_parts.append(spark)
    if trend_parts:
        embed.add_field(name="📈 Тренд", value=" · ".join(trend_parts), inline=True)

    category = str(status.get("category") or "")
    if category and category != "—":
        embed.add_field(name="🎮 Категория", value=truncate(category), inline=True)

    description = str(status.get("description") or "")
    if description:
        embed.add_field(name="📝 Описание", value=truncate(description), inline=False)
    return embed


def offline_card(
    platform: str,
    *,
    url: str | None,
    session: dict[str, Any] | None = None,
    vod_url: str | None = None,
    top_talkers: list[dict[str, Any]] | None = None,
) -> discord.Embed:
    """Карточка после эфира: итоги стрима либо нейтральное «офлайн»."""
    label = _LABELS.get(platform, platform)
    embed = discord.Embed(
        title=_OFFLINE_TITLES.get(platform, f"📺 {label}: офлайн"),
        color=NEUTRAL,
    )
    embed.set_footer(text=f"Спасибо за просмотр • {BOT_NAME}")
    embed.timestamp = datetime.now(UTC)

    if vod_url:
        embed.add_field(name="📼 Запись", value=f"[Посмотреть запись]({vod_url})", inline=False)

    if not session or not session.get("title"):
        embed.description = f"[{label}]({url}) сейчас офлайн." if url else "Канал сейчас офлайн."
        return embed

    embed.description = _link(str(session["title"]), url)

    peak = int(session.get("peak") or 0)
    if peak:
        embed.add_field(name="📈 Пик зрителей", value=_count(peak), inline=True)

    duration = _duration(session.get("started_at"), _parse_dt(session.get("captured_at")))
    if duration:
        embed.add_field(name="⏱ Длительность", value=duration, inline=True)

    category = str(session.get("category") or "")
    if category and category != "—":
        embed.add_field(name="🎮 Категория", value=truncate(category), inline=True)

    if top_talkers:
        lines = [f"**{str(t.get('name') or '?')}** — {_count(int(t.get('count') or 0))}" for t in top_talkers]
        embed.add_field(name="💬 Говорили в чате", value="\n".join(lines), inline=False)

    thumbnail = str(session.get("thumbnail") or "")
    if thumbnail:
        embed.set_image(url=thumbnail)
    return embed
