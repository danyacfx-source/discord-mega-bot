"""Устойчивые кнопки тикетов: открытие и закрытие."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from app.core import embeds
from app.core.views import reply_unexpected

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.features.tickets.service import TicketService

TICKET_OPEN_ID = "ticket:open"
TICKET_CLOSE_ID = "ticket:close"


class _TicketBaseView(discord.ui.View):
    ticket_service: TicketService

    def __init__(self, ticket_service: TicketService) -> None:
        super().__init__(timeout=None)
        self.ticket_service = ticket_service


class TicketOpenView(_TicketBaseView):
    """Устойчивая кнопка открытия тикета (работает после рестарта)."""

    def __init__(
        self,
        ticket_service: TicketService,
        *,
        label: str = "Открыть тикет",
        emoji: str | None = "🎫",
    ) -> None:
        super().__init__(ticket_service)
        self.open_ticket.label = label
        self.open_ticket.emoji = emoji or None

    @discord.ui.button(label="Открыть тикет", style=discord.ButtonStyle.success, custom_id=TICKET_OPEN_ID, emoji="🎫")
    async def open_ticket(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        try:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message(
                    embed=embeds.error("Не удалось открыть тикет", "Кнопка работает только на сервере."),
                    ephemeral=True,
                )
                return
            result = await self.ticket_service.create(interaction.guild, interaction.user)
            if result.error:
                embed = embeds.error("Не удалось открыть тикет", result.error)
            else:
                channel = result.channel
                if channel is None:
                    await interaction.response.send_message(
                        embed=embeds.error("Не удалось открыть тикет", "Канал тикета не был создан."),
                        ephemeral=True,
                    )
                    return
                embed = embeds.success("Тикет открыт", f"Перейдите в {channel.mention} и опишите вопрос одним сообщением.")
                embed.add_field(name="КАНАЛ ПОДДЕРЖКИ", value=channel.mention, inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            logger.exception("Сбой кнопки open_ticket")
            await reply_unexpected(interaction)


class TicketCloseView(_TicketBaseView):
    """Устойчивая кнопка закрытия тикета (работает после рестарта)."""

    def __init__(
        self,
        ticket_service: TicketService,
        *,
        label: str = "Закрыть тикет",
        emoji: str | None = "🔒",
    ) -> None:
        super().__init__(ticket_service)
        self.close_ticket.label = label
        self.close_ticket.emoji = emoji or None

    @discord.ui.button(label="Закрыть тикет", style=discord.ButtonStyle.danger, custom_id=TICKET_CLOSE_ID, emoji="🔒")
    async def close_ticket(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        try:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message(
                    embed=embeds.error("Не удалось закрыть тикет", "Кнопка работает только на сервере."),
                    ephemeral=True,
                )
                return
            channel = interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None
            result = await self.ticket_service.close(interaction.guild, channel, interaction.user)
            if result.error:
                embed = embeds.error("Не удалось закрыть тикет", result.error)
            else:
                embed = embeds.success("Тикет закрыт", result.transcript_channel_mention)
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            logger.exception("Сбой кнопки close_ticket")
            await reply_unexpected(interaction)
