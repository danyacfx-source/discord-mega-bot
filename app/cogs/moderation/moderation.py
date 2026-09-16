"""Команды модерации: kick, ban, timeout, purge, warn, роли, slowmode."""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.utils import utcnow

from app.core import embeds
from app.core.base import MegaCog
from app.core.checks import moderation_reason
from app.services.logging_service import LoggingService
from app.services.moderation_service import SLOWMODE_SUGGESTIONS, TIMEOUT_SUGGESTIONS, ModerationService
from app.utils.pagination import PaginatorView

if TYPE_CHECKING:
    from app.core.bot import MegaBot


def _member_embed(action: str, target: discord.User | discord.Member, reason: str) -> discord.Embed:
    embed = embeds.success(f"✅ {action}: {target}")
    embed.add_field(name="Пользователь", value=f"{target.mention} ({target.id})", inline=True)
    if reason:
        embed.add_field(name="Причина", value=reason, inline=False)
    return embed


async def _timeout_autocomplete(_interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=value, value=value) for value in TIMEOUT_SUGGESTIONS if current in value]


async def _slowmode_autocomplete(_interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=value, value=value) for value in SLOWMODE_SUGGESTIONS if current in value]


class ModerationCog(MegaCog, name="Moderation"):
    def __init__(self, bot: MegaBot, moderation: ModerationService, logging: LoggingService) -> None:
        super().__init__(bot)
        self.moderation = moderation
        self.logging = logging

    async def _guard_target(self, interaction: discord.Interaction, member: discord.Member) -> bool:
        me = interaction.guild.me
        assert isinstance(me, discord.Member)
        if not self.moderation.can_moderate(me, member):
            await interaction.response.send_message(
                embed=embeds.error(
                    "Недостаточно прав",
                    "Бот не может модернировать этого участника (иерархия ролей или это владелец/бот).",
                ),
                ephemeral=True,
            )
            return False
        return True

    @app_commands.command(name="kick", description="Кикнуть участника")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.guild_only()
    async def kick(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "",
    ) -> None:
        if not await self._guard_target(interaction, member):
            return
        await member.kick(reason=moderation_reason(interaction.user, reason))
        embed = _member_embed("Кик", member, reason or "не указана")
        await interaction.response.send_message(embed=embed)
        await self.logging.log_mod_action(
            interaction.guild, "kick", member, interaction.user, reason, description=f"{member.mention} исключён"
        )

    @app_commands.command(name="ban", description="Забанить участника")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    async def ban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "",
        delete_days: app_commands.Range[int, 0, 7] = 0,
    ) -> None:
        if not await self._guard_target(interaction, member):
            return
        await member.ban(reason=moderation_reason(interaction.user, reason), delete_message_seconds=delete_days * 86400)
        embed = _member_embed("Бан", member, reason or "не указана")
        await interaction.response.send_message(embed=embed)
        await self.logging.log_mod_action(
            interaction.guild, "ban", member, interaction.user, reason, description=f"{member.mention} забанен"
        )

    @app_commands.command(name="unban", description="Разбанить пользователя по ID")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    async def unban(self, interaction: discord.Interaction, user_id: str) -> None:
        guild = interaction.guild
        assert guild is not None
        try:
            ban_entry = await guild.fetch_ban(discord.Object(id=int(user_id)))
        except discord.NotFound:
            await interaction.response.send_message(embed=embeds.error("Не найден", "Пользователь с таким ID не забанен."), ephemeral=True)
            return
        await guild.unban(ban_entry.user, reason=moderation_reason(interaction.user))
        embed = _member_embed("Разбан", ban_entry.user, "")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="timeout", description="Тайм-аут участника")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(duration="Длительность: 1m, 10m, 1h, 1d")
    @app_commands.autocomplete(duration=_timeout_autocomplete)
    @app_commands.guild_only()
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, duration: str, reason: str = "") -> None:
        seconds = self.moderation.parse_duration(duration)
        if seconds is None:
            await interaction.response.send_message(
                embed=embeds.error("Ошибка формата", "Пример формата: `1h 30m` или `7d`."),
                ephemeral=True,
            )
            return
        if not await self._guard_target(interaction, member):
            return
        await member.timeout(utcnow() + timedelta(seconds=seconds), reason=moderation_reason(interaction.user, reason))
        embed = _member_embed("Тайм-аут", member, f"{duration} · {reason or 'не указана'}")
        await interaction.response.send_message(embed=embed)
        await self.logging.log_mod_action(
            interaction.guild,
            "timeout",
            member,
            interaction.user,
            reason,
            description=f"{member.mention} получил тайм-аут {duration}",
        )

    @app_commands.command(name="purge", description="Массовое удаление сообщений")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(amount="Сколько сообщений удалить (1–200)")
    @app_commands.guild_only()
    async def purge(
        self,
        interaction: discord.Interaction,
        amount: app_commands.Range[int, 1, 200],
        member: discord.Member | None = None,
    ) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                embed=embeds.error("Ошибка", "Команду можно использовать только в текстовых каналах."),
                ephemeral=True,
            )
            return

        def _check(message: discord.Message) -> bool:
            return not message.author.bot if member is None else message.author == member

        deleted = await channel.purge(limit=amount, check=_check, bulk=True)
        embed = embeds.success("Очистка завершена", f"Удалено сообщений: **{len(deleted)}**")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="warn", description="Выдать предупреждение")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str) -> None:
        count = await self.moderation.warn(interaction.guild.id, member.id, interaction.user.id, reason)
        embed = _member_embed("Предупреждение", member, reason)
        embed.add_field(name="Всего предупреждений", value=str(count), inline=True)
        await interaction.response.send_message(embed=embed)
        await self.logging.log_mod_action(
            interaction.guild, "warn", member, interaction.user, reason, description=f"{member.mention} получил предупреждение {count}"
        )

    async def _warns_response(self, interaction: discord.Interaction, member: discord.Member) -> None:
        warns = await self.moderation.warns_for_user(interaction.guild.id, member.id)
        if not warns:
            embed = embeds.info("Предупреждения", f"У {member.mention} нет предупреждений.")
            await interaction.response.send_message(embed=embed)
            return

        chunk_size = 8
        pages: list[discord.Embed] = []
        for start in range(0, len(warns), chunk_size):
            page = embeds.info(f"Предупреждения: {member}", f"Всего: **{len(warns)}**")
            for warn in warns[start : start + chunk_size]:
                moderator = interaction.guild.get_member(warn["moderator_id"])
                page.add_field(
                    name=f"#{warn['id']} — {warn['created_at'][:19].replace('T', ' ')}",
                    value=f"Причина: {warn['reason']}\nМодератор: {moderator.mention if moderator else warn['moderator_id']}",
                    inline=False,
                )
                page.set_footer(text=f"Страница {start // chunk_size + 1}")
            pages.append(page)

        view = PaginatorView(pages, interaction.user)
        await interaction.response.send_message(embed=pages[0], view=view)

    @app_commands.command(name="warns", description="Список предупреждений участника")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def warns(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await self._warns_response(interaction, member)

    @app_commands.command(name="clearwarns", description="Снять все предупреждения")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def clear_warns(self, interaction: discord.Interaction, member: discord.Member) -> None:
        removed = await self.moderation.clear_warns(interaction.guild.id, member.id)
        embed = embeds.success("Предупреждения сняты", f"Удалено: **{removed}** у {member.mention}")
        await interaction.response.send_message(embed=embed)
        await self.logging.log_mod_action(interaction.guild, "clearwarns", member, interaction.user, "")

    @app_commands.command(name="slowmode", description="Задать задержку сообщений в канале")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.autocomplete(duration=_slowmode_autocomplete)
    @app_commands.guild_only()
    async def slowmode(self, interaction: discord.Interaction, duration: str) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                embed=embeds.error("Ошибка", "Команда работает только в текстовых каналах."),
                ephemeral=True,
            )
            return
        seconds = self.moderation.parse_slowmode(duration)
        await channel.edit(slowmode_delay=seconds)
        text = "отключён" if seconds == 0 else f"установлен на {duration}"
        await interaction.response.send_message(embed=embeds.success("Слоумод", f"В канале {channel.mention} слоумод {text}."))

    @app_commands.command(name="roles", description="Выдать или снять роль у участника")
    @app_commands.default_permissions(manage_roles=True)
    @app_commands.guild_only()
    async def roles(self, interaction: discord.Interaction, member: discord.Member, role: discord.Role, action: str) -> None:
        action = action.strip().lower()
        if action not in {"give", "remove"}:
            await interaction.response.send_message(embed=embeds.error("Ошибка", "Действие: `give` или `remove`."), ephemeral=True)
            return
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                embed=embeds.error("Ошибка", "Этот роль выше бота — не могу выдать/снять."),
                ephemeral=True,
            )
            return
        try:
            if action == "give":
                await member.add_roles(role, reason=moderation_reason(interaction.user))
            else:
                await member.remove_roles(role, reason=moderation_reason(interaction.user))
        except discord.Forbidden:
            await interaction.response.send_message(embed=embeds.error("Ошибка", "Нет прав на изменение ролей."), ephemeral=True)
            return
        verb = "выдана" if action == "give" else "снята"
        await interaction.response.send_message(embed=embeds.success(f"Роль {verb}", f"{role.mention} — у {member.mention}."))
