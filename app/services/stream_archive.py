"""Архив завершённых эфиров в KV: сводки для /stream_stats и очистка по возрасту."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db.kv_repository import KvRepository

#: Сколько завершённых эфиров хранится на канал (старые отсекаются).
ARCHIVE_LIMIT = 50
#: Возраст сводки, после которой она выпадает из архива (если не задан свой).
DEFAULT_MAX_AGE_DAYS = 90


def parse_dt(value: Any) -> datetime | None:
    """ISO-время → aware-дatetime (UTC); None для пустого/битого значения."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


class StreamArchiveStore:
    """Список сводок завершённых эфиров (новые впереди) в одном KV-ключе."""

    def __init__(self, repo: KvRepository, key: str) -> None:
        self._repo = repo
        self._key = key

    async def list(self) -> list[dict[str, Any]]:
        raw = await self._repo.get(self._key)
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [entry for entry in data if isinstance(entry, dict)]

    async def append(self, entry: dict[str, Any], *, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> None:
        """Кладёт сводку в начало, срезая по лимиту и возрасту."""
        kept = _slice([entry, *(await self.list())], max_age_days)
        await self._repo.set(self._key, json.dumps(kept, ensure_ascii=False))

    async def trim(self, *, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> None:
        """Выбрасывает протухшие сводки, даже если новых эфиров не было."""
        entries = await self.list()
        kept = _slice(entries, max_age_days)
        if kept != entries:
            await self._repo.set(self._key, json.dumps(kept, ensure_ascii=False))


def _slice(entries: list[dict[str, Any]], max_age_days: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(days=max(1, max_age_days))
    kept: list[dict[str, Any]] = []
    for entry in entries:
        ended = parse_dt(entry.get("ended_at"))
        if ended is not None and ended < cutoff:
            continue
        kept.append(entry)
        if len(kept) >= ARCHIVE_LIMIT:
            break
    return kept
