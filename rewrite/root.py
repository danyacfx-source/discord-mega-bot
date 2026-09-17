"""Типизированный корень приложения: всё, чем владеет процесс бота."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Config
from app.db.database import Database
from app.services import Services
from rewrite.bot import Bot


@dataclass(slots=True)
class Root:
    """Единая точка владения графом зависимостей (composition root's output).

    ``db`` — низкоуровневая деталь; потребители по возможности работают с
    ``services`` (сервисы) или с портами из rewrite/ports.py, а не с БД напрямую.
    """

    config: Config
    db: Database
    bot: Bot
    services: Services
