"""Starboard: сообщения с N реакциями публикуются в отдельный канал.

Канал/порог/эмодзи — из .env (STARBOARD_CHANNEL_ID / STARBOARD_THRESHOLD /
STARBOARD_EMOJI). Связь «исходное сообщение → звёздное» хранится в KV
(`starboard:{message_id}`), поэтому счётчик редактируется, а при снятии
реакций ниже порога звёздное сообщение удаляется.
"""
from __future__ import annotations

import json
import logging

import discord
from discord.ext import commands

from app.core.base import MegaCog
from app.services.kv_service import KvService

logger = logging.getLogger("bot.cogs")

_STAR_COLOR = 0xF5C518
_MAX_DESCRIPTION = 1000


class StarboardCog(MegaCog, name="Starboard"):
    def __init__(self, bot, kv: KvService) -> None:
        super().__init__(bot)
        self.kv = kv

    # ------------------------------------------------------------- правила

    def _target_channel_id(self, guild: discord.Guild) -> int | None:
        del guild
        return self.bot.config.starboard_channel_id

    def _is_star_emoji(self, emoji: discord.emoji.Emoji | discord.PartialEmoji | str) -> bool:
        return str(emoji) == self.bot.config.starboard_emoji

    def _key(self, message_id: int) -> str:
        return f"starboard:{message_id}"

    # ------------------------------------------------------------- события

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User) -> None:
        if user.bot or not self._is_star_emoji(reaction.emoji):
            return
        await self._sync(reaction)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.User) -> None:
        if user.bot or not self._is_star_emoji(reaction.emoji):
            return
        await self._sync(reaction)

    # ------------------------------------------------------------- логика

    async def _sync(self, reaction: discord.Reaction) -> None:
        message = reaction.message
        channel = getattr(message, "channel", None)
        guild = getattr(channel, "guild", None)
        if guild is None:
            return  # ЛС — не участвуют
        target_id = self._target_channel_id(guild)
        if not target_id or channel.id == target_id:
            return  # starboard выключен или сообщение уже в starboard
        author = getattr(message, "author", None)
        if author is None or author.bot:
            return

        try:
            users = [u async for u in reaction.users() if not u.bot]
        except discord.HTTPException:
            logger.debug("Starboard: не удалось получить реакции", exc_info=True)
            return
        count = len(users)
        threshold = self.bot.config.starboard_threshold

        if count >= threshold:
            await self._publish(guild, message, count)
        else:
            await self._retire(message)

    async def _publish(self, guild: discord.Guild, message, count: int) -> None:
        target_id = self._target_channel_id(guild)
        if not target_id:
            return
        try:
            target = guild.get_channel(target_id) or await guild.fetch_channel(target_id)
        except discord.HTTPException:
            logger.debug("Starboard: канал %s не найден", target_id, exc_info=True)
            return
        if not hasattr(target, "send"):
            return  # голосовые/категории не умеют слать эмбеды

        embed = self._star_embed(message, count)
        stored = json.loads(await self.kv.get(self._key(message.id)) or "null")

        if stored:
            try:
                star_msg = await target.fetch_message(int(stored["msg_id"]))
                await star_msg.edit(embed=embed)
                return
            except Exception:
                await self.kv.delete(self._key(message.id))  # звёздное удалено — постим заново

        try:
            star_msg = await target.send(embed=embed)
        except discord.HTTPException:
            logger.warning("Starboard: не удалось отправить пост в #%s", target.name, exc_info=True)
            return
        await self.kv.set(
            self._key(message.id),
            json.dumps({"channel_id": target.id, "msg_id": star_msg.id}),
        )

    async def _retire(self, message) -> None:
        stored = json.loads(await self.kv.get(self._key(message.id)) or "null")
        if not stored:
            return
        guild = getattr(getattr(message, "channel", None), "guild", None)
        if guild is None:
            return
        try:
            target = guild.get_channel(int(stored["channel_id"])) or await guild.fetch_channel(
                int(stored["channel_id"])
            )
            star_msg = await target.fetch_message(int(stored["msg_id"]))
            await star_msg.delete()
        except discord.HTTPException:
            pass  # уже удалено — норма
        await self.kv.delete(self._key(message.id))

    def _star_embed(self, message, count: int) -> discord.Embed:
        content = (getattr(message, "content", "") or "").strip()
        jump = getattr(message, "jump_url", "")
        parts = [f"**{content}**" if content else "*без текста*"]
        if jump:
            parts.append(f"[перейти к сообщению]({jump})")
        description = "\n\n".join(parts)
        if len(description) > _MAX_DESCRIPTION:
            description = description[: _MAX_DESCRIPTION - 1] + "…"

        embed = discord.Embed(description=description, color=_STAR_COLOR)
        author = getattr(message, "author", None)
        if author is not None:
            embed.set_author(
                name=getattr(author, "display_name", None) or str(author),
                icon_url=getattr(getattr(author, "display_avatar", None), "url", None),
            )
        attachments = getattr(message, "attachments", None) or []
        if attachments:
            embed.set_image(url=attachments[0].url)
        channel = getattr(message, "channel", None)
        name = getattr(channel, "name", None)
        if name:
            embed.set_footer(text=f"#{name}")
        embed.title = f"{self.bot.config.starboard_emoji} {count}"
        return embed
