"""Composition root: единственное место, где собирается весь граф зависимостей.

Вместо дерева контейнеров (app/core/container.py + app/core/packages.py) каждая
зависимость создаётся явно в порядке сверху вниз. Порядок здесь и есть
«граф»: репозитории → сервисы → сервисы, зависящие от бота → бот.services.

Замена реализации (фейк в тестах, другая база, другой бот) — это параметры
``assemble()``, а не правка потребителей.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.config import Config
from app.services import Services

if TYPE_CHECKING:
    from app.db.database import Database
    from rewrite.bot import Bot
    from rewrite.root import Root

logger = logging.getLogger("bot")


def assemble(
    *,
    config: Config,
    db: Database,
    bot: Bot | None = None,
    #: Точечные подмены реализаций (для тестов и переключения инфраструктуры).
    **overrides: Any,
) -> Root:
    """Строит и возвращает Root со всеми сервисами и ботом."""
    from app.db.birthdays_repository import BirthdaysRepository
    from app.db.donations_repository import DonationsRepository
    from app.db.giveaways_repository import GiveawaysRepository
    from app.db.kv_repository import KvRepository
    from app.db.moderation_cases_repository import ModerationCasesRepository
    from app.db.polls_repository import PollsRepository
    from app.db.reaction_roles_repository import ReactionRolesRepository
    from app.db.reminders_repository import RemindersRepository
    from app.db.scheduled_repository import ScheduledRepository
    from app.db.season_repository import SeasonRepository
    from app.db.settings_repository import SettingsRepository
    from app.db.temp_voices_repository import TempVoicesRepository
    from app.db.tickets_repository import TicketsRepository
    from app.db.warns_repository import WarnsRepository
    from app.services.birthday_service import BirthdayService
    from app.services.donation_service import DonationService
    from app.services.giveaway_service import GiveawayService
    from app.services.kick_service import KickService
    from app.services.logging_service import LoggingService
    from app.services.moderation_case_service import ModerationCaseService
    from app.services.moderation_service import ModerationService
    from app.services.music_service import MusicService
    from app.services.poll_service import PollService
    from app.services.reaction_roles_service import ReactionRolesService
    from app.services.reminder_service import ReminderService
    from app.services.scheduler_service import ScheduledMessagesService
    from app.services.season_service import SeasonService
    from app.services.settings_service import SettingsService
    from app.services.temp_voice_service import TempVoiceService
    from app.services.ticket_service import TicketService
    from app.services.twitch_service import TwitchService
    from app.services.vk_video_service import VkVideoService
    from rewrite.bot import Bot

    # --- Репозитории (слой данных) ---
    settings_repo = override_or(overrides, "settings_repo", SettingsRepository, db)
    kv_repo = override_or(overrides, "kv_repo", KvRepository, db)

    # --- Сервисы, зависящие только от репозиториев ---
    settings = override_or(overrides, "settings", SettingsService, settings_repo)
    reminders = override_or(overrides, "reminders", ReminderService, RemindersRepository(db))
    polls = override_or(overrides, "polls", PollService, PollsRepository(db))
    giveaways = override_or(overrides, "giveaways", GiveawayService, GiveawaysRepository(db))
    reaction_roles = override_or(overrides, "reaction_roles", ReactionRolesService, ReactionRolesRepository(db))
    tempvoice = override_or(overrides, "tempvoice", TempVoiceService, TempVoicesRepository(db))
    birthdays = override_or(overrides, "birthdays", BirthdayService, BirthdaysRepository(db))
    seasons = override_or(overrides, "seasons", SeasonService, SeasonRepository(db))
    scheduled = override_or(overrides, "scheduled", ScheduledMessagesService, ScheduledRepository(db))

    # --- Бот (нужен сервисам, которые пишут в Discord) ---
    if bot is None:
        bot = Bot(config)

    # --- Сервисы, зависящие от бота и/или настроек ---
    logging_svc = override_or(overrides, "logging", LoggingService, settings, bot)
    moderation = override_or(overrides, "moderation", ModerationService, WarnsRepository(db), settings)
    cases = override_or(overrides, "cases", ModerationCaseService, ModerationCasesRepository(db))
    tickets = override_or(
        overrides, "tickets", TicketService, settings, TicketsRepository(db), logging_svc
    )
    music = override_or(overrides, "music", MusicService, bot)
    donations = override_or(
        overrides, "donations", DonationService, DonationsRepository(db), kv_repo, config
    )
    twitch = override_or(overrides, "twitch", TwitchService, kv_repo, config)
    kick = override_or(overrides, "kick", KickService, kv_repo, config)
    vk_video = override_or(overrides, "vk_video", VkVideoService, kv_repo, config)

    # --- Собираем типизированную связку сервисов ---
    services = Services(
        settings=settings,
        moderation=moderation,
        cases=cases,
        music=music,
        tickets=tickets,
        logging=logging_svc,
        reminders=reminders,
        polls=polls,
        giveaways=giveaways,
        reaction_roles=reaction_roles,
        donations=donations,
        twitch=twitch,
        kick=kick,
        vk_video=vk_video,
        tempvoice=tempvoice,
        birthdays=birthdays,
        seasons=seasons,
        scheduled=scheduled,
    )

    # --- Прошиваем корень в бота (то же, что делал контейнер через supplied) ---
    bot.config = config
    bot.services = services

    from rewrite.root import Root

    root = Root(config=config, db=db, bot=bot, services=services)
    bot.root = root
    logger.info(
        "Composition root собран: сервисов %d, bot=%s", len(Services.__dataclass_fields__), bot.__class__.__name__
    )
    return root


def override_or(overrides: dict[str, Any], name: str, cls: type, *args: Any) -> Any:
    """Возвращает явную подмену из ``overrides`` либо создаёт ``cls(*args)``."""
    if name in overrides:
        return overrides[name]
    return cls(*args)
