"""Тесты rewrite: реальный граф без контейнера, порты, подмена реализации, коги."""

from __future__ import annotations

import pytest

from app.config import Config
from app.db.database import Database
from app.services import Services
from rewrite.composition import assemble
from rewrite.ports import DonationsSource, KickStatusSource, SettingsStore
from rewrite.root import Root


class FakeKick:
    """Фейк, структурно реализующий KickStatusSource (подмена реального сервиса)."""

    async def channel_status(self, channel_slug: str) -> dict[str, object] | None:
        return {"is_live": False, "viewer_count": 0}


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("BOT_TOKEN", "test-token")
    return Config.from_env()


@pytest.fixture
def db(tmp_path) -> Database:
    return Database(str(tmp_path / "rewrite_bot.db"))


def test_assemble_builds_really_all_services(config: Config, db: Database) -> None:
    root = assemble(config=config, db=db)

    assert isinstance(root, Root)
    assert root.bot.config is config
    assert root.bot.services is root.services
    assert isinstance(root.services, Services)

    # Каждое поле Services — реальный класс из app/, а не заглушка.
    assert root.services.settings.__class__.__name__ == "SettingsService"
    assert root.services.moderation.__class__.__name__ == "ModerationService"
    assert root.services.kick.__class__.__name__ == "KickService"
    assert root.services.donations.__class__.__name__ == "DonationService"
    assert root.services.logging.__class__.__name__ == "LoggingService"
    assert root.services.tickets.__class__.__name__ == "TicketService"
    assert root.services.tempvoice.__class__.__name__ == "TempVoiceService"
    assert root.services.birthdays.__class__.__name__ == "BirthdayService"


def test_real_services_conform_to_ports(config: Config, db: Database) -> None:
    root = assemble(config=config, db=db)

    # Реальные классы структурно соответствуют портам (runtime_checkable).
    assert isinstance(root.services.settings, SettingsStore)
    assert isinstance(root.services.kick, KickStatusSource)
    assert isinstance(root.services.donations, DonationsSource)


def test_override_swaps_real_service_via_port(config: Config, db: Database) -> None:
    fake = FakeKick()
    root = assemble(config=config, db=db, kick=fake)

    # Composition root подменил реализацию без правки потребителей.
    assert root.services.kick is fake
    assert isinstance(root.services.kick, KickStatusSource)


async def test_build_all_cogs_loads_real_cogs(config: Config, db: Database) -> None:
    root = assemble(config=config, db=db)
    from rewrite.cogs import build_all_cogs

    loaded = await build_all_cogs(root, start_tasks=False)
    assert len(loaded) == 34, loaded
    kick_cog = root.bot.get_cog("Kick")
    assert kick_cog is not None
    # Ког реально получил сервис из графа (не пересоздан контейнером).
    assert kick_cog.kick is root.services.kick  # type: ignore[attr-defined]

    setup_cog = root.bot.get_cog("Setup")
    assert setup_cog is not None
    assert setup_cog.settings is root.services.settings  # type: ignore[attr-defined]


async def test_cogs_receive_fake_when_overridden(config: Config, db: Database) -> None:
    from rewrite.cogs import build_all_cogs

    root = assemble(config=config, db=db, kick=FakeKick())
    await build_all_cogs(root, start_tasks=False)

    kick_cog = root.bot.get_cog("Kick")
    assert kick_cog is not None
    assert kick_cog.kick is root.services.kick  # type: ignore[attr-defined]
    assert isinstance(root.services.kick, FakeKick)


def test_adapters_ports_assert_assemble_matches_config(config: Config, db: Database) -> None:
    from rewrite.adapters import PORT_MAP, assert_ports

    # Карта «реальный класс → порт» замкнута на реальные имена.
    names = {cls.__name__: port.__name__ for cls, port in PORT_MAP}
    assert names == {
        "KvRepository": "KvStore",
        "SettingsService": "SettingsStore",
        "KickService": "KickStatusSource",
        "DonationService": "DonationsSource",
        "LoggingService": "LogSink",
    }
    assert_ports()

    root = assemble(config=config, db=db)
    assert root.config is config
    assert root.db is db


async def test_pipeline_smoke(config: Config, db: Database) -> None:
    """Полный offline-прогон: собрать граф, загрузить коги, закрыть бота."""
    from rewrite.cogs import build_all_cogs

    root = assemble(config=config, db=db)
    await build_all_cogs(root, start_tasks=False)
    assert root.bot.get_cog("General") is not None
    await root.bot.close()
    assert root.bot.db is None


async def test_privileged_cogs_wired_to_real_services(config: Config, db: Database) -> None:
    """Security: привилегированные коги получают реальные сервисы из Root."""
    from rewrite.cogs import build_all_cogs
    from rewrite.security import PRIVILEGED_WIRING, assert_wiring

    root = assemble(config=config, db=db)
    await build_all_cogs(root, start_tasks=False)

    # Инвариант склейки: никакой ког из таблицы не может получить не тот сервис.
    assert_wiring(root)

    # Ни один привилегированный ког не отсутствует в сборке.
    assert set(PRIVILEGED_WIRING) <= set(root.bot.cogs)


def test_no_secret_literals_in_rewrite() -> None:
    """Security: в rewrite нет секретов литералами — только чтение из Config."""
    import pathlib
    import re

    rewrite_dir = pathlib.Path(__file__).resolve().parents[1] / "rewrite"
    assert rewrite_dir.is_dir(), str(rewrite_dir)

    pattern = re.compile(
        r"(?im)^\s*"
        r"(?:token|secret|password|api_key|refresh_token|client_secret)"
        r"\s*=\s*['\"][^'\"]{8,}['\"]"
    )
    offenders: list[tuple[str, int]] = []
    for f in rewrite_dir.rglob("*.py"):
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append((str(f), lineno))
    assert not offenders, f"секреты литералами в rewrite: {offenders}"

    # Проверку умеем запускать и против самого склада app/ (контрольный вызов).
    assert pattern.search("token = 'super-secret-value-12345'")  # матчер рабочий
