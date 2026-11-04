"""Автореспондер: ответ на триггеры и выдача роли за точную фразу.

Правила и роль — из .env (AUTORESPOND_RULES, AUTORESPOND_ROLE_RULES,
AUTORESPOND_ROLE_ID, AUTORESPOND_COOLDOWN). Триггер ищется как подстрока
(без учёта регистра), фразы роли — только точное совпадение.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from app.core.base import MegaCog

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")

#: Не держим в памяти кулы неактивных пар дольше этого числа записей.
_MAX_COOLDOWN_KEYS = 5000


class AutorespondCog(MegaCog, name="Autorespond"):
    def __init__(self, bot: MegaBot) -> None:
        super().__init__(bot)
        self._last_reply: dict[tuple[int, int], float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        text = (message.content or "").strip()
        if not text:
            return
        low = text.lower()
        await self._maybe_grant_role(message, low)
        await self._maybe_reply(message, low)

    async def _maybe_reply(self, message: discord.Message, low: str) -> None:
        rules = self.config.autorespond_rules
        if not rules:
            return
        cooldown = self.config.autorespond_cooldown
        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        if cooldown and now - self._last_reply.get(key, -1e9) < cooldown:
            return
        for trigger, reply in rules:
            if trigger not in low:
                continue
            try:
                await message.channel.send(reply)
            except discord.HTTPException:
                logger.debug("Автореспондер: не удалось ответить", exc_info=True)
                return
            if len(self._last_reply) > _MAX_COOLDOWN_KEYS:
                self._last_reply.clear()
            self._last_reply[key] = now
            return

    async def _maybe_grant_role(self, message: discord.Message, low: str) -> None:
        phrases = self.config.autorespond_role_phrases
        role_id = self.config.autorespond_role_id
        if not phrases or not role_id:
            return
        if low not in {phrase.lower() for phrase in phrases}:
            return
        guild = message.guild
        role = guild.get_role(role_id)
        member = (
            message.author
            if isinstance(message.author, discord.Member)
            else guild.get_member(message.author.id)
        )
        if role is None or member is None or role in member.roles:
            return
        try:
            await member.add_roles(role, reason="Автореспондер: фраза-триггер")
        except discord.HTTPException:
            logger.debug("Автореспондер: не удалось выдать роль", exc_info=True)
