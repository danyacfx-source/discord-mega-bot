"""Авто-модерация как на Node automod.js (спам/слова/ссылки/капс/растяжки)."""
from __future__ import annotations

import logging
import re
import time
from datetime import timedelta
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from app.core.base import MegaCog
from app.services.settings_service import SettingsService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")

_INVITE_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_HOST_RE = re.compile(r"//(?:www\.)?([^/]+)", re.IGNORECASE)
_STRETCH_RE = re.compile(r"(.)\1{5,}", re.IGNORECASE)

_SPAM_WINDOW = 5.0


def _normalized_allowed_links(raw: str) -> list[str]:
    hosts: list[str] = []
    for link in (part.strip().lower() for part in raw.split(",") if part.strip()):
        host = link
        if host.startswith(("http://", "https://")):
            host = re.sub(r"^https?://", "", host)
        host = host.rstrip("/").split(":")[0]
        if host:
            hosts.append(host)
    return hosts


def _blocked_link_host(content: str, allowed_hosts: list[str]) -> str | None:
    for match in _INVITE_URL_RE.findall(content):
        host_match = _HOST_RE.search(match)
        if not host_match:
            continue
        host = host_match.group(1).strip().split(":")[0].split("?")[0].split("#")[0].rstrip(".")
        if not host:
            continue
        if not any(host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts):
            return host
    return None


def _is_caps(content: str, threshold: float = 0.8, min_len: int = 12) -> bool:
    if len(content) < min_len:
        return False
    stripped = _INVITE_URL_RE.sub("", content)
    alpha = re.sub(r"[^a-zA-Zа-яА-ЯёЁ]", "", stripped)
    if len(alpha) < min_len:
        return False
    upper = sum(1 for ch in alpha if ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
    return upper / len(alpha) >= threshold if alpha else False


def _is_stretched(content: str) -> bool:
    return bool(_STRETCH_RE.search(content))


class AutoModCog(MegaCog, name="AutoMod"):
    def __init__(self, bot: MegaBot, settings: SettingsService) -> None:
        super().__init__(bot)
        self.settings = settings
        self._messages: dict[int, list[float]] = {}
        self._timeout_counts: dict[int, list[float]] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not self.bot.config.automod_enabled:
            return
        if message.author.bot or message.guild is None or isinstance(message.channel, discord.DMChannel):
            return

        settings = await self.settings.get(message.guild.id)
        if not settings.get("automod_enabled", True):
            return

        member = message.author
        if isinstance(member, discord.User):
            member = message.guild.get_member(member.id)
        if member is None or not isinstance(member, discord.Member):
            return
        if self._has_ignored_role(member):
            return
        if member.guild_permissions.manage_messages:
            return
        config = self.bot.config
        if message.channel.id in set(config.automod_ignored_channels):
            return

        self._track_spam(member.id)
        blocked_words = await self.settings.blocked_words(message.guild.id)
        reason = self._analyze(member.id, message.content or "", blocked_words)
        if not reason:
            return

        try:
            await message.delete()
        except discord.HTTPException:
            pass
        await self._punish(member, reason)
        channel_name = getattr(message.channel, "name", message.channel.id)
        logger.warning("Automod: %s в #%s: %s", message.author, channel_name, reason)

    def _has_ignored_role(self, member: discord.Member) -> bool:
        ignored = set(self.bot.config.automod_ignore_roles)
        return bool(ignored and any(role.name in ignored for role in member.roles))

    def _analyze(self, user_id: int, content: str, blocked_words: list[str] | None = None) -> str | None:
        if self._is_spam(user_id):
            return "спам"
        lowered = content.lower()

        banned: set[str] = {w.strip() for w in (blocked_words or []) if w and w.strip()}
        for raw in (self.bot.config.automod_banned_words or "").split(","):
            word = raw.strip()
            if word:
                banned.add(word)
        for word in banned:
            if word and word in lowered:
                return f"запрещённое слово: «{word}»"

        config = self.bot.config
        if config.automod_block_links:
            allowed = _normalized_allowed_links(config.automod_allowed_links)
            host = _blocked_link_host(lowered, allowed)
            if host:
                return f"ссылка на неразрешённый домен: {host}"
        if _is_caps(content, config.automod_caps_threshold, config.automod_caps_min_len):
            return "капс"
        if _is_stretched(content):
            return "растянутый спам"
        return None

    def _track_spam(self, user_id: int) -> None:
        now = time.monotonic()
        stamps = self._messages.setdefault(user_id, [])
        while stamps and now - stamps[0] > _SPAM_WINDOW:
            stamps.pop(0)
        stamps.append(now)
        while len(stamps) > 20:
            stamps.pop(0)

    def _is_spam(self, user_id: int) -> bool:
        max_in_window = self.bot.config.automod_max_messages_in_window
        if max_in_window <= 0:
            return False
        stamps = self._messages.get(user_id, [])
        now = time.monotonic()
        recent = [stamp for stamp in stamps if now - stamp <= _SPAM_WINDOW]
        return len(stamps) > max_in_window or len(recent) > max_in_window

    async def _punish(self, member: discord.Member, reason: str) -> None:
        config = self.bot.config
        duration = config.automod_timeout_seconds
        if duration > 0:
            try:
                await member.timeout(discord.utils.utcnow() + timedelta(seconds=duration), reason=f"Automod: {reason}")
            except discord.HTTPException:
                pass

        ban_after = config.automod_ban_after_timeouts
        if ban_after > 0:
            now = time.monotonic()
            window = config.automod_ban_window_seconds
            stamps = self._timeout_counts.setdefault(member.id, [])
            while stamps and now - stamps[0] > window:
                stamps.pop(0)
            stamps.append(now)
            if len(stamps) >= ban_after:
                try:
                    await member.ban(reason=f"Automod: {ban_after} нарушений за {window}с")
                    logger.warning("Automod: бан %s (%s)", member, reason)
                except discord.HTTPException:
                    pass
                stamps.clear()
