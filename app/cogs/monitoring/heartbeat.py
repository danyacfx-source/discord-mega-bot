"""Heartbeat: алерт в канал логов, если бот молчит дольше N минут.

Любое сообщение (входящее или отправленное ботом) сбрасывает счётчик тишины.
Один эпизод тишины — один алерт: после отправки ког ждёт новой активности.
Дополнительно ловится «залипание»: сообщение, чей created_at старше порога,
значит event loop или шлюз Discord зависали — алерт уходит сразу.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from app.core import embeds
from app.core.base import MegaCog
from app.services.settings_service import SettingsService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")


class HeartbeatCog(MegaCog, name="Heartbeat"):
    def __init__(self, bot: MegaBot, settings: SettingsService) -> None:
        super().__init__(bot)
        self.settings = settings
        self._last_activity = datetime.now(UTC)
        self._alerted = False

    async def cog_load(self) -> None:
        minutes = self.bot.config.heartbeat_silence_minutes
        if minutes > 0:
            self.silence_loop.change_interval(minutes=max(1, min(30, minutes // 4)))
            self.silence_loop.start()
            logger.info("Heartbeat: алерт о тишине бота дольше %s мин в канал(ы) логов", minutes)

    async def cog_unload(self) -> None:
        self.silence_loop.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        now = datetime.now(UTC)
        was_alerted = self._alerted
        self._last_activity = now
        self._alerted = False
        if self.bot.config.heartbeat_silence_minutes <= 0:
            return
        threshold = timedelta(minutes=self.bot.config.heartbeat_silence_minutes)
        created = message.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        backlog = now - created
        if backlog >= threshold and not was_alerted:
            # Сообщение доехало с опозданием — event loop вис или шлюз отставал.
            await self._send_alert([f"сообщение обработано с опозданием на {self._fmt(backlog)}"])

    @tasks.loop(minutes=5)
    async def silence_loop(self) -> None:
        await self._tick()

    async def _tick(self) -> None:
        """Проверка тишины; вызывается из silence_loop (и напрямую в тестах)."""
        if self.bot.config.heartbeat_silence_minutes <= 0 or self._alerted:
            return
        threshold = timedelta(minutes=self.bot.config.heartbeat_silence_minutes)
        silenced = datetime.now(UTC) - self._last_activity
        if silenced >= threshold:
            await self._send_alert([f"нет сообщений уже {self._fmt(silenced)}"])

    @silence_loop.before_loop
    async def _before_silence(self) -> None:
        await self.bot.wait_until_ready()
        # Сразу после старта активности ещё не было — окно считаем с готовности.
        self._last_activity = datetime.now(UTC)

    async def _send_alert(self, reasons: list[str]) -> None:
        self._alerted = True
        targets = await self._log_targets()
        if not targets:
            logger.warning("Heartbeat: тишина обнаружена (%s), но канал логов не настроен", "; ".join(reasons))
            return
        embed = embeds.warning(
            "Heartbeat: бот молчит",
            "\n".join(f"• {reason}" for reason in reasons)
            + f"\nПоследняя активность: <t:{int(self._last_activity.timestamp())}:R>.",
        )
        for channel in targets:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                logger.exception(
                    "Heartbeat: не удалось отправить алерт в #%s",
                    getattr(channel, "name", channel.id),
                )

    async def _log_targets(self) -> list[discord.abc.Messageable]:
        """Все каналы «Бот» из настроек гильдий с fallback на BOT_LOG_CHANNEL_ID.

        Дедупликация по id: env-канал один на всех, алерт уходит один раз.
        """
        targets: dict[int, discord.abc.Messageable] = {}
        for guild in self.bot.guilds:
            settings = await self.settings.get(guild.id)
            channel_id = settings.get("bot_log_channel_id") or self.bot.config.bot_log_channel_id
            if not channel_id:
                continue
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                targets[channel.id] = channel
        return list(targets.values())

    @staticmethod
    def _fmt(delta: timedelta) -> str:
        minutes = max(1, int(delta.total_seconds() // 60))
        return f"{minutes} мин"
