"""Spotify Client Credentials resolver для треков и публичных плейлистов."""
from __future__ import annotations

import base64
import time
from typing import Any
from urllib.parse import urlparse

from app.core.api_client import ApiClient


class SpotifyResolver:
    def __init__(self, client_id: str | None, client_secret: str | None, api: ApiClient | None = None) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.api = api or ApiClient("Spotify")
        self._token: str | None = None
        self._token_expires_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def close(self) -> None:
        await self.api.close()

    async def _access_token(self) -> str:
        if not self.configured:
            raise RuntimeError("SPOTIFY_CLIENT_ID и SPOTIFY_CLIENT_SECRET не настроены")
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        raw = f"{self.client_id}:{self.client_secret}".encode()
        auth = base64.b64encode(raw).decode()
        _, data, _ = await self.api.json(
            "POST",
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
            data="grant_type=client_credentials",
        )
        if not isinstance(data, dict) or not data.get("access_token"):
            raise RuntimeError("Spotify не вернул access token")
        self._token = str(data["access_token"])
        self._token_expires_at = time.monotonic() + max(30, int(data.get("expires_in", 3600)) - 60)
        return self._token

    @staticmethod
    def _resource(url: str) -> tuple[str, str] | None:
        parsed = urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"track", "playlist"}:
            return parts[0], parts[1].split("?")[0]
        return None

    async def _get(self, endpoint: str) -> dict[str, Any]:
        _, data, _ = await self.api.json(
            "GET",
            f"https://api.spotify.com/v1/{endpoint.lstrip('/')}",
            headers={"Authorization": f"Bearer {await self._access_token()}"},
        )
        if not isinstance(data, dict):
            raise RuntimeError("Spotify вернул некорректный ответ")
        return data

    async def track_queries(self, url: str) -> list[str]:
        resource = self._resource(url)
        if resource is None:
            return []
        kind, resource_id = resource
        if kind == "track":
            track = await self._get(f"tracks/{resource_id}")
            name = str(track.get("name") or "")
            artists = " ".join(str(item.get("name") or "") for item in track.get("artists", []) if isinstance(item, dict))
            return [f"{artists} {name}".strip()] if name else []
        if kind != "playlist":
            return []
        queries: list[str] = []
        endpoint = f"playlists/{resource_id}/tracks?limit=100"
        while endpoint and len(queries) < 100:
            data = await self._get(endpoint)
            for item in data.get("items", []):
                playlist_track = item.get("track") if isinstance(item, dict) else None
                if not isinstance(playlist_track, dict) or not playlist_track.get("name"):
                    continue
                artists = " ".join(
                    str(a.get("name") or "")
                    for a in playlist_track.get("artists", [])
                    if isinstance(a, dict)
                )
                queries.append(f"{artists} {playlist_track['name']}".strip())
                if len(queries) >= 100:
                    break
            next_url = data.get("next")
            endpoint = next_url.split("/v1/", 1)[1] if isinstance(next_url, str) and "/v1/" in next_url else ""
        return queries
