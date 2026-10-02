"""Лента последних сообщений чата стрима — источник для оверлей-виджета «Чат»."""
from __future__ import annotations

import time
from collections import deque
from typing import Any


class ChatFeed:
    """Кольцо последних сообщений (Kick/Twitch) в памяти; один event loop — без блокировок."""

    def __init__(self, maxlen: int = 300) -> None:
        self._items: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def push(self, platform: str, name: str, text: str, *, is_mod: bool = False) -> None:
        self._items.append(
            {
                "platform": str(platform)[:16],
                "name": str(name)[:64],
                "text": str(text)[:500],
                "mod": bool(is_mod),
                "ts": time.time(),
            }
        )

    def recent(self, limit: int = 60) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        return list(self._items)[-limit:]
