"""Публичный клиент каталога игровых серверов WARDOGS."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp

_API_URL = "https://api.wardogservers.com/v1/servers"


class WardogsUnavailable(RuntimeError):
    """Каталог серверов временно недоступен или сервер не найден."""


@dataclass(slots=True, frozen=True)
class WardogsServer:
    instance_id: str
    join_id: str
    name: str
    players: int
    max_players: int
    region: str
    map_name: str
    mode: str
    password_protected: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "instanceId": self.instance_id,
            "joinId": self.join_id,
            "name": self.name,
            "players": self.players,
            "maxPlayers": self.max_players,
            "region": self.region,
            "map": self.map_name,
            "mode": self.mode,
            "passwordProtected": self.password_protected,
        }


class WardogsService:
    def __init__(self, *, server_name: str, server_id: str | None = None, timeout: float = 12.0) -> None:
        self.server_name = server_name.strip()
        self.server_id = (server_id or "").strip() or None
        self.timeout = timeout

    async def get_server(self) -> WardogsServer:
        query = self.server_id or self.server_name
        timeout = aiohttp.ClientTimeout(total=self.timeout, connect=min(5.0, self.timeout))
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(_API_URL, params={"q": query, "limit": "100"}) as response:
                    if response.status != 200:
                        raise WardogsUnavailable(f"WARDOGS API вернул {response.status}")
                    payload = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise WardogsUnavailable("Каталог WARDOGS временно недоступен") from exc

        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise WardogsUnavailable("WARDOGS API вернул неизвестный формат")
        selected = self._select([row for row in rows if isinstance(row, dict)])
        if selected is None:
            raise WardogsUnavailable(f"Сервер «{query}» сейчас не найден")
        return self._parse(selected)

    def _select(self, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not rows:
            return None
        if self.server_id:
            exact_id = [row for row in rows if str(row.get("serverId", "")).casefold() == self.server_id.casefold()]
            if exact_id:
                return exact_id[0]
            return None
        exact_name = [row for row in rows if str(row.get("name", "")).strip().casefold() == self.server_name.casefold()]
        if not exact_name:
            return None
        return max(exact_name, key=lambda row: int(row.get("players") or 0))

    @staticmethod
    def _parse(row: dict[str, Any]) -> WardogsServer:
        map_data = row.get("map") if isinstance(row.get("map"), dict) else {}
        mode_data = row.get("mode") if isinstance(row.get("mode"), dict) else {}
        return WardogsServer(
            instance_id=str(row.get("id") or ""),
            join_id=str(row.get("serverId") or ""),
            name=str(row.get("name") or "WARDOGS"),
            players=int(row.get("players") or 0),
            max_players=int(row.get("maxPlayers") or 0),
            region=str(row.get("region") or "—"),
            map_name=str(map_data.get("variant") or map_data.get("base") or "—"),
            mode=str(mode_data.get("experience") or mode_data.get("gameMode") or "—"),
            password_protected=bool(row.get("passwordProtected")),
        )
