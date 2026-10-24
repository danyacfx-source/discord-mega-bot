"""Safe bot-account OAuth refresh for the existing Twitch IRC transport.

Twitch recommends EventSub/Helix for new integrations. This module keeps the
repository's existing IRC chatbot working while allowing a separate bot account.
Never log tokens or serialize them into the Git repository.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import quote

import aiohttp

logger = logging.getLogger("bot.services")

_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
_VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
_TTG_REFRESH_URL = "https://twitchtokengenerator.com/api/refresh/"
_REQUIRED_IRC_SCOPES = {"chat:read", "chat:edit"}


class TwitchBotAuth:
    """Refresh Twitch bot credentials; persist rotating refresh token in data/."""

    def __init__(
        self,
        *,
        login: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        access_token: str = "",
        refresh_provider: str = "twitch",
        cache_file: str = "data/twitch_bot_oauth.json",
    ) -> None:
        if refresh_provider not in {"twitch", "ttg"}:
            raise ValueError("Unsupported Twitch bot token refresh provider")
        self.provider = refresh_provider
        self.login = login.strip().lower()
        self.client_id = client_id
        self.client_secret = client_secret
        self._access = access_token.removeprefix("oauth:")
        self._refresh = refresh_token
        self._expires = 0.0
        self._file = Path(cache_file)
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self._file.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return
        if (
            payload.get("login") != self.login
            or payload.get("client_id") != self.client_id
            or payload.get("provider", "twitch") != self.provider
        ):
            return
        if payload.get("refresh_token"):
            self._refresh = str(payload["refresh_token"])
            self._access = str(payload.get("access_token") or "")
            self._expires = float(payload.get("expires_at") or 0)

    def _save(self) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "login": self.login,
                "client_id": self.client_id,
                "provider": self.provider,
                "access_token": self._access,
                "refresh_token": self._refresh,
                "expires_at": self._expires,
            },
            ensure_ascii=False,
        )
        temp = self._file.with_name(self._file.name + ".tmp")
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
            os.replace(temp, self._file)
            os.chmod(self._file, 0o600)
        finally:
            if temp.exists():
                temp.unlink()

    async def _refresh_token(self) -> None:
        """Rotate a Twitch bot user's credentials, never logging tokens or URLs."""
        if self.provider == "ttg":
            # TwitchTokenGenerator's API (not a Twitch-operated service).
            # This HTTPS request exposes the refresh token in the path to TTG
            # and its access logs. Never follow redirects to other hosts.
            if not self.client_id:
                raise RuntimeError("Twitch bot: TWITCH_BOT_CLIENT_ID is required for TTG")
            url = _TTG_REFRESH_URL + quote(self._refresh, safe="")
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    if response.status != 200:
                        raise RuntimeError("Twitch TTG token refresh failed (HTTP status)")
                    payload = await response.json(content_type=None)
            if (
                not isinstance(payload, dict)
                or payload.get("success") is not True
                or str(payload.get("client_id") or "") != self.client_id
            ):
                raise RuntimeError("Twitch TTG token refresh failed or client ID mismatch")
            access = str(payload.get("token") or "")
            refresh = str(payload.get("refresh") or "")
        else:
            if not self.client_id or not self.client_secret:
                raise RuntimeError("Twitch OAuth: TWITCH_CLIENT_ID/SECRET are required")
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "refresh_token": self._refresh,
                    },
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    if response.status != 200:
                        raise RuntimeError("Twitch OAuth: refresh failed")
                    payload = await response.json()
            access = str(payload.get("access_token") or "")
            refresh = str(payload.get("refresh_token") or "")

        if not access or not refresh:
            raise RuntimeError("Twitch OAuth: refresh response missing access/refresh token")
        self._access = access.removeprefix("oauth:")
        self._refresh = refresh
        # Twitch's validation endpoint provides the authoritative time-to-live.
        self._expires = 0.0
        try:
            self._save()
        except OSError:
            logger.error("Twitch OAuth: failed to persist rotated refresh token")
            raise RuntimeError("Twitch OAuth: unable to save rotated token") from None

    def seconds_until_refresh(self) -> float | None:
        """Duration until the IRC session should reconnect with rotated credentials."""
        if not self._refresh or not self._expires:
            return None
        return max(1.0, self._expires - time.time() - 120.0)

    async def token(self) -> str:
        """Return a validated bot IRC token; refresh the user token when needed."""
        if not self.login:
            return self._access
        if not self._refresh and not self._access:
            return ""

        if self._refresh and (not self._access or self._expires <= time.time() + 120):
            await self._refresh_token()

        async with aiohttp.ClientSession() as session:
            async with session.get(
                _VALIDATE_URL,
                headers={"Authorization": f"OAuth {self._access}"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    raise RuntimeError("Twitch OAuth: access token validation failed")
                payload = await response.json()

        if str(payload.get("login") or "").lower() != self.login:
            raise RuntimeError("Twitch OAuth: token belongs to a different user than TWITCH_BOT_LOGIN")
        if not _REQUIRED_IRC_SCOPES.issubset(set(payload.get("scopes") or [])):
            raise RuntimeError("Twitch OAuth: missing chat:read / chat:edit scopes")
        # Manual IRC tokens can come from a separate OAuth app; managed refresh
        # tokens must match their own app, not the broadcaster stream API app.
        if self._refresh and self.client_id and payload.get("client_id") != self.client_id:
            raise RuntimeError("Twitch OAuth: token client_id mismatch")
        expires_in = int(payload.get("expires_in") or 0)
        if expires_in < 60:
            raise RuntimeError("Twitch OAuth: access token expiring; reauthorization may be needed")
        self._expires = time.time() + expires_in
        return self._access
