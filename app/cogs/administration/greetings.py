"""Приветствия и прощания участников (порт welcome.js из Node)."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from app.core import embeds
from app.core.base import MegaCog
from app.services.settings_service import SettingsService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")

_DEFAULT_INTRO = "Рады видеть тебя на сервере! Загляни в чаты и приходи на стримы."
_DEFAULT_DESC = "Общение в канале"
_DEFAULT_VOICE_DESC = "Голосовой канал"


class GreetingsCog(MegaCog, name="Greetings"):
    def __init__(self, bot: MegaBot, settings: SettingsService) -> None:
        super().__init__(bot)
        self.settings = settings

    # ------------------------------------------------------------- catalog LD

    def _json(self, raw: str) -> dict:
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Загружен невалидный JSON конфигурации welcome")
            return {}
        return data if isinstance(data, dict) else {}

    def _json_list(self, raw: str) -> list:
        if not raw.strip():
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    async def _catalog(self, member: discord.Member) -> discord.Embed:
        config = self.bot.config
        descriptions = self._json(config.welcome_channel_descriptions)
        voice_descriptions = self._json(config.welcome_voice_descriptions)
        hidden_voice = set(self._json_list(config.welcome_hidden_voice))

        lines: list[str] = []
        for category in sorted(member.guild.categories, key=lambda c: c.position):
            text_channels = [
                channel
                for channel in category.text_channels
                if channel.permissions_for(member.guild.default_role).view_channel
            ]
            text_channels.sort(key=lambda c: c.name)
            if not text_channels:
                continue
            lines.append(f"**{category.name}**")
            for channel in text_channels:
                desc = descriptions.get(channel.name, _DEFAULT_DESC)
                lines.append(f"• **<#{channel.id}>** — {desc}")
            lines.append("")

        voice_lines: list[str] = []
        for channel in sorted(member.guild.voice_channels, key=lambda c: c.position):
            if channel.name in hidden_voice:
                continue
            if not channel.permissions_for(member.guild.default_role).connect:
                continue
            desc = voice_descriptions.get(channel.name, _DEFAULT_VOICE_DESC)
            voice_lines.append(f"• **{channel.name}** — {desc}")
        if voice_lines:
            lines.append("**Голосовые каналы**")
            lines.extend(voice_lines)

        intro = config.welcome_intro or _DEFAULT_INTRO
        embed = embeds.brand(config.welcome_title, intro)
        channel_text = "\n".join(lines).strip()
        if channel_text:
            if len(channel_text) > 1024:
                channel_text = channel_text[:1020] + "\n…"
            embed.add_field(name="КАНАЛЫ СЕРВЕРА", value=channel_text, inline=False)

        if member.guild.rules_channel:
            embed.add_field(
                name="ПЕРЕД НАЧАЛОМ",
                value=f"Ознакомься с правилами сервера: <#{member.guild.rules_channel.id}>",
                inline=False,
            )
        embed.set_footer(text=config.welcome_footer)
        return embed

    # ------------------------------------------------------------- join / leave

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        config = self.bot.config
        if not config.welcome_enabled:
            return
        if config.welcome_send_dm:
            try:
                embed = await self._catalog(member)
                payload_size = len(json.dumps(embed.to_dict(), ensure_ascii=False))
                if payload_size > 6000:
                    embed = embeds.brand(config.welcome_title, (config.welcome_intro or _DEFAULT_INTRO)[:4096])
                await member.send(embed=embed)
                logger.info("Welcome: приветствие отправлено %s", member.name)
            except discord.Forbidden:
                logger.info("Welcome: нельзя отправить ЛС %s", member.name)
            except discord.HTTPException:
                logger.warning("Welcome: ошибка отправки ЛС %s", member.name)

        if config.welcome_channel_enabled:
            await self._public_join(member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.bot:
            return
        config = self.bot.config
        if not config.welcome_enabled or not config.welcome_leave_channel_enabled:
            return
        await self._public_leave(member)

    async def _public_join(self, member: discord.Member) -> None:
        channel = await self._channel(member.guild, self.bot.config.welcome_channel_id, "welcome_channel_id")
        if channel is None:
            return
        embed = embeds.success(
            "Добро пожаловать",
            f"## {member.display_name}\n{member.mention} присоединяется к сообществу. Осваивайся и чувствуй себя как дома.",
        )
        embed.set_thumbnail(url=member.display_avatar.with_size(256).url)
        embed.add_field(name="ТЕПЕРЬ НАС", value=f"**{member.guild.member_count}**", inline=True)
        if member.guild.rules_channel:
            embed.add_field(name="НАЧАТЬ ЗДЕСЬ", value=member.guild.rules_channel.mention, inline=True)
        embed.set_footer(text=f"ZAVOD  •  USER ID {member.id}")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.warning("Welcome: ошибка отправки в %s", getattr(channel, "name", channel.id))

    async def _public_leave(self, member: discord.Member) -> None:
        channel = await self._channel(member.guild, self.bot.config.welcome_leave_channel_id, "farewell_channel_id")
        if channel is None:
            return
        embed = embeds.info(
            "Участник покинул сервер",
            f"**{member.display_name}** вышел из сообщества. Надеемся ещё увидеться.",
        )
        embed.set_thumbnail(url=member.display_avatar.with_size(256).url)
        embed.set_footer(text=f"ZAVOD  •  USER ID {member.id}")
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.warning("Welcome: ошибка отправки в %s", getattr(channel, "name", channel.id))

    async def _channel(
        self, guild: discord.Guild, config_id: int | None, db_key: str
    ) -> discord.TextChannel | None:
        settings = await self.settings.get(guild.id)
        channel_id = settings[db_key]
        if channel_id is None:
            channel_id = config_id
        if not channel_id:
            return None
        channel = guild.get_channel(channel_id)
        return channel if isinstance(channel, discord.TextChannel) else None
