"""Шина событий для живой ленты вебпанели.

Публикаторы (коги, бот, логи) зовут ``publish`` — потокобезопасно, дёшево,
никто не ждёт доставки. Вебпанель периодически забирает новое через ``drain``
и раздаёт ws-клиентам; при отсутствии клиентов шина просто ротирует буфер.
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any


class EventBus:
    def __init__(self, maxlen: int = 300) -> None:
        self._lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._seq = 0

    def publish(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._seq += 1
            event = {
                "seq": self._seq,
                "type": event_type,
                "data": data,
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            self._events.append(event)
        return event

    def drain(self, after_seq: int = 0) -> list[dict[str, Any]]:
        """События с номером больше ``after_seq`` (для новых клиентов — с 0)."""
        with self._lock:
            return [event for event in self._events if event["seq"] > after_seq]

    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq
