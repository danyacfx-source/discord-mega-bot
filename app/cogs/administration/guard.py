"""Команда /guard: kill-switch, блокировки команд и состояние rate-limit."""
from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from app.core import embeds
from app.core.base import MegaCog
from app.core.checks import is_owner
from app.services.command_guard_service import CommandGuardService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

guard_group = app_commands.Group(name="guard", description="Глобальная защита: лимиты команд и kill-switch")

_MAX_LISTED = 15


async def _command_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Подсказывает имена зарегистрированных команд для /guard block и /guard unblock."""
    tree = getattr(interaction.client, "tree", None)
    commands = tree.get_commands() if tree is not None else []
    names = _flatten_command_names(commands)
    needle = current.strip().lower()
    return [
        app_commands.Choice(name=name, value=name)
        for name in names
        if not needle or needle in name
    ][:25]


def _flatten_command_names(commands: Iterable[object]) -> list[str]:
    names: list[str] = []
    for command in commands:
        name = getattr(command, "name", None)
        if not name:
            continue
        children = getattr(command, "commands", None)
        if children:
            for child in _flatten_command_names(children):
                names.append(f"{name} {child}")
        else:
            names.append(str(name))
    return sorted(set(names))


class GuardCog(MegaCog, name="Administration"):
    def __init__(self, bot: MegaBot, guard: CommandGuardService) -> None:
        super().__init__(bot)
        self.guard = guard

    @guard_group.command(name="status", description="Состояние guard-а: лимиты, блокировки, счётчики")
    @is_owner()
    async def status(self, interaction: discord.Interaction) -> None:
        state = self.guard.snapshot()
        limits = state["limits"]
        mode = "🟡 режим обслуживания" if state["paused"] else "🟢 активен"
        if not state["enabled"]:
            mode = "⚪ выключен конфигом"
        embed = embeds.brand("Guard", f"Состояние: {mode}")
        embed.add_field(
            name="Лимиты",
            value=(
                f"пользователь: `{limits['user_max']}` / `{limits['user_window']:.0f}с`\n"
                f"сервер: `{limits['guild_max']}` / `{limits['guild_window']:.0f}с`\n"
                f"обход админов: `{'да' if limits['bypass_admin'] else 'нет'}`"
            ),
            inline=False,
        )
        embed.add_field(
            name="Счётчики",
            value=(
                f"проверок: `{state['checks']}`\n"
                f"отклонено: `{state['blocked_total']}`\n"
                f"в окне: `{state['tracked_users']}` юзеров / `{state['tracked_guilds']}` серверов"
            ),
            inline=False,
        )
        embed.add_field(
            name="Отключённые команды",
            value=", ".join(f"`/{name}`" for name in state["blocked_commands"]) or "нет",
            inline=False,
        )
        embed.add_field(
            name="Серверы в муте",
            value=", ".join(f"`{guild_id}`" for guild_id in state["muted_guilds"]) or "нет",
            inline=False,
        )
        if state["last_reason"]:
            embed.set_footer(text=state["last_reason"][:200])
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @guard_group.command(name="pause", description="Kill-switch: остановить все команды, кроме владельца")
    @app_commands.describe(reason="Причина, которую увидят пользователи")
    @is_owner()
    async def pause(self, interaction: discord.Interaction, reason: str = "") -> None:
        await self.guard.set_paused(True)
        text = "Команды приостановлены."
        if reason.strip():
            text += f" Причина: {reason.strip()[:200]}"
        self.publish_event("guard", {"msg": f"Guard: {text}"})
        await interaction.response.send_message(embed=embeds.warning("Режим обслуживания", text), ephemeral=True)

    @guard_group.command(name="resume", description="Снять режим обслуживания")
    @is_owner()
    async def resume(self, interaction: discord.Interaction) -> None:
        await self.guard.set_paused(False)
        self.publish_event("guard", {"msg": "Guard: режим обслуживания снят"})
        await interaction.response.send_message(embed=embeds.success("Готово", "Команды снова доступны."), ephemeral=True)

    @guard_group.command(name="block", description="Отключить конкретную команду")
    @app_commands.describe(command="Имя команды, например purge или music play")
    @app_commands.autocomplete(command=_command_autocomplete)
    @is_owner()
    async def block(self, interaction: discord.Interaction, command: str) -> None:
        if not await self.guard.block_command(command):
            await interaction.response.send_message(
                embed=embeds.info("Без изменений", f"Команда `/{command.strip().lower()}` уже отключена или пуста."),
                ephemeral=True,
            )
            return
        self.publish_event("guard", {"msg": f"Guard: команда /{command.strip().lower()} отключена"})
        await interaction.response.send_message(
            embed=embeds.warning("Отключено", f"Команда `/{command.strip().lower()}` больше не выполняется."),
            ephemeral=True,
        )

    @guard_group.command(name="unblock", description="Включить ранее отключённую команду")
    @app_commands.describe(command="Имя команды")
    @app_commands.autocomplete(command=_command_autocomplete)
    @is_owner()
    async def unblock(self, interaction: discord.Interaction, command: str) -> None:
        if not await self.guard.unblock_command(command):
            listed = ", ".join(f"`/{name}`" for name in self.guard.blocked_commands) or "нет"
            await interaction.response.send_message(
                embed=embeds.info("Без изменений", f"Такая команда не отключена. Отключены: {listed}"),
                ephemeral=True,
            )
            return
        self.publish_event("guard", {"msg": f"Guard: команда /{command.strip().lower()} включена"})
        await interaction.response.send_message(
            embed=embeds.success("Включено", f"Команда `/{command.strip().lower()}` снова работает."),
            ephemeral=True,
        )

    @guard_group.command(name="mute", description="Отключить команды на этом сервере")
    @app_commands.guild_only()
    @is_owner()
    async def mute(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        if not await self.guard.mute_guild(interaction.guild_id):
            await interaction.response.send_message(
                embed=embeds.info("Без изменений", "Команды на этом сервере уже отключены."),
                ephemeral=True,
            )
            return
        self.publish_event("guard", {"msg": f"Guard: сервер {interaction.guild_id} в муте"})
        await interaction.response.send_message(
            embed=embeds.warning("Сервер в муте", "Команды бота на этом сервере отключены."),
            ephemeral=True,
        )

    @guard_group.command(name="unmute", description="Включить команды на этом сервере")
    @app_commands.guild_only()
    @is_owner()
    async def unmute(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        if not await self.guard.unmute_guild(interaction.guild_id):
            await interaction.response.send_message(
                embed=embeds.info("Без изменений", "Мут для этого сервера не установлен."),
                ephemeral=True,
            )
            return
        self.publish_event("guard", {"msg": f"Guard: мут сервера {interaction.guild_id} снят"})
        await interaction.response.send_message(
            embed=embeds.success("Мут снят", "Команды на этом сервере снова работают."),
            ephemeral=True,
        )

    @guard_group.command(name="reset", description="Сбросить окна rate-limit (разблокировать всех участников)")
    @is_owner()
    async def reset(self, interaction: discord.Interaction) -> None:
        self.guard.reset()
        self.publish_event("guard", {"msg": "Guard: окна rate-limit сброшены"})
        await interaction.response.send_message(
            embed=embeds.success("Сброшено", "Окна лимитов очищены, все участники снова могут звать команды."),
            ephemeral=True,
        )
