"""Сервис логирования событий сервера в веб-ленту (вместо Discord-каналов)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from app.core.bot import MegaBot
    from app.services.settings_service import SettingsService

logger = logging.getLogger("bot.services")

_AUDIT_LOGGER = logger.getChild("audit")
_AUDIT_LOGGER.setLevel(logging.INFO)

_CATEGORY_KEYS = {
    "general": "log_channel_id",
    "bot": "bot_log_channel_id",
    "member": "member_log_channel_id",
    "message": "message_log_channel_id",
    "voice": "voice_log_channel_id",
    "mod": "mod_log_channel_id",
}


def _embed_to_text(embed: discord.Embed) -> str:
    """Превращает эмбед в компактный текст для веб-ленты."""
    parts: list[str] = []
    if embed.title:
        parts.append(embed.title)
    if embed.description:
        parts.append(embed.description)
    for field in embed.fields:
        value = str(field.value or "").replace("\n", " ")
        parts.append(f"{field.name}: {value}")
    text = "\n".join(p for p in parts if p)
    return text[:2000] if text else "(пустое событие)"


class LoggingService:
    """Пишет аудит-события в веб-ленту и (если настроен) в лог-каналы Discord."""

    def __init__(self, settings: SettingsService, bot: MegaBot) -> None:
        self._settings = settings
        self._bot = bot

    async def target_channel(
        self, guild: discord.Guild, *, category: str | None = None
    ) -> discord.TextChannel | None:
        """Резолвит канал для категории логов: настройки сервера → env → общий лог."""
        key = _CATEGORY_KEYS.get(category or "general")
        if key is None:
            return None
        settings = await self._settings.get(guild.id)
        config = getattr(self._bot, "config", None)
        channel_id = settings.get(key) or getattr(config, key, None)
        if not channel_id and key != "log_channel_id":
            channel_id = settings.get("log_channel_id")
        if not channel_id:
            return None
        channel = guild.get_channel(channel_id)
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _post(
        self,
        guild: discord.Guild,
        category: str,
        *,
        embed: discord.Embed | None = None,
        text: str | None = None,
    ) -> None:
        """Дополнительно отправляет событие в лог-канал Discord (если настроен)."""
        try:
            channel = await self.target_channel(guild, category=category)
        except Exception:
            logger.debug("Не удалось определить лог-канал", exc_info=True)
            return
        if channel is None:
            return
        try:
            if embed is not None:
                await channel.send(embed=embed)
            elif text:
                await channel.send(text[:2000])
        except discord.HTTPException:
            logger.debug("Не удалось отправить лог в канал %s", getattr(channel, "id", "?"), exc_info=True)

    async def send_embed(self, guild: discord.Guild, embed: discord.Embed, *, category: str | None = None) -> None:
        cat = category or "general"
        text = _embed_to_text(embed)
        guild_name = guild.name if guild is not None else "?"
        self._emit(cat, f"[{guild_name}] {text}")
        await self._post(guild, cat, embed=embed)

    async def log_event(
        self,
        guild: discord.Guild,
        title: str,
        description: str | None = None,
        *,
        color: discord.Colour | None = None,
        author: discord.Member | discord.User | None = None,
    ) -> None:
        parts: list[str] = []
        if title:
            parts.append(title)
        if description:
            parts.append(description)
        if author is not None:
            parts.append(f"Инициатор: {author} ({author.id})")
        guild_name = guild.name if guild is not None else "?"
        text = f"[{guild_name}] " + (" | ".join(parts) if parts else "(пустое событие)")
        self._emit("general", text)
        await self._post(guild, "general", text=text)

    async def log_mod_action(
        self,
        guild: discord.Guild,
        action: str,
        target: discord.User | discord.Member,
        moderator: discord.Member,
        reason: str = "",
        description: str | None = None,
    ) -> None:
        parts: list[str] = []
        if description:
            parts.append(description)
        parts.append(f"Модерация: {action}")
        parts.append(f"Нарушитель: {target} ({target.id})")
        parts.append(f"Модератор: {moderator} ({moderator.id})")
        if reason:
            parts.append(f"Причина: {reason}")
        guild_name = guild.name if guild is not None else "?"
        text = f"[{guild_name}] " + " | ".join(parts)
        self._emit("mod", text)
        await self._post(guild, "mod", text=text)

    def _emit(self, category: str, text: str) -> None:
        """Пишет событие в логгер bot.audit.<category> — его ловит веб-лента панели."""
        try:
            _AUDIT_LOGGER.getChild(category).info(text)
        except Exception:
            logger.debug("Не удалось записать аудит-событие в ленту", exc_info=True)
