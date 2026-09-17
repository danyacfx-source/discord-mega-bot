"""Автозагрузчик когов и регистрация persistent-представлений.

Коги собираются по явной таблице ``COG_PROVIDERS`` (имя параметра конструктора →
сервис из ``bot.services``) вместо рефлексии DI-контейнера. Граница слоёв
(коги не видят репозитории/БД) гарантирована статически: имена параметров
допускают только ``bot`` и ключи таблицы.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from collections.abc import Callable
from typing import TYPE_CHECKING

from discord.ext import commands

from app.cogs import COGS_PACKAGE

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot")

#: Источники зависимостей когов: имя параметра → сервис из bot.services.
#: Параметр ``bot`` подставляется первым позиционным аргументом.
COG_PROVIDERS: dict[str, Callable[[MegaBot], object]] = {
    "settings": lambda b: b.services.settings,
    "moderation": lambda b: b.services.moderation,
    "music": lambda b: b.services.music,
    "tickets": lambda b: b.services.tickets,
    "logging": lambda b: b.services.logging,
    "reminders": lambda b: b.services.reminders,
    "polls": lambda b: b.services.polls,
    "giveaways": lambda b: b.services.giveaways,
    "reaction_roles": lambda b: b.services.reaction_roles,
    "donations": lambda b: b.services.donations,
    "twitch": lambda b: b.services.twitch,
    "kick": lambda b: b.services.kick,
    "tempvoice": lambda b: b.services.tempvoice,
    "birthdays": lambda b: b.services.birthdays,
    "seasons": lambda b: b.services.seasons,
}


def _build_cog(bot: MegaBot, cls: type) -> object:
    """Строит ког по сигнатуре конструктора и таблице ``COG_PROVIDERS``.

    Все обязательные зависимости резолвятся — ``cls(bot, **kwargs)``.
    Иначе (неизвестный обязательный параметр) — откат к ``cls(bot)``.
    """
    params = list(inspect.signature(cls.__init__).parameters.values())[1:]
    kwargs: dict[str, object] = {}
    resolvable = True
    for param in params:
        if param.name == "bot":
            continue
        if param.name in COG_PROVIDERS:
            kwargs[param.name] = COG_PROVIDERS[param.name](bot)
        elif param.default is not inspect.Parameter.empty:
            continue
        else:
            resolvable = False
            break
    if not resolvable:
        logger.debug("Явная сборка %s невозможна — резерв cls(bot)", cls.__name__)
        return cls(bot)
    return cls(bot, **kwargs)


async def load_cogs(bot: MegaBot) -> list[str]:
    """Обходит app.cogs детерминированно и регистрирует коги по одному.

    - порядок определяется именами модулей (стабильный лог);
    - сбой одного кога не мешает остальным (ошибка логируется);
    - защита от повторной регистрации когов-тёзок.
    """
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
            if not isinstance(member, type) or not issubclass(member, commands.Cog):
                continue
            if member is commands.Cog or member.__module__ != mod.__name__:
                continue
            if member.__name__ in used_names:
                logger.error("Ког %s пропущен: имя %s уже занято", module.name, member_name)
                failures.append((module.name, f"duplicate:{member_name}"))
                continue
            try:
                instance = _build_cog(bot, member)
                await bot.add_cog(instance)
            except Exception:
                logger.exception("Не удалось загрузить ког %s.%s", module.name, member_name)
                failures.append((module.name, "add_cog"))
                continue
            used_names.add(member.__name__)
            loaded.append(module.name)
            logger.info("Ког загружен: %s.%s", module.name, member_name)

    if failures:
        logger.error("Загружено когов: %d, с ошибками: %d", len(loaded), len(failures))
    else:
        logger.info("Загружено когов: %d", len(loaded))
    return loaded


async def register_persistent_views(bot: MegaBot) -> None:
    """Регистрирует кнопки тикетов, опросов и розыгрышей, которые переживают рестарт бота."""
    import json

    from app.core.views import GiveawayView, PollView, TicketCloseView, TicketOpenView

    services = bot.services
    assert services is not None
    bot.add_view(TicketOpenView(services.tickets), message_id=None)
    bot.add_view(TicketCloseView(services.tickets), message_id=None)

    giveaway_count = poll_count = 0
    for giveaway in await services.giveaways.active_with_message():
        try:
            bot.add_view(GiveawayView(), message_id=giveaway["message_id"])
            giveaway_count += 1
        except Exception:
            logger.exception("Не удалось зарегистрировать view розыгрыша #%s", giveaway["id"])
    for poll in await services.polls.active_with_message():
        try:
            option_count = len(json.loads(poll["options"]))
            bot.add_view(PollView(poll["id"], option_count), message_id=poll["message_id"])
            poll_count += 1
        except Exception:
            logger.exception("Не удалось зарегистрировать view опроса #%s", poll["id"])

    logger.info(
        "Persistent views: тикеты 2, розыгрыши %d, опросы %d, всего %d",
        giveaway_count,
        poll_count,
        2 + giveaway_count + poll_count,
    )
