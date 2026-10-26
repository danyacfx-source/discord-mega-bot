"""Discord community idea board, persisted in the existing PostgreSQL/SQLite KV.

No new external tokens, Discord intents or database migrations are required.
All votes are keyed to Discord member IDs and survive container redeploys.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.kv_service import KvService

MAX_IDEAS = 200
SUBMISSION_COOLDOWN = 300
STATUSES = ("new", "review", "planned", "done", "declined")
STATUS_LABELS = {
    "new": "📨 Новая",
    "review": "🔎 На рассмотрении",
    "planned": "🗓️ В планах",
    "done": "✅ Реализовано",
    "declined": "❌ Отклонено",
}


class IdeaError(ValueError):
    pass


class IdeaBoardService:
    def __init__(self, kv: KvService) -> None:
        self._kv = kv
        self._lock = asyncio.Lock()

    @staticmethod
    def _index_key(guild_id: int) -> str:
        return f"community:ideas:v1:index:{guild_id}"

    @staticmethod
    def _item_key(guild_id: int, idea_id: str) -> str:
        return f"community:ideas:v1:item:{guild_id}:{idea_id.upper()}"

    @staticmethod
    def _message_key(guild_id: int, message_id: int) -> str:
        return f"community:ideas:v1:message:{guild_id}:{message_id}"

    @staticmethod
    def _cooldown_key(guild_id: int, user_id: int) -> str:
        return f"community:ideas:v1:cooldown:{guild_id}:{user_id}"

    async def _index(self, guild_id: int) -> list[str]:
        raw = await self._kv.get(self._index_key(guild_id))
        try:
            result = json.loads(raw) if raw else []
            return result if isinstance(result, list) else []
        except (ValueError, TypeError):
            return []

    async def _get(self, guild_id: int, idea_id: str) -> dict[str, Any] | None:
        if not idea_id or len(idea_id) != 8 or not all(c in "0123456789ABCDEF" for c in idea_id.upper()):
            return None
        raw = await self._kv.get(self._item_key(guild_id, idea_id))
        try:
            record = json.loads(raw) if raw else None
            return record if isinstance(record, dict) else None
        except (TypeError, ValueError):
            return None

    async def get(self, guild_id: int, idea_id: str) -> dict[str, Any] | None:
        return await self._get(guild_id, idea_id)

    @staticmethod
    def scores(record: dict[str, Any]) -> tuple[int, int]:
        votes = record.get("votes", {})
        return sum(v == 1 for v in votes.values()), sum(v == -1 for v in votes.values())

    async def create(self, guild_id: int, author_id: int, channel_id: int, text: str) -> dict[str, Any]:
        description = " ".join(text.split()) if isinstance(text, str) else ""
        if not 12 <= len(description) <= 400:
            raise IdeaError("Длина идеи — от 12 до 400 символов.")
        async with self._lock:
            index = await self._index(guild_id)
            if len(index) >= MAX_IDEAS:
                raise IdeaError("Доска заполнена. Попросите модератора удалить старые идеи.")
            now = time.time()
            last = await self._kv.get(self._cooldown_key(guild_id, author_id))
            if last:
                try:
                    left = SUBMISSION_COOLDOWN - (now - float(last))
                except (ValueError, OverflowError):
                    left = 0
                if left > 0:
                    raise IdeaError(f"Следующую идею можно отправить через {int(left) + 1} сек.")
            idea_id = secrets.token_hex(4).upper()
            while idea_id in index:
                idea_id = secrets.token_hex(4).upper()
            record: dict[str, Any] = {
                "id": idea_id,
                "guild_id": guild_id,
                "author_id": author_id,
                "channel_id": channel_id,
                "message_id": 0,
                "text": description,
                "status": "new",
                "votes": {},
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            await self._kv.set(self._item_key(guild_id, idea_id), json.dumps(record, ensure_ascii=False))
            await self._kv.set(self._index_key(guild_id), json.dumps([idea_id, *index]))
            await self._kv.set(self._cooldown_key(guild_id, author_id), str(now))
            return record

    async def bind(self, guild_id: int, idea_id: str, message_id: int) -> None:
        async with self._lock:
            record = await self._get(guild_id, idea_id)
            if record is None:
                raise IdeaError("Идея не найдена.")
            record["message_id"] = message_id
            await self._kv.set(self._item_key(guild_id, idea_id), json.dumps(record, ensure_ascii=False))
            await self._kv.set(self._message_key(guild_id, message_id), idea_id)

    async def by_message(self, guild_id: int, message_id: int) -> dict[str, Any] | None:
        idea_id = await self._kv.get(self._message_key(guild_id, message_id))
        return await self._get(guild_id, idea_id) if idea_id else None

    async def vote(self, guild_id: int, idea_id: str, user_id: int, direction: int) -> dict[str, Any]:
        if direction not in (-1, 1):
            raise IdeaError("Неизвестный тип голоса.")
        async with self._lock:
            record = await self._get(guild_id, idea_id)
            if record is None:
                raise IdeaError("Идея не найдена.")
            if record["status"] in {"done", "declined"}:
                raise IdeaError("Голосование по этой идее уже закрыто.")
            votes: dict[str, int] = record["votes"]
            user = str(user_id)
            if votes.get(user) == direction:
                del votes[user]  # Same button again removes the vote.
            else:
                votes[user] = direction
            await self._kv.set(self._item_key(guild_id, idea_id), json.dumps(record, ensure_ascii=False))
            return record

    async def status(self, guild_id: int, idea_id: str, status: str) -> dict[str, Any]:
        if status not in STATUSES:
            raise IdeaError("Неизвестный статус.")
        async with self._lock:
            record = await self._get(guild_id, idea_id)
            if record is None:
                raise IdeaError("Идея не найдена.")
            record["status"] = status
            await self._kv.set(self._item_key(guild_id, idea_id), json.dumps(record, ensure_ascii=False))
            return record

    async def list_ideas(self, guild_id: int, *, limit: int = 10, top: bool = False) -> list[dict[str, Any]]:
        ids = await self._index(guild_id)
        records = [await self._get(guild_id, idea_id) for idea_id in ids]
        items = [record for record in records if record is not None]
        if top:
            items.sort(key=lambda r: self.scores(r)[0] - self.scores(r)[1], reverse=True)
        return items[: max(1, min(20, limit))]

    async def remove(self, guild_id: int, idea_id: str) -> dict[str, Any]:
        async with self._lock:
            record = await self._get(guild_id, idea_id)
            if record is None:
                raise IdeaError("Идея не найдена.")
            ids = await self._index(guild_id)
            await self._kv.set(self._index_key(guild_id), json.dumps([x for x in ids if x != record["id"]]))
            if record["message_id"]:
                await self._kv.delete(self._message_key(guild_id, record["message_id"]))
            await self._kv.delete(self._item_key(guild_id, idea_id))
            return record
