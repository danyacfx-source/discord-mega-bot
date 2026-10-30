"""Общие фикстуры: фабрика MegaBot с config-оверрайдами для panel-тестов."""
from __future__ import annotations

import pytest

from app.config import Config
from app.core import crypto
from app.core.bot import MegaBot


@pytest.fixture
def at_rest_key(tmp_path, monkeypatch):
    """Изолирует ключ шифрования at-rest в tmp_path.

    Без этого тесты создавали бы ``data/.panel-key`` в репозитории и опирались
    на ключ, доставшийся от соседнего теста.
    """
    monkeypatch.delenv("PANEL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("PANEL_KEY_FILE", str(tmp_path / ".panel-key"))
    crypto._reset_for_tests()
    yield tmp_path / ".panel-key"
    crypto._reset_for_tests()


@pytest.fixture
def make_panel_bot(tmp_path, at_rest_key):
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
