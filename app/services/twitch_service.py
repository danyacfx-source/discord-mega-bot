"""Сервис Twitch: статус стрима канала через Helix (client_credentials) или анонимный GQL."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import aiohttp

from app.core.api_client import ApiClient, ApiRequestError
from app.services.stream_archive import StreamArchiveStore, parse_dt
from app.services.stream_rsvp import StreamRsvpStore
from app.services.stream_session import StreamSessionStore
from app.services.viewer_sessions import ViewerSessionStore

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
            max_concurrency=config.api_max_concurrency,
            circuit_failure_threshold=config.api_circuit_failure_threshold,
            circuit_reset_seconds=config.api_circuit_reset_seconds,
        )
        self._token: str | None = None
        self._token_expires: datetime = datetime.now(UTC)
        self._user_token: str | None = None
        self._user_token_expires: datetime = datetime.now(UTC)
        self._user_refresh: str | None = config.twitch_refresh_token

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
            "user_id": str(stream.get("user_id") or ""),
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

    # ------------------------------------------------------------------ VOD

    async def latest_vod_url(self, login: str, user_id: str | None = None) -> str | None:
        """URL последнего архива стрима (Helix /videos, type=archive).

        Без TWITCH_CLIENT_ID/SECRET или user_id — None: вызывающий откатывается
        на страницу ``/videos`` канала.
        """
        config = self._config
        if not (config.twitch_client_id and config.twitch_client_secret):
            return None
        try:
            if not user_id:
                user_id = await self._helix_user_id(login)
            if not user_id:
                return None
            token = await self._access_token()
            headers = {"Client-ID": config.twitch_client_id or "", "Authorization": f"Bearer {token}"}
            async with self.session.get(
                "https://api.twitch.tv/helix/videos",
                params={"user_id": user_id, "type": "archive", "sort": "time", "first": "1"},
                headers=headers,
            ) as response:
                if response.status != 200:
                    logger.debug("Twitch %s: Helix videos вернул статус %d", login, response.status)
                    return None
                body = await response.json(content_type=None)
        except (ApiRequestError, RuntimeError):
            logger.debug("Twitch %s: не удалось получить VOD", login, exc_info=True)
            return None
        videos = (body or {}).get("data") or []
        return videos[0].get("url") if videos else None

    async def _helix_user_id(self, login: str) -> str | None:
        config = self._config
        if not (config.twitch_client_id and config.twitch_client_secret):
            return None
        try:
            token = await self._access_token()
            headers = {"Client-ID": config.twitch_client_id or "", "Authorization": f"Bearer {token}"}
            async with self.session.get(
                "https://api.twitch.tv/helix/users", params={"login": login}, headers=headers
            ) as response:
                if response.status != 200:
                    return None
                body = await response.json(content_type=None)
        except (ApiRequestError, RuntimeError):
            return None
        users = (body or {}).get("data") or []
        return str(users[0]["id"]) if users else None

    # -------------------------------------------------------------- schedule

    async def schedule(self, login: str, *, limit: int = 5) -> list[dict[str, Any]] | None:
        """Ближайшие сегменты расписания канала (Helix /schedule, app-токен).

        Возвращает будущие эфиры, отсортированные по времени; ``[]`` —
        расписание пусто; ``None`` — нет кредов или API недоступен.
        """
        config = self._config
        if not (config.twitch_client_id and config.twitch_client_secret):
            return None
        try:
            user_id = await self._helix_user_id(login)
            if not user_id:
                return None
            token = await self._access_token()
            headers = {"Client-ID": config.twitch_client_id or "", "Authorization": f"Bearer {token}"}
            async with self.session.get(
                "https://api.twitch.tv/helix/schedule",
                params={"broadcaster_id": user_id},
                headers=headers,
            ) as response:
                if response.status != 200:
                    logger.debug("Twitch %s: Helix schedule вернул статус %d", login, response.status)
                    return None
                body = await response.json(content_type=None)
        except (ApiRequestError, RuntimeError):
            logger.debug("Twitch: не удалось получить расписание %s", login, exc_info=True)
            return None
        segments = ((body or {}).get("data") or {}).get("segments") or []
        return _parse_schedule(segments, limit=limit)

    # ------------------------------------------------------------------ clips

    async def create_clip(self, login: str, *, title: str | None = None) -> str | None:
        """Создаёт клип с живого стрима (Helix clips, user-токен). None — не удалось.

        Токен берётся из TWITCH_REFRESH_TOKEN (scope ``clips:edit``) и обновляется
        автоматически; без кредов или после неуспешного 401-ретрая — None.
        """
        config = self._config
        if not (config.twitch_client_id and config.twitch_client_secret and config.twitch_refresh_token):
            return None
        user_id = await self._helix_user_id(login)
        if not user_id:
            return None
        params: dict[str, Any] = {"broadcaster_id": user_id}
        if title:
            params["title"] = title[:140]
        client_headers = {"Client-ID": config.twitch_client_id or ""}
        for attempt in range(2):
            token = await self._user_access_token(force=attempt == 1)
            if not token:
                return None
            try:
                status, body, _ = await self._http.json(
                    "POST",
                    "https://api.twitch.tv/helix/clips",
                    attempts=1,
                    acceptable=(200, 401),
                    params=params,
                    headers={**client_headers, "Authorization": f"Bearer {token}"},
                )
            except ApiRequestError:
                logger.debug("Twitch: не удалось создать клип %s", login, exc_info=True)
                return None
            if status == 200:
                clips = (body or {}).get("data") or []
                return str(clips[0].get("url")) if clips else None
        logger.debug("Twitch: Helix clips 401 для %s даже после обновления токена", login)
        return None

    async def _user_access_token(self, *, force: bool = False) -> str | None:
        """User-токен через refresh_token; кэш в памяти, авторефреш по истечении."""
        config = self._config
        if not (config.twitch_client_id and config.twitch_client_secret and config.twitch_refresh_token):
            return None
        now = datetime.now(UTC)
        if not force and self._user_token and self._user_token_expires > now + timedelta(minutes=2):
            return self._user_token
        try:
            _, body, _ = await self._http.json(
                "POST",
                _TOKEN_URL,
                attempts=2,
                data={
                    "client_id": config.twitch_client_id,
                    "client_secret": config.twitch_client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": self._user_refresh or config.twitch_refresh_token,
                },
            )
        except ApiRequestError:
            logger.debug("Twitch: не удалось обновить user-токен", exc_info=True)
            return None
        body = body or {}
        self._user_token = str(body.get("access_token") or "")
        self._user_refresh = str(body.get("refresh_token") or self._user_refresh or config.twitch_refresh_token)
        self._user_token_expires = now + timedelta(seconds=int(body.get("expires_in") or 14400))
        return self._user_token or None

    # ------------------------------------------------------------------ sticky

    def session_store(self, login: str) -> StreamSessionStore:
        """Хранилище сессии стрима (пик зрителей, метаданные) для карточек."""
        return StreamSessionStore(self._repo, f"stream:session:twitch:{login.lower()}")

    def rsvp_store(self, login: str) -> StreamRsvpStore:
        """Хранилище id старт-анонса для команды /stream_rsvp."""
        return StreamRsvpStore(self._repo, f"stream:rsvp:twitch:{login.lower()}")

    def viewer_store(self) -> ViewerSessionStore:
        """Онлайн-сессии зрителей чата (из IRC-сообщений, читает StreamChatCog)."""
        return ViewerSessionStore(self._repo, "stream:viewers:twitch")

    def archive_store(self, login: str) -> StreamArchiveStore:
        """Архив завершённых эфиров канала для /stream_stats."""
        return StreamArchiveStore(self._repo, f"stream:archive:twitch:{login.lower()}")

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


def _parse_schedule(segments: list[Any], *, limit: int, now: datetime | None = None) -> list[dict[str, Any]]:
    """Будущие сегменты расписания, отсортированные по старту, без прошедших."""
    moment = now or datetime.now(UTC)
    parsed: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start = parse_dt(segment.get("start_time"))
        end = parse_dt(segment.get("end_time"))
        if start is None:
            continue
        if end is None or end < moment:
            continue
        category = segment.get("category")
        parsed.append(
            {
                "start_time": start,
                "end_time": end,
                "title": str(segment.get("title") or "Без названия"),
                "category": str(category.get("name") or "") if isinstance(category, dict) else "",
                "url": str(segment.get("url") or ""),
            }
        )
    parsed.sort(key=lambda item: item["start_time"])
    return parsed[: max(1, limit)]
