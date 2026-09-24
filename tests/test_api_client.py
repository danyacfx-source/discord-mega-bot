"""Тесты общего retry-aware HTTP-клиента."""

from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import TestServer

from app.core.api_client import ApiClient, ApiRequestError


async def test_api_client_retries_temporary_http_error() -> None:
    calls = 0

    async def handler(_request: web.Request) -> web.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return web.json_response({"error": "busy"}, status=503)
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_get("/", handler)
    server = TestServer(app)
    await server.start_server()
    client = ApiClient("test", timeout=2)
    client._backoff = AsyncMock()
    try:
        status, body, _ = await client.json("GET", server.make_url("/"), attempts=2)
        assert status == 200
        assert body == {"ok": True}
        assert calls == 2
        client._backoff.assert_awaited_once()
    finally:
        await client.close()
        await server.close()


async def test_api_client_exposes_non_retryable_error() -> None:
    async def handler(_request: web.Request) -> web.Response:
        return web.json_response({"error": "not found"}, status=404)

    app = web.Application()
    app.router.add_get("/", handler)
    server = TestServer(app)
    await server.start_server()
    client = ApiClient("test", timeout=2)
    try:
        try:
            await client.json("GET", server.make_url("/"))
        except ApiRequestError as exc:
            assert exc.status == 404
        else:
            raise AssertionError("ApiRequestError не был выброшен")
    finally:
        await client.close()
        await server.close()
