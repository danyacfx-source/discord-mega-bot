"""Онлайн-сессии зрителей Kick: кто из чата сейчас смотрит стрим.

Сессии обновляются из Pusher-событий чата (``_handle_chat_message`` в коге),
``sweep()`` закрывает тех, кто молчит дольше порога — вызывается из
поллинг-цикла. Отдельная сессия на каждое сообщение не заводится: одно
активное окно на зрителя (first_seen/last_seen/messages).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from app.db.kv_repository import KvRepository

#: Без сообщений столько секунд — зритель считается вышедшим из эфира.
OFFLINE_AFTER_SECONDS = 300
#: Сколько завершённых сессий помнит хранилище.
_HISTORY_LIMIT = 50


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


class ViewerSessionStore:
    """Сессии зрителей в KV: ``touch()`` на сообщение, ``sweep()`` — закрытие."""

    def __init__(self, repo: KvRepository, key: str = "stream:viewers:kick") -> None:
        self._repo = repo
        self._key = key

    async def _load(self) -> dict[str, Any]:
        raw = await self._repo.get(self._key)
        if raw:
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                data = None
            if isinstance(data, dict) and isinstance(data.get("active"), dict):
                data.setdefault("history", [])
                return data
        return {"active": {}, "history": []}

    async def _save(self, data: dict[str, Any]) -> None:
        await self._repo.set(self._key, json.dumps(data, ensure_ascii=False))

    async def touch(self, username: str, *, stream_id: str | None = None) -> dict[str, Any] | None:
        """Отмечает сообщение зрителя: открывает сессию или продлевает её.

        Плюс копит общий счёт сообщений за эфир в ``tally`` (топ говорящих):
        при смене ``stream_id`` (новый стрим) счётчики обнуляются.
        """
        username = str(username or "").strip()
        if not username:
            return None
        data = await self._load()
        if stream_id and data.get("stream_id") != stream_id:
            data["tally"] = {}
            data["stream_id"] = stream_id
        key = username.casefold()
        now = datetime.now(UTC).isoformat()
        session = data["active"].get(key)
        if not isinstance(session, dict):
            session = {"name": username, "first_seen": now, "messages": 0}
        session["last_seen"] = now
        try:
            session["messages"] = int(session.get("messages") or 0) + 1
        except (TypeError, ValueError):
            session["messages"] = 1
        data["active"][key] = session
        tally = data.get("tally")
        if not isinstance(tally, dict):
            tally = {}
            data["tally"] = tally
        entry = tally.get(key)
        if not isinstance(entry, dict):
            entry = {"name": username, "count": 0}
        entry["name"] = username
        try:
            entry["count"] = int(entry.get("count") or 0) + 1
        except (TypeError, ValueError):
            entry["count"] = 1
        tally[key] = entry
        await self._save(data)
        return session

    async def sweep(self) -> list[dict[str, Any]]:
        """Закрывает сессии без сообщений дольше ``OFFLINE_AFTER_SECONDS``.

        Возвращает закрытые сессии (с ``closed_at``); они уезжают в history.
        """
        data = await self._load()
        now = datetime.now(UTC)
        closed: list[dict[str, Any]] = []
        for key, session in list(data["active"].items()):
            if not isinstance(session, dict):
                data["active"].pop(key, None)
                continue
            last_seen = _parse_dt(session.get("last_seen"))
            if last_seen is None or (now - last_seen).total_seconds() > OFFLINE_AFTER_SECONDS:
                data["active"].pop(key, None)
                session["closed_at"] = now.isoformat()
                closed.append(session)
        if closed:
            data["history"] = (closed + list(data.get("history") or []))[:_HISTORY_LIMIT]
            await self._save(data)
        return closed

    async def active(self) -> dict[str, dict[str, Any]]:
        """Сейчас в чате: ключ — username.casefold()."""
        return dict((await self._load())["active"])

    async def top_talkers(self, *, limit: int = 5) -> list[dict[str, Any]]:
        """Топ по числу сообщений за текущий эфир: ``{"name", "count"}``, новые первыми."""
        data = await self._load()
        tally = data.get("tally")
        entries = [v for v in tally.values() if isinstance(v, dict)] if isinstance(tally, dict) else []
        counted: list[tuple[int, dict[str, Any]]] = []
        for entry in entries:
            try:
                count = int(entry.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            counted.append((count, entry))
        counted.sort(key=lambda pair: -pair[0])
        return [{"name": str(entry.get("name") or ""), "count": count} for count, entry in counted[: max(1, limit)]]

    async def history(self) -> list[dict[str, Any]]:
        return list((await self._load()).get("history") or [])
