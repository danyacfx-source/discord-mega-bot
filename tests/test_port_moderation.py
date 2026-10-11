"""Тесты webpanel-кейсов модерации: guild-scope, фильтр по юзеру, 404."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.core.bot import MegaBot
from app.core.webpanel.webpanel import WebPanel


def _cases_row(case_id: int, user_id: int = 111) -> dict:
    return {
        "case_id": case_id,
        "guild_id": 1,
        "user_id": user_id,
        "moderator_id": 222,
        "action": "ban",
        "reason": "спам",
        "created_at": "2026-10-01T12:00:00+00:00",
        "expires_at": None,
        "active": 0,
    }


def _cases_bot(make_panel_bot, cases) -> MegaBot:
    bot = make_panel_bot(guild_id=1)
    member = SimpleNamespace(id=111, name="alice", display_name="Alice", discriminator=0)
    guild = SimpleNamespace(
        id=1,
        # известные id резолвятся: иначе _member_name упрётся в bot.user (None до логина)
        get_member=lambda uid: (
            SimpleNamespace(id=uid, name=f"user{uid}", display_name=f"User{uid}")
            if uid in {111, 222, 333}
            else None
        ),
        members=[member],
    )
    bot.get_guild = lambda gid: guild
    bot.services = SimpleNamespace(cases=cases)
    return bot


@pytest.mark.asyncio
async def test_webpanel_api_moderation_cases_guild_scope(make_panel_bot):
    cases = SimpleNamespace(
        list_for_guild=AsyncMock(return_value=[_cases_row(1), _cases_row(2, user_id=333)]),
        list_for_user=AsyncMock(),
    )
    bot = _cases_bot(make_panel_bot, cases)
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}
            assert (await client.get("/api/moderation/cases")).status == 401
            resp = await client.get("/api/moderation/cases", headers=headers)
            assert resp.status == 200
            data = await resp.json()
            assert data["ok"] is True
            assert data["total"] == 2
            assert data["cases"][0]["action"] == "ban"
            assert data["cases"][0]["user_name"] == "User111"
            assert data["cases"][0]["moderator_name"] == "User222"
            assert data["cases"][1]["user_name"] == "User333"
            cases.list_for_guild.assert_awaited_once_with(1, 200)
            cases.list_for_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_webpanel_api_moderation_cases_by_user(make_panel_bot):
    cases = SimpleNamespace(
        list_for_guild=AsyncMock(),
        list_for_user=AsyncMock(return_value=[_cases_row(5)]),
    )
    bot = _cases_bot(make_panel_bot, cases)
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}
            resp = await client.get("/api/moderation/cases?user_id=111", headers=headers)
            assert resp.status == 200
            data = await resp.json()
            assert data["total"] == 1
            assert data["cases"][0]["case_id"] == 5
            cases.list_for_user.assert_awaited_once_with(1, 111, 200)
            cases.list_for_guild.assert_not_awaited()


@pytest.mark.asyncio
async def test_webpanel_api_moderation_cases_unknown_member_404(make_panel_bot):
    cases = SimpleNamespace(list_for_guild=AsyncMock(), list_for_user=AsyncMock())
    bot = _cases_bot(make_panel_bot, cases)
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}
            resp = await client.get("/api/moderation/cases?user_id=555", headers=headers)
            assert resp.status == 404
            cases.list_for_user.assert_not_awaited()
