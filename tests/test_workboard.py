"""Integration tests for the DENDICH Command Center workboard."""
from __future__ import annotations

import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.core.webpanel.webpanel import WebPanel


@pytest.mark.asyncio
async def test_workboard_crud_persists_in_database(make_panel_bot):
    bot = make_panel_bot()
    await bot.setup_hook()
    panel = WebPanel(bot)
    headers = {"X-Panel-Token": panel._static_token or ""}
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                anonymous = await client.get("/api/workboard")
                assert anonymous.status == 401

                initial = await client.get("/api/workboard", headers=headers)
                assert initial.status == 200
                assert (await initial.json())["items"] == []

                added = await client.post("/api/workboard", json={
                    "action": "create", "type": "task", "title": "  Проверить правила  ",
                    "note": "Обновить раздел информации", "priority": "high",
                }, headers=headers)
                assert added.status == 200
                board = (await added.json())["items"]
                assert len(board) == 1
                item_id = board[0]["id"]
                assert board[0]["title"] == "Проверить правила"
                assert board[0]["status"] == "todo"

                updated = await client.post("/api/workboard", json={
                    "action": "update", "id": item_id, "status": "done",
                }, headers=headers)
                assert updated.status == 200
                assert (await updated.json())["items"][0]["status"] == "done"

                # New WebPanel instance and same DB/KV must see the same state.
                other_panel = WebPanel(bot)
                assert (await other_panel._workboard_items())[0]["id"] == item_id

                invalid = await client.post("/api/workboard", json={
                    "action": "update", "id": item_id, "status": "published",
                }, headers=headers)
                assert invalid.status == 400

                invalid_title = await client.post("/api/workboard", json={
                    "action": "create", "type": "idea", "title": "x" * 121,
                }, headers=headers)
                assert invalid_title.status == 400

                idea = await client.post("/api/workboard", json={
                    "action": "create", "type": "idea", "title": "Arma лучшие моменты",
                }, headers=headers)
                assert idea.status == 200
                assert len((await idea.json())["items"]) == 2

                deleted = await client.post("/api/workboard", json={
                    "action": "delete", "id": item_id,
                }, headers=headers)
                assert deleted.status == 200
                final = (await deleted.json())["items"]
                assert len(final) == 1 and final[0]["type"] == "idea"
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_workboard_role_limits_and_private_data(make_panel_bot):
    bot = make_panel_bot()
    await bot.setup_hook()
    panel = WebPanel(bot)
    panel._check_token = lambda request: "moderator"  # type: ignore[method-assign]
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                allowed = await client.get("/api/workboard")
                assert allowed.status == 200
                denied = await client.post("/api/workboard", json={
                    "action": "create", "type": "task", "title": "Нет прав",
                })
                assert denied.status == 403
                assert not (await denied.json())["ok"]

                # Public showcase does not leak private team notes.
                showcase = await client.get("/api/public/showcase")
                assert showcase.status == 200
                assert "workboard" not in (await showcase.text())
    finally:
        await bot.close()


@pytest.mark.asyncio
async def test_workboard_recovers_from_malformed_kv(make_panel_bot):
    bot = make_panel_bot()
    await bot.setup_hook()
    panel = WebPanel(bot)
    try:
        await bot.services.kv.set("panel.command_center.workboard.v1", json.dumps({"wrong": True}))
        assert await panel._workboard_items() == []
        await bot.services.kv.set("panel.command_center.workboard.v1", "bad json")
        assert await panel._workboard_items() == []
    finally:
        await bot.close()
