"""Smoke-тест: полная сборка бота без подключения к Discord."""
import os
import tempfile

import pytest

from app.config import Config
from app.core.bot import MegaBot


@pytest.mark.asyncio
async def test_bot_bootstrap():
    with tempfile.TemporaryDirectory() as tmp:
        config = Config(
            token="dummy-token",
            prefix="!",
            db_path=os.path.join(tmp, "bot.db"),
            log_level="ERROR",
            status_activity="test",
            owner_id=None,
        )
        bot = MegaBot(config)
        try:
            await bot.setup_hook()
            assert bot.db is not None
            assert bot.services is not None
            cog_names = {c.__class__.__name__ for c in bot.cogs.values()}
            assert len(cog_names) >= 19, f"Мало когов: {sorted(cog_names)}"
            for expected in (
                "GiveawaysCog",
                "PollsCog",
                "ReactionRolesCog",
                "RemindersCog",
                "SnipeCog",
                "UtilityCog",
                "WarnsCog",
                "RamReportCog",
                "DonationsCog",
            ):
                assert expected in cog_names, f"Не загружен ког {expected}"

            from app.services.audio.player import GuildPlayer

            player = bot.services.music.get_player(0)
            assert isinstance(player, GuildPlayer)
        finally:
            await bot.close()

        assert bot.db is None
