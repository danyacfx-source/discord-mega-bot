"""Сборка когов: явная таблица зависимостей вместо рефлексии контейнера.

Обход модулей совпадает с app/core/loader.py (детерминированный порядок,
защита от тёзок), но ког строится по читаемой таблице ``COG_PROVIDERS``:
имя параметра конструктора → откуда из ``Root`` его взять.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from collections.abc import Callable
from typing import TYPE_CHECKING

from app.cogs import COGS_PACKAGE

if TYPE_CHECKING:
    from rewrite.root import Root

logger = logging.getLogger("bot")

#: Источники зависимостей для когов: имя параметра → поставщик значения.
#: Если параметр называется ``bot`` — бот подставляется первым позиционным аргументом.
COG_PROVIDERS: dict[str, Callable[[Root], object]] = {
    "settings": lambda r: r.services.settings,
    "moderation": lambda r: r.services.moderation,
    "cases": lambda r: r.services.cases,
    "music": lambda r: r.services.music,
    "tickets": lambda r: r.services.tickets,
    "logging": lambda r: r.services.logging,
    "reminders": lambda r: r.services.reminders,
    "polls": lambda r: r.services.polls,
    "giveaways": lambda r: r.services.giveaways,
    "reaction_roles": lambda r: r.services.reaction_roles,
    "scheduled": lambda r: r.services.scheduled,
    "donations": lambda r: r.services.donations,
    "twitch": lambda r: r.services.twitch,
    "kick": lambda r: r.services.kick,
    "vk_video": lambda r: r.services.vk_video,
    "tempvoice": lambda r: r.services.tempvoice,
    "birthdays": lambda r: r.services.birthdays,
    "seasons": lambda r: r.services.seasons,
}


def _build_cog(root: Root, cls: type) -> object:
    """Строит ког по сигнатуре конструктора и таблице ``COG_PROVIDERS``.

    Если все необязательные зависимости резолвятся — ``cls(bot, **kwargs)``.
    Иначе (неизвестный обязательный параметр) — откат к ``cls(bot)``, как в loader.
    """
    params = list(inspect.signature(cls).parameters.values())
    kwargs: dict[str, object] = {}
    resolvable = True
    for param in params:
        if param.name == "bot":
            continue
        if param.name in COG_PROVIDERS:
            kwargs[param.name] = COG_PROVIDERS[param.name](root)
        elif param.default is not inspect.Parameter.empty:
            continue
        else:
            resolvable = False
            break
    if not resolvable:
        logger.debug("Явная сборка %s невозможна — резерв cls(bot)", cls.__name__)
        return cls(root.bot)
    return cls(root.bot, **kwargs)


async def build_all_cogs(root: Root, *, start_tasks: bool = True) -> list[str]:
    """Регистрирует все реальные коги из app/ через явную таблицу зависимостей.

    ``start_tasks=False`` (тесты/офлайн-проверка) подавляет ``cog_load`` —
    фоновые лупы когов требует работающего соединения с Discord.
    """
    async def _cog_load_noop(self: object) -> None:  # noqa: ANN001
        """Заглушка cog_load: не стартует фоновые задачи без живого бота."""

    loaded: list[str] = []
    failures: list[tuple[str, str]] = []
    used_names: set[str] = set()
    package = importlib.import_module(COGS_PACKAGE)
    modules = sorted(
        (m for m in pkgutil.walk_packages(package.__path__, prefix=f"{COGS_PACKAGE}.") if not m.ispkg),
        key=lambda m: m.name,
    )

    for module in modules:
        try:
            mod = importlib.import_module(module.name)
        except Exception:
            logger.exception("Не удалось импортировать модуль кога %s", module.name)
            failures.append((module.name, "import"))
            continue

        for member_name, member in vars(mod).items():
            if not isinstance(member, type) or member.__name__ in used_names or member.__module__ != mod.__name__:
                continue
            if not hasattr(member, "__mro__") or not any(base.__name__ == "Cog" for base in member.__mro__):
                continue
            try:
                instance = _build_cog(root, member)
                if not start_tasks:
                    # Отключаем cog_load только у этого экземпляра (заглушкой),
                    # чтобы add_cog не поднимал фоновые лупы до подключения к Discord.
                    instance.cog_load = _cog_load_noop.__get__(instance)  # type: ignore[attr-defined]
                await root.bot.add_cog(instance)
            except Exception:
                logger.exception("Не удалось загрузить ког %s.%s", module.name, member_name)
                failures.append((module.name, "add_cog"))
                continue
            used_names.add(member.__name__)
            loaded.append(module.name)

    if failures:
        logger.error("Загружено когов: %d, с ошибками: %d", len(loaded), len(failures))
    else:
        logger.info("Загружено когов: %d (compose root)", len(loaded))
    return loaded
