"""Реестр сервисов всех фич.

Сервисы не знают, кто их создал: граф собирается в composition root
(``app/core/composition.py``), где репозитории подставляются явно.
Как добавить сервис:
  1. создать ``app/features/<фича>/service.py`` (класс наследует ``BaseService``);
  2. добавить поле в :class:`Services` и строку в ``assemble()``.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.features.birthdays.service import BirthdayService
from app.features.donations.service import DonationService
from app.features.event_logs.service import LoggingService
from app.features.giveaways.service import GiveawayService
from app.features.guard.service import CommandGuardService
from app.features.ideas.service import IdeaBoardService
from app.features.moderation.cases_service import ModerationCaseService
from app.features.moderation.service import ModerationService
from app.features.music.service import MusicService
from app.features.polls.service import PollService
from app.features.reaction_roles.service import ReactionRolesService
from app.features.reminders.service import ReminderService
from app.features.scheduler.service import ScheduledMessagesService
from app.features.seasons.service import SeasonService
from app.features.streams.chat_coins_service import ChatCoinsService
from app.features.streams.chat_commands_service import ChatCommandsService
from app.features.streams.chat_feed import ChatFeed
from app.features.streams.kick_service import KickService
from app.features.streams.live_vote_service import LiveVoteService
from app.features.streams.twitch_service import TwitchService
from app.features.streams.vk_video_service import VkVideoService
from app.features.tempvoice.service import TempVoiceService
from app.features.tickets.service import TicketService
from app.shared.event_bus import EventBus
from app.shared.kv_service import KvService
from app.shared.settings_service import SettingsService


@dataclass(slots=True)
class Services:
    settings: SettingsService
    kv: KvService
    moderation: ModerationService
    cases: ModerationCaseService
    music: MusicService
    tickets: TicketService
    logging: LoggingService
    reminders: ReminderService
    polls: PollService
    giveaways: GiveawayService
    idea_board: IdeaBoardService
    reaction_roles: ReactionRolesService
    donations: DonationService
    twitch: TwitchService
    kick: KickService
    vk_video: VkVideoService
    tempvoice: TempVoiceService
    birthdays: BirthdayService
    seasons: SeasonService
    scheduled: ScheduledMessagesService
    chat_coins: ChatCoinsService
    chat_commands: ChatCommandsService
    chat_feed: ChatFeed
    live_vote: LiveVoteService
    guard: CommandGuardService
    events: EventBus
