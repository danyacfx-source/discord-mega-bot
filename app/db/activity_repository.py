"""Почасовая активность гильдий: сколько сообщений в каждом часе."""
from __future__ import annotations

from typing import Any

from app.db.base_repository import BaseRepository


class ActivityRepository(BaseRepository):
    async def increment(self, guild_id: int, bucket: str, amount: int = 1) -> None:
        await self.db.execute(
            """
            INSERT INTO activity_hourly(guild_id, bucket, messages)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, bucket) DO UPDATE SET
                messages = activity_hourly.messages + excluded.messages
            """,
            (guild_id, bucket, max(1, amount)),
        )

    async def list_hourly(self, guild_id: int, limit: int = 1000) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            """
            SELECT bucket, messages
            FROM activity_hourly
            WHERE guild_id = ?
            ORDER BY bucket DESC
            LIMIT ?
            """,
            (guild_id, max(1, min(limit, 5000))),
        )
        return [dict(row) for row in rows]
