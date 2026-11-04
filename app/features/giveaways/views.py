"""Устойчивая кнопка участия в розыгрыше."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord

from app.core import embeds
from app.core.views import reply_unexpected

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.core.services import Services

GIVEAWAY_ENTER_ID = "giveaway:enter"


class GiveawayView(discord.ui.View):
    """Устойчивая кнопка участия в розыгрыше (работает после рестарта)."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Участвовать", style=discord.ButtonStyle.success, custom_id=GIVEAWAY_ENTER_ID, emoji="🎉")
    async def enter(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        try:
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
        except Exception:
            logger.exception("Сбой кнопки enter")
            await reply_unexpected(interaction)
