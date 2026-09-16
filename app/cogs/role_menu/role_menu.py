"""Меню ролей: две select-панели «получить/снять роль» (порт role_menu.js из Node)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from app.core import embeds
from app.core.base import MegaCog

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")

PANEL_FOOTER = "Роли через меню выбора"
ADD_ID = "role_menu_add"
REMOVE_ID = "role_menu_remove"


class RoleMenuView(discord.ui.View):
    def __init__(self, roles: tuple[str, ...], max_values: int) -> None:
        super().__init__(timeout=None)
        limit = min(max(1, max_values), len(roles))
        self.add_item(RoleSelect(ADD_ID, "Получить роль…", roles, limit))
        self.add_item(RoleSelect(REMOVE_ID, "Снять роль…", roles, limit))


class RoleSelect(discord.ui.Select):
    def __init__(self, custom_id: str, placeholder: str, roles: tuple[str, ...], max_values: int) -> None:
        options = [
            discord.SelectOption(label=name, value=name, description=f"Роль «{name}»")
            for name in roles
        ]
        super().__init__(
            custom_id=custom_id,
            placeholder=placeholder,
            min_values=0,
            max_values=max_values,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        add = self.custom_id == ADD_ID
        guild = interaction.guild
        member = interaction.user
        if guild is None or member is None or not isinstance(member, discord.Member):
            await interaction.response.send_message(content="Не удалось определить участника.", ephemeral=True)
            return
        added: list[str] = []
        already: list[str] = []
        missing: list[str] = []
        values = [str(v) for v in ((interaction.data or {}).get("values") or [])]
        logger.debug("Роль-меню %s для %s: %s", self.custom_id, getattr(member, "id", "?"), values)
        for name in values:
            target = discord.utils.get(guild.roles, name=name)
            if target is None:
                missing.append(name)
                continue
            try:
                if add and target not in member.roles:
                    await member.add_roles(target, reason="Выбор роли в меню")
                    added.append(name)
                elif not add and target in member.roles:
                    await member.remove_roles(target, reason="Снятие роли в меню")
                    added.append(name)
                else:
                    already.append(name)
            except discord.HTTPException:
                logger.debug("Нет прав изменить роль %s у %s", name, getattr(member, "id", "?"))
                missing.append(name)
        verb = "добавлены" if add else "сняты"
        parts = [f"Роли {verb} ({len(added)}): " + ", ".join(f"**{name}**" for name in added) if added else f"Роли {verb}: 0"]
        if already:
            parts.append("Уже " + ("были" if add else "отсутствовали") + ": " + ", ".join(f"**{name}**" for name in already))
        if missing:
            parts.append("Не найдены/без прав: " + ", ".join(f"**{name}**" for name in missing))
        await interaction.response.send_message(content="\n".join(parts), ephemeral=True)


class RoleMenuCog(MegaCog, name="RoleMenu"):
    def __init__(self, bot: MegaBot) -> None:
        super().__init__(bot)
        self._started = False

    async def cog_load(self) -> None:
        config = self.bot.config
        if not config.role_menu_enabled or not config.role_menu_roles:
            return
        self.bot.add_view(
            RoleMenuView(config.role_menu_roles, config.role_menu_max_values),
            message_id=None,
        )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._started:
            return
        self._started = True
        channel_id = self.bot.config.role_menu_channel_id
        if not channel_id:
            return
        for guild in self.bot.guilds:
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                await self._ensure_panel(channel)

    async def _ensure_panel(self, channel: discord.TextChannel) -> None:
        config = self.bot.config
        role_names = [name for name in config.role_menu_roles if discord.utils.get(channel.guild.roles, name=name)]
        if not role_names:
            return
        embed = self._panel_embed(role_names, config.role_menu_message)
        view = RoleMenuView(tuple(role_names), config.role_menu_max_values)
        try:
            messages = [m async for m in channel.history(limit=30)]
            for message in messages:
                if message.author.id != self.bot.user.id or not message.embeds:
                    continue
                footer = (message.embeds[0].footer.text or "").strip()
                if footer != PANEL_FOOTER:
                    continue
                await message.edit(embed=embed, view=view)
                logger.info("Панель ролей обновлена в #%s", channel.name)
                return
        except discord.HTTPException:
            pass
        try:
            await channel.send(embed=embed, view=view)
            logger.info("Панель ролей создана в #%s", channel.name)
        except discord.HTTPException:
            logger.warning("Не удалось создать панель ролей в #%s", channel.name)

    @staticmethod
    def _panel_embed(role_names: list[str], message: str) -> discord.Embed:
        description = "Первое меню — получить роль, второе — снять.\n\n" + "\n".join(f"• **{name}**" for name in role_names)
        embed = embeds.info(message or "Уведомления и роли меню", description)
        embed.color = discord.Color(0x9B59B6)
        embed.set_footer(text=PANEL_FOOTER)
        return embed
