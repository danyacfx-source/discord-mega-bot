"""Heartbeat: алерт в канал логов о тишине бота, нехватке диска и деградации шлюза.

Три независимых детектора в одном тике:
- тишина: нет сообщений дольше ``heartbeat_silence_minutes`` (любое сообщение
  сбрасывает счётчик; один эпизод — один алерт);
- диск: свободно меньше ``disk_alert_mb`` рядом с файлом БД (перевзводится,
  когда места снова хватает);
- латентность: ``bot.latency`` стабильно выше ``latency_alert_seconds``
  несколько тиков подряд (перевзводится после улучшения).

Дополнительно ловится залипание: сообщение, чей created_at старше порога тишины,
значит event loop или шлюз Discord зависали — алерт уходит сразу.
"""
from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from app.core import embeds
from app.core.base import MegaCog, wait_ready_or_stop
from app.services.settings_service import SettingsService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")

#: Сколько тиков подряд латентность должна быть выше порога до алерта.
_LATENCY_STRIKES = 3


class HeartbeatCog(MegaCog, name="Heartbeat"):
    def __init__(self, bot: MegaBot, settings: SettingsService) -> None:
        super().__init__(bot)
        self.settings = settings
        self._last_activity = datetime.now(UTC)
        self._alerted = False
        self._disk_alerted = False
        self._latency_alerted = False
        self._latency_strikes = 0

    async def cog_load(self) -> None:
        minutes = self.bot.config.heartbeat_silence_minutes
        if self._enabled():
            interval = max(1, min(30, minutes // 4)) if minutes > 0 else 5
            self.silence_loop.change_interval(minutes=interval)
            self.silence_loop.start()
            logger.info(
                "Heartbeat: включены проверки (тишина=%s мин, диск=%s МБ, латентность=%s с), тик каждые %s мин",
                minutes,
                self.bot.config.disk_alert_mb,
                self.bot.config.latency_alert_seconds,
                interval,
            )

    async def cog_unload(self) -> None:
        self.silence_loop.cancel()

    def _enabled(self) -> bool:
        config = self.bot.config
        return (
            config.heartbeat_silence_minutes > 0
            or config.disk_alert_mb > 0
            or config.latency_alert_seconds > 0
        )

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
        """Один прогон всех проверок; вызывается из silence_loop (и в тестах)."""
        reasons: list[str] = []
        silence = False
        config = self.bot.config

        if config.heartbeat_silence_minutes > 0 and not self._alerted:
            threshold = timedelta(minutes=config.heartbeat_silence_minutes)
            silenced = datetime.now(UTC) - self._last_activity
            if silenced >= threshold:
                reasons.append(f"нет сообщений уже {self._fmt(silenced)}")
                silence = True

        disk_reason = self._disk_check()
        if disk_reason:
            reasons.append(disk_reason)

        latency_reason = self._latency_check()
        if latency_reason:
            reasons.append(latency_reason)

        if reasons:
            await self._send_alert(reasons, silence=silence)

    def _disk_check(self) -> str | None:
        threshold_mb = self.bot.config.disk_alert_mb
        if threshold_mb <= 0:
            return None
        try:
            target = Path(self.bot.config.db_path)
            directory = target if target.is_dir() else target.parent
            free_mb = shutil.disk_usage(directory).free // (1024 * 1024)
        except OSError:
            logger.warning("Heartbeat: не удалось проверить свободное место на диске", exc_info=True)
            return None
        if free_mb < threshold_mb:
            if not self._disk_alerted:
                self._disk_alerted = True
                return f"на диске осталось {free_mb} МБ свободно (порог {threshold_mb} МБ)"
            return None
        self._disk_alerted = False  # места хватает — перевзводим детектор
        return None

    def _latency_check(self) -> str | None:
        threshold = self.bot.config.latency_alert_seconds
        if threshold <= 0:
            return None
        latency = self.bot.latency  # секунды; -1/inf до готовности шлюза
        if latency is None or latency < 0 or latency == float("inf"):
            self._latency_strikes = 0
            return None
        if latency >= threshold:
            self._latency_strikes += 1
            if self._latency_strikes >= _LATENCY_STRIKES and not self._latency_alerted:
                self._latency_alerted = True
                return f"Discord-шлюз деградировал: {latency * 1000:.0f} мс (порог {threshold * 1000:.0f} мс)"
            return None
        self._latency_strikes = 0
        if latency < threshold / 2:
            self._latency_alerted = False
        return None

    @silence_loop.before_loop
    async def _before_silence(self) -> None:
        if not await wait_ready_or_stop(self.bot, self.silence_loop):
            return
        # Сразу после старта активности ещё не было — окно считаем с готовности.
        self._last_activity = datetime.now(UTC)

    async def _send_alert(self, reasons: list[str], *, silence: bool = True) -> None:
        if silence:
            self._alerted = True
        targets = await self._log_targets()
        if not targets:
            logger.warning("Heartbeat: обнаружена проблема (%s), но канал логов не настроен", "; ".join(reasons))
            return
        embed = embeds.warning(
            "Heartbeat: бот не в порядке",
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
