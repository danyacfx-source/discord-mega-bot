"""Cross-platform Twitch/Kick live voting works without write-enabled chat OAuth."""
from __future__ import annotations

import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.config import Config
from app.core.bot import MegaBot
from app.core.webpanel.webpanel import WebPanel
from app.services.chat_commands_service import ChatMessage
from app.services.live_vote_service import LiveVoteService, VoteError


class _KV:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str, default: str | None = None) -> str | None:
        return self.data.get(key, default)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None


@pytest.mark.asyncio
async def test_votes_from_two_platforms_survive_restart() -> None:
    kv = _KV()
    service = LiveVoteService(kv)  # type: ignore[arg-type]
    with pytest.raises(VoteError):
        await service.start("", ["a", "b"], 60)
    with pytest.raises(VoteError):
        await service.start("Choice", ["yes", "YES"], 60)
    with pytest.raises(VoteError):
        await service.start("Choice", ["a", "b"], 10)
    created = await service.start("Что стримим?", ["CS2", "Minecraft", "Разговоры"], 90)
    assert created["total"] == 0 and created["status"] == "active"
    with pytest.raises(VoteError):
        await service.start("Other", ["a", "b"], 60)
    assert await service.register_message("twitch", "alice", "!vote 1")
    assert await service.register_message("kick", "alice", "!голос 2")
    assert await service.register_message("twitch", "bob", "!v 1")
    assert await service.register_message("twitch", "alice", "!vote 3")  # change one vote
    for text in ("1", "!vote 9", "!help", "!vote a"):
        assert not await service.register_message("twitch", "bob", text)
    assert not await service.register_message("discord", "bob", "!vote 1")
    result = await service.status()
    assert result is not None
    assert result["counts"] == [1, 1, 1]
    assert result["total"] == 3
    assert "alice" not in str(result)
    # New process instance / redeploy, same KV data.
    another = LiveVoteService(kv)  # type: ignore[arg-type]
    restored = await another.status()
    assert restored == result
    assert await another.register_message("kick", "bob", "!vote 2")
    final = await another.finish()
    assert final is not None
    assert final["counts"] == [1, 2, 1]
    assert final["leaders"] == [2]
    assert not await another.register_message("kick", "bob", "!vote 1")
    await another.clear()
    assert await another.status() is None


@pytest.mark.asyncio
async def test_live_vote_auto_expires_after_deadline() -> None:
    kv = _KV()
    service = LiveVoteService(kv)  # type: ignore[arg-type]
    await service.start("Проверка", ["да", "нет"], 30)
    assert service._state is not None
    service._state["ends_at"] = time.time() - 1
    closed = await service.status()
    assert closed is not None and closed["status"] == "closed"
    assert (await LiveVoteService(kv).status())["status"] == "closed"  # type: ignore[arg-type, index]


@pytest.mark.asyncio
async def test_live_vote_panel_and_old_obs_links(tmp_path) -> None:
    overlay_token = "never-rotate-existing-overlay-token"
    config = Config(
        token="x", prefix="!", db_path=str(tmp_path / "bot.db"), log_level="ERROR",
        status_activity="s", owner_id=None, panel_port=17091,
        overlay_port=18091, overlay_token=overlay_token,
        chat_commands_enabled=False,
    )
    bot = MegaBot(config)
    await bot.setup_hook()
    panel = WebPanel(bot)
    admin = {"X-Panel-Token": panel._static_token or ""}
    obs = {"X-Overlay-Token": overlay_token}
    try:
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                assert (await client.post("/api/live-vote", json={"action": "start"})).status == 401
                assert (await client.get("/overlay/vote/api")).status == 401
                assert (await client.get("/overlay/chat?token=" + overlay_token)).status == 200
                create = await client.post(
                    "/api/live-vote",
                    json={"action": "start", "question": "Игра?", "options": ["CS2", "Minecraft"], "seconds": 60},
                    headers=admin,
                )
                assert create.status == 200
                # IRC/Pusher just READ the messages; normal chat commands are off.
                await bot.services.chat_commands.handle(
                    ChatMessage(platform="twitch", username="alice", display_name="Alice", content="!vote 1")
                )
                await bot.services.chat_commands.handle(
                    ChatMessage(platform="kick", username="boris", display_name="Boris", content="!голос 2")
                )
                stream = await client.get("/overlay/vote/api", headers=obs)
                assert stream.status == 200
                body = await stream.json()
                assert body["poll"]["counts"] == [1, 1]
                assert body["poll"]["total"] == 2
                assert (await client.get("/overlay/vote?token=" + overlay_token)).status == 200
                old = await client.get("/overlay/api", headers=obs)
                assert old.status == 200
                assert len((await old.json())["chat"]) == 2

                stopped = await client.post("/api/live-vote", json={"action": "finish"}, headers=admin)
                assert stopped.status == 200 and (await stopped.json())["poll"]["status"] == "closed"
                clear = await client.post("/api/live-vote", json={"action": "clear"}, headers=admin)
                assert clear.status == 200
                assert (await (await client.get("/overlay/vote/api", headers=obs)).json())["poll"] is None
    finally:
        await bot.close()
