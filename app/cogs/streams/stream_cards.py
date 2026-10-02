"""Discord-карточки стримов: живой эфир и завершённый трансляция.

Единый вид для Twitch, Kick и VK Видео: платформенный цвет, превью-картинка,
зрители/пик/длительность во время эфира — итоговые цифры после эфира.

Пресеты (`stream:cards` в KV) переопределяют заголовки, цвета, футер и имена
полей; редактируются в вебпанели (раздел «Карточки стримов»).
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import discord

from app.core.embeds import BOT_NAME, NEUTRAL
from app.utils.format import truncate
from app.utils.stream_history import sparkline, trend

#: KV-ключ пресетов карточек (JSON, см. вебпанель «Карточки стримов»).
CARDS_KEY = "stream:cards"

_HEX_RE = re.compile(r"#?([0-9a-fA-F]{6})\Z")

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


def _section(preset: dict[str, Any] | None, name: str) -> dict[str, Any]:
    sec = (preset or {}).get(name)
    return sec if isinstance(sec, dict) else {}


def _p_title(sec: dict[str, Any], platform: str, default: str) -> str:
    titles = sec.get("titles")
    if isinstance(titles, dict):
        value = titles.get(platform)
        if isinstance(value, str) and value.strip():
            return truncate(value.strip(), 256)
    return default


def _p_color(sec: dict[str, Any], platform: str, default: discord.Color) -> discord.Color:
    colors = sec.get("colors")
    if isinstance(colors, dict):
        value = colors.get(platform)
        if isinstance(value, str):
            match = _HEX_RE.match(value.strip())
            if match:
                return discord.Color(int(match.group(1), 16))
    return default


def _p_footer(sec: dict[str, Any], platform: str, default: str) -> str:
    value = sec.get("footer")
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("{bot}", BOT_NAME).replace("{label}", platform)
        return truncate(text, 2048)
    return default


def _p_field(sec: dict[str, Any], key: str, default: str) -> str:
    fields = sec.get("fields")
    if isinstance(fields, dict):
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            return truncate(value.strip(), 256)
    return default


async def card_presets(kv: Any) -> dict[str, Any]:
    """Пресеты карточек из KV; мусор/ошибка чтения → пустой пресет (дефолтный вид)."""
    try:
        raw = await kv.get(CARDS_KEY)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def live_card(
    platform: str,
    *,
    url: str | None,
    status: dict[str, Any],
    session: dict[str, Any] | None = None,
    preset: dict[str, Any] | None = None,
) -> discord.Embed:
    """Карточка во время эфира: превью, актуальные зрители, пик и таймер."""
    label = _LABELS.get(platform, platform)
    sec = _section(preset, "live")
    embed = discord.Embed(
        title=_p_title(sec, platform, _LIVE_TITLES.get(platform, f"🔴 {label}: в эфире")),
        description=_link(str(status.get("title") or "Без названия"), url),
        color=_p_color(sec, platform, _COLORS.get(platform, NEUTRAL)),
    )
    embed.set_footer(text=_p_footer(sec, label, f"{label} • {BOT_NAME}"))
    embed.timestamp = datetime.now(UTC)

    thumbnail = str(status.get("thumbnail") or "")
    if thumbnail:
        embed.set_image(url=thumbnail)

    viewers = int(status.get("viewers") or 0)
    peak = int((session or {}).get("peak") or 0)
    if viewers or peak:
        embed.add_field(name=_p_field(sec, "viewers", "👁 Зрители"), value=_count(max(viewers, 0)), inline=True)
    if peak:
        embed.add_field(name=_p_field(sec, "peak", "📈 Пик"), value=_count(peak), inline=True)

    duration = _duration(status.get("started_at"))
    if duration:
        embed.add_field(name=_p_field(sec, "duration", "⏱ В эфире"), value=duration, inline=True)

    delta = trend((session or {}).get("history"))
    spark = sparkline((session or {}).get("history"))
    trend_parts: list[str] = []
    if delta is not None:
        sign = "▲" if delta >= 0 else "▼"
        trend_parts.append(f"{_count(abs(delta))} {sign} за 10 мин")
    if spark:
        trend_parts.append(spark)
    if trend_parts:
        embed.add_field(name=_p_field(sec, "trend", "📈 Тренд"), value=" · ".join(trend_parts), inline=True)

    category = str(status.get("category") or "")
    if category and category != "—":
        embed.add_field(name=_p_field(sec, "category", "🎮 Категория"), value=truncate(category), inline=True)

    description = str(status.get("description") or "")
    if description:
        embed.add_field(name=_p_field(sec, "description", "📝 Описание"), value=truncate(description), inline=False)
    return embed


def offline_card(
    platform: str,
    *,
    url: str | None,
    session: dict[str, Any] | None = None,
    vod_url: str | None = None,
    top_talkers: list[dict[str, Any]] | None = None,
    preset: dict[str, Any] | None = None,
) -> discord.Embed:
    """Карточка после эфира: итоги стрима либо нейтральное «офлайн»."""
    label = _LABELS.get(platform, platform)
    sec = _section(preset, "offline")
    embed = discord.Embed(
        title=_p_title(sec, platform, _OFFLINE_TITLES.get(platform, f"📺 {label}: офлайн")),
        color=_p_color(sec, platform, NEUTRAL),
    )
    embed.set_footer(text=_p_footer(sec, label, f"Спасибо за просмотр • {BOT_NAME}"))
    embed.timestamp = datetime.now(UTC)

    if vod_url:
        embed.add_field(name=_p_field(sec, "vod", "📼 Запись"), value=f"[Посмотреть запись]({vod_url})", inline=False)

    if not session or not session.get("title"):
        embed.description = f"[{label}]({url}) сейчас офлайн." if url else "Канал сейчас офлайн."
        return embed

    embed.description = _link(str(session["title"]), url)

    peak = int(session.get("peak") or 0)
    if peak:
        embed.add_field(name=_p_field(sec, "peak", "📈 Пик зрителей"), value=_count(peak), inline=True)

    duration = _duration(session.get("started_at"), _parse_dt(session.get("captured_at")))
    if duration:
        embed.add_field(name=_p_field(sec, "duration", "⏱ Длительность"), value=duration, inline=True)

    category = str(session.get("category") or "")
    if category and category != "—":
        embed.add_field(name=_p_field(sec, "category", "🎮 Категория"), value=truncate(category), inline=True)

    if top_talkers:
        lines = [f"**{str(t.get('name') or '?')}** — {_count(int(t.get('count') or 0))}" for t in top_talkers]
        embed.add_field(name=_p_field(sec, "talkers", "💬 Говорили в чате"), value="\n".join(lines), inline=False)

    thumbnail = str(session.get("thumbnail") or "")
    if thumbnail:
        embed.set_image(url=thumbnail)
    return embed
