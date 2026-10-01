"""Клиппинг Twitch: user-токен из refresh_token и create_clip."""
from __future__ import annotations

import pytest

from app.config import Config
from app.services.twitch_service import TwitchService


class FakeKv:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str, default: str | None = None) -> str | None:
        return self.data.get(key, default)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None


def _config(**overrides) -> Config:
    base: dict = {
        "token": "x",
        "prefix": "!",
        "db_path": ":",
        "log_level": "INFO",
        "status_activity": "",
        "owner_id": None,
    }
    base.update(overrides)
    return Config(**base)


def _creds() -> Config:
    return _config(twitch_client_id="cid", twitch_client_secret="sec", twitch_refresh_token="rt-1")


async def _fake_user_id(login: str) -> str | None:
    return "42"


@pytest.mark.asyncio
async def test_create_clip_requires_credentials():
    service = TwitchService(FakeKv(), _config())
    assert await service.create_clip("someone") is None, "без кредов клип не создаётся"
    assert await service._user_access_token() is None


@pytest.mark.asyncio
async def test_create_clip_happy_path(monkeypatch):
    service = TwitchService(FakeKv(), _creds())
    monkeypatch.setattr(service, "_helix_user_id", _fake_user_id)
    calls: list[tuple[str, dict]] = []

    async def fake_json(method: str, url: str, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/oauth2/token"):
            return 200, {"access_token": "user-tok", "expires_in": 3600, "refresh_token": "rt-2"}, {}
        return 200, {"data": [{"url": "https://clips.twitch.tv/Clip"}]}, {}

    monkeypatch.setattr(service._http, "json", fake_json)

    title = "Очень длинный заголовок " * 10
    url = await service.create_clip("someone", title=title)
    assert url == "https://clips.twitch.tv/Clip"

    clip_calls = [(u, k) for u, k in calls if "helix/clips" in u]
    assert len(clip_calls) == 1
    _, kwargs = clip_calls[0]
    assert kwargs["params"]["broadcaster_id"] == "42"
    assert len(kwargs["params"]["title"]) <= 140, "заголовок обрезается до 140 символов"
    assert kwargs["headers"]["Authorization"] == "Bearer user-tok"
    assert kwargs["headers"]["Client-ID"] == "cid"


@pytest.mark.asyncio
async def test_create_clip_retries_after_401(monkeypatch):
    service = TwitchService(FakeKv(), _creds())
    monkeypatch.setattr(service, "_helix_user_id", _fake_user_id)
    clip_attempts = 0
    token_calls = 0

    async def fake_json(method: str, url: str, **kwargs):
        nonlocal clip_attempts, token_calls
        if url.endswith("/oauth2/token"):
            token_calls += 1
            return 200, {"access_token": f"tok-{token_calls}", "expires_in": 3600}, {}
        clip_attempts += 1
        if clip_attempts == 1:
            return 401, {"error": "Unauthorized"}, {}
        return 200, {"data": [{"url": "https://clips.twitch.tv/x"}]}, {}

    monkeypatch.setattr(service._http, "json", fake_json)

    url = await service.create_clip("someone")
    assert url == "https://clips.twitch.tv/x"
    assert clip_attempts == 2, "401 → принудительный рефреш → повтор"
    assert token_calls == 2, "вторая попытка берёт свежий токен"


@pytest.mark.asyncio
async def test_user_token_cached_until_forced(monkeypatch):
    service = TwitchService(FakeKv(), _creds())
    token_calls = 0

    async def fake_json(method: str, url: str, **kwargs):
        nonlocal token_calls
        token_calls += 1
        return 200, {"access_token": "user-tok", "expires_in": 3600}, {}

    monkeypatch.setattr(service._http, "json", fake_json)

    assert await service._user_access_token() == "user-tok"
    assert await service._user_access_token() == "user-tok"
    assert token_calls == 1, "токен кэшируется до истечения"
    assert await service._user_access_token(force=True) == "user-tok"
    assert token_calls == 2, "force обходит кэш"
