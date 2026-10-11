"""Базовый сервис стрим-платформы: HTTP-клиент, sticky и хранилища в KV.

Общий каркас для TwitchService / KickService / VkVideoService: наследник
задаёт платформенные сегменты ключей и имя HTTP-клиента, платформенный API
(поллинг, чат, модерация) остаётся в наследнике.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp

from app.core.api_client import ApiClient
from app.services.stream_archive import StreamArchiveStore
from app.services.stream_rsvp import StreamRsvpStore
from app.services.stream_session import StreamSessionStore
from app.services.viewer_sessions import ViewerSessionStore

if TYPE_CHECKING:
    from app.config import Config
    from app.db.kv_repository import KvRepository


class StreamPlatformService:
    """Каркас стрим-платформы: ApiClient из config.api.*, хранилища, sticky."""

    #: Сегмент ключей session/archive/viewer (``stream:session:<platform>:...``).
    platform: str = ""
    #: Сегмент ключа sticky (``<sticky_platform>:sticky``).
    sticky_platform: str = ""
    #: Сегмент ключа rsvp (``stream:rsvp:<rsvp_platform>...``).
    rsvp_platform: str = ""
    #: Имя сервиса в ApiClient (логи, circuit breaker).
    http_name: str = ""
    default_user_agent: str = "DiscordMegaBot/3.3"

    def __init__(self, repo: KvRepository, config: Config) -> None:
        self._repo = repo
        self._config = config
        self._http = ApiClient(
            self.http_name,
            timeout=config.api_timeout_seconds,
            user_agent=self.default_user_agent,
            proxy=config.api_proxy,
            max_concurrency=config.api_max_concurrency,
            circuit_failure_threshold=config.api_circuit_failure_threshold,
            circuit_reset_seconds=config.api_circuit_reset_seconds,
        )

    @property
    def session(self) -> aiohttp.ClientSession:
        return self._http.session

    async def aclose(self) -> None:
        await self._http.close()

    # -- хранилища -----------------------------------------------------------

    def session_store(self, slug: str) -> StreamSessionStore:
        """Хранилище сессии стрима (пик зрителей, метаданные) для карточек."""
        return StreamSessionStore(self._repo, f"stream:session:{self.platform}:{slug.lower()}")

    def archive_store(self, slug: str) -> StreamArchiveStore:
        """Архив завершённых эфиров для /stream_stats."""
        return StreamArchiveStore(self._repo, f"stream:archive:{self.platform}:{slug.lower()}")

    def viewer_store(self) -> ViewerSessionStore:
        """Онлайн-сессии зрителей чата (источник событий зависит от платформы)."""
        return ViewerSessionStore(self._repo, f"stream:viewers:{self.platform}")

    def rsvp_store(self, slug: str | None = None) -> StreamRsvpStore:
        """Хранилище id старт-анонса для команды /stream_rsvp."""
        key = f"stream:rsvp:{self.rsvp_platform}"
        if slug:
            key += f":{slug.lower()}"
        return StreamRsvpStore(self._repo, key)

    # -- sticky ---------------------------------------------------------------

    def _sticky_key(self) -> str:
        return f"{self.sticky_platform}:sticky"

    async def sticky_message_id(self) -> int | None:
        raw = await self._repo.get(self._sticky_key())
        return int(raw) if raw and raw.isdigit() else None

    async def set_sticky_message(self, message_id: int) -> None:
        await self._repo.set(self._sticky_key(), str(message_id))

    async def clear_sticky_message(self) -> None:
        await self._repo.delete(self._sticky_key())
