"""Общий надёжный HTTP-клиент для внешних API.

Все внешние интеграции используют одинаковые правила:
- короткие connect/read таймауты;
- повтор только для временных ошибок и 429;
- уважение Retry-After;
- ограничение времени ожидания;
- единый User-Agent и понятная ошибка с HTTP-статусом.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp
from multidict import CIMultiDictProxy

logger = logging.getLogger("bot.api")

_RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class ApiRequestError(RuntimeError):
    """Ошибка HTTP-запроса с сохранёнными статусом и телом ответа."""

    def __init__(self, service: str, status: int, body: Any = None) -> None:
        self.service = service
        self.status = status
        self.body = body
        detail = body if isinstance(body, str) else ""
        super().__init__(f"{service}: HTTP {status}" + (f" — {detail[:240]}" if detail else ""))


class ApiClient:
    """Минимальный retry-aware клиент поверх aiohttp."""

    def __init__(
        self,
        service: str,
        *,
        timeout: float = 20.0,
        user_agent: str = "DiscordMegaBot/3.3 (+https://discord.com)",
        proxy: str | None = None,
    ) -> None:
        self.service = service
        self.timeout = aiohttp.ClientTimeout(total=timeout, connect=min(5.0, timeout), sock_read=timeout)
        self.user_agent = user_agent
        self.proxy = proxy
        self._session: aiohttp.ClientSession | None = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent},
                proxy=self.proxy,
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def json(
        self,
        method: str,
        url: str,
        *,
        attempts: int = 3,
        acceptable: tuple[int, ...] = (200,),
        circuit: str | None = None,
        **kwargs: Any,
    ) -> tuple[int, Any, CIMultiDictProxy[str]]:
        """Возвращает `(status, json, headers)` или выбрасывает ApiRequestError.

        Запрос автоматически проходит через circuit breaker с именем
        ``circuit`` (по умолчанию — название сервиса в нижнем регистре).
        При открытом breaker поднимается ApiRequestError со статусом 503.
        """
        from app.core.circuit_breaker import CircuitOpenError, get_circuit_breaker

        breaker = get_circuit_breaker((circuit or self.service).lower())

        def _is_failure(exc: BaseException) -> bool:
            if isinstance(exc, CircuitOpenError):
                return False
            if isinstance(exc, ApiRequestError):
                return exc.status in _RETRY_STATUSES or exc.status == 599
            return True

        try:
            return await breaker.call(
                self._request_json(
                    method,
                    url,
                    attempts=attempts,
                    acceptable=acceptable,
                    **kwargs,
                ),
                is_failure=_is_failure,
            )
        except CircuitOpenError as exc:
            raise ApiRequestError(self.service, 503, str(exc)) from exc

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        attempts: int = 3,
        acceptable: tuple[int, ...] = (200,),
        **kwargs: Any,
    ) -> tuple[int, Any, CIMultiDictProxy[str]]:
        """Возвращает `(status, json, headers)` или выбрасывает ApiRequestError."""
        attempts = max(1, min(attempts, 5))
        for attempt in range(attempts):
            try:
                async with self.session.request(method, url, **kwargs) as response:
                    try:
                        body = await response.json(content_type=None)
                    except (aiohttp.ContentTypeError, ValueError):
                        body = None
                    if response.status in acceptable:
                        return response.status, body, response.headers
                    error = ApiRequestError(self.service, response.status, body)
                    if response.status not in _RETRY_STATUSES or attempt == attempts - 1:
                        raise error
                    await self._backoff(response.headers, attempt)
            except ApiRequestError:
                raise
            except (aiohttp.ClientError, TimeoutError) as exc:
                if attempt == attempts - 1:
                    raise ApiRequestError(self.service, 599, str(exc)) from exc
                await self._backoff({}, attempt)
        raise ApiRequestError(self.service, 599, "исчерпаны попытки")

    async def json_with_circuit(
        self,
        method: str,
        url: str,
        *,
        circuit_name: str,
        attempts: int = 3,
        acceptable: tuple[int, ...] = (200,),
        **kwargs: Any,
    ) -> tuple[int, Any, CIMultiDictProxy[str]]:
        """Устаревший алиас: ``json()`` уже защищает все запросы circuit breaker'ом."""
        return await self.json(
            method,
            url,
            attempts=attempts,
            acceptable=acceptable,
            circuit=circuit_name,
            **kwargs,
        )

    async def text(
        self,
        method: str,
        url: str,
        *,
        attempts: int = 3,
        acceptable: tuple[int, ...] = (200,),
        circuit: str | None = None,
        **kwargs: Any,
    ) -> tuple[int, str, CIMultiDictProxy[str]]:
        from app.core.circuit_breaker import CircuitOpenError, get_circuit_breaker

        breaker = get_circuit_breaker((circuit or self.service).lower())

        def _is_failure(exc: BaseException) -> bool:
            if isinstance(exc, CircuitOpenError):
                return False
            if isinstance(exc, ApiRequestError):
                return exc.status in _RETRY_STATUSES or exc.status == 599
            return True

        try:
            return await breaker.call(
                self._request_text(
                    method,
                    url,
                    attempts=attempts,
                    acceptable=acceptable,
                    **kwargs,
                ),
                is_failure=_is_failure,
            )
        except CircuitOpenError as exc:
            raise ApiRequestError(self.service, 503, str(exc)) from exc

    async def _request_text(
        self,
        method: str,
        url: str,
        *,
        attempts: int = 3,
        acceptable: tuple[int, ...] = (200,),
        **kwargs: Any,
    ) -> tuple[int, str, CIMultiDictProxy[str]]:
        attempts = max(1, min(attempts, 5))
        for attempt in range(attempts):
            try:
                async with self.session.request(method, url, **kwargs) as response:
                    body = await response.text()
                    if response.status in acceptable:
                        return response.status, body, response.headers
                    error = ApiRequestError(self.service, response.status, body)
                    if response.status not in _RETRY_STATUSES or attempt == attempts - 1:
                        raise error
                    await self._backoff(response.headers, attempt)
            except ApiRequestError:
                raise
            except (aiohttp.ClientError, TimeoutError) as exc:
                if attempt == attempts - 1:
                    raise ApiRequestError(self.service, 599, str(exc)) from exc
                await self._backoff({}, attempt)
        raise ApiRequestError(self.service, 599, "исчерпаны попытки")

    async def _backoff(self, headers: Any, attempt: int) -> None:
        """Exponential backoff with jitter."""
        retry_after = _retry_after_seconds(headers)

        if retry_after is not None:
            # Respect Discord/API retry-after header
            delay = retry_after
        else:
            # Exponential backoff: 1s, 2s, 4s, 8s, ... max 30s
            base_delay = min(30.0, 2.0 ** attempt)
            # Add jitter (0-10% of base delay)
            jitter = random.uniform(0.0, base_delay * 0.1)
            delay = base_delay + jitter

        logger.warning(
            "%s: retry %d in %.2fs (retry_after=%s)",
            self.service,
            attempt + 1,
            delay,
            retry_after is not None
        )
        await asyncio.sleep(delay)


def _retry_after_seconds(headers: Any) -> float | None:
    raw = headers.get("Retry-After") if headers else None
    if not raw:
        return None
    try:
        return max(0.0, min(30.0, float(raw)))
    except (TypeError, ValueError):
        try:
            target = parsedate_to_datetime(str(raw))
            if target.tzinfo is None:
                target = target.replace(tzinfo=UTC)
            return max(0.0, min(30.0, (target - datetime.now(UTC)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return None
