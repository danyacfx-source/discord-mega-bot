"""Persistent Discord community suggestions without new tokens or migrations."""
from __future__ import annotations

import pytest

from app.config import Config
from app.core.bot import MegaBot
from app.services.idea_board_service import IdeaBoardService, IdeaError


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
async def test_ideas_persist_votes_and_status_over_redeploy() -> None:
    kv = _KV()
    board = IdeaBoardService(kv)  # type: ignore[arg-type]
    with pytest.raises(IdeaError):
        await board.create(1, 42, 8, "коротко")

    item = await board.create(1, 42, 8, "Добавить тематические вечерние стримы")
    ident = item["id"]
    assert len(ident) == 8
    with pytest.raises(IdeaError, match="Следующую"):
        await board.create(1, 42, 8, "Ещё одна идея без ожидания")
    await board.bind(1, ident, 9001)
    assert (await board.by_message(1, 9001))["id"] == ident

    assert IdeaBoardService.scores(await board.vote(1, ident, 55, 1)) == (1, 0)
    assert IdeaBoardService.scores(await board.vote(1, ident, 56, -1)) == (1, 1)
    assert IdeaBoardService.scores(await board.vote(1, ident, 55, -1)) == (0, 2)
    assert IdeaBoardService.scores(await board.vote(1, ident, 55, -1)) == (0, 1)
    # Another guild and an invalid vote must not cross streams.
    with pytest.raises(IdeaError, match="не найдена"):
        await board.vote(2, ident, 55, 1)
    with pytest.raises(IdeaError, match="тип"):
        await board.vote(1, ident, 55, 7)

    fresh = IdeaBoardService(kv)  # type: ignore[arg-type]
    restored = await fresh.get(1, ident)
    assert restored is not None
    assert restored["message_id"] == 9001
    assert IdeaBoardService.scores(restored) == (0, 1)
    assert (await fresh.list_ideas(1, top=True))[0]["id"] == ident

    done = await fresh.status(1, ident, "done")
    assert done["status"] == "done"
    with pytest.raises(IdeaError, match="закрыто"):
        await fresh.vote(1, ident, 55, 1)
    with pytest.raises(IdeaError, match="статус"):
        await fresh.status(1, ident, "secret")
    reopened = await fresh.status(1, ident, "planned")
    assert reopened["status"] == "planned"
    assert IdeaBoardService.scores(await fresh.vote(1, ident, 55, 1)) == (1, 1)

    deleted = await fresh.remove(1, ident)
    assert deleted["id"] == ident
    assert await fresh.get(1, ident) is None
    assert await fresh.by_message(1, 9001) is None
    assert await fresh.list_ideas(1) == []


@pytest.mark.asyncio
async def test_cog_autoloads_and_vote_view_is_persistent(tmp_path) -> None:
    bot = MegaBot(Config(
        token="test", prefix="!", db_path=str(tmp_path / "bot.db"),
        log_level="ERROR", status_activity="s", owner_id=None,
    ))
    try:
        await bot.setup_hook()
        cog = bot.get_cog("CommunityIdeas")
        assert cog is not None
        views = [v for v in bot.persistent_views if v.__class__.__name__ == "IdeaVoteView"]
        assert views, "buttons must work after restart"
        ids = {item.custom_id for item in views[0].children}
        assert ids == {"dendich:idea:up", "dendich:idea:down"}
    finally:
        await bot.close()
