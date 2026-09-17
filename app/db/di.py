"""DI пакета ``app.db``: свой контейнер слоя данных, репозитории регистрируются здесь."""

from __future__ import annotations

from app.core.container import DependencyContainer
from app.db import REPOSITORY_CLASSES

#: Контейнер, в который этот пакет включается как ребёнок (данные видят ядро).
PARENT = "app.core"


def register(container: DependencyContainer) -> None:
    for repo_cls in REPOSITORY_CLASSES:
        container.register_class(repo_cls)
