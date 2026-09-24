"""Команда ping — алиас для /status."""

from __future__ import annotations

# NOTE: Основные команды /ping, /status и /health перенесены в health.py.
# Для обратной совместимости имя PingCog остаётся доступным.
from app.cogs.general.health import HealthCog

PingCog = HealthCog
__all__ = ["PingCog"]