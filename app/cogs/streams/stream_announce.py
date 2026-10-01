"""Старт-анонс стрима отдельным постом и реакция «пойду смотреть» (🔔)."""
from __future__ import annotations

import logging

import discord

from app.services.stream_rsvp import StreamRsvpStore

logger = logging.getLogger("bot.cogs")

#: Кто откликнулся на анонс: жмут 🔔 под постом «Стрим начался».
RSVP_EMOJI = "\U0001f514"


async def pin_sticky(message: discord.Message) -> None:
    """Закрепляет стрим-пост на время эфира; без прав — тихий no-op."""
    try:
        await message.pin(reason="Стрим-уведомление")
    except discord.HTTPException:
        logger.debug("Не удалось закрепить стрим-пост", exc_info=True)


async def unpin_sticky(message: discord.Message) -> None:
    """Снимает закреп после окончания стрима; без прав — тихий no-op."""
    try:
        await message.unpin(reason="Стрим завершён")
    except discord.HTTPException:
        logger.debug("Не удалось открепить стрим-пост", exc_info=True)


async def post_rsvp(channel: discord.abc.Messageable, *, store: StreamRsvpStore, title: str, url: str) -> None:
    """Шлёт отдельный пост-анонс на старте эфира и ставит реакцию 🔔.

    Пинг роли остаётся на sticky-карточке — здесь текст без упоминаний,
    чтобы не дублировать пинг. Сбой не должен ронять поллинг.
    """
    text = f"🚀 Стрим начался: **{title}**\n{url}\nНажмите {RSVP_EMOJI}, если пойдёте смотреть."
    try:
        message = await channel.send(text)
        await message.add_reaction(RSVP_EMOJI)
    except discord.HTTPException:
        logger.warning("Не удалось отправить старт-анонс стрима", exc_info=True)
        return
    try:
        await store.save(message.id)
    except Exception:
        logger.warning("Не удалось сохранить id старт-анонса", exc_info=True)


async def rsvp_users(
    channel: discord.abc.Messageable, *, store: StreamRsvpStore
) -> list[discord.User] | None:
    """Кто откликнулся 🔔 на последнем старт-анонсе.

    ``None`` — анонса ещё не было (или сообщение удалено), ``[]`` — реакций нет.
    """
    message_id = await store.message_id()
    if message_id is None:
        return None
    try:
        message = await channel.fetch_message(message_id)
    except discord.HTTPException:
        return None
    reaction = next((r for r in message.reactions if str(r.emoji) == RSVP_EMOJI), None)
    if reaction is None:
        return []
    users = [user async for user in reaction.users(limit=100)]
    return [user for user in users if not user.bot]
