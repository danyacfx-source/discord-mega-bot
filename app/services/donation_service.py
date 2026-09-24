"""Сервис донатов DonationAlerts: поллинг API, OAuth refresh, персональные коды, подсчёт новых донатов."""
from __future__ import annotations

import json
import logging
import re
import secrets
import time
from typing import TYPE_CHECKING, Any

import aiohttp

from app.core.api_client import ApiClient, ApiRequestError

if TYPE_CHECKING:
    from app.config import Config
    from app.db.donations_repository import DonationsRepository
    from app.db.kv_repository import KvRepository

logger = logging.getLogger("bot.services")

_API_BASE = "https://www.donationalerts.com"
_TOKEN_URL = f"{_API_BASE}/oauth/token"
_DONATIONS_URL = f"{_API_BASE}/api/v1/alerts/donations"

_SPONSOR_MESSAGE_KEY = "sponsor_message_id"


class DonationService:
    def __init__(self, repo: DonationsRepository, kv: KvRepository, config: Config) -> None:
        self._repo = repo
        self._kv = kv
        self._config = config
        self._http = ApiClient(
            "DonationAlerts",
            timeout=config.api_timeout_seconds,
            user_agent="DiscordMegaBot/3.3 DonationAlerts",
            proxy=config.api_proxy,
        )
        self._token: str | None = config.donations_token

    @property
    def session(self) -> aiohttp.ClientSession:
        return self._http.session

    async def aclose(self) -> None:
        await self._http.close()

    async def _refresh_token(self) -> bool:
        config = self._config
        if not (config.donations_client_id and config.donations_refresh_token):
            return False
        try:
            _, body, _ = await self._http.json(
                "POST",
                _TOKEN_URL,
                attempts=2,
                data={
                    "grant_type": "refresh_token",
                    "client_id": config.donations_client_id,
                    "refresh_token": config.donations_refresh_token,
                },
            )
        except ApiRequestError:
            logger.exception("DonationAlerts: сеть при обновлении токена")
            return False
        token = body.get("access_token")
        if not token:
            return False
        self._token = token
        logger.info("DonationAlerts: токен обновлён")
        return True

    async def fetch_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        """Возвращает последние донаты (без фильтрации), либо [] при отсутствии токена."""
        if not self._token:
            return []
        for attempt in (1, 2):
            try:
                status, body, _ = await self._http.json(
                    "GET",
                    _DONATIONS_URL,
                    attempts=2,
                    acceptable=(200, 401),
                    params={"limit": limit},
                    headers={"Authorization": f"Bearer {self._token}"},
                )
                if status == 401 and attempt == 1 and await self._refresh_token():
                    continue
                if status != 200:
                    raise RuntimeError(f"DonationAlerts API вернул {status}")
            except (ApiRequestError, aiohttp.ClientError) as exc:
                raise RuntimeError(f"DonationAlerts: сеть ({exc})") from exc
            return [self._normalize(item) for item in (body or {}).get("data", [])]
        return []

    @staticmethod
    def _normalize(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "da_id": int(item["id"]),
            "username": item.get("username") or "?",
            "amount": float(item.get("amount") or 0),
            "currency": item.get("currency") or "",
            "message": item.get("message") or "",
        }

    async def process_new(self, limit: int = 50) -> list[dict[str, Any]]:
        """Отмечает новые донаты в БД и возвращает их с персональным кодом из сообщения."""
        prefix = self._config.donation_code_prefix
        pattern = re.compile(rf"{re.escape(prefix)}-[A-Fa-f0-9]{{8}}", re.IGNORECASE) if prefix else None
        new_donations: list[dict[str, Any]] = []
        for item in await self.fetch_recent(limit):
            if await self._repo.is_known(item["da_id"]):
                continue
            message = item["message"]
            match = pattern.search(message) if pattern else None
            code = match.group(0).upper() if match else None
            inserted = await self._repo.record(
                item["da_id"], item["username"], item["amount"], item["currency"], message, bool(code)
            )
            if not inserted:
                continue
            item["code"] = code
            item["created_at"] = None
            new_donations.append(item)
        return new_donations

    def _gen_code(self) -> str:
        return f"{self._config.donation_code_prefix}-{secrets.token_hex(4).upper()}"

    async def create_code(self, user_id: int, guild_id: int, role: str, role_id: int | None) -> str:
        """Генерирует персональный код для доната и сохраняет привязку в kv."""
        code = self._gen_code()
        await self._kv.set(
            f"da_code:{code}",
            json.dumps(
                {
                    "user_id": user_id,
                    "guild_id": guild_id,
                    "role": role,
                    "role_id": role_id,
                    "created_at": int(time.time()),
                }
            ),
        )
        return code

    async def lookup_code(self, code: str) -> dict[str, Any] | None:
        raw = await self._kv.get(f"da_code:{code}")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            await self._kv.delete(f"da_code:{code}")
            return None

    async def delete_code(self, code: str) -> None:
        await self._kv.delete(f"da_code:{code}")

    async def get_sponsor_message_id(self) -> int | None:
        raw = await self._kv.get(_SPONSOR_MESSAGE_KEY)
        return int(raw) if raw else None

    async def set_sponsor_message_id(self, message_id: int) -> None:
        await self._kv.set(_SPONSOR_MESSAGE_KEY, str(message_id))
