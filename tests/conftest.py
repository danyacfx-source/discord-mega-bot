"""Общие фикстуры: фабрика MegaBot с config-оверрайдами для panel-тестов."""
from __future__ import annotations

import pytest

from app.config import Config
from app.core.bot import MegaBot


@pytest.fixture
def make_panel_bot(tmp_path):
    """Бот с тестовой конфигурацией; kwargs переопределяют поля Config."""

    def _make(**kwargs) -> MegaBot:
        value = {"panel_port": 17890, **kwargs}
        config = Config(
            token="x",
            prefix="!",
            db_path=str(tmp_path / "bot.db"),
            log_level="ERROR",
            status_activity="s",
            owner_id=None,
            **value,
        )
        return MegaBot(config)

    return _make
