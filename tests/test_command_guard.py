"""Guard: rate-limit инвоков команд, kill-switch и его интеграция с деревом команд."""
from __future__ import annotations

import dataclasses
import os
import tempfile
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord

from app.config import Config
from app.core.bot import MegaBot
from app.core.composition import assemble
from app.services.command_guard_service import CommandGuardService
from app.services.kv_service import KvService


class _DictRepo:
    """KV-репозиторий на словаре: тот же контракт, что и у KvRepository."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.fail = False

    async def get(self, key: str, default: str | None = None) -> str | None:
        if self.fail:
            raise RuntimeError("kv down")
        return self.data.get(key, default)

    async def set(self, key: str, value: str) -> None:
        if self.fail:
            raise RuntimeError("kv down")
        self.data[key] = value

    async def delete(self, key: str) -> bool:
        if self.fail:
            raise RuntimeError("kv down")
        return self.data.pop(key, None) is not None


def _config(tmp: str, **overrides: Any) -> Config:
    cfg = Config(
        token="x",
        prefix="!",
        db_path=os.path.join(tmp, "bot.db"),
        log_level="ERROR",
        status_activity="s",
        owner_id=None,
    )
    return dataclasses.replace(cfg, **overrides) if overrides else cfg


def _guard(cfg: Config, kv: KvService | None = None) -> CommandGuardService:
    return CommandGuardService(cfg, kv or KvService(_DictRepo()))


def _verdict(svc: CommandGuardService, *, user: int = 1, guild: int | None = 10, command: str = "ping", bypass: bool = False):
    return svc.check(user, guild, command, bypass=bypass)


# --- лимиты ---


def test_allows_within_limits() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        svc = _guard(_config(tmp, guard_user_max=3, guard_user_window=60.0))
        assert all(_verdict(svc).allowed for _ in range(3))


def test_user_window_blocks_and_reports_retry() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        svc = _guard(_config(tmp, guard_user_max=2, guard_user_window=60.0))
        assert _verdict(svc).allowed
        assert _verdict(svc).allowed

        verdict = _verdict(svc)
        assert verdict.allowed is False
        assert verdict.retry_after > 0
        assert verdict.reason
        assert svc.blocked_total == 1


def test_blocked_attempt_does_not_extend_window() -> None:
    """Отклонённый вызов не записывается в бакет — иначе спам делает лок вечным."""
    with tempfile.TemporaryDirectory() as tmp:
        svc = _guard(_config(tmp, guard_user_max=1, guard_user_window=60.0))
        assert _verdict(svc).allowed
        for _ in range(10):
            assert _verdict(svc).allowed is False
        assert len(svc._user_hits[1]) == 1


def test_guild_window_independent_from_user() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _config(tmp, guard_user_max=100, guard_guild_max=3, guard_guild_window=60.0)
        svc = _guard(cfg)
        assert _verdict(svc, user=1).allowed
        assert _verdict(svc, user=2).allowed
        assert _verdict(svc, user=3).allowed
        verdict = _verdict(svc, user=4)
        assert verdict.allowed is False
        assert "сервере" in verdict.reason


def test_window_lets_user_through_after_expiry() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        svc = _guard(_config(tmp, guard_user_max=1, guard_user_window=0.01))
        assert _verdict(svc).allowed
        assert _verdict(svc).allowed is False
        import time

        time.sleep(0.05)
        assert _verdict(svc).allowed


def test_disabled_guard_allows_everything() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        svc = _guard(_config(tmp, guard_enabled=False, guard_user_max=1, guard_user_window=60.0))
        assert all(_verdict(svc).allowed for _ in range(50))
        assert svc.blocked_total == 0


def test_bypass_skips_limits() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        svc = _guard(_config(tmp, guard_user_max=1, guard_user_window=60.0))
        assert all(_verdict(svc, bypass=True).allowed for _ in range(50))


def test_windows_do_not_leak_keys() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        svc = _guard(_config(tmp, guard_user_max=100, guard_user_window=0.01))
        for user_id in range(50):
            _verdict(svc, user=user_id)
        import time

        time.sleep(0.05)
        for user_id in range(50, 100):
            _verdict(svc, user=user_id)
        # _prune срабатывает каждые 512 проверок; 100 хватает, чтобы ключи ушли
        svc._checks = 511
        _verdict(svc)
        assert len(svc._user_hits) <= 1


# --- kill-switch ---


async def test_pause_blocks_all_commands() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        svc = _guard(_config(tmp))
        await svc.set_paused(True)
        verdict = _verdict(svc)
        assert verdict.allowed is False
        assert "обслуживания" in verdict.reason
        # пауза не копит счётчик лимита
        assert len(svc._user_hits[1]) == 0


async def test_resume_restores_commands() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        svc = _guard(_config(tmp))
        await svc.set_paused(True)
        assert _verdict(svc).allowed is False
        await svc.set_paused(False)
        assert _verdict(svc).allowed


async def test_block_and_unblock_command() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        svc = _guard(_config(tmp))
        assert await svc.block_command("Purge") is True
        assert await svc.block_command("purge") is False
        assert _verdict(svc, command="purge").allowed is False
        assert _verdict(svc, command="ping").allowed is True

        assert await svc.unblock_command("purge") is True
        assert await svc.unblock_command("purge") is False
        assert _verdict(svc, command="purge").allowed is True


async def test_mute_and_unmute_guild() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        svc = _guard(_config(tmp))
        assert await svc.mute_guild(10) is True
        assert await svc.mute_guild(10) is False
        verdict = _verdict(svc, guild=10)
        assert verdict.allowed is False
        assert "сервере" in verdict.reason
        assert svc.blocked_total == 1
        # соседний сервер не затронут
        assert _verdict(svc, guild=11, user=2).allowed is True

        assert await svc.unmute_guild(10) is True
        assert _verdict(svc, guild=10, user=3).allowed is True


async def test_kill_switch_survives_restart() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = _DictRepo()
        cfg = _config(tmp)
        first = _guard(cfg, KvService(repo))
        await first.set_paused(True)
        await first.block_command("purge")
        await first.mute_guild(77)

        second = _guard(cfg, KvService(repo))
        await second.load()
        assert second.paused is True
        assert second.blocked_commands == ("purge",)
        assert second.muted_guilds == (77,)
        assert _verdict(second).allowed is False


async def test_kv_failure_keeps_guard_enabled() -> None:
    """Падение KV не должно молча выключать guard — остаются настройки окружения."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _DictRepo()
        repo.fail = True
        svc = _guard(_config(tmp, guard_user_max=1, guard_user_window=60.0), KvService(repo))
        await svc.load()
        assert svc.loaded is True
        assert svc.paused is False
        assert _verdict(svc).allowed
        assert _verdict(svc).allowed is False


