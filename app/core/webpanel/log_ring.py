"""Кольцевой буфер логов для вкладки «Логи» вебпанели."""
from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime


class RingBufferHandler(logging.Handler):
    """Хранит последние N записей лога в памяти (не блокирует приложение)."""

    def __init__(self, capacity: int = 500) -> None:
        super().__init__(level=logging.INFO)
        self.capacity = capacity
        self._records: deque[dict[str, str]] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
            text = record.getMessage()
            if len(text) > 2000:
                text = text[:2000] + "…"
            entry = {"t": ts, "level": record.levelname, "name": record.name, "msg": text}
            with self._lock:
                self._records.append(entry)
        except Exception:
            pass

    def snapshot(self, limit: int | None = None) -> list[dict[str, str]]:
        with self._lock:
            items = list(self._records)
        if limit:
            items = items[-limit:]
        return items
