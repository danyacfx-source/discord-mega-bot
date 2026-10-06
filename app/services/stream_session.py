"""Сессия стрима в KV: пик зрителей, история сэмплов и метаданные для карточек."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.db.kv_repository import KvRepository

#: Хранится максимум столько сэмплов зрителей (60 × 60 с ≈ час эфира).
_HISTORY_LIMIT = 60


def session_is_live(
    session: dict[str, Any] | None,
    *,
    poll_seconds: float,
    sticky_seconds: float,
) -> bool:
    """Эфир считается идущим, пока сессия свежая (поллинг её дописывает).

    Сессия переживает офлайн (это «последний эфир»), поэтому простого наличия
    недостаточно — смотрим на ``captured_at``. Окно — три интервала поллинга
    (как в панели), но не меньше трёх sticky-интервалов.
    """
    if not session or not session.get("captured_at"):
        return False
    try:
        captured = datetime.fromisoformat(str(session["captured_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=UTC)
    window = max(poll_seconds, sticky_seconds) * 3
    return (datetime.now(UTC) - captured).total_seconds() <= window


class StreamSessionStore:
    """Хранит данные текущего (или последнего) стрима.

    Пик зрителей накапливается между поллингами — Discord-карточка во время
    эфира показывает актуальных зрителей, карточка после эфира — итоговый пик
    и длительность. Смена ``started_at`` означает новый стрим: накопления
    сбрасываются.
    """

    def __init__(self, repo: KvRepository, key: str) -> None:
        self._repo = repo
        self._key = key

    async def load(self) -> dict[str, Any] | None:
        raw = await self._repo.get(self._key)
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    async def capture(self, status: dict[str, Any], *, url: str | None = None) -> dict[str, Any]:
        """Сливает свежий статус стрима в сессию, обновляя пик зрителей.

        Плюс дописывает сэмпл зрителей в ``history`` (для тренда и спарклайна
        в карточках/оверлее): не более ``_HISTORY_LIMIT`` последних замеров.
        """
        previous = await self.load()
        started = status.get("started_at")
        if previous and started and previous.get("started_at") and previous["started_at"] != started:
            previous = None
        viewers = int(status.get("viewers") or 0)
        peak = max(viewers, int((previous or {}).get("peak") or 0))
        captured_at = datetime.now(UTC).isoformat()
        history = list((previous or {}).get("history") or [])
        history.append({"t": captured_at, "v": viewers})
        history = history[-_HISTORY_LIMIT:]
        session = {
            "title": str(status.get("title") or "")[:200],
            "category": str(status.get("category") or "")[:100],
            "description": str(status.get("description") or "")[:500],
            "user_id": str(status.get("user_id") or ""),
            "started_at": started,
            "thumbnail": str(status.get("thumbnail") or ""),
            "url": url or (previous or {}).get("url"),
            "viewers": viewers,
            "peak": peak,
            "history": history,
            "captured_at": captured_at,
        }
        await self._repo.set(self._key, json.dumps(session, ensure_ascii=False))
        return session

    async def clear(self) -> None:
        await self._repo.delete(self._key)
