"""Настройка каналов: приветствия, прощания, логи, категория тикетов."""
from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from app.core import embeds
from app.core.base import MegaCog
from app.services.settings_service import SettingsService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

setup_group = app_commands.Group(name="setup", description="Настройка сервера")


class SetupCog(MegaCog, name="Setup"):
    def __init__(self, bot: MegaBot, settings: SettingsService) -> None:
        super().__init__(bot)
        self.settings = settings

    @setup_group.command(name="welcome-channel", description="Канал для приветствий новых участников")
    @app_commands.guild_only()
    async def welcome_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await self.settings.update(interaction.guild.id, welcome_channel_id=channel.id)
        await interaction.response.send_message(embed=embeds.success("Настройка", f"Приветствия → {channel.mention}"))

    @setup_group.command(name="farewell-channel", description="Канал для прощаний с участниками")
    @app_commands.guild_only()
    async def farewell_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await self.settings.update(interaction.guild.id, farewell_channel_id=channel.id)
        await interaction.response.send_message(embed=embeds.success("Настройка", f"Прощания → {channel.mention}"))

    @setup_group.command(name="log-channel", description="Канал для логов событий и модерации")
    @app_commands.guild_only()
    async def log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await self.settings.update(interaction.guild.id, log_channel_id=channel.id)
        await interaction.response.send_message(embed=embeds.success("Настройка", f"Логи → {channel.mention}"))

    @setup_group.command(name="ticket-category", description="Категория для создания тикетов")
    @app_commands.guild_only()
    async def ticket_category(self, interaction: discord.Interaction, category: discord.CategoryChannel) -> None:
        await self.settings.update(interaction.guild.id, ticket_category_id=category.id)
        await interaction.response.send_message(embed=embeds.success("Настройка", f"Тикеты → {category.mention}"))

    @setup_group.command(name="unset", description="Сбросить настройку канала")
    @app_commands.describe(option="Какую настройку сбросить")
    @app_commands.guild_only()
    async def unset(self, interaction: discord.Interaction, option: str) -> None:
        mapping = {
            "welcome": "welcome_channel_id",
            "farewell": "farewell_channel_id",
            "log": "log_channel_id",
            "ticket": "ticket_category_id",
        }
        column = mapping.get(option.strip().lower())
        if column is None:
            await interaction.response.send_message(
                embed=embeds.error("Ошибка", "Варианты: `welcome`, `farewell`, `log`, `ticket`."),
                ephemeral=True,
            )
            return
        await self.settings.update(interaction.guild.id, **{column: None})
        await interaction.response.send_message(embed=embeds.success("Сброшено", f"`{column}` → пусто."))

    @setup_group.command(name="show", description="Текущие настройки сервера")
    @app_commands.guild_only()
    async def show(self, interaction: discord.Interaction) -> None:
        settings = await self.settings.get(interaction.guild.id)

        def mention(value, kind: discord.ChannelType | None = None):
            return f"<#{value}>" if value else "—"

        embed = embeds.info("Настройки сервера")
        embed.add_field(name="Канал приветствий", value=mention(settings["welcome_channel_id"]), inline=True)
        embed.add_field(name="Канал прощаний", value=mention(settings["farewell_channel_id"]), inline=True)
        embed.add_field(name="Канал логов", value=mention(settings["log_channel_id"]), inline=True)
        embed.add_field(name="Категория тикетов", value=mention(settings["ticket_category_id"]), inline=True)
        embed.add_field(name="Авто-модерация", value="включена ✅" if settings["automod_enabled"] else "выключена ❌", inline=True)
        await interaction.response.send_message(embed=embed)
