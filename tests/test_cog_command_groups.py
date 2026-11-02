"""Группы слеш-команд должны быть атрибутами кога: иначе discord.py их не регистрирует."""
from __future__ import annotations

import pytest

from app.cogs.administration.guard import GuardCog
from app.cogs.administration.scan_bans import ScanBansCog
from app.cogs.administration.setup import SetupCog
from app.cogs.administration.tickets import TicketCog


@pytest.mark.parametrize(
    ("cog", "group_name"),
    [
        (GuardCog, "guard"),
        (SetupCog, "setup"),
        (TicketCog, "ticket"),
        (ScanBansCog, "scanbans"),
    ],
)
def test_cog_collects_its_command_group(cog, group_name):
    """Модульная группа без атрибута кога не попадает в __cog_app_commands__ и не синхронизируется."""
    names = [group.name for group in cog.__cog_app_commands__]
    assert group_name in names
