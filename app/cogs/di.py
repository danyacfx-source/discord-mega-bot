"""DI пакета ``app.cogs``: контейнер когов, слой данных для него закрыт.

Все коги (включая коги из подпакетов, например ``app.cogs.moderation``) собираются
в контейнерах этой ветки: сервисы доступны, репозитории и БД запрещены.
"""

from __future__ import annotations

from app.db import REPOSITORY_CLASSES

#: Контейнер, в который этот пакет включается как ребёнок (коги видят сервисы).
PARENT = "app.services"

#: Ключи слоя данных, недоступные для когов (граница презентации).
DENIED = frozenset(("db", "Database", "app.db.database.Database")) | {cls.__name__ for cls in REPOSITORY_CLASSES}
