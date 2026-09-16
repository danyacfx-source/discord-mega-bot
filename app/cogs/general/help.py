"""Команда справки по всем слэш-командам."""
from __future__ import annotations

import discord
from discord import app_commands

from app.core import embeds
from app.core.base import MegaCog
from app.utils.format import truncate


class HelpCog(MegaCog, name="Справка"):

    def _flatten(self) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for command in self.bot.tree.get_commands():
            if hasattr(command, "commands"):
                for sub in command.commands:
                    result.append((f"/{command.name} {sub.name}", sub.description))
            else:
                result.append((f"/{command.name}", command.description))
        return sorted(result)

    @app_commands.command(name="help", description="Справка по командам бота")
    @app_commands.guild_only()
    async def help_command(self, interaction: discord.Interaction) -> None:
        entries = self._flatten()
        embed = embeds.info("Справка по командам", f"Доступно команд: **{len(entries)}**")
        if self.bot.user:
            embed.set_author(name=self.bot.user.display_name)
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        for name, description in entries:
            embed.add_field(name=name, value=truncate(description or "—"), inline=False)
        await interaction.response.send_message(embed=embed)
