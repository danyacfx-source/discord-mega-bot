"""RamReport: периодический отчёт по ОЗУ бота в канал. Порт Node ``ram_report.js``."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import tasks

from app.core import embeds
from app.core.base import MegaCog, wait_ready_or_stop

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")

class RamReportCog(MegaCog, name="RamReport"):
    def __init__(self, bot: MegaBot) -> None:
        super().__init__(bot)

    async def cog_load(self) -> None:
        if self.bot.config.ram_report_channel_id is not None:
            self.ram_report_loop.change_interval(minutes=self.bot.config.ram_report_interval_minutes)
            self.ram_report_loop.start()
            logger.info(
                "Отчёт по ОЗУ: каждые %s мин в канал %s",
                self.bot.config.ram_report_interval_minutes,
                self.bot.config.ram_report_channel_id,
            )

    async def cog_unload(self) -> None:
        self.ram_report_loop.cancel()

    @tasks.loop(minutes=30)
    async def ram_report_loop(self) -> None:
        channel_id = self.bot.config.ram_report_channel_id
        if not channel_id:
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None or not isinstance(channel, discord.TextChannel):
            logger.warning("Канал %s для отчёта по ОЗУ не найден", channel_id)
            return
        current = self._rss_mb()
        peak = self._peak_mb()
        embed = embeds.neutral("Монитор памяти", "Автоматическая диагностика процесса бота «Асуна Юки».")
        embed.add_field(name="СЕЙЧАС", value=f"`{current:.1f} MB`", inline=True)
        embed.add_field(name="ПИК", value=f"`{peak:.1f} MB`", inline=True)
        embed.add_field(name="ИНТЕРВАЛ", value=f"`{self.bot.config.ram_report_interval_minutes} min`", inline=True)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.exception("Ошибка отправки отчёта по ОЗУ")

    @ram_report_loop.before_loop
    async def before_ram_report_loop(self) -> None:
        await wait_ready_or_stop(self.bot, self.ram_report_loop)

    def _rss_mb(self) -> float:
        import psutil

        return psutil.Process().memory_info().rss / (1024 * 1024)

    def _peak_mb(self) -> float:
        import psutil

        info = psutil.Process().memory_info()
        peak = getattr(info, "peak_wset", None)
        if peak is not None:
            return peak / (1024 * 1024)
        return info.rss / (1024 * 1024)
