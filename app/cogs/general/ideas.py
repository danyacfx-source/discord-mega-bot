"""Discord suggestion board commands and persistent voting."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands

from app.core.base import MegaCog
from app.services.idea_board_service import STATUS_LABELS, IdeaBoardService, IdeaError

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")
_NO_MENTIONS = discord.AllowedMentions.none()


def idea_embed(record: dict[str, Any]) -> discord.Embed:
    up, down = IdeaBoardService.scores(record)
    status = record["status"]
    colors = {
        "done": discord.Color.green(),
        "planned": discord.Color.orange(),
        "declined": discord.Color.red(),
    }
    embed = discord.Embed(
        title=f"📡 Идея #{record['id']}",
        description=discord.utils.escape_mentions(discord.utils.escape_markdown(record["text"])),
        color=colors.get(status, discord.Color.blurple()),
    )
    embed.add_field(name="Статус", value=STATUS_LABELS[status], inline=True)
    embed.add_field(name="Голоса", value=f"👍 {up} · 👎 {down} · итог {up - down:+d}", inline=True)
    embed.add_field(name="Автор", value=f"<@{record['author_id']}>", inline=False)
    embed.set_footer(text="RADIO SILENCE · Предлагайте идеи · Голосуйте кнопками")
    return embed


class IdeaVoteView(discord.ui.View):
    def __init__(self, service: IdeaBoardService) -> None:
        super().__init__(timeout=None)
        self.service = service

    async def _vote(self, interaction: discord.Interaction, direction: int) -> None:
        if interaction.guild is None or interaction.message is None or interaction.user.bot:
            await interaction.response.send_message("Доступно только на сервере.", ephemeral=True)
            return
        record = await self.service.by_message(interaction.guild.id, interaction.message.id)
        if record is None:
            await interaction.response.send_message("Идея не найдена.", ephemeral=True)
            return
        try:
            updated = await self.service.vote(interaction.guild.id, record["id"], interaction.user.id, direction)
        except IdeaError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.edit_message(embed=idea_embed(updated), view=self)

    @discord.ui.button(label="Поддержать", emoji="👍", style=discord.ButtonStyle.success, custom_id="dendich:idea:up")
    async def up(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await self._vote(interaction, 1)

    @discord.ui.button(label="Против", emoji="👎", style=discord.ButtonStyle.secondary, custom_id="dendich:idea:down")
    async def down(self, interaction: discord.Interaction, button: discord.ui.Button[Any]) -> None:
        await self._vote(interaction, -1)


class IdeasCog(MegaCog, name="CommunityIdeas"):
    def __init__(self, bot: MegaBot, idea_board: IdeaBoardService) -> None:
        super().__init__(bot)
        self.ideas = idea_board

    async def cog_load(self) -> None:
        self.bot.add_view(IdeaVoteView(self.ideas))

    @app_commands.command(name="idea", description="Предложить идею для стрима или сервера")
    @app_commands.describe(text="Ваша идея: 12–400 символов")
    @app_commands.guild_only()
    async def submit(self, interaction: discord.Interaction, text: str) -> None:
        channel = interaction.channel
        if interaction.guild is None or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Используй текстовый канал сервера.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            record = await self.ideas.create(interaction.guild.id, interaction.user.id, channel.id, text)
        except IdeaError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        try:
            message = await channel.send(embed=idea_embed(record), view=IdeaVoteView(self.ideas), allowed_mentions=_NO_MENTIONS)
            await self.ideas.bind(interaction.guild.id, record["id"], message.id)
        except discord.HTTPException:
            await self.ideas.remove(interaction.guild.id, record["id"])
            logger.warning("Ideas: не удалось отправить сообщение", exc_info=True)
            await interaction.followup.send("Боту не удалось опубликовать карточку. Проверь права Embed Links.", ephemeral=True)
            return
        await interaction.followup.send(f"📨 Идея #{record['id']} опубликована: {message.jump_url}", ephemeral=True)

    @app_commands.command(name="ideas", description="Топ или последние идеи сообщества")
    @app_commands.describe(mode="Сортировка")
    @app_commands.choices(mode=[
        app_commands.Choice(name="🔥 Лучшие", value="top"),
        app_commands.Choice(name="🕑 Новые", value="new"),
    ])
    @app_commands.guild_only()
    async def board(self, interaction: discord.Interaction, mode: app_commands.Choice[str] | None = None) -> None:
        if interaction.guild is None:
            return
        is_top = mode is None or mode.value == "top"
        entries = await self.ideas.list_ideas(interaction.guild.id, limit=10, top=is_top)
        if not entries:
            await interaction.response.send_message("Идей пока нет. Начни с /idea.", ephemeral=True)
            return
        lines: list[str] = []
        for item in entries:
            up, down = self.ideas.scores(item)
            link = (
                f"https://discord.com/channels/{interaction.guild.id}/{item['channel_id']}/{item['message_id']}"
                if item["message_id"] else None
            )
            name = f"[#{item['id']}]({link})" if link else f"#{item['id']}"
            safe_text = discord.utils.escape_mentions(discord.utils.escape_markdown(item["text"][:140]))
            lines.append(f"**{up - down:+d}** · {name} · {STATUS_LABELS[item['status']]}\\n{safe_text}")
        embed = discord.Embed(
            title="🏆 Лучшие идеи" if is_top else "📨 Последние идеи",
            description="\\n\\n".join(lines)[:4000],
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, allowed_mentions=_NO_MENTIONS)

    @staticmethod
    def _is_staff(interaction: discord.Interaction) -> bool:
        perms = getattr(interaction.user, "guild_permissions", None)
        return bool(perms and (perms.administrator or perms.manage_guild))

    @app_commands.command(name="idea_status", description="Изменить статус идеи (модераторам)")
    @app_commands.describe(idea_id="ID из карточки", status="Новый статус")
    @app_commands.choices(status=[
        app_commands.Choice(name="Новая", value="new"),
        app_commands.Choice(name="На рассмотрении", value="review"),
        app_commands.Choice(name="В планах", value="planned"),
        app_commands.Choice(name="Реализована", value="done"),
        app_commands.Choice(name="Отклонена", value="declined"),
    ])
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def set_status(
        self, interaction: discord.Interaction, idea_id: str, status: app_commands.Choice[str]
    ) -> None:
        if interaction.guild is None or not self._is_staff(interaction):
            await interaction.response.send_message("Нужны права Управление сервером.", ephemeral=True)
            return
        try:
            item = await self.ideas.status(interaction.guild.id, idea_id.upper(), status.value)
        except IdeaError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await self._update_message(item)
        await interaction.response.send_message(f"Идея #{item['id']}: {STATUS_LABELS[item['status']]}", ephemeral=True)

    @app_commands.command(name="idea_delete", description="Удалить идею (модераторам)")
    @app_commands.describe(idea_id="ID из карточки")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def delete(self, interaction: discord.Interaction, idea_id: str) -> None:
        if interaction.guild is None or not self._is_staff(interaction):
            await interaction.response.send_message("Нужны права Управление сервером.", ephemeral=True)
            return
        try:
            item = await self.ideas.remove(interaction.guild.id, idea_id.upper())
        except IdeaError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        channel = self.bot.get_channel(item["channel_id"])
        if item["message_id"] and isinstance(channel, discord.TextChannel):
            try:
                message = await channel.fetch_message(item["message_id"])
                await message.edit(content="🗑️ Идея удалена модератором.", embed=None, view=None)
            except discord.HTTPException:
                logger.debug("Ideas: не удалось обновить удалённое сообщение", exc_info=True)
        await interaction.response.send_message(f"Идея #{item['id']} удалена.", ephemeral=True)

    async def _update_message(self, item: dict[str, Any]) -> None:
        channel = self.bot.get_channel(item["channel_id"])
        if not item["message_id"] or not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(item["message_id"])
            active = item["status"] not in ("done", "declined")
            await message.edit(embed=idea_embed(item), view=IdeaVoteView(self.ideas) if active else None)
        except discord.HTTPException:
            logger.debug("Ideas: не удалось обновить карточку", exc_info=True)
