"""Сервис Kick: статус стрима (публичный API v2) и модерация (Dev API v1)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import aiohttp

from app.core.api_client import ApiClient, ApiRequestError

if TYPE_CHECKING:
    from app.config import Config
    from app.db.kv_repository import KvRepository

logger = logging.getLogger("bot.services")

_PUBLIC_BASE = "https://kick.com/api/v2"
_DEV_BASE = "https://api.kick.com/public/v1"  # https://docs.kick.com/reference/


def _first_viewer_count(*values: Any) -> int:
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return 0


class KickService:
    def __init__(self, repo: KvRepository, config: Config) -> None:
        self._repo = repo
        self._config = config
        self._http = ApiClient(
            "Kick",
            timeout=config.api_timeout_seconds,
            user_agent="DiscordMegaBot/3.3 Kick",
            proxy=config.api_proxy,
            max_concurrency=config.api_max_concurrency,
            circuit_failure_threshold=config.api_circuit_failure_threshold,
            circuit_reset_seconds=config.api_circuit_reset_seconds,
        )
        self._broadcaster: dict[str, Any] | None = None

    @property
    def session(self) -> aiohttp.ClientSession:
        return self._http.session

    async def aclose(self) -> None:
        await self._http.close()

    # ------------------------------------------------------------------ стримы

    async def channel_status(self, slug: str) -> dict[str, Any] | None:
        """Статус канала: None — офлайн, иначе dict с полями стрима."""
        try:
            status, body, _ = await self._http.json(
                "GET", f"{_PUBLIC_BASE}/channels/{slug}", acceptable=(200, 404)
            )
            if status == 404:
                return None
        except ApiRequestError:
            logger.exception("Kick: сеть при статусе канала %s", slug)
            return None
        live = body.get("livestream") if isinstance(body, dict) else None
        if not isinstance(live, dict) or not live.get("is_live"):
            return None
        categories = live.get("categories") or []
        category = categories[0].get("name") if categories and isinstance(categories[0], dict) else None
        thumbnail = live.get("thumbnail") or {}
        return {
            "slug": slug,
            "title": live.get("session_title") or live.get("title") or "Без названия",
            "viewers": _first_viewer_count(live.get("viewer_count"), live.get("viewers"), body.get("viewer_count")),
            "category": category or "—",
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
            status, body, _ = await self._http.json(
                "GET", f"{_PUBLIC_BASE}/users/{username}", acceptable=(200, 404)
            )
            body = body if status == 200 else None
            if isinstance(body, dict) and isinstance(body.get("id"), int):
                return {"id": int(body["id"]), "username": body.get("username") or username}
            status, body, _ = await self._http.json(
                "GET",
                f"{_PUBLIC_BASE}/search",
                params={"q": username, "type": "users"},
                acceptable=(200, 404),
            )
            body = body if status == 200 else None
            if isinstance(body, dict):
                for user in body.get("users") or []:
                    if str(user.get("username", "")).lower() == username.lower():
                        return {"id": int(user["id"]), "username": user.get("username", username)}
                if body.get("users"):
                    user = body["users"][0]
                    return {"id": int(user["id"]), "username": user.get("username", username)}
        except (ApiRequestError, TypeError, ValueError, KeyError):
            logger.exception("Kick: не удалось найти пользователя %s", username)
        return None

    async def resolve_broadcaster(self) -> dict[str, Any] | None:
        """Определяет текущего пользователя токена (вещателя) через GET /users.

        Как в Node ``kick_mod.js`` getBroadcaster: токен должен быть от личного
        аккаунта, ответ может быть списком или одиночным объектом.
        """
        if self._broadcaster is not None:
            return self._broadcaster
        try:
            _, body, _ = await self._http.json("GET", f"{_DEV_BASE}/users", headers=self._headers())
        except (ApiRequestError, ValueError):
            logger.exception("Kick: ошибка запроса вещателя")
            return None
        me = (body or {}).pop("data", None) if isinstance(body, dict) else body
        if isinstance(me, list):
            me = me[0] if me else None
        if not isinstance(me, dict) or not me.get("user_id"):
            logger.warning("Kick: ответ /users без user_id — токен должен быть от личного аккаунта")
            return None
        self._broadcaster = {
            "user_id": int(me["user_id"]),
            "name": str(me.get("name") or me.get("username") or ""),
        }
        return self._broadcaster

    async def resolve_chatroom_id(self, slug: str, retries: int = 3) -> int | None:
        """Определяет id чатрума канала через GET /api/v2/channels/{slug}/chatroom."""
        try:
            _, body, _ = await self._http.json(
                "GET", f"{_PUBLIC_BASE}/channels/{slug}/chatroom", attempts=retries
            )
            if isinstance(body, dict) and body.get("id"):
                return int(body["id"])
            raise ValueError("в ответе нет id")
        except (ApiRequestError, TypeError, ValueError) as exc:
            logger.error("Kick: не удалось получить chatroom канала %s: %s", slug, exc)
        return None

    async def delete_message(self, message_id: int | str) -> bool:
        """Удаляет сообщение из чата Kick (Dev API)."""
        try:
            async with self.session.delete(f"{_DEV_BASE}/chat/{message_id}", headers=self._headers()) as response:
                return response.status in (200, 204)
        except aiohttp.ClientError:
            logger.exception("Kick: не удалось удалить сообщение %s", message_id)
            return False

    async def ban(self, user_id: int, *, minutes: int | None = None, reason: str = "") -> bool:
        """Бан/таймаут пользователя в чате через POST /moderation/bans (как Node kick_mod.js)."""
        broadcaster = await self.resolve_broadcaster()
        if broadcaster is None:
            return False
        payload: dict[str, Any] = {
            "broadcaster_user_id": broadcaster["user_id"],
            "user_id": user_id,
            "reason": (reason or "")[:100],
        }
        if minutes is not None:
            payload["duration"] = minutes
        try:
            async with self.session.post(f"{_DEV_BASE}/moderation/bans", json=payload, headers=self._headers()) as response:
                ok = response.status in (200, 201, 204)
                if not ok:
                    logger.warning("Kick: бан %s вернул HTTP %s", user_id, response.status)
                return ok
        except aiohttp.ClientError:
            logger.exception("Kick: ошибка бана пользователя %s", user_id)
            return False

    async def unban(self, user_id: int) -> bool:
        """Снимает бан/таймаут через DELETE /moderation/bans."""
        broadcaster = await self.resolve_broadcaster()
        if broadcaster is None:
            return False
        try:
            async with self.session.delete(
                f"{_DEV_BASE}/moderation/bans",
                json={"broadcaster_user_id": broadcaster["user_id"], "user_id": user_id},
                headers=self._headers(),
            ) as response:
                return response.status in (200, 204)
        except aiohttp.ClientError:
            logger.exception("Kick: ошибка разбана пользователя %s", user_id)
            return False
