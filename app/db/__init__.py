"""Слой данных: подключение к БД и репозитории."""

from app.db.birthdays_repository import BirthdaysRepository
from app.db.donations_repository import DonationsRepository
from app.db.giveaways_repository import GiveawaysRepository
from app.db.kv_repository import KvRepository
from app.db.polls_repository import PollsRepository
from app.db.reaction_roles_repository import ReactionRolesRepository
from app.db.reminders_repository import RemindersRepository
from app.db.season_repository import SeasonRepository
from app.db.settings_repository import SettingsRepository
from app.db.temp_voices_repository import TempVoicesRepository
from app.db.tickets_repository import TicketsRepository
from app.db.warns_repository import WarnsRepository

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
