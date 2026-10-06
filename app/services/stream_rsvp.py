"""Анонс стрима в KV: id поста «кто откликнулся» (реакция 🔔)."""
from __future__ import annotations

from typing import Any

from app.db.kv_repository import KvRepository

#: Роль «На стриме» — выдаётся за 🔔 под старт-анонсом.
RSVP_ROLE_NAME = "На стриме"


def resolve_rsvp_role(guild: Any, role_id: int | None = None) -> Any | None:
    """Роль RSVP по ``STREAM_RSVP_ROLE_ID``, иначе по имени «На стриме» (без учёта регистра).

    ``guild`` утинтипизирован — хелпер юзают и ког, и вебпанель без импорта discord.
    """
    if role_id:
        role = guild.get_role(role_id)
        if role is not None:
            return role
    wanted = RSVP_ROLE_NAME.casefold()
    return next(
        (role for role in getattr(guild, "roles", []) if str(getattr(role, "name", "")).casefold() == wanted),
        None,
    )


class StreamRsvpStore:
    """Хранит id старт-анонса стрима для команды /stream_rsvp."""

    def __init__(self, repo: KvRepository, key: str) -> None:
        self._repo = repo
        self._key = key
        self._granted_key = f"{key}:granted"

    async def save(self, message_id: int) -> None:
        await self._repo.set(self._key, str(message_id))

    async def add_granted(self, user_id: int) -> None:
        """Запоминает, кому выдана роль «На стриме» (снимется в конце эфира)."""
        raw = await self._repo.get(self._granted_key) or ""
        ids = {int(x) for x in raw.split(",") if x.strip().isdigit()}
        if user_id in ids:
            return
        ids.add(user_id)
        await self._repo.set(self._granted_key, ",".join(str(i) for i in sorted(ids)))

    async def granted_ids(self) -> list[int]:
        raw = await self._repo.get(self._granted_key) or ""
        return [int(x) for x in raw.split(",") if x.strip().isdigit()]

    async def clear_granted(self) -> None:
        await self._repo.delete(self._granted_key)

    async def message_id(self) -> int | None:
        raw = await self._repo.get(self._key)
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    async def clear(self) -> None:
        await self._repo.delete(self._key)
        await self.clear_granted()
