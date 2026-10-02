"""Монеты чата стримов: платформа + ник → баланс и счётчик сообщений."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.db.base_repository import BaseRepository


class ChatCoinsRepository(BaseRepository):
    async def get(self, platform: str, username: str) -> dict[str, Any] | None:
        row = await self.db.fetchone(
            "SELECT username, display_name, coins, messages FROM chat_coins "
            "WHERE platform = ? AND username = ?",
            (platform, username),
        )
        return dict(row) if row else None

    async def add(
        self, platform: str, username: str, display_name: str, amount: int, *, count_message: bool = False
    ) -> int:
        """Начисляет монеты (upsert) и возвращает новый баланс."""
        now = datetime.now(UTC).isoformat()
        row = await self.db.execute_returning(
            "INSERT INTO chat_coins (platform, username, display_name, coins, messages, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(platform, username) DO UPDATE SET "
            "coins = chat_coins.coins + excluded.coins, "
            "messages = chat_coins.messages + excluded.messages, "
            "display_name = excluded.display_name, "
            "updated_at = excluded.updated_at "
            "RETURNING coins",
            (
                platform,
                username,
                display_name,
                amount,
                1 if count_message else 0,
                now,
            ),
        )
        return int(row["coins"]) if row else amount

    async def spend(
        self, platform: str, username: str, display_name: str, amount: int
    ) -> int | None:
        """Списывает сумму; None — если баланса не хватает (атомарно)."""
        now = datetime.now(UTC).isoformat()
        await self.db.execute(
            "INSERT INTO chat_coins (platform, username, display_name, coins, messages, updated_at) "
            "VALUES (?, ?, ?, ?, 0, ?) ON CONFLICT(platform, username) DO NOTHING",
            (platform, username, display_name, max(0, -amount), now),
        )
        cursor = await self.db.execute(
            "UPDATE chat_coins SET coins = coins - ?, updated_at = ? "
            "WHERE platform = ? AND username = ? AND coins >= ?",
            (amount, now, platform, username, amount),
        )
        if cursor.rowcount <= 0:
            return None
        row = await self.db.fetchone(
            "SELECT coins FROM chat_coins WHERE platform = ? AND username = ?",
            (platform, username),
        )
        return int(row["coins"]) if row else None

    async def top(self, platform: str, limit: int = 10) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            "SELECT username, display_name, coins, messages FROM chat_coins "
            "WHERE platform = ? ORDER BY coins DESC LIMIT ?",
            (platform, limit),
        )
        return [dict(row) for row in rows]
