"""Репозиторий настроек серверов."""
from __future__ import annotations

from typing import Any

from app.db.base_repository import BaseRepository

DEFAULT_SETTINGS: dict[str, Any] = {
    "welcome_channel_id": None,
    "farewell_channel_id": None,
    "log_channel_id": None,
    "ticket_category_id": None,
    "member_log_channel_id": None,
    "message_log_channel_id": None,
    "voice_log_channel_id": None,
    "mod_log_channel_id": None,
    "bot_log_channel_id": None,
    "donation_channel_id": None,
    "automod_enabled": 1,
    "blocked_words": "[]",
    "ticket_panel_title": "Поддержка",
    "ticket_panel_description": "Нажмите на кнопку, чтобы открыть тикет.",
    "ticket_panel_footer": "Тикеты помогают решать личные вопросы без шума в каналах.",
    "ticket_open_label": "Открыть тикет",
    "ticket_open_emoji": "🎫",
    "ticket_intro_title": "Новый тикет",
    "ticket_intro_description": "Опишите свою проблему, {member}.",
    "ticket_intro_footer": "Нажмите кнопку ниже, чтобы закрыть тикет по завершении.",
    "ticket_close_label": "Закрыть тикет",
    "ticket_close_emoji": "🔒",
    "ticket_channel_prefix": "ticket",
}

_INT_COLUMNS = (
    "welcome_channel_id",
    "farewell_channel_id",
    "log_channel_id",
    "ticket_category_id",
    "member_log_channel_id",
    "message_log_channel_id",
    "voice_log_channel_id",
    "mod_log_channel_id",
    "bot_log_channel_id",
    "donation_channel_id",
)


class SettingsRepository(BaseRepository):
    async def ensure_row(self, guild_id: int) -> None:
        await self.db.execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,))

    async def get(self, guild_id: int) -> dict[str, Any]:
        row = await self.db.fetchone("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
        if row is None:
            await self.ensure_row(guild_id)
            row = await self.db.fetchone("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
        assert row is not None
        data = dict(row)
        for column, default in DEFAULT_SETTINGS.items():
            data.setdefault(column, default)
        for column, default in DEFAULT_SETTINGS.items():
            if data.get(column) is None and default is not None:
                data[column] = default
        return data

    async def set(self, guild_id: int, column: str, value: Any) -> None:
        if column not in DEFAULT_SETTINGS:
            raise ValueError(f"Неизвестная колонка настроек: {column}")
        await self.ensure_row(guild_id)
        await self.db.execute(f"UPDATE guild_settings SET {column} = ? WHERE guild_id = ?", (value, guild_id))

    async def set_defaults_missing(self, guild_id: int) -> dict[str, Any]:
        current = await self.get(guild_id)
        updates: list[tuple[Any, str]] = []
        for column, default in DEFAULT_SETTINGS.items():
            if current.get(column) is None and default is not None:
                updates.append((default, column))
        for value, column in updates:
            await self.set(guild_id, column, value)
        return await self.get(guild_id)
