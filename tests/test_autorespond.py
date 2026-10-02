"""Тесты автореспондера: триггеры, кулдаун, выдача роли, игнор ботов/ЛС."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.cogs.general.autorespond import AutorespondCog
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


def _cog(**config_overrides) -> AutorespondCog:
    config = _config(**{"autorespond_cooldown": 0, **config_overrides})
    return AutorespondCog(SimpleNamespace(config=config))  # type: ignore[arg-type]


def _message(content: str, *, bot: bool = False, dm: bool = False) -> SimpleNamespace:
    member = SimpleNamespace(
        id=7,
        bot=bot,
        roles=[],
        add_roles=AsyncMock(),
    )
    role = object()
    guild = None if dm else SimpleNamespace(id=1, get_role=lambda rid: role if rid == 55 else None,
                                            get_member=lambda uid: member)
    channel = SimpleNamespace(send=AsyncMock())
    return SimpleNamespace(content=content, author=member, guild=guild, channel=channel)


@pytest.mark.asyncio
async def test_rule_replies_on_substring_match() -> None:
    cog = _cog(autorespond_rules=(("привет", "Здрасте!"),))
    message = _message("ПРИВЕТ, мир")  # регистр не важен

    await cog.on_message(message)  # type: ignore[arg-type]

    message.channel.send.assert_awaited_once_with("Здрасте!")


@pytest.mark.asyncio
async def test_no_match_sends_nothing() -> None:
    cog = _cog(autorespond_rules=(("привет", "Здрасте!"),))
    message = _message("пока")

    await cog.on_message(message)  # type: ignore[arg-type]

    message.channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_cooldown_blocks_second_reply() -> None:
    cog = _cog(autorespond_rules=(("привет", "хай"),), autorespond_cooldown=60)
    first = _message("привет")
    second = _message("привет")

    await cog.on_message(first)  # type: ignore[arg-type]
    await cog.on_message(second)  # type: ignore[arg-type]

    first.channel.send.assert_awaited_once()
    second.channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_matching_rule_wins() -> None:
    cog = _cog(autorespond_rules=(("бот", "первый"), ("привет", "второй")))
    message = _message("привет, бот")

    await cog.on_message(message)  # type: ignore[arg-type]

    message.channel.send.assert_awaited_once_with("первый")


@pytest.mark.asyncio
async def test_role_granted_on_exact_phrase_only() -> None:
    cog = _cog(
        autorespond_role_phrases=("Гайд полный",),
        autorespond_role_id=55,
    )
    exact = _message("гайд полный")
    substring = _message("гайд полный в описании")

    await cog.on_message(exact)  # type: ignore[arg-type]
    await cog.on_message(substring)  # type: ignore[arg-type]

    exact.author.add_roles.assert_awaited_once()
    role_arg = exact.author.add_roles.await_args.args[0]
    assert role_arg is not None
    substring.author.add_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_role_not_granted_when_role_id_disabled() -> None:
    cog = _cog(autorespond_role_phrases=("гайд",), autorespond_role_id=None)
    message = _message("гайд")

    await cog.on_message(message)  # type: ignore[arg-type]

    message.author.add_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_ignores_bots_and_dms() -> None:
    cog = _cog(autorespond_rules=(("привет", "хай"),))
    bot_msg = _message("привет", bot=True)
    dm_msg = _message("привет", dm=True)

    await cog.on_message(bot_msg)  # type: ignore[arg-type]
    await cog.on_message(dm_msg)  # type: ignore[arg-type]

    bot_msg.channel.send.assert_not_awaited()
    dm_msg.channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_config_is_noop() -> None:
    cog = _cog()
    message = _message("что угодно")

    await cog.on_message(message)  # type: ignore[arg-type]

    message.channel.send.assert_not_awaited()


def test_env_rules_parsing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("AUTORESPOND_RULES", "Привет=>Здрасте!|пока=>бай|мусор без стрелки")
    monkeypatch.setenv("AUTORESPOND_ROLE_RULES", "гайд, лор")
    monkeypatch.setenv("AUTORESPOND_ROLE_ID", "55")
    monkeypatch.setenv("AUTORESPOND_COOLDOWN", "7")

    config = Config.from_env(tmp_path / "absent.env")

    assert config.autorespond_rules == (("привет", "Здрасте!"), ("пока", "бай"))
    assert config.autorespond_role_phrases == ("гайд", "лор")
    assert config.autorespond_role_id == 55
    assert config.autorespond_cooldown == 7
