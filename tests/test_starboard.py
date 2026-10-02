"""Тесты starboard: публикация по порогу, редактирование, удаление ниже порога."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.cogs.general.starboard import StarboardCog
from app.config import Config


def _config(**overrides) -> Config:
    config = Config(
        token="x",
        prefix="!",
        db_path="bot.db",
        log_level="ERROR",
        status_activity="s",
        owner_id=None,
    )
    for key, value in overrides.items():
        object.__setattr__(config, key, value)
    return config


def _kv(store: dict[str, str] | None = None) -> SimpleNamespace:
    data = store if store is not None else {}

    async def get(key: str) -> str | None:
        return data.get(key)

    async def set_(key: str, value: str) -> None:
        data[key] = value

    async def delete(key: str) -> None:
        data.pop(key, None)

    return SimpleNamespace(get=get, set=set_, delete=delete, _data=data)


def _users(*users) -> object:
    async def gen():
        for user in users:
            yield user

    return gen


class _Target:
    def __init__(self) -> None:
        self.name = "starboard"
        self.id = 555
        self.sent: list = []
        self.star_message = SimpleNamespace(edit=AsyncMock(), delete=AsyncMock())
        self.fetch_message = AsyncMock(return_value=self.star_message)
        self.send = AsyncMock(side_effect=self._send)

    async def _send(self, embed) -> SimpleNamespace:
        msg = SimpleNamespace(id=9000 + len(self.sent), embed=embed)
        self.sent.append(msg)
        return msg


def _guild(target: _Target) -> SimpleNamespace:
    return SimpleNamespace(get_channel=lambda cid: target if cid == 555 else None)


def _message(guild, channel_id: int = 100, author_bot: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        content="привет мир",
        jump_url="https://discord.com/channels/1/100/42",
        author=SimpleNamespace(bot=author_bot, display_name="Alice", display_avatar=SimpleNamespace(url="http://x/a.png")),
        channel=SimpleNamespace(id=channel_id, name="general", guild=guild),
        attachments=[],
    )


def _reaction(users, message, emoji: str = "⭐") -> SimpleNamespace:
    return SimpleNamespace(emoji=emoji, message=message, users=_users(*users))


def _cog(config=None, kv=None) -> tuple[StarboardCog, SimpleNamespace]:
    config = config or _config(starboard_channel_id=555)
    kv = kv or _kv()
    bot = SimpleNamespace(config=config)
    return StarboardCog(bot, kv), bot  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_disabled_when_no_channel() -> None:
    cog, _ = _cog(config=_config(starboard_channel_id=None))
    target = _Target()
    guild = _guild(target)
    message = _message(guild)
    user = SimpleNamespace(bot=False)

    await cog.on_reaction_add(_reaction([user, SimpleNamespace(bot=False)], message), user)  # type: ignore[arg-type]

    target.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_publishes_at_threshold_and_stores_kv() -> None:
    kv = _kv()
    cog, _ = _cog(kv=kv)
    target = _Target()
    guild = _guild(target)
    message = _message(guild)
    reaction = _reaction([SimpleNamespace(bot=False) for _ in range(5)], message)

    await cog._sync(reaction)

    target.send.assert_awaited_once()
    embed = target.send.await_args.kwargs["embed"]
    assert embed.title == "⭐ 5"
    assert "привет мир" in embed.description
    assert kv._data["starboard:42"] == json.dumps({"channel_id": 555, "msg_id": 9000})


@pytest.mark.asyncio
async def test_below_threshold_does_not_publish() -> None:
    cog, _ = _cog()
    target = _Target()
    message = _message(_guild(target))
    reaction = _reaction([SimpleNamespace(bot=False) for _ in range(4)], message)

    await cog._sync(reaction)

    target.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_second_sync_edits_existing_star_message() -> None:
    kv = _kv({"starboard:42": json.dumps({"channel_id": 555, "msg_id": 777})})
    cog, _ = _cog(kv=kv)
    target = _Target()
    message = _message(_guild(target))
    reaction = _reaction([SimpleNamespace(bot=False) for _ in range(6)], message)

    await cog._sync(reaction)

    target.send.assert_not_awaited()
    target.fetch_message.assert_awaited_once_with(777)
    target.star_message.edit.assert_awaited_once()
    edited = target.star_message.edit.await_args.kwargs["embed"]
    assert edited.title == "⭐ 6"


@pytest.mark.asyncio
async def test_repost_when_star_message_was_deleted() -> None:
    kv = _kv({"starboard:42": json.dumps({"channel_id": 555, "msg_id": 777})})
    cog, _ = _cog(kv=kv)
    target = _Target()
    target.fetch_message = AsyncMock(side_effect=Exception("missing"))

    message = _message(_guild(target))
    reaction = _reaction([SimpleNamespace(bot=False) for _ in range(5)], message)

    await cog._sync(reaction)

    assert target.send.await_count == 1
    assert json.loads(kv._data["starboard:42"])["msg_id"] == 9000


@pytest.mark.asyncio
async def test_removal_below_threshold_deletes_star_message() -> None:
    kv = _kv({"starboard:42": json.dumps({"channel_id": 555, "msg_id": 777})})
    cog, _ = _cog(kv=kv)
    target = _Target()
    message = _message(_guild(target))
    reaction = _reaction([SimpleNamespace(bot=False) for _ in range(4)], message)

    await cog._sync(reaction)

    target.fetch_message.assert_awaited_once_with(777)
    target.star_message.delete.assert_awaited_once()
    assert "starboard:42" not in kv._data


@pytest.mark.asyncio
async def test_ignores_wrong_emoji_bot_users_and_bot_messages() -> None:
    cog, _ = _cog()
    target = _Target()
    guild = _guild(target)

    wrong = _reaction([SimpleNamespace(bot=False)], _message(guild), emoji="🔥")
    await cog.on_reaction_add(wrong, SimpleNamespace(bot=False))  # type: ignore[arg-type]

    bot_user = SimpleNamespace(bot=True)
    await cog.on_reaction_add(
        _reaction([bot_user], _message(guild)), bot_user  # type: ignore[arg-type]
    )

    bot_msg = _message(guild, author_bot=True)
    await cog.on_reaction_add(
        _reaction([SimpleNamespace(bot=False)] * 9, bot_msg), SimpleNamespace(bot=False)  # type: ignore[arg-type]
    )

    target.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_ignores_dms() -> None:
    cog, _ = _cog()
    message = SimpleNamespace(
        id=42,
        content="x",
        jump_url="",
        author=SimpleNamespace(bot=False, display_name="A", display_avatar=SimpleNamespace(url="u")),
        channel=SimpleNamespace(id=1, name="dm", guild=None),
        attachments=[],
    )
    reaction = _reaction([SimpleNamespace(bot=False) for _ in range(9)], message)

    await cog._sync(reaction)  # не должно падать и не должно слать


@pytest.mark.asyncio
async def test_embed_includes_image_and_footer() -> None:
    cog, _ = _cog()
    target = _Target()
    guild = _guild(target)
    message = _message(guild)
    message.attachments = [SimpleNamespace(url="http://x/pic.png")]

    embed = cog._star_embed(message, 7)

    assert embed.title == "⭐ 7"
    assert embed.image.url == "http://x/pic.png"
    assert embed.footer.text == "#general"
    assert "перейти к сообщению" in embed.description
