"""Маскирует токены в query-строке access-лога aiohttp.

Страницы оверлея открываются по ссылке с ``?token=…`` (OBS browser source).
Без фильтра токен попадает в access-лог. Фильтр заменяет значение на ``***``.
"""

from __future__ import annotations

import logging
import re

_TOKEN_RE = re.compile(r"((?:[?&]|%3F|%26)token=)[^\s&\"'%]+", re.IGNORECASE)
_ACCESS_LOGGER = "aiohttp.access"


class TokenMaskFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        # Почти все строки лога не содержат токена: дешёвая проверка подстроки
        # отсекает regex до его запуска.
        if "token=" not in message.lower():
            return True
        masked = _TOKEN_RE.sub(r"\1***", message)
        if masked != message:
            record.msg = masked
            record.args = ()
        return True


def install() -> None:
    """Идемпотентно вешает фильтр на логгер access-лога."""
    logger = logging.getLogger(_ACCESS_LOGGER)
    if not any(isinstance(f, TokenMaskFilter) for f in logger.filters):
        logger.addFilter(TokenMaskFilter())
