"""Бизнес-логика: сервисы поверх репозиториев + регистрация в собственном DI-контейнере.

Каждый пакет приложения — отдельный DI-контейнер; сервисы регистрируются в
контейнере ``app.services`` (см. ``app/services/di.py``) с родителем ``app.data``.
Композиционный корень собирает дерево пакетов: ``app/core/packages.py``.

Как добавить сервис:
  1. создать ``app/services/xxx_service.py`` (класс наследует ``BaseService``);
  2. добавить класс сервиса в ``SERVICE_CLASSES``;
  3. при необходимости — короткий ключ для инъекции в ``SERVICE_ALIASES``;
  4. добавить поле в :class:`Services` и строку в :func:`build_services`.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.container import DependencyContainer
from app.services.birthday_service import BirthdayService
from app.services.donation_service import DonationService
from app.services.giveaway_service import GiveawayService
from app.services.kick_service import KickService
from app.services.logging_service import LoggingService
from app.services.moderation_service import ModerationService
from app.services.music_service import MusicService
from app.services.poll_service import PollService
from app.services.reaction_roles_service import ReactionRolesService
from app.services.reminder_service import ReminderService
from app.services.season_service import SeasonService
from app.services.settings_service import SettingsService
from app.services.temp_voice_service import TempVoiceService
from app.services.ticket_service import TicketService
from app.services.twitch_service import TwitchService
from app.services.youtube_service import YouTubeService

SERVICE_CLASSES: tuple[type, ...] = (
    SettingsService,
    ModerationService,
    MusicService,
    TicketService,
    LoggingService,
    ReminderService,
    PollService,
    GiveawayService,
    ReactionRolesService,
    DonationService,
    TwitchService,
    KickService,
    TempVoiceService,
    BirthdayService,
    SeasonService,
    YouTubeService,
)

SERVICE_ALIASES: dict[str, str] = {
    "settings": SettingsService.__name__,
    "moderation": ModerationService.__name__,
    "music": MusicService.__name__,
    "tickets": TicketService.__name__,
    "logging": LoggingService.__name__,
    "reminders": ReminderService.__name__,
    "polls": PollService.__name__,
    "giveaways": GiveawayService.__name__,
    "reaction_roles": ReactionRolesService.__name__,
    "donations": DonationService.__name__,
    "twitch": TwitchService.__name__,
    "kick": KickService.__name__,
    "tempvoice": TempVoiceService.__name__,
    "birthdays": BirthdayService.__name__,
    "seasons": SeasonService.__name__,
    "youtube": YouTubeService.__name__,
}


@dataclass(slots=True)
class Services:
    settings: SettingsService
    moderation: ModerationService
    music: MusicService
    tickets: TicketService
    logging: LoggingService
    reminders: ReminderService
    polls: PollService
    giveaways: GiveawayService
    reaction_roles: ReactionRolesService
    donations: DonationService
    twitch: TwitchService
    kick: KickService
    tempvoice: TempVoiceService
    birthdays: BirthdayService
    seasons: SeasonService
    youtube: YouTubeService


def build_services(container: DependencyContainer) -> Services:
    """Достаёт готовые сервисы из контейнера в типизированную обвязку."""
    return Services(
        settings=container.resolve("settings"),
        moderation=container.resolve("moderation"),
        music=container.resolve("music"),
        tickets=container.resolve("tickets"),
        logging=container.resolve("logging"),
        reminders=container.resolve("reminders"),
        polls=container.resolve("polls"),
        giveaways=container.resolve("giveaways"),
        reaction_roles=container.resolve("reaction_roles"),
        donations=container.resolve("donations"),
        twitch=container.resolve("twitch"),
        kick=container.resolve("kick"),
        tempvoice=container.resolve("tempvoice"),
        birthdays=container.resolve("birthdays"),
        seasons=container.resolve("seasons"),
        youtube=container.resolve("youtube"),
    )
