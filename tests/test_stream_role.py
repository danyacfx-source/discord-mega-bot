"""Роль «В эфире»: выдача/снятие на старте и финише стрима."""
from __future__ import annotations

from types import SimpleNamespace

import discord
import pytest

from app.cogs.streams.stream_role import update_stream_role


class FakeRole:
    def __init__(self, role_id: int) -> None:
        self.id = role_id


class FakeMember:
    def __init__(self, roles: list[FakeRole]) -> None:
        self.roles = roles
        self.added: list[FakeRole] = []
        self.removed: list[FakeRole] = []

    async def add_roles(self, role: FakeRole, reason: str = "") -> None:
        self.added.append(role)
        self.roles.append(role)

    async def remove_roles(self, role: FakeRole, reason: str = "") -> None:
        self.removed.append(role)
        self.roles.remove(role)


class FakeGuild:
    def __init__(self, role: FakeRole | None, member: FakeMember | None) -> None:
        self._role = role
        self._member = member

    def get_role(self, role_id: int) -> FakeRole | None:
        return self._role if self._role is not None and self._role.id == role_id else None

    def get_member(self, user_id: int) -> FakeMember | None:
        return self._member


def _bot(role_id=10, user_ids=(42,), *, role=True, member_roles=()) -> SimpleNamespace:
    guild = FakeGuild(FakeRole(10) if role else None, FakeMember(list(member_roles)))
    config = SimpleNamespace(stream_role_id=role_id, stream_role_user_ids=user_ids)
    return SimpleNamespace(config=config, guilds=[guild])


@pytest.mark.asyncio
async def test_role_added_on_live_and_removed_on_offline():
    role = FakeRole(10)
    bot = _bot(member_roles=())
    bot.guilds[0] = FakeGuild(role, FakeMember([]))
    member = bot.guilds[0]._member

    await update_stream_role(bot, enable=True)
    assert member.added == [role]

    await update_stream_role(bot, enable=True)
    assert len(member.added) == 1, "повторный вызов не должен слать API-запрос"

    await update_stream_role(bot, enable=False)
    assert member.removed == [role]


@pytest.mark.asyncio
async def test_role_removed_when_already_held():
    role = FakeRole(10)
    bot = _bot()
    bot.guilds[0] = FakeGuild(role, FakeMember([role]))
    member = bot.guilds[0]._member

    await update_stream_role(bot, enable=False)
    assert member.removed == [role]


@pytest.mark.asyncio
async def test_noop_without_config_or_member():
    await update_stream_role(_bot(role_id=None), enable=True)
    await update_stream_role(_bot(user_ids=()), enable=True)

    bot = _bot(role=False)
    await update_stream_role(bot, enable=True)  # роли нет в гильдии — без исключений

    guild = FakeGuild(FakeRole(10), None)
    bot2 = SimpleNamespace(config=SimpleNamespace(stream_role_id=10, stream_role_user_ids=(42,)), guilds=[guild])
    await update_stream_role(bot2, enable=True)  # участник не найден в кэше — без исключений


@pytest.mark.asyncio
async def test_http_error_is_logged_not_raised(monkeypatch):
    role = FakeRole(10)
    member = FakeMember([])

    async def boom(role, reason=""):
        raise discord.HTTPException(SimpleNamespace(status=403, reason="Forbidden"), "Forbidden")

    member.add_roles = boom  # type: ignore[method-assign]
    bot = _bot()
    bot.guilds[0] = FakeGuild(role, member)

    await update_stream_role(bot, enable=True)  # не должно поднять исключение
