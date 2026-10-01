"""Тесты отправки сообщений в чат Kick (Dev API POST /public/v1/chat)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.kick_service import KickService, truncate_chat_content


def _service(token: str = "dev-token") -> KickService:
    return KickService(
        SimpleNamespace(),  # type: ignore[arg-type]  # репозиторий не используется в этом тесте
        SimpleNamespace(
            kick_access_token=token,
            api_timeout_seconds=2.0,
            api_proxy=None,
            api_max_concurrency=4,
            api_circuit_failure_threshold=5,
            api_circuit_reset_seconds=30.0,
        ),  # type: ignore[arg-type]
    )


def test_truncate_chat_content_respects_both_limits() -> None:
    assert truncate_chat_content("  привет  ") == "привет"
    assert len(truncate_chat_content("a" * 900)) == 500
    emoji = "😀" * 600
    truncated = truncate_chat_content(emoji)
    assert len(truncated.encode("utf-8")) <= 2048
    assert truncated


async def test_send_chat_message_uses_official_endpoint() -> None:
    service = _service()
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_json(method: str, url: str, **kwargs: object) -> tuple[int, object, dict[str, str]]:
        calls.append((url, dict(kwargs)))
        return 200, {"data": {"is_sent": True, "message_id": "abc"}}, {}

    service._http.json = fake_json  # type: ignore[method-assign]
    try:
        message_id = await service.send_chat_message("привет")
        assert message_id == "abc"
        url, kwargs = calls[0]
        assert url == "https://api.kick.com/public/v1/chat"
        assert kwargs["json"] == {"content": "привет", "type": "bot"}
        assert kwargs["headers"] == {"Authorization": "Bearer dev-token"}
    finally:
        await service.aclose()


async def test_send_chat_message_as_user_includes_broadcaster_id() -> None:
    service = _service()
    calls: list[dict[str, object]] = []

    async def fake_json(method: str, url: str, **kwargs: object) -> tuple[int, object, dict[str, str]]:
        calls.append(dict(kwargs))
        return 200, {"data": {"is_sent": True, "message_id": "abc"}}, {}

    service._http.json = fake_json  # type: ignore[method-assign]
    service.resolve_broadcaster = AsyncMock(return_value={"user_id": 42, "name": "streamer"})  # type: ignore[method-assign]
    try:
        await service.send_chat_message("привет", as_user=True, reply_to_message_id="m-9")
        payload = calls[0]["json"]
        assert payload["type"] == "user"
        assert payload["broadcaster_user_id"] == 42
        assert payload["reply_to_message_id"] == "m-9"
    finally:
        await service.aclose()


async def test_send_chat_message_reports_rejection_and_empty_text() -> None:
    service = _service()

    async def fake_json(method: str, url: str, **kwargs: object) -> tuple[int, object, dict[str, str]]:
        return 200, {"data": {"is_sent": False}}, {}

    service._http.json = fake_json  # type: ignore[method-assign]
    try:
        assert await service.send_chat_message("привет") is None
        assert await service.send_chat_message("   ") is None
    finally:
        await service.aclose()
