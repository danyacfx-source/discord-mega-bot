"""Алерт о прерванном стриме: эфир закончился раньше порога — вероятно сбой."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

import discord

from app.core.embeds import BOT_NAME

logger = logging.getLogger("bot.cogs")


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


async def abort_alert(
    channel: discord.abc.Messageable,
    *,
    session: dict | None,
    label: str,
    url: str | None,
    threshold_minutes: int,
) -> None:
    """Пишет ⚠️-алерт, если стрим длился меньше ``threshold_minutes``.

    ``threshold_minutes <= 0`` выключает фичу. Алерт идёт в тот же канал,
    что и стрим-уведомления, без упоминаний (не будит роль).
    """
    if threshold_minutes <= 0 or not session or not session.get("title"):
        return
    started = _parse_dt(session.get("started_at"))
    captured = _parse_dt(session.get("captured_at"))
    if started is None or captured is None:
        return
    minutes = (captured - started).total_seconds() / 60.0
    if not 0 < minutes < threshold_minutes:
        return
    embed = discord.Embed(
        title="⚠️ Стрим прерван",
        description=f"[{label}]({url}) — **{session['title']}**" if url else str(session["title"]),
        color=discord.Color(0xFAA61A),
    )
    embed.add_field(name="⏱ Длился", value=f"{round(minutes)} мин", inline=True)
    embed.add_field(name="Порог", value=f"{threshold_minutes} мин", inline=True)
    embed.set_footer(text=f"Эфир завершился раньше ожидаемого • {BOT_NAME}")
    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        logger.warning("Не удалось отправить алерт о прерванном стриме", exc_info=True)
