"""Корень приложения: всё, чем владеет процесс бота (результат composition root)."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Config
from app.core.bot import MegaBot
from app.core.services import Services
from app.db.database import Database


@dataclass(slots=True)
class Root:
    """Единая точка владения графом зависимостей.

    ``db`` — низкоуровневая деталь; потребители работают с ``services``,
    а не с БД напрямую.
    """

    config: Config
    db: Database
    bot: MegaBot
    services: Services
