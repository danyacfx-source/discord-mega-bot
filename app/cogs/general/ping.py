"""Команда ping."""
from __future__ import annotations

import discord
from discord import app_commands

from app.core import embeds
from app.core.base import MegaCog
from app.utils.time import format_duration


class PingCog(MegaCog, name="General"):
    @app_commands.command(name="ping", description="Проверка задержки бота")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency = round(self.bot.latency * 1000)
        embed = embeds.success("🏓 Pong!", f"Задержка: **{latency} мс**")
        embed.add_field(name="Версия", value=self.config.version, inline=True)
        embed.add_field(name="Аптайм", value=format_duration(int(self.bot.uptime.total_seconds())), inline=True)
        await interaction.response.send_message(embed=embed)
