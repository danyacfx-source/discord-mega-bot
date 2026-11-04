"""Общие интерактивные представления (views), нужные нескольким фичам."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import discord

from app.core import embeds

logger = logging.getLogger(__name__)


async def reply_unexpected(interaction: discord.Interaction) -> None:
    embed = embeds.error("Ошибка", "Неожиданная ошибка. Попробуйте позже.")
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.HTTPException:
        logger.debug("Не удалось отправить сообщение об ошибке кнопки", exc_info=True)


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
