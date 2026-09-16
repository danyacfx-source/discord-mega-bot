"""Команды информации: сервер и пользователь."""
from __future__ import annotations

import datetime as dt

import discord
from discord import app_commands

from app.core import embeds
from app.core.base import MegaCog

_BOT_BADGES = {
    "partner": "🤝 Partner",
    "verified_bot_developer": "👨‍💻 Verified Dev",
    "certified_moderator": "🛡️ Certified Moderator",
}


class InfoCog(MegaCog, name="Информация"):

    @app_commands.command(name="serverinfo", description="Информация о сервере")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None

        members = guild.members
        total_members = sum(1 for m in members if not m.bot)
        total_bots = sum(1 for m in members if m.bot)

        embed = embeds.info(f"Информация о сервере: {guild.name}")
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Владелец", value=guild.owner.mention if guild.owner else "—", inline=True)
        embed.add_field(name="ID", value=guild.id, inline=True)
        embed.add_field(name="Создан", value=guild.created_at.strftime("%d.%m.%Y"), inline=True)
        embed.add_field(
            name="Участники",
            value=f"{total_members} человек • {total_bots} ботов",
            inline=True,
        )
        embed.add_field(name="Каналы", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="Бусты", value=f"{guild.premium_subscription_count} 🔥", inline=True)
        embed.add_field(name="Роли", value=str(len(guild.roles)), inline=True)
        if guild.description:
            embed.add_field(name="Описание", value=guild.description, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Информация о пользователе")
    @app_commands.describe(user="Пользователь (по умолчанию — вы)")
    @app_commands.guild_only()
    async def userinfo(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        embed = embeds.info(f"Информация: {target}")
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Никнейм", value=target.mention, inline=True)
        embed.add_field(name="ID", value=target.id, inline=True)
        embed.add_field(name="Аккаунт создан", value=target.created_at.strftime("%d.%m.%Y"), inline=True)
        embed.add_field(name="Присоединился", value=target.joined_at.strftime("%d.%m.%Y") if target.joined_at else "—", inline=True)
        top_role = target.top_role if target.top_role.color.value else None
        embed.add_field(name="Топ-роль", value=top_role.mention if top_role else "—", inline=True)
        if target.premium_since:
            embed.add_field(name="Нитробустер", value="Да 🚀", inline=True)
        roles = [r.mention for r in target.roles[1:][:10]]
        if roles:
            embed.add_field(name=f"Роли ({len(target.roles) - 1})", value=" ".join(roles), inline=False)
        if target.id == interaction.guild.owner_id:
            embed.add_field(name="Владелец сервера", value="Да", inline=True)
        await interaction.response.send_message(embed=embed)


class AboutCog(MegaCog, name="About"):
    @app_commands.command(name="about", description="О боте")
    async def about(self, interaction: discord.Interaction) -> None:
        guilds = len(self.bot.guilds)
        uptime = dt.datetime.now(tz=dt.UTC) - self.bot.start_time

        embed = embeds.info("Асуна Юки", "Модульный бот: модерация, музыка, администрирование.")
        embed.add_field(name="Серверов", value=str(guilds), inline=True)
        embed.add_field(name="Версия", value=self.bot.config.version, inline=True)
        embed.add_field(name="Аптайм", value=str(uptime).split(".")[0], inline=True)
        public_flags = getattr(interaction.application, "flags", None)
        if public_flags:
            badges = [_BOT_BADGES[name] for name, label in _BOT_BADGES.items() if getattr(public_flags, name, False)]
            if badges:
                embed.add_field(name="Бейджи", value=", ".join(badges), inline=False)
        await interaction.response.send_message(embed=embed)
