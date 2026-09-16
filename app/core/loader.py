"""Автозагрузчик когов и регистрация persistent-представлений."""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING

from discord.ext import commands

from app.cogs import COGS_PACKAGE

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot")


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
                container = bot.packages.container_for(module.name) if bot.packages is not None else None
                if container is not None:
                    instance = container.build(member)
                else:
                    instance = member(bot)
            except Exception:
                logger.debug("DI-сборка кога не удалась, резерв: %s.%s", module.name, member_name, exc_info=True)
                instance = member(bot)
            try:
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
