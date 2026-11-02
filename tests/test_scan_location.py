"""Локация сканера берётся из заголовков Cloudflare и только от доверенных пиров."""
from __future__ import annotations

import ipaddress

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.core.webpanel.payload import _SCAN_LIMIT
from app.core.webpanel.webpanel import WebPanel

_CF_HEADERS = {"CF-Connecting-IP": "203.0.113.7", "CF-IPCity": "Frankfurt", "CF-IPCountry": "DE"}


async def _scan(client: TestClient, headers: dict[str, str]) -> None:
    for _ in range(_SCAN_LIMIT):
        await client.get("/.env", headers=headers)


@pytest.mark.asyncio
async def test_scan_ban_records_location_from_trusted_cloudflare(make_panel_bot):
    panel = WebPanel(make_panel_bot())
    panel._trusted_proxy = True
    panel._trusted_networks = (ipaddress.ip_network("127.0.0.0/8"),)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            await _scan(client, _CF_HEADERS)
    assert panel._scan_locations == {"203.0.113.7": "Frankfurt, DE"}


@pytest.mark.asyncio
async def test_location_headers_ignored_from_untrusted_peer(make_panel_bot):
    panel = WebPanel(make_panel_bot())
    panel._trusted_proxy = True
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            await _scan(client, _CF_HEADERS)
    assert panel._scan_locations == {}


@pytest.mark.asyncio
async def test_unknown_country_marker_is_skipped(make_panel_bot):
    panel = WebPanel(make_panel_bot())
    panel._trusted_proxy = True
    panel._trusted_networks = (ipaddress.ip_network("127.0.0.0/8"),)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            await _scan(client, {"CF-Connecting-IP": "203.0.113.8", "CF-IPCountry": "XX"})
    assert panel._scan_locations == {}
