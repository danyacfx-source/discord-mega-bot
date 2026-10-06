"""Старт-анонс стрима: пост с 🔔 и список откликнувшихся."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import discord
import pytest

from app.cogs.streams.rsvp import StreamRsvp
from app.cogs.streams.stream_announce import RSVP_EMOJI, post_rsvp, rsvp_stream_end, rsvp_users
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


# ---------------------------------------------------------------- роль «На стриме»
class FakeRole:
    def __init__(self, role_id: int, name: str = "") -> None:
        self.id = role_id
        self.name = name


class FakeMember:
    def __init__(self) -> None:
        self.added: list[FakeRole] = []
        self.removed: list[FakeRole] = []
        self.fail: Exception | None = None

    async def add_roles(self, role: FakeRole, reason: str = "") -> None:
        if self.fail:
            raise self.fail
        self.added.append(role)

    async def remove_roles(self, role: FakeRole, reason: str = "") -> None:
        if self.fail:
            raise self.fail
        self.removed.append(role)


class FakeGuild:
    def __init__(self, roles: list[FakeRole], member: FakeMember | None) -> None:
        self.id = 1
        self.roles = roles
        self._member = member

    def get_role(self, role_id: int) -> FakeRole | None:
        return next((r for r in self.roles if r.id == role_id), None)

    def get_member(self, user_id: int) -> FakeMember | None:
        return self._member

    async def fetch_member(self, user_id: int) -> FakeMember:
        raise discord.HTTPException(SimpleNamespace(status=404, reason="Not Found"), "gone")


class FakeSessionStore:
    def __init__(self, captured_at: str | None) -> None:
        self._captured = captured_at

    async def load(self) -> dict | None:
        if self._captured is None:
            return None
        return {"captured_at": self._captured}


class FakeTwitch:
    def __init__(
        self,
        store: StreamRsvpStore,
        *,
        captured_at: str | None = None,
        has_session: bool = True,
    ) -> None:
        self._store = store
        self._captured = captured_at or datetime.now(UTC).isoformat()
        self._has_session = has_session

    def rsvp_store(self, login: str) -> StreamRsvpStore:
        return self._store

    def session_store(self, login: str) -> FakeSessionStore:
        return FakeSessionStore(self._captured if self._has_session else None)


def _rsvp_cog(
    *,
    guild: FakeGuild,
    role_id: int | None = None,
    live: bool = True,
    has_session: bool = True,
) -> tuple:
    """(cog, store, member): twitch-анонс id=77 в канале 555 гильдии 1."""
    store = StreamRsvpStore(FakeKv(), "stream:rsvp:test")
    channel = SimpleNamespace(guild=SimpleNamespace(id=1))
    captured = datetime.now(UTC).isoformat()
    if not live:
        captured = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    config = SimpleNamespace(
        twitch_channels=("alice",),
        twitch_notify_channel_id=555,
        twitch_poll_seconds=300,
        kick_channel_slug="",
        kick_notify_channel_id=None,
        vk_channel_slug="",
        vk_notify_channel_id=None,
        stream_rsvp_role_id=role_id,
        stream_sticky_poll_seconds=60,
    )
    bot = SimpleNamespace(
        config=config,
        guilds=[guild],
        user=SimpleNamespace(id=999),
        get_guild=lambda gid: guild if gid == 1 else None,
        get_channel=lambda cid: channel if cid == 555 else None,
    )
    twitch = FakeTwitch(store, captured_at=captured, has_session=has_session)
    cog = StreamRsvp(bot, twitch, kick=None, vk_video=None)  # type: ignore[arg-type]
    return cog, store, guild._member


def _payload(**over) -> SimpleNamespace:
    base = dict(guild_id=1, message_id=77, user_id=5, emoji=RSVP_EMOJI)
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_rsvp_role_added_on_bell_and_removed_on_unreact():
    role = FakeRole(10, "На стриме")
    member = FakeMember()
    cog, store, member = _rsvp_cog(guild=FakeGuild([role], member))
    await store.save(77)

    await cog._rsvp_role(_payload(), remove=False)
    assert member.added == [role]
    assert await store.granted_ids() == [5], "выдача роли запоминается для снятия в конце"

    await cog._rsvp_role(_payload(), remove=True)
    assert member.removed == [role]


@pytest.mark.asyncio
async def test_rsvp_role_env_id_overrides_name_lookup():
    role = FakeRole(10, "На стриме")
    member = FakeMember()
    cog, store, member = _rsvp_cog(guild=FakeGuild([role], member), role_id=10)
    await store.save(77)

    await cog._rsvp_role(_payload(), remove=False)
    assert member.added == [role]


@pytest.mark.asyncio
async def test_rsvp_role_ignores_foreign_message_wrong_emoji_and_bot():
    role = FakeRole(10, "На стриме")
    member = FakeMember()
    cog, store, member = _rsvp_cog(guild=FakeGuild([role], member))
    await store.save(77)

    await cog._rsvp_role(_payload(message_id=78), remove=False)
    await cog._rsvp_role(_payload(emoji="\U0001f44d"), remove=False)
    await cog._rsvp_role(_payload(user_id=999), remove=False)
    assert member.added == []


@pytest.mark.asyncio
async def test_rsvp_role_missing_role_warns_once_and_continues(caplog):
    member = FakeMember()
    cog, store, member = _rsvp_cog(guild=FakeGuild([], member))
    await store.save(77)

    with caplog.at_level("WARNING"):
        await cog._rsvp_role(_payload(), remove=False)
        await cog._rsvp_role(_payload(user_id=6), remove=False)

    warns = [r for r in caplog.records if "роль" in r.message]
    assert len(warns) == 1, "варн о пропавшей роли — один раз на guild"
    assert member.added == []


@pytest.mark.asyncio
async def test_rsvp_role_forbidden_is_logged_not_raised():
    role = FakeRole(10, "На стриме")
    member = FakeMember()
    member.fail = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "нет прав")
    cog, store, member = _rsvp_cog(guild=FakeGuild([role], member))
    await store.save(77)

    await cog._rsvp_role(_payload(), remove=False)  # не должно поднять исключение


# ------------------------------------------- гейт: вне эфира роль за 🔔 не выдаётся
@pytest.mark.asyncio
async def test_rsvp_role_not_granted_when_stream_offline():
    role = FakeRole(10, "На стриме")
    member = FakeMember()
    cog, store, member = _rsvp_cog(guild=FakeGuild([role], member), live=False)
    await store.save(77)

    await cog._rsvp_role(_payload(), remove=False)
    assert member.added == [], "анонс-сообщение есть, но стрим не идёт — роль не выдаётся"
    assert await store.granted_ids() == []


@pytest.mark.asyncio
async def test_rsvp_role_not_granted_without_session():
    role = FakeRole(10, "На стриме")
    member = FakeMember()
    cog, store, member = _rsvp_cog(guild=FakeGuild([role], member), has_session=False)
    await store.save(77)

    await cog._rsvp_role(_payload(), remove=False)
    assert member.added == [], "сессии стрима не было вовсе — роль не выдаётся"


@pytest.mark.asyncio
async def test_rsvp_role_remove_works_even_when_stream_offline():
    role = FakeRole(10, "На стриме")
    member = FakeMember()
    cog, store, member = _rsvp_cog(guild=FakeGuild([role], member), live=False)
    await store.save(77)

    await cog._rsvp_role(_payload(), remove=True)
    assert member.removed == [role], "снятие роли реакцией работает и после эфира"


# ------------------------------------------------ финал эфира: снятие роли и благодарность
class FakeAnnounceChannel:
    def __init__(self, guild: FakeGuild) -> None:
        self.guild = guild
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)


def _end_bot() -> SimpleNamespace:
    return SimpleNamespace(config=SimpleNamespace(stream_rsvp_role_id=None))


@pytest.mark.asyncio
async def test_granted_store_tracks_dedupes_and_clears():
    store = StreamRsvpStore(FakeKv(), "stream:rsvp:test")
    await store.add_granted(5)
    await store.add_granted(5)
    await store.add_granted(7)
    assert await store.granted_ids() == [5, 7]

    await store.clear()
    assert await store.granted_ids() == []


@pytest.mark.asyncio
async def test_rsvp_stream_end_removes_role_and_thanks_once():
    role = FakeRole(10, "На стриме")
    member = FakeMember()
    store = StreamRsvpStore(FakeKv(), "stream:rsvp:test")
    await store.add_granted(5)
    await store.add_granted(6)
    channel = FakeAnnounceChannel(FakeGuild([role], member))

    await rsvp_stream_end(_end_bot(), store=store, channel=channel)
    assert member.removed == [role, role]
    assert channel.sent == ["Спасибо, что пришли на стрим!"]
    assert await store.granted_ids() == []

    await rsvp_stream_end(_end_bot(), store=store, channel=channel)  # повтор — no-op
    assert member.removed == [role, role]
    assert channel.sent == ["Спасибо, что пришли на стрим!"]


@pytest.mark.asyncio
async def test_rsvp_stream_end_silent_without_granted_and_without_role():
    store = StreamRsvpStore(FakeKv(), "stream:rsvp:test")
    channel = FakeAnnounceChannel(FakeGuild([], FakeMember()))
    await rsvp_stream_end(_end_bot(), store=store, channel=channel)
    assert channel.sent == [], "без откликнувшихся благодарность не шлётся"

    await store.add_granted(5)
    await rsvp_stream_end(_end_bot(), store=store, channel=channel)
    assert channel.sent == ["Спасибо, что пришли на стрим!"], "роль не нашлась — благодарность всё равно"
