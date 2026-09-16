"""Сервис Kick: статус стрима (публичный API v2) и модерация (Dev API v1)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import aiohttp

if TYPE_CHECKING:
    from app.config import Config
    from app.data.kv_repository import KvRepository

logger = logging.getLogger("bot.services")

_PUBLIC_BASE = "https://kick.com/api/v2"
_DEV_BASE = "https://api.kick.com/public/v1"


class KickService:
    def __init__(self, repo: KvRepository, config: Config) -> None:
        self._repo = repo
        self._config = config
        self._session: aiohttp.ClientSession | None = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def aclose(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------ стримы

    async def channel_status(self, slug: str) -> dict[str, Any] | None:
        """Статус канала: None — офлайн, иначе dict с полями стрима."""
        try:
            async with self.session.get(f"{_PUBLIC_BASE}/channels/{slug}") as response:
                if response.status != 200:
                    logger.warning("Kick %s: статус %s", slug, response.status)
                    return None
                body = await response.json(content_type=None)
        except aiohttp.ClientError:
            logger.exception("Kick: сеть при статусе канала %s", slug)
            return None
        live = body.get("livestream") if isinstance(body, dict) else None
        if not isinstance(live, dict) or not live.get("is_live"):
            return None
        category = live.get("category") or {}
        thumbnail = live.get("thumbnail") or {}
        return {
            "slug": slug,
            "title": live.get("session_title") or live.get("title") or "Без названия",
            "viewers": int(live.get("viewers") or 0),
            "category": category.get("name") or "—",
            "started_at": live.get("created_at"),
            "thumbnail": thumbnail.get("url"),
        }

    # ------------------------------------------------------------------ sticky

    @staticmethod
    def _sticky_key() -> str:
        return "kick:sticky"

    async def sticky_message_id(self) -> int | None:
        raw = await self._repo.get(self._sticky_key())
        return int(raw) if raw and raw.isdigit() else None

    async def set_sticky_message(self, message_id: int) -> None:
        await self._repo.set(self._sticky_key(), str(message_id))

    async def clear_sticky_message(self) -> None:
        await self._repo.delete(self._sticky_key())

    # ------------------------------------------------------------------ модерация

    def _headers(self) -> dict[str, str]:
        token = self._config.kick_access_token
        return {"Authorization": f"Bearer {token}"} if token else {}

    async def resolve_user(self, username: str) -> dict[str, Any] | None:
        """Ищет Kick-пользователя по нику: id и нормализованный username."""
        username = username.strip().lstrip("@")
        try:
            async with self.session.get(f"{_PUBLIC_BASE}/users/{username}") as response:
                body = await response.json(content_type=None) if response.status == 200 else None
            if isinstance(body, dict) and isinstance(body.get("id"), int):
                return {"id": int(body["id"]), "username": body.get("username") or username}
            async with self.session.get(f"{_PUBLIC_BASE}/search", params={"q": username, "type": "users"}) as response:
                body = await response.json(content_type=None) if response.status == 200 else None
            if isinstance(body, dict):
                for user in body.get("users") or []:
                    if str(user.get("username", "")).lower() == username.lower():
                        return {"id": int(user["id"]), "username": user.get("username", username)}
                if body.get("users"):
                    user = body["users"][0]
                    return {"id": int(user["id"]), "username": user.get("username", username)}
        except (aiohttp.ClientError, TypeError, ValueError, KeyError):
            logger.exception("Kick: не удалось найти пользователя %s", username)
        return None

    async def ban(self, channel_id: int, user_id: int, *, minutes: int | None = None, reason: str = "") -> bool:
        return await self._moderate("ban", channel_id, user_id, minutes=minutes, reason=reason)

    async def unban(self, channel_id: int, user_id: int) -> bool:
        url = f"{_DEV_BASE}/channels/{channel_id}/users/{user_id}/ban"
        try:
            async with self.session.delete(url, headers=self._headers()) as response:
                return response.status in (200, 204)
        except aiohttp.ClientError:
            logger.exception("Kick: ошибка разбана пользователя %s", user_id)
            return False

    async def _moderate(
        self,
        action: str,
        channel_id: int,
        user_id: int,
        *,
        minutes: int | None,
        reason: str,
    ) -> bool:
        url = f"{_DEV_BASE}/channels/{channel_id}/users/{user_id}/ban"
        payload: dict[str, Any] = {"reason": reason or ""}
        if minutes is not None:
            payload["banned_duration"] = minutes * 60
        try:
            async with self.session.post(url, json=payload, headers=self._headers()) as response:
                ok = response.status in (200, 201, 204)
                if not ok:
                    logger.warning("Kick %s %s/%s: статус %s", action, channel_id, user_id, response.status)
                return ok
        except aiohttp.ClientError:
            logger.exception("Kick: ошибка %s пользователя %s", action, user_id)
            return False
