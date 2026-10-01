"""Старт-анонс стрима: пост с 🔔 и список откликнувшихся."""
from __future__ import annotations

from types import SimpleNamespace

import discord
import pytest

from app.cogs.streams.stream_announce import RSVP_EMOJI, post_rsvp, rsvp_users
from app.services.stream_rsvp import StreamRsvpStore


class FakeKv:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str, default: str | None = None) -> str | None:
        return self.data.get(key, default)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None


class FakeMessage:
    def __init__(self, message_id: int = 1) -> None:
        self.id = message_id
        self.reactions: list[object] = []
        self.added: list[str] = []

    async def add_reaction(self, emoji: str) -> None:
        self.added.append(emoji)


class FakeChannel:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.messages: dict[int, FakeMessage] = {}
        self.fail_send = False

    async def send(self, content: str) -> FakeMessage:
        if self.fail_send:
            raise discord.HTTPException(SimpleNamespace(status=500, reason="boom"), "boom")
        self.sent.append(content)
        message = FakeMessage(len(self.sent))
        self.messages[message.id] = message
        return message

    async def fetch_message(self, message_id: int) -> FakeMessage:
        return self.messages[message_id]


class FakeReaction:
    def __init__(self, emoji: str, users: list) -> None:
        self.emoji = emoji
        self._users = users

    def users(self, limit: int = 100):
        async def gen():
            for user in self._users:
                yield user

        return gen()


@pytest.mark.asyncio
async def test_post_rsvp_sends_announce_and_saves_id():
    store = StreamRsvpStore(FakeKv(), "stream:rsvp:test")
    channel = FakeChannel()

    await post_rsvp(channel, store=store, title="Вечерний стрим", url="https://twitch.tv/alice")

    assert len(channel.sent) == 1
    assert "Вечерний стрим" in channel.sent[0]
    assert "https://twitch.tv/alice" in channel.sent[0]
    message = channel.messages[1]
    assert message.added == [RSVP_EMOJI]
    assert await store.message_id() == 1


@pytest.mark.asyncio
async def test_post_rsvp_survives_send_failure():
    store = StreamRsvpStore(FakeKv(), "stream:rsvp:test")
    channel = FakeChannel()
    channel.fail_send = True

    await post_rsvp(channel, store=store, title="x", url="https://x")  # не должно поднять исключение
    assert await store.message_id() is None


@pytest.mark.asyncio
async def test_rsvp_users_none_without_announce_and_empty_without_reactions():
    store = StreamRsvpStore(FakeKv(), "stream:rsvp:test")
    channel = FakeChannel()

    assert await rsvp_users(channel, store=store) is None

    await post_rsvp(channel, store=store, title="t", url="u")
    assert await rsvp_users(channel, store=store) == []


@pytest.mark.asyncio
async def test_rsvp_users_filters_bots():
    store = StreamRsvpStore(FakeKv(), "stream:rsvp:test")
    channel = FakeChannel()
    await post_rsvp(channel, store=store, title="t", url="u")

    human = SimpleNamespace(mention="<@1>", display_name="alice", bot=False)
    bot = SimpleNamespace(mention="<@2>", display_name="helper", bot=True)
    channel.messages[1].reactions = [FakeReaction(RSVP_EMOJI, [human, bot])]

    users = await rsvp_users(channel, store=store)
    assert users == [human]


@pytest.mark.asyncio
async def test_rsvp_users_none_when_announce_message_deleted():
    store = StreamRsvpStore(FakeKv(), "stream:rsvp:test")
    await store.save(999)
    channel = FakeChannel()

    async def gone(message_id: int):
        raise discord.HTTPException(SimpleNamespace(status=404, reason="Not Found"), "gone")

    channel.fetch_message = gone  # type: ignore[method-assign]
    assert await rsvp_users(channel, store=store) is None


@pytest.mark.asyncio
async def test_pin_helpers_track_and_survive_errors():
    from app.cogs.streams.stream_announce import pin_sticky, unpin_sticky

    class PinnableMessage(FakeMessage):
        def __init__(self) -> None:
            super().__init__()
            self.pinned = []
            self.unpinned = []

        async def pin(self, reason: str = "") -> None:
            self.pinned.append(reason)

        async def unpin(self, reason: str = "") -> None:
            self.unpinned.append(reason)

    message = PinnableMessage()
    await pin_sticky(message)
    await unpin_sticky(message)
    assert message.pinned and message.unpinned

    class BrokenMessage(PinnableMessage):
        async def pin(self, reason: str = "") -> None:
            raise discord.HTTPException(SimpleNamespace(status=403, reason="Forbidden"), "no perms")

        async def unpin(self, reason: str = "") -> None:
            raise discord.HTTPException(SimpleNamespace(status=403, reason="Forbidden"), "no perms")

    await pin_sticky(BrokenMessage())   # без прав — не падаем
    await unpin_sticky(BrokenMessage())
