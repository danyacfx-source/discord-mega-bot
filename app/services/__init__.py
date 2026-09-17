"""Бизнес-логика: сервисы поверх репозиториев.

Сервисы не знают, кто их создал: граф собирается в composition root
(``app/core/composition.py``), где репозитории подставляются явно.
Как добавить сервис:
  1. создать ``app/services/xxx_service.py`` (класс наследует ``BaseService``);
  2. добавить поле в :class:`Services` и строку в ``assemble()``.
"""
from __future__ import annotations

from dataclasses import dataclass

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
