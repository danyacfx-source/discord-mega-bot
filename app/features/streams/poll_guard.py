"""Дедупликация ошибок поллинга стримов: лог не забивается повторами."""
from __future__ import annotations

import logging

logger = logging.getLogger("bot.cogs")


class PollGuard:
    """Серия ошибок поллинга: первая — со стеком, повторы — редкие и короткие.

    Вызов ``ok()`` закрывает серию; если ошибок набралось 3 и больше,
    пишется info о восстановлении — инцидент остаётся видимым, но лог не
    забивается stack trace'ами каждые 60 секунд.
    """

    def __init__(self) -> None:
        self._fails: dict[str, int] = {}

    def fail(self, key: str, message: str) -> None:
        """Записывает ошибку поллинга (вызывать внутри ``except``)."""
        count = self._fails.get(key, 0) + 1
        self._fails[key] = count
        if count == 1:
            logger.exception(message)
        elif count in (2, 3) or count % 30 == 0:
            logger.warning("%s (сбой №%d)", message, count)

    def ok(self, key: str) -> None:
        """Закрывает серию ошибок после успешного поллинга."""
        count = self._fails.pop(key, 0)
        if count >= 3:
            logger.info("Поллинг %s восстановился после %d ошибок", key, count)

    @property
    def failures(self) -> dict[str, int]:
        """Текущие счётчики серий (для тестов/диагностики)."""
        return dict(self._fails)
