"""Сервис Twitch: статус стрима канала через Helix (client_credentials) или анонимный GQL."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import aiohttp

from app.core.api_client import ApiClient, ApiRequestError

if TYPE_CHECKING:
    from app.config import Config
    from app.db.kv_repository import KvRepository

logger = logging.getLogger("bot.services")

_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_STREAMS_URL = "https://api.twitch.tv/helix/streams"
_GQL_URL = "https://gql.twitch.tv/gql"
_GQL_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
_GQL_STREAM_QUERY = """
query Stream($login: String!) {
  user(login: $login) {
    stream {
      id
      title
      viewersCount
      createdAt
      game {
        name
      }
      previewImageURL
    }
  }
}
"""


class TwitchService:
    def __init__(self, repo: KvRepository, config: Config) -> None:
        self._repo = repo
        self._config = config
        self._http = ApiClient(
            "Twitch",
            timeout=config.api_timeout_seconds,
            user_agent="DiscordMegaBot/3.3 Twitch",
            proxy=config.api_proxy,
        )
        self._token: str | None = None
        self._token_expires: datetime = datetime.now(UTC)

    @property
    def session(self) -> aiohttp.ClientSession:
        return self._http.session

    async def aclose(self) -> None:
        await self._http.close()

    async def _access_token(self) -> str:
        config = self._config
        if self._token and self._token_expires > datetime.now(UTC) + timedelta(minutes=5):
            return self._token
        if not (config.twitch_client_id and config.twitch_client_secret):
            raise RuntimeError("Twitch: не настроены TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET")
        try:
            _, body, _ = await self._http.json(
                "POST",
                _TOKEN_URL,
                attempts=2,
                data={
                    "client_id": config.twitch_client_id,
                    "client_secret": config.twitch_client_secret,
                    "grant_type": "client_credentials",
                },
            )
        except ApiRequestError as exc:
            raise RuntimeError(f"Twitch: сеть при получении токена ({exc})") from exc
        self._token = body["access_token"]
        self._token_expires = datetime.now(UTC) + timedelta(seconds=int(body.get("expires_in", 3600)))
        return self._token

    async def channel_status(self, login: str) -> dict[str, Any] | None:
        """Статус канала: None — офлайн, иначе dict с полями стрима.

        Как на Node twitch.js: сначала Helix (нужны client_id/secret), при ошибке
        или отсутствии кредов — анонимный публичный GraphQL Twitch.
        """
        helix = await self._helix_status(login)
        if helix is not None:
            return helix
        try:
            return await self._gql_status(login)
        except ApiRequestError:
            logger.warning("Twitch: GQL временно недоступен для %s", login, exc_info=True)
            return None

    async def _helix_status(self, login: str) -> dict[str, Any] | None:
        config = self._config
        if not (config.twitch_client_id and config.twitch_client_secret):
            return None
        try:
            token = await self._access_token()
            headers = {"Client-ID": config.twitch_client_id or "", "Authorization": f"Bearer {token}"}
            async with self.session.get(_STREAMS_URL, params={"user_login": login}, headers=headers) as response:
                if response.status != 200:
                    logger.warning("Twitch %s: Helix вернул статус %d", login, response.status)
                    return None
                body = await response.json(content_type=None)
        except (ApiRequestError, RuntimeError):
            logger.exception("Twitch: не удалось получить статус канала %s (Helix)", login)
            return None
        streams = (body or {}).get("data") or []
        if not streams:
            return None
        stream = streams[0]
        return {
            "login": stream.get("user_login", login),
            "title": stream.get("title") or "Без названия",
            "viewers": int(stream.get("viewer_count") or 0),
            "category": stream.get("game_name") or "—",
            "started_at": stream.get("started_at"),
            "thumbnail": (stream.get("thumbnail_url") or "").replace("{width}x{height}", "640x360"),
        }

    async def _gql_status(self, login: str) -> dict[str, Any] | None:
        payload = [
            {
                "query": _GQL_STREAM_QUERY,
                "variables": {"login": login},
            }
        ]
        _, body, _ = await self._http.json(
            "POST",
            _GQL_URL,
            attempts=2,
            json=payload,
            headers={"Client-Id": _GQL_CLIENT_ID},
        )
        stream = ((body or [{}])[0].get("data") or {}).get("user") or {}
        live = (stream.get("stream") or {}) if stream.get("stream") else None
        if not live:
            return None
        return {
            "login": login,
            "title": live.get("title") or "Без названия",
            "viewers": int(live.get("viewersCount") or 0),
            "category": (live.get("game") or {}).get("name") or "—",
            "started_at": live.get("createdAt"),
            "thumbnail": live.get("previewImageURL") or "",
        }

    # ------------------------------------------------------------------ sticky

    @staticmethod
    def _sticky_key(login: str) -> str:
        return f"twitch:sticky:{login.lower()}"

    async def sticky_message_id(self, login: str) -> int | None:
        raw = await self._repo.get(self._sticky_key(login))
        return int(raw) if raw and raw.isdigit() else None

    async def set_sticky_message(self, login: str, message_id: int) -> None:
        await self._repo.set(self._sticky_key(login), str(message_id))

    async def clear_sticky_message(self, login: str) -> None:
        await self._repo.delete(self._sticky_key(login))
