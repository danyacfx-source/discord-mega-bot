"""Protocol-контракты портов — границы, через которые ядро зависит от инфраструктуры.

Порты структурно совпадают с реальными классами app/ (проверяется в
rewrite/adapters.py и в тестах). Это позволяет подменять реальную инфраструктуру
фейками в тестах без изменения потребителей.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class KvStore(Protocol):
    """Хранилище «ключ-значение» (реальный кандидат: app/.../KvRepository)."""

    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str) -> None: ...
    async def delete(self, key: str) -> None: ...


@runtime_checkable
class SettingsStore(Protocol):
    """Настройки гильдии (реальный кандидат: app/.../SettingsService)."""

    async def get(self, guild_id: int) -> dict[str, object]: ...
    async def update(self, guild_id: int, **values: object) -> None: ...


@runtime_checkable
class KickStatusSource(Protocol):
    """Статус канала Kick (реальный кандидат: app/.../KickService)."""

    async def channel_status(self, channel_slug: str) -> dict[str, object] | None: ...


@runtime_checkable
class DonationsSource(Protocol):
    """Последние донаты (реальный кандидат: app/.../DonationService)."""

    async def fetch_recent(self, limit: int = 50) -> list[dict[str, object]]: ...


@runtime_checkable
class LogSink(Protocol):
    """Аудиты/логи в Discord-каналы (реальный кандидат: app/.../LoggingService)."""

    async def send_embed(self, guild: object, embed: object, *, category: str | None = None) -> None: ...
