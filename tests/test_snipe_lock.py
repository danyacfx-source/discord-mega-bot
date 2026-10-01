"""Регрессионные тесты: утечка snipe-кэша и сохранение перезаписей при lock/unlock."""

from unittest.mock import AsyncMock, MagicMock

import discord

from app.cogs.snipe.snipe import SnipeCog
from app.cogs.utility.utility import UtilityCog


def _message(guild_id: int, channel_id: int) -> MagicMock:
    message = MagicMock(spec=discord.Message)
    message.author.bot = False
    message.guild = MagicMock(spec=discord.Guild)
    message.guild.id = guild_id
    message.channel = MagicMock()
    message.channel.id = channel_id
    message.content = "text"
    return message


async def test_snipe_records_deletes_per_channel() -> None:
    cog = SnipeCog(MagicMock())
    message = _message(1, 2)

    await cog.on_message_delete(message)

    assert cog._deleted[(1, 2)][-1] is message
    assert (1, 2) in cog._last_touch


async def test_snipe_channel_delete_drops_history() -> None:
    cog = SnipeCog(MagicMock())
    message = _message(1, 2)
    await cog.on_message_delete(message)

    channel = MagicMock(spec=discord.TextChannel)
    channel.guild = MagicMock(spec=discord.Guild)
    channel.guild.id = 1
    channel.id = 2
    await cog.on_guild_channel_delete(channel)

    assert (1, 2) not in cog._deleted
    assert (1, 2) not in cog._last_touch


async def test_snipe_guild_remove_drops_history() -> None:
    cog = SnipeCog(MagicMock())
    await cog.on_message_delete(_message(1, 2))
    await cog.on_message_delete(_message(1, 3))
    await cog.on_message_delete(_message(9, 4))

    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    await cog.on_guild_remove(guild)

    assert (1, 2) not in cog._deleted
    assert (1, 3) not in cog._deleted
    assert (9, 4) in cog._deleted


async def test_snipe_tracked_channels_capped() -> None:
    from app.cogs.snipe.snipe import _MAX_TRACKED_CHANNELS

    cog = SnipeCog(MagicMock())
    message = _message(1, 0)
    for channel_id in range(_MAX_TRACKED_CHANNELS + 100):
        cog._record(cog._deleted, (1, channel_id), message)

    assert len(cog._last_touch) <= _MAX_TRACKED_CHANNELS
    assert len(cog._deleted) <= _MAX_TRACKED_CHANNELS


def _lock_setup() -> tuple[UtilityCog, MagicMock, MagicMock]:
    cog = UtilityCog(MagicMock())
    interaction = MagicMock(spec=discord.Interaction)
    guild = MagicMock(spec=discord.Guild)
    guild.default_role = MagicMock(spec=discord.Role)
    interaction.guild = guild
    interaction.user = MagicMock(spec=discord.Member)
    interaction.response.send_message = AsyncMock()
    target = MagicMock(spec=discord.TextChannel)
    target.set_permissions = AsyncMock()
    target.mention = "<#1>"
    return cog, interaction, target


async def test_unlock_preserves_other_overwrites() -> None:
    cog, interaction, target = _lock_setup()
    overwrite = discord.PermissionOverwrite()
    overwrite.read_messages = False
    target.overwrites_for.return_value = overwrite

    assert await cog._set_lock(interaction, target, locked=False) is True

    passed = target.set_permissions.call_args.kwargs["overwrite"]
    assert passed.send_messages is None
    assert passed.read_messages is False


async def test_lock_preserves_other_overwrites() -> None:
    cog, interaction, target = _lock_setup()
    overwrite = discord.PermissionOverwrite()
    overwrite.attach_files = False
    target.overwrites_for.return_value = overwrite

    assert await cog._set_lock(interaction, target, locked=True) is True

    passed = target.set_permissions.call_args.kwargs["overwrite"]
    assert passed.send_messages is False
    assert passed.attach_files is False
