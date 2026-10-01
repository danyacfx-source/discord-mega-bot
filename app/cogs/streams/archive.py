"""Печать завершённого эфира в архив: needs_seal/seal_archive для offline-хуков."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.services.stream_archive import StreamArchiveStore, parse_dt


async def needs_seal(store: StreamArchiveStore, session: dict[str, Any] | None) -> bool:
    """True, если этот эфир ещё не запечатан в архиве (один KV-чтение)."""
    started = str((session or {}).get("started_at") or "")
    if not started:
        return False
    entries = await store.list()
    return not (entries and str(entries[0].get("started_at") or "") == started)


async def seal_archive(
    store: StreamArchiveStore,
    session: dict[str, Any] | None,
    *,
    platform: str,
    url: str | None = None,
    vod_url: str | None = None,
    max_age_days: int = 90,
) -> bool:
    """Пишет сводку завершённого эфира в архив. Идемпотентно по ``started_at``.

    Длительность считается от ``started_at`` до ``captured_at`` (последний
    поллинг), пик берётся из накопленной сессии. Возвращает True, если
    сводка реально добавлена.
    """
    if not session or not session.get("started_at"):
        return False
    entries = await store.list()
    if entries and str(entries[0].get("started_at") or "") == str(session["started_at"]):
        return False
    started = parse_dt(session.get("started_at"))
    if started is None:
        return False
    ended = parse_dt(session.get("captured_at")) or datetime.now(UTC)
    entry = {
        "platform": platform,
        "title": str(session.get("title") or "")[:200],
        "category": str(session.get("category") or "")[:100],
        "url": url or (str(session.get("url")) if session.get("url") else None),
        "vod": vod_url,
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "seconds": max(0, int((ended - started).total_seconds())),
        "peak": int(session.get("peak") or 0),
    }
    await store.append(entry, max_age_days=max_age_days)
    return True
