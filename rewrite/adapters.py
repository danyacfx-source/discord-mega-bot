"""Адаптеры портов: реальные классы app/ как реализации интерфейсов.

Ничего не переопределяется: реальные сервисы/репозитории и есть адаптеры.
Здесь они сводятся к портам и структурно проверяются, чтобы «работает ли
подмена фейком» гарантировалось компиляцией/тестом, а не соглашением.

Пример использования (на реальном объекте):
    assert isinstance(kick_service, KickStatusSource)  # структурный чек
"""

from __future__ import annotations

from app.db.kv_repository import KvRepository
from app.services.donation_service import DonationService
from app.services.kick_service import KickService
from app.services.logging_service import LoggingService
from app.services.settings_service import SettingsService
from rewrite.ports import DonationsSource, KickStatusSource, KvStore, LogSink, SettingsStore

#: Все реальные классы обязаны структурно соответствовать своим портам.
PORT_MAP: tuple[tuple[type, type], ...] = (
    (KvRepository, KvStore),
    (SettingsService, SettingsStore),
    (KickService, KickStatusSource),
    (DonationService, DonationsSource),
    (LoggingService, LogSink),
)


def assert_ports() -> None:
    """Падает, если реальный класс перестал соответствовать своему порту."""
    for concrete, port in PORT_MAP:
        assert isinstance(concrete, port), (
            f"{concrete.__name__} не реализует {port.__name__} "
            "(методы порта перестали совпадать с реальным классом)"
        )
