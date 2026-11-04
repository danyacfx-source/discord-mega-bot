"""Тихий режим стримов: в заданные часы старт-карточка не пингует роль."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import Config

logger = logging.getLogger("bot.cogs")

#: Чтобы не спамить warning'ом на каждый поллинг при битой зоне.
_warned_tz: set[str] = set()


def resolve_tz(name: str) -> ZoneInfo | timezone:
    """ZoneInfo по имени; невалидная зона — warning один раз и UTC."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        if name not in _warned_tz:
            _warned_tz.add(name)
            logger.warning("STREAM_QUIET_TZ=%s не найдена — тихий час считается по UTC", name)
        return UTC


def is_quiet(config: Config, *, now: datetime | None = None) -> bool:
    """True, если сейчас окно тихого часа в часовом поясе ``stream_quiet_tz``.

    По умолчанию Европа/Москва — ``STREAM_QUIET_HOURS=23-8`` работает по
    московскому времени независимо от таймзоны хоста (в docker по умолчанию
    UTC). Интервал может переходить через полночь (``23-8``: 23:00–07:59).
    Наивный ``now`` трактуется как локальное время зоны (для тестов).
    """
    window = config.stream_quiet_hours
    if window is None:
        return False
    tz = resolve_tz(config.stream_quiet_tz)
    moment = now if now is not None else datetime.now(tz)
    if moment.tzinfo is not None:
        moment = moment.astimezone(tz)
    hour = moment.hour
    start, end = window
    if start > end:  # интервал через полночь
        return hour >= start or hour < end
    return start <= hour < end
