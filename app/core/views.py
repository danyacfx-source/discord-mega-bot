"""Кастомные интерактивные представления (views)."""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import discord

from app.core import embeds

if TYPE_CHECKING:
    from app.services import Services
    from app.services.ticket_service import TicketService

TICKET_OPEN_ID = "ticket:open"
TICKET_CLOSE_ID = "ticket:close"
GIVEAWAY_ENTER_ID = "giveaway:enter"


class ConfirmView(discord.ui.View):
    """Кнопка-подтверждение для необратимых действий.

    Опционально привязывается к пользователю: чужие нажатия игнорируются.
    """

    def __init__(
        self,
        on_confirm: Callable[[discord.Interaction], Awaitable[Any]] | None = None,
        on_cancel: Callable[[discord.Interaction], Awaitable[Any]] | None = None,
        *,
        timeout: float = 60.0,
        user: discord.User | None = None,
        confirm_label: str = "Подтвердить",
        cancel_label: str = "Отмена",
        confirm_emoji: str | None = None,
        cancel_emoji: str | None = None,
    ) -> None:
        super().__init__(timeout=timeout)
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel
        self.user = user
        self.yes_btn.label = confirm_label
        self.no_btn.label = cancel_label
        if confirm_emoji:
            self.yes_btn.emoji = confirm_emoji
        if cancel_emoji:
            self.no_btn.emoji = cancel_emoji

    def _allowed(self, interaction: discord.Interaction) -> bool:
        return self.user is None or interaction.user.id == self.user.id

    def _disable_all_items(self) -> None:
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True

    async def _default_cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=embeds.info("Действие отменено"), view=None)

    @discord.ui.button(label="Подтвердить", style=discord.ButtonStyle.success)
    async def yes_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not self._allowed(interaction):
            await interaction.response.defer()
            return
        self._disable_all_items()
        await interaction.response.edit_message(view=self)
        callback = self.on_confirm or self._default_cancel
        await callback(interaction)

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def no_btn(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if not self._allowed(interaction):
            await interaction.response.defer()
            return
        self._disable_all_items()
        await interaction.response.edit_message(view=self)
        callback = self.on_cancel or self._default_cancel
        await callback(interaction)

    async def on_timeout(self) -> None:
        self._disable_all_items()


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


class GiveawayView(discord.ui.View):
    """Устойчивая кнопка участия в розыгрыше (работает после рестарта)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Участвовать", style=discord.ButtonStyle.success, custom_id=GIVEAWAY_ENTER_ID, emoji="🎉")
    async def enter(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        services: Services | None = getattr(interaction.client, "services", None)
        if services is None:
            await interaction.response.send_message(embed=embeds.error("Ошибка", "Сервисы недоступны."), ephemeral=True)
            return
        giveaway = await services.giveaways.get_by_message(interaction.message.id)
        if giveaway is None:
            await interaction.response.send_message(embed=embeds.error("Розыгрыш не найден"), ephemeral=True)
            return
        if interaction.guild_id is not None and giveaway["guild_id"] != interaction.guild_id:
            await interaction.response.send_message(embed=embeds.error("Не на этом сервере"), ephemeral=True)
            return
        if not giveaway["active"]:
            await interaction.response.send_message(embed=embeds.warning("Розыгрыш завершён"), ephemeral=True)
            return

        min_days = giveaway.get("min_days", 0)
        if min_days > 0 and interaction.guild is not None:
            member = interaction.guild.get_member(interaction.user.id)
            if member is None:
                try:
                    member = await interaction.guild.fetch_member(interaction.user.id)
                except discord.HTTPException:
                    member = None
            if member is None or member.joined_at is None:
                await interaction.response.send_message(
                    embed=embeds.error("Ошибка", "Не удалось определить дату вашего вступления на сервер."), ephemeral=True
                )
                return
            joined = member.joined_at
            if joined.tzinfo is None:
                joined = joined.replace(tzinfo=UTC)
            delta = datetime.now(UTC) - joined
            if delta.days < min_days:
                await interaction.response.send_message(
                    embed=embeds.error(
                        "Не выполнено условие",
                        f"Для участия нужно находиться на сервере минимум {min_days} дн. (вы на сервере {delta.days} дн.).",
                    ),
                    ephemeral=True,
                )
                return

        added = await services.giveaways.join(giveaway["id"], interaction.user.id)
        embed = (
            embeds.success("Заявка принята", "Вы участвуете в розыгрыше. Результат появится здесь после завершения.")
            if added
            else embeds.info("Вы уже участвуете", "Повторно нажимать кнопку не нужно.")
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        try:
            embed = await services.giveaways.embed(giveaway)
            await interaction.message.edit(embed=embed)
        except discord.HTTPException:
            pass


class PollView(discord.ui.View):
    """Кнопки голосования в опросе. Переживает рестарт (данные в БД, view перерегистрируется)."""

    def __init__(self, poll_id: int, option_count: int) -> None:
        super().__init__(timeout=None)
        for index in range(option_count):
            self.add_item(_PollOptionButton(poll_id, index))


class _PollOptionButton(discord.ui.Button):
    def __init__(self, poll_id: int, index: int) -> None:
        super().__init__(label=str(index + 1), custom_id=f"poll:{poll_id}:{index}", style=discord.ButtonStyle.primary)
        self.poll_id = poll_id
        self.index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        services: Services | None = getattr(interaction.client, "services", None)
        if services is None:
            await interaction.response.send_message(embed=embeds.error("Ошибка", "Сервисы недоступны."), ephemeral=True)
            return
        poll = await services.polls.get(self.poll_id)
        if poll is None or not poll["active"]:
            await interaction.response.send_message(embed=embeds.warning("Опрос завершён"), ephemeral=True)
            return
        if interaction.guild_id is not None and poll["guild_id"] != interaction.guild_id:
            await interaction.response.send_message(embed=embeds.error("Не на этом сервере"), ephemeral=True)
            return
        option_count = len(json.loads(poll["options"]))
        if self.index >= option_count:
            await interaction.response.send_message(embed=embeds.error("Вариант недоступен"), ephemeral=True)
            return
        status = await services.polls.vote(self.poll_id, interaction.user.id, self.index, option_count)
        embed = await services.polls.embed(self.poll_id)
        await interaction.response.edit_message(embed=embed)
        if status == 2:
            notice = embeds.success("Голос учтён")
        elif status == 1:
            notice = embeds.info("Голос изменён")
        else:
            notice = embeds.info("Вы уже голосовали за этот вариант")
        await interaction.followup.send(embed=notice, ephemeral=True)


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
