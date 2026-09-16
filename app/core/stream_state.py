"""Присутствие бота: как на Node stream_state.js (смотреть стрим / «Стрим офлайн»)."""
from __future__ import annotations

import discord


def stream_activity(title: str | None, viewers: int = 0, *, fallback: str = "Стрим офлайн") -> discord.Activity:
    """WATCHING-активность: «🔴 ⟨название⟩ · 1 234 зрит.» или fallback, когда лайва нет."""
    if title:
        label = f"🔴 {title[:80]} · {_thousands(viewers)} зрит."
    else:
        label = fallback
    return discord.Activity(type=discord.ActivityType.watching, name=label[:128])


def _thousands(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")
