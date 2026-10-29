"""Общие настройки промосообщений Twitch для кога и веб-панели."""
from __future__ import annotations

import json
from typing import Any

TWITCH_PROMO_KEY = "panel.twitch.promo"
TWITCH_PROMO_MAX_LENGTH = 450
TWITCH_PROMO_DEFAULT_INTERVAL = 30
TWITCH_PROMO_MIN_INTERVAL = 5
TWITCH_PROMO_MAX_INTERVAL = 180


def clean_promo_text(value: Any) -> str:
    return " ".join(str(value or "").split())[:TWITCH_PROMO_MAX_LENGTH]


def normalize_promo_interval(value: Any) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError):
        interval = TWITCH_PROMO_DEFAULT_INTERVAL
    return max(TWITCH_PROMO_MIN_INTERVAL, min(TWITCH_PROMO_MAX_INTERVAL, interval))


def default_promo_text(config: Any) -> str:
    discord_url = config.twitch_discord_url or config.socials_discord
    return clean_promo_text(
        f"{discord_url} проект спонсор данного стрима" if discord_url else ""
    )


async def load_twitch_promo_settings(kv: Any, config: Any) -> dict[str, Any]:
    try:
        raw = await kv.get(TWITCH_PROMO_KEY, "{}")
        stored = json.loads(raw or "{}")
    except (TypeError, ValueError, AttributeError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    text = stored.get("text") if isinstance(stored.get("text"), str) else ""
    return {
        "enabled": stored.get("enabled", True) is not False,
        "text": clean_promo_text(text) or default_promo_text(config),
        "interval_minutes": normalize_promo_interval(stored.get("interval_minutes")),
    }