async def test_persist_failure_keeps_in_memory_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = _DictRepo()
        svc = _guard(_config(tmp), KvService(repo))
        repo.fail = True
        await svc.set_paused(True)
        assert svc.paused is True
        assert _verdict(svc).allowed is False


def test_snapshot_reports_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        svc = _guard(_config(tmp))
        _verdict(svc)
        state = svc.snapshot()
        assert state["enabled"] is True
        assert state["paused"] is False
        assert state["limits"]["user_max"] == Config.__dataclass_fields__["guard_user_max"].default
        assert state["checks"] == 1


# --- интеграция с деревом команд ---


def _interaction(*, user_id: int = 1, guild_id: int | None = 10, name: str = "ping") -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.type = discord.InteractionType.application_command
    interaction.guild_id = guild_id
    interaction.command = MagicMock(qualified_name=name)
    interaction.user = MagicMock(id=user_id)
    interaction.response.is_done.return_value = False
    interaction.response.send_message = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


async def _bot_with_guard(tmp: str, **overrides: Any) -> MegaBot:
    from app.db.database import Database

    bot = MegaBot(_config(tmp, **overrides))
    bot.db = Database(os.path.join(tmp, "bot.db"))
    await bot.db.connect()
    assemble(config=bot.config, db=bot.db, bot=bot)
    await bot._install_guards()
    return bot


async def test_tree_check_allows_normal_invocation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bot = await _bot_with_guard(tmp, guard_user_max=3, guard_user_window=60.0)
        try:
            assert await bot.tree.interaction_check(_interaction()) is True
        finally:
            await bot.close()


async def test_tree_check_blocks_and_explains() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bot = await _bot_with_guard(tmp, guard_user_max=1, guard_user_window=60.0)
        try:
            assert await bot.tree.interaction_check(_interaction()) is True
            blocked = _interaction(user_id=1)
            assert await bot.tree.interaction_check(blocked) is False
            blocked.response.send_message.assert_awaited_once()
            text = blocked.response.send_message.call_args.args[0]
            assert "Повторите через" in text
        finally:
            await bot.close()


async def test_tree_check_names_blocked_command() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bot = await _bot_with_guard(tmp)
        try:
            await bot.services.guard.block_command("purge")
            interaction = _interaction(name="purge")
            assert await bot.tree.interaction_check(interaction) is False
            interaction.response.send_message.assert_awaited_once()
        finally:
            await bot.close()


async def test_tree_check_keeps_autocomplete_unblocked() -> None:
    """Autocomplete нельзя ответить сообщением — guard его не тормозит."""
    with tempfile.TemporaryDirectory() as tmp:
        bot = await _bot_with_guard(tmp, guard_user_max=1, guard_user_window=60.0)
        try:
            assert await bot.tree.interaction_check(_interaction()) is True
            autocomplete = _interaction()
            autocomplete.type = discord.InteractionType.autocomplete
            assert await bot.tree.interaction_check(autocomplete) is True
        finally:
            await bot.close()


async def test_owner_bypasses_limits() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bot = await _bot_with_guard(tmp, guard_user_max=1, guard_user_window=60.0, owner_id=42)
        try:
            assert await bot.tree.interaction_check(_interaction(user_id=42)) is True
            assert await bot.tree.interaction_check(_interaction(user_id=42)) is True
            assert await bot.tree.interaction_check(_interaction(user_id=1)) is True
            assert await bot.tree.interaction_check(_interaction(user_id=1)) is False
        finally:
            await bot.close()


async def test_guard_cog_loads_through_composition() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        bot = await _bot_with_guard(tmp)
        try:
            from app.cogs.administration.guard import GuardCog
            from app.core.loader import load_cogs

            loaded = await load_cogs(bot)
            assert any(name.endswith("administration.guard") for name in loaded), loaded

            # loader уже прошёл по всем модулям — ког обязан быть собран и получить синглтон
            cog = bot.get_cog("Administration")
            assert isinstance(cog, GuardCog)
            assert cog.guard is bot.services.guard
        finally:
            await bot.close()
