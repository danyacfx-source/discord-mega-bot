"""Сервис настроек серверов."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.db.settings_repository import _INT_COLUMNS

if TYPE_CHECKING:
    from app.core.bot import MegaBot
    from app.db.settings_repository import SettingsRepository


class SettingsService:
    def __init__(self, repo: SettingsRepository) -> None:
        self._repo = repo

    async def ensure_all_guilds(self, bot: MegaBot) -> None:
        for guild in bot.guilds:
            await self._repo.ensure_row(guild.id)

    async def get(self, guild_id: int) -> dict[str, Any]:
        settings = await self._repo.get(guild_id)
        for column in _INT_COLUMNS:
            raw = settings.get(column)
            settings[column] = int(raw) if raw else None
        settings["automod_enabled"] = bool(settings.get("automod_enabled"))
        return settings

    async def update(self, guild_id: int, **kwargs: Any) -> None:
        for column, value in kwargs.items():
            if value is not None:
                await self._repo.set(guild_id, column, value)

    async def blocked_words(self, guild_id: int) -> list[str]:
        settings = await self._repo.get(guild_id)
        try:
            return list(json.loads(settings.get("blocked_words") or "[]"))
        except (TypeError, json.JSONDecodeError):
            return []

    async def add_blocked_word(self, guild_id: int, word: str) -> list[str]:
        words = await self.blocked_words(guild_id)
        normalized = word.strip().lower()
        if normalized and normalized not in words:
            words.append(normalized)
            await self._repo.set(guild_id, "blocked_words", json.dumps(words, ensure_ascii=False))
        return words

    async def remove_blocked_word(self, guild_id: int, word: str) -> list[str]:
        words = await self.blocked_words(guild_id)
        normalized = word.strip().lower()
        if normalized in words:
            words.remove(normalized)
            await self._repo.set(guild_id, "blocked_words", json.dumps(words, ensure_ascii=False))
        return words
