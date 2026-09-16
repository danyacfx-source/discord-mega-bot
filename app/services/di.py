"""DI пакета ``app.services``: свой контейнер бизнес-логики, сервисы регистрируются здесь."""

from __future__ import annotations

from app.core.container import DependencyContainer
from app.services import SERVICE_ALIASES, SERVICE_CLASSES

#: Контейнер, в который этот пакет включается как ребёнок (сервисы видят слой данных).
PARENT = "app.data"


def register(container: DependencyContainer) -> None:
    for service_cls in SERVICE_CLASSES:
        container.register_class(service_cls)
    for short, class_name in SERVICE_ALIASES.items():
        container.alias(short, class_name)
