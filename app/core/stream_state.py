"""Присутствие бота: как на Node stream_state.js (смотреть стрим / «Стрим офлайн»)."""
from __future__ import annotations

import discord

_OFFLINE = "Стрим офлайн"


def stream_activity(title: str | None, viewers: int = 0) -> discord.Activity:
    """STREAMING-активность (красный кружок в Discord): «🔴 ⟨название⟩ · 1 234 зрит.» или «Стрим офлайн»."""
    if title:
        label = f"🔴 {title[:80]} · {_thousands(viewers)} зрит."
    else:
        label = _OFFLINE
    return discord.Activity(type=discord.ActivityType.streaming, name=label[:128])


def _thousands(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")
