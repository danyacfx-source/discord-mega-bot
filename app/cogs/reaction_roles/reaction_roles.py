"""Reaction-роли: назначение ролей по реакции на сообщение."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.core import embeds
from app.core.base import MegaCog
from app.services.reaction_roles_service import ReactionRolesService
from app.utils.pagination import PaginatorView

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")


class ReactionRolesCog(MegaCog, name="ReactionRoles"):
    def __init__(self, bot: MegaBot, reaction_roles: ReactionRolesService) -> None:
        super().__init__(bot)
        self.reaction_roles = reaction_roles

    @staticmethod
    def _emoji_key(emoji: discord.PartialEmoji) -> str:
        return str(emoji)

    async def _resolve_message(self, message_id: int, channel: discord.TextChannel) -> discord.Message:
        return await channel.fetch_message(message_id)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self._handle_reaction(payload, remove=False)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self._handle_reaction(payload, remove=True)

    async def _handle_reaction(self, payload: discord.RawReactionActionEvent, *, remove: bool) -> None:
        if payload.user_id == self.bot.user.id:
            return
        emoji = self._emoji_key(payload.emoji)
        configs = await self.reaction_roles.by_message(payload.message_id)
        for config in configs:
            if config["emoji"] != emoji:
                continue
            guild = self.bot.get_guild(payload.guild_id)
            if guild is None or config["guild_id"] != payload.guild_id:
                continue
            member = guild.get_member(payload.user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(payload.user_id)
                except discord.HTTPException:
                    return
            role = guild.get_role(config["role_id"])
            if role is None:
                continue
            try:
                if remove:
                    await member.remove_roles(role, reason="Reaction-роль снята")
                else:
                    await member.add_roles(role, reason="Reaction-роль выдана")
            except (discord.Forbidden, discord.HTTPException):
                logger.debug("Не удалось изменить роли для %s", member.id)

    @app_commands.command(name="reactrole", description="Привязать эмодзи к роли на сообщении")
    @app_commands.describe(
        message_id="ID сообщения с реакциями",
        emoji="Эмодзи (обычный или серверный) или её имя",
        role="Роль, которую выдаём",
        channel="Канал с сообщением (по умолчанию текущий)",
    )
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def rr_add(self, interaction: discord.Interaction, message_id: int, emoji: str, role: discord.Role,
                     channel: discord.TextChannel | None = None) -> None:
        channel = channel or interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                embed=embeds.error("Ошибка", "Укажите текстовый канал с сообщением."),
                ephemeral=True,
            )
            return
        try:
            await self._resolve_message(message_id, channel)
        except discord.HTTPException:
            await interaction.response.send_message(
                embed=embeds.error("Сообщение не найдено", "Проверьте канал и ID сообщения."), ephemeral=True
            )
            return
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(embed=embeds.error("Роль выше бота", "Дайте боту роль выше целевой."), ephemeral=True)
            return

        emoji_key = emoji.strip()
        added = await self.reaction_roles.add(interaction.guild.id, channel.id, message_id, role.id, emoji_key)
        embed = embeds.success("Reaction-роль настроена", f"Эмодзи `{emoji_key}` → роль {role.mention} на сообщении `{message_id}`")
        embed.add_field(name="Повтор", value="Уже привязано, обновил данные" if not added else "Успешно добавлено")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="reactrole_remove", description="Убрать привязку эмодзи к роли")
    @app_commands.describe(message_id="ID сообщения", emoji="Эмодзи, привязку которой убираем")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def rr_remove(self, interaction: discord.Interaction, message_id: int, emoji: str) -> None:
        removed = await self.reaction_roles.remove(interaction.guild.id, message_id, emoji.strip())
        embed = embeds.success("Привязка удалена") if removed else embeds.error("Не найдено", "Такой привязки нет.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="reactrole_clear", description="Убрать все привязки с сообщения")
    @app_commands.describe(message_id="ID сообщения")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def rr_clear(self, interaction: discord.Interaction, message_id: int) -> None:
        cleared = await self.reaction_roles.clear_message(message_id)
        if cleared <= 0:
            embed = embeds.error("Не найдено", "На этом сообщении нет привязок.")
        else:
            embed = embeds.success("Готово", f"Удалено привязок: **{cleared}**.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="reactrole_list", description="Список reaction-ролей сервера")
    @app_commands.guild_only()
    async def rr_list(self, interaction: discord.Interaction) -> None:
        configs = await self.reaction_roles.list_for_guild(interaction.guild.id)
        if not configs:
            await interaction.response.send_message(embed=embeds.info("Пока пусто", "Настройте через `/reactrole`."), ephemeral=True)
            return

        pages: list[discord.Embed] = []
        per_page = 5
        for start in range(0, len(configs), per_page):
            embed = embeds.info(f"Reaction-роли сервера ({len(configs)})")
            for config in configs[start:start + per_page]:
                role = interaction.guild.get_role(config["role_id"])
                role_text = role.mention if role else f"`{config['role_id']}` (удалена)"
                embed.add_field(
                    name=config["emoji"],
                    value=f"Сообщение `{config['message_id']}` • {role_text}",
                    inline=False,
                )
            pages.append(embed)
        view = PaginatorView(pages, interaction.user) if len(pages) > 1 else None
        if view:
            await interaction.response.send_message(embed=pages[0], view=view)
        else:
            await interaction.response.send_message(embed=pages[0])
