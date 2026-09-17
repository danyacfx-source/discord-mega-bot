"""Слой данных: подключение к БД и репозитории."""

from app.data.birthdays_repository import BirthdaysRepository
from app.data.donations_repository import DonationsRepository
from app.data.giveaways_repository import GiveawaysRepository
from app.data.kv_repository import KvRepository
from app.data.polls_repository import PollsRepository
from app.data.reaction_roles_repository import ReactionRolesRepository
from app.data.reminders_repository import RemindersRepository
from app.data.season_repository import SeasonRepository
from app.data.settings_repository import SettingsRepository
from app.data.temp_voices_repository import TempVoicesRepository
from app.data.tickets_repository import TicketsRepository
from app.data.warns_repository import WarnsRepository

REPOSITORY_CLASSES: tuple[type, ...] = (
    SettingsRepository,
    WarnsRepository,
    TicketsRepository,
    RemindersRepository,
    PollsRepository,
    GiveawaysRepository,
    ReactionRolesRepository,
    KvRepository,
    DonationsRepository,
    TempVoicesRepository,
    BirthdaysRepository,
    SeasonRepository,
)