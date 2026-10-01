"""Роль «В эфире»: выдаётся броадкастеру на время стрима и снимается после."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")


async def update_stream_role(bot: MegaBot, *, enable: bool) -> None:
    """Выдаёт или снимает роль стрима у настроенных пользователей.

    Вызывается из поллинг-цикла при live/offline: если роль уже в нужном
    состоянии, API не трогается (проверка по кэшу участников). Без
    STREAM_ROLE_ID / STREAM_ROLE_USER_IDS — тихий no-op.
    """
    config = bot.config
    role_id = config.stream_role_id
    user_ids = config.stream_role_user_ids
    if not role_id or not user_ids:
        return
    for guild in bot.guilds:
        role = guild.get_role(role_id)
        if role is None:
            continue
        for user_id in user_ids:
            member = guild.get_member(user_id)
            if member is None:
                continue
            has_role = role in member.roles
            if enable and not has_role:
                reason = "Стрим в эфире"
            elif not enable and has_role:
                reason = "Стрим завершён"
            else:
                continue
            try:
                if enable:
                    await member.add_roles(role, reason=reason)
                else:
                    await member.remove_roles(role, reason=reason)
            except discord.HTTPException:
                logger.warning("Не удалось изменить роль стрима у участника %s", user_id, exc_info=True)
