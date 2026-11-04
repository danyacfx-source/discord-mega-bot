"""Кнопки голосования в опросе."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import discord

from app.core import embeds

if TYPE_CHECKING:
    from app.core.services import Services


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
