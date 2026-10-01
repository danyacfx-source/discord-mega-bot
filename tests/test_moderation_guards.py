"""Регрессионные тесты: иерархия взводящего, обработка ошибок действий, лимит тайм-аута."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord

from app.cogs.moderation.moderation import ModerationCog
from app.utils.time import parse_duration


def _member(user_id: int, top_position: int) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.top_role.position = top_position
    member.bot = False
    return member


def _guild(*, owner_id: int = 999, me: MagicMock | None = None) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.owner_id = owner_id
    guild.me = me if me is not None else _member(500, 10)
    return guild


def _interaction(invoker: MagicMock, guild: MagicMock) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = invoker
    interaction.guild = guild
    interaction.guild_id = guild.id
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _cog(*, can_moderate: bool = True) -> ModerationCog:
    bot = MagicMock()
    moderation = MagicMock()
    moderation.can_moderate.return_value = can_moderate
    moderation.parse_duration.side_effect = parse_duration
    logging_service = MagicMock()
    logging_service.log_mod_action = AsyncMock()
    cases = MagicMock()
    cases.create = AsyncMock(return_value=None)
    return ModerationCog(bot, moderation, logging_service, cases)


async def test_guard_blocks_invoker_hierarchy() -> None:
    cog = _cog()
    invoker = _member(1, 3)
    target = _member(2, 5)
    interaction = _interaction(invoker, _guild())

    assert await cog._guard_target(interaction, target) is False
    interaction.response.send_message.assert_awaited_once()


async def test_guard_blocks_self_action() -> None:
    cog = _cog()
    invoker = _member(1, 3)
    interaction = _interaction(invoker, _guild())

    assert await cog._guard_target(interaction, invoker) is False
    interaction.response.send_message.assert_awaited_once()


async def test_guard_allows_guild_owner_invoker() -> None:
    cog = _cog()
    invoker = _member(999, 1)
    target = _member(2, 50)
    interaction = _interaction(invoker, _guild(owner_id=999))

    assert await cog._guard_target(interaction, target) is True
    interaction.response.send_message.assert_not_awaited()


async def test_guard_blocks_bot_hierarchy() -> None:
    cog = _cog(can_moderate=False)
    invoker = _member(1, 10)
    target = _member(2, 3)
    interaction = _interaction(invoker, _guild())

    assert await cog._guard_target(interaction, target) is False
    interaction.response.send_message.assert_awaited_once()


async def test_perform_handles_forbidden() -> None:
    cog = _cog()
    interaction = _interaction(_member(1, 10), _guild())
    response = MagicMock(status=403)
    failing = AsyncMock(side_effect=discord.Forbidden(response, "нет прав"))

    assert await cog._perform(interaction, failing(), "кик") is False
    interaction.response.send_message.assert_awaited_once()


async def test_timeout_rejects_over_28_days() -> None:
    cog = _cog()
    invoker = _member(1, 10)
    target = _member(2, 3)
    interaction = _interaction(invoker, _guild())
    target.timeout = AsyncMock()

    await ModerationCog.timeout.callback(cog, interaction, target, "29d")

    target.timeout.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once()


async def test_timeout_allows_exactly_28_days() -> None:
    cog = _cog()
    invoker = _member(1, 10)
    target = _member(2, 3)
    interaction = _interaction(invoker, _guild())
    target.timeout = AsyncMock()

    with patch("app.cogs.moderation.moderation.moderation_reason", return_value="reason"):
        await ModerationCog.timeout.callback(cog, interaction, target, "28d")

    target.timeout.assert_awaited_once()
    interaction.response.send_message.assert_awaited_once()
