"""Тесты DI-контейнера: автосборка, синглтоны, ошибки и инъекция когов."""
import os
import tempfile

import pytest

from app.core.container import CycleError, DependencyContainer, ResolutionError


class _A:
    def __init__(self, value: int = 42) -> None:
        self.value = value


class _B:
    def __init__(self, a: _A) -> None:
        self.a = a


class _Labeled:
    def __init__(self, label: str) -> None:
        self.label = label


class _X:
    def __init__(self, y: "_Y") -> None:
        self.y = y


class _Y:
    def __init__(self, x: "_X") -> None:
        self.x = x


def test_resolves_by_annotation():
    container = DependencyContainer()
    b = container.build(_B)
    assert isinstance(b.a, _A)
    assert b.a.value == 42


def test_defaults_used_when_dependency_missing():
    container = DependencyContainer()
    container.supply("a", _A(value=1))
    c = container.build(_B)
    assert c.a.value == 1


def test_instances_are_singletons():
    container = DependencyContainer()
    assert container.build(_A) is container.build(_A)


def test_unknown_param_raises():
    container = DependencyContainer()
    with pytest.raises(ResolutionError):
        container.build(_Labeled)


def test_cycle_detected():
    container = DependencyContainer()
    container.register_class(_X)
    container.register_class(_Y)
    with pytest.raises(CycleError):
        container.build(_X)


@pytest.mark.asyncio
async def test_app_container_injects_cog():
    from app.cogs.administration.setup import SetupCog
    from app.config import Config
    from app.core.bot import MegaBot
    from app.services.settings_service import SettingsService

    with tempfile.TemporaryDirectory() as tmp:
        config = Config(token="x", prefix="!", db_path=os.path.join(tmp, "bot.db"), log_level="ERROR", status_activity="s", owner_id=None)
        bot = MegaBot(config)
        await bot.setup_hook()
        packages = bot.packages
        assert packages is not None

        settings = packages["app.services"].resolve("settings")
        assert isinstance(settings, SettingsService)

        cog_container = packages.container_for("app.cogs.administration.setup")
        assert cog_container is not None
        cog = cog_container.build(SetupCog)
        assert isinstance(cog.settings, SettingsService)
        assert cog.settings is settings
        await bot.close()


@pytest.mark.asyncio
async def test_all_cogs_build_through_di():
    import importlib
    import pkgutil

    from discord.ext import commands

    from app.cogs import COGS_PACKAGE
    from app.config import Config
    from app.core.bot import MegaBot

    with tempfile.TemporaryDirectory() as tmp:
        config = Config(token="x", prefix="!", db_path=os.path.join(tmp, "bot.db"), log_level="ERROR", status_activity="s", owner_id=None)
        bot = MegaBot(config)
        await bot.setup_hook()
        try:
            packages = bot.packages
            assert packages is not None
            package = importlib.import_module(COGS_PACKAGE)
            modules = sorted(
                (m for m in pkgutil.walk_packages(package.__path__, prefix=f"{COGS_PACKAGE}.") if not m.ispkg),
                key=lambda m: m.name,
            )
            built_names: set[str] = set()
            for module in modules:
                mod = importlib.import_module(module.name)
                for member_name, member in vars(mod).items():
                    if not (isinstance(member, type) and issubclass(member, commands.Cog)):
                        continue
                    if member is commands.Cog or member.__module__ != mod.__name__:
                        continue
                    container = packages.container_for(module.name)
                    assert container is not None, f"нет контейнера для {module.name}"
                    # если DI не собрал ког, loader молча уходит в fallback member(bot) — ловим это
                    cogs = container.build(member)
                    assert isinstance(cogs, member)
                    built_names.add(member.__name__)
            assert len(built_names) >= 20, f"собрано когов через DI: {len(built_names)}"
        finally:
            await bot.close()


@pytest.mark.asyncio
async def test_layers_block_repository_in_cogs():
    from app.config import Config
    from app.core.bot import MegaBot
    from app.data.settings_repository import SettingsRepository

    with tempfile.TemporaryDirectory() as tmp:
        config = Config(token="x", prefix="!", db_path=os.path.join(tmp, "bot.db"), log_level="ERROR", status_activity="s", owner_id=None)
        bot = MegaBot(config)
        await bot.setup_hook()
        packages = bot.packages

        data_container = packages["app.data"]
        services_container = packages["app.services"]
        cogs_container = packages["app.cogs"]

        repo = data_container.resolve(SettingsRepository)
        assert isinstance(repo, SettingsRepository)
        assert services_container.resolve("settings")._repo is repo
        with pytest.raises(ResolutionError):
            cogs_container.resolve("SettingsRepository")
        with pytest.raises(ResolutionError):
            cogs_container.resolve("db")
        # подпакет кога наследует границу слоя через родителя
        cog_pkg_container = packages.container_for("app.cogs.administration.setup")
        assert cog_pkg_container is not None
        with pytest.raises(ResolutionError):
            cog_pkg_container.resolve("SettingsRepository")
        await bot.close()
