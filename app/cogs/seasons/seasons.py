"""Сезоны: сезонная активность (сообщения + голос), /season_top и /season_end."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import tasks

from app.core import embeds
from app.core.base import MegaCog
from app.services.season_service import SeasonService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")

_MEDALS = ("🥇", "🥈", "🥉")
_VOICE_INTERVAL_SECONDS = 5 * 60
_TOP_COLOR = 0xF1C40F


class SeasonsCog(MegaCog, name="Seasons"):
    def __init__(self, bot: MegaBot, seasons: SeasonService) -> None:
        super().__init__(bot)
        self.seasons = seasons

    async def cog_load(self) -> None:
        if self.config.season_enabled:
            self.voice_credit_loop.start()

    async def cog_unload(self) -> None:
        self.voice_credit_loop.cancel()

    @tasks.loop(seconds=_VOICE_INTERVAL_SECONDS)
    async def voice_credit_loop(self) -> None:
        for guild in self.bot.guilds:
            members_ids: list[int] = []
            for channel in guild.channels:
                if isinstance(channel, discord.VoiceChannel):
                    members_ids.extend(member.id for member in channel.members if not member.bot)
            if not members_ids:
                continue
            try:
                await self.seasons.add_points(guild.id, list(dict.fromkeys(members_ids)))
            except Exception:
                logger.exception("Seasons: ошибка начисления голоса для %s", guild.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        if not self.config.season_enabled:
            return
        try:
            await self.seasons.add_message(message.guild.id, message.author.id)
        except Exception:
            logger.debug("Seasons: ошибка начисления сообщения", exc_info=True)

    @app_commands.command(name="season_top", description="Топ активности за текущий сезон")
    @app_commands.guild_only()
    async def season_top(self, interaction: discord.Interaction) -> None:
        rows = await self.seasons.leaderboard(interaction.guild.id, 10)
        if not rows:
            await interaction.response.send_message("Сезон только начался — данных пока нет.")
            return
        await interaction.response.defer()
        lines = []
        for index, row in enumerate(rows):
            pos = index + 1
            name = f"Пользователь {row['user_id']}"
            member = interaction.guild.get_member(int(row["user_id"]))
            if member is not None:
                name = member.display_name or member.name
            medal = _MEDALS[pos - 1] if pos <= 3 else f"**{pos}.**"
            lines.append(f"{medal} {name} — {row['points']} сообщений")
        embed = embeds.info("🏆 Сезонный топ", "Сезонная активность: сообщения + голос.")
        embed.description = "\n".join(lines)
        embed.color = discord.Color(_TOP_COLOR)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="season_end", description="Подвести итоги сезона: наградить топ-3 и сбросить счётчики")
    @app_commands.default_permissions(administrator=True, manage_guild=True)
    @app_commands.guild_only()
    async def season_end(self, interaction: discord.Interaction) -> None:
        perms = interaction.user.guild_permissions if isinstance(interaction.user, discord.Member) else None
        if perms is None or not (perms.administrator or perms.manage_guild):
            await interaction.response.send_message(
                embed=embeds.error("Недостаточно прав", "Требуется **Administrator** или **Manage Guild**."), ephemeral=True
            )
            return
        if not self.config.season_enabled:
            await interaction.response.send_message(
                embed=embeds.warning("Отключено", "Сезонный модуль отключён в конфиге."), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        reward_names = [str(name).strip() for name in self.config.season_reward_roles if str(name).strip()]
        if len(reward_names) < 3:
            await interaction.followup.send(embed=embeds.error("Конфиг", "В конфиге меньше 3 ролей наград."), ephemeral=True)
            return
        lowered = [name.lower() for name in reward_names]
        if len(set(lowered)) != len(lowered):
            await interaction.followup.send(embed=embeds.error("Конфиг", "В конфиге дублируются роли наград."), ephemeral=True)
            return
        roles_by_name = {role.name: role for role in interaction.guild.roles}
        missing = [name for name in reward_names if name not in roles_by_name]
        if missing:
            await interaction.followup.send(
                embed=embeds.error("Ошибка", f"Роли не найдены на сервере: {', '.join(missing)}"), ephemeral=True
            )
            return

        rows = await self.seasons.leaderboard(interaction.guild.id, 3)
        if not rows:
            await interaction.followup.send(embed=embeds.warning("Пусто", "Нет данных за сезон — награждать некого."), ephemeral=True)
            return

        awarded: list[str] = []
        for index, row in enumerate(rows):
            member = interaction.guild.get_member(int(row["user_id"]))
            role = roles_by_name[reward_names[index]]
            if member is None:
                awarded.append(f"{_MEDALS[index]} Пользователь {row['user_id']}: пропущен (нет участника)")
                continue
            for old_name in reward_names:
                old_role = roles_by_name.get(old_name)
                if old_role is not None and old_role in member.roles:
                    try:
                        await member.remove_roles(old_role, reason="Награды нового сезона")
                    except discord.HTTPException:
                        logger.debug("Seasons: не удалось снять роль %s", old_name, exc_info=True)
            try:
                await member.add_roles(role, reason="Награда за сезон")
                awarded.append(f"{_MEDALS[index]} **{member.display_name}** + {role.mention} ({row['points']} сообщений)")
            except discord.HTTPException:
                awarded.append(f"{_MEDALS[index]} {member.display_name}: нет прав на выдачу")

        await self.seasons.reset(interaction.guild.id)

        summary = "\n".join(awarded)
        announce_id = self.config.season_announce_channel_id
        if announce_id is not None:
            channel = self.bot.get_channel(announce_id)
            if isinstance(channel, discord.TextChannel):
                embed = embeds.success("🏆 Итоги сезона!", summary)
                embed.color = discord.Color(_TOP_COLOR)
                embed.set_footer(text=f"{datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC")
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    logger.debug("Seasons: не удалось отправить анонс итогов", exc_info=True)
        await interaction.followup.send(embed=embeds.success("🏆 Итоги сезона!", summary), ephemeral=True)