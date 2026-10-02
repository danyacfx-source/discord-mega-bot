"""Ежедневный дайджест: статистика суток в канал логов.

Считает сообщения/входы/выходы сам (память → KV-флеш раз в минуту, чтобы
пережить рестарт в пределах окна), модерацию читает из moderation_cases,
эфиры — из архива стримов. Публикует один раз в сутки в digest_hour
(локальное время stream_quiet_tz), дубль-флаг лежит в KV.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands, tasks

from app.cogs.streams.quiet import resolve_tz
from app.core import embeds
from app.core.base import MegaCog
from app.services.kv_service import KvService
from app.services.logging_service import LoggingService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")

#: Сколько дней счётчиков хранится в KV.
_COUNTS_RETENTION_DAYS = 21
#: Сколько дней хранятся флаги «опубликовано».
_POSTED_RETENTION_DAYS = 45
#: Разделители действий модерации в дайджесте.
_ACTION_LABELS = {
    "warn": "⚠ варны",
    "timeout": "⏳ тайм-ауты",
    "kick": "👢 кики",
    "ban": "🔨 баны",
    "unban": "♻ разбаны",
}


class DigestCog(MegaCog, name="Digest"):
    def __init__(self, bot: MegaBot, logging: LoggingService, kv: KvService) -> None:
        super().__init__(bot)
        self.logging = logging
        self.kv = kv
        # (guild_id, локальная дата) → {"messages": n, "joins": n, "leaves": n}
        self._counts: dict[tuple[int, str], dict[str, int]] = {}
        # Сколько уже выгружено в KV по каждому ключу (для дельт).
        self._flushed: dict[tuple[int, str], dict[str, int]] = {}

    # ------------------------------------------------------------- lifecycle

    async def cog_load(self) -> None:
        if self.bot.config.digest_hour >= 0:
            self.check_loop.start()
            self.flush_loop.start()
            logger.info(
                "Digest: дайджест в %02d:00 (%s), тик каждые 10 мин",
                self.bot.config.digest_hour,
                self.bot.config.stream_quiet_tz,
            )

    async def cog_unload(self) -> None:
        self.check_loop.cancel()
        self.flush_loop.cancel()
        try:
            await self._flush()
        except Exception:
            logger.debug("Digest: не удалось выгрузить счётчики при остановке", exc_info=True)

    # ------------------------------------------------------------- счётчики

    def _bump(self, guild_id: int, field: str) -> None:
        date = self._local_now().date().isoformat()
        key = (guild_id, date)
        counts = self._counts.setdefault(key, {"messages": 0, "joins": 0, "leaves": 0})
        counts[field] = counts.get(field, 0) + 1

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        self._bump(message.guild.id, "messages")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not member.bot:
            self._bump(member.guild.id, "joins")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if not member.bot:
            self._bump(member.guild.id, "leaves")

    def _local_now(self) -> datetime:
        return datetime.now(resolve_tz(self.bot.config.stream_quiet_tz))

    def _counts_key(self, guild_id: int, date: str) -> str:
        return f"digest:counts:{guild_id}:{date}"

    def _posted_key(self, guild_id: int, date: str) -> str:
        return f"digest:posted:{guild_id}:{date}"

    @tasks.loop(seconds=60)
    async def flush_loop(self) -> None:
        try:
            await self._flush()
        except Exception:
            logger.warning("Digest: не удалось выгрузить счётчики в KV", exc_info=True)

    async def _flush(self) -> None:
        """Сохраняет дельты накопленных счётчиков в KV (идемпотентно к рестарту)."""
        for key, counts in list(self._counts.items()):
            guild_id, date = key
            flushed = self._flushed.setdefault(key, {f: 0 for f in counts})
            payload = dict(json.loads(await self.kv.get(self._counts_key(guild_id, date)) or "{}"))
            changed = False
            for field, value in counts.items():
                delta = value - flushed.get(field, 0)
                if delta:
                    payload[field] = int(payload.get(field, 0)) + delta
                    flushed[field] = value
                    changed = True
            if changed:
                await self.kv.set(self._counts_key(guild_id, date), json.dumps(payload))

    # ------------------------------------------------------------- публикация

    @tasks.loop(minutes=10)
    async def check_loop(self) -> None:
        await self._check()

    async def _check(self) -> None:
        """Публикация дайджеста за вчера, если наступил digest_hour; в тестах зовётся напрямую."""
        now = self._local_now()
        if now.hour != self.bot.config.digest_hour:
            return
        for guild in list(self.bot.guilds):
            date = now.date().isoformat()
            try:
                if await self.kv.get(self._posted_key(guild.id, date)):
                    continue
                await self._publish(guild, now.date() - timedelta(days=1))
                await self.kv.set(self._posted_key(guild.id, date), "1")
                await self._trim(guild.id, now.date())
            except Exception:
                logger.exception("Digest: не удалось построить дайджест для %s", guild.name)

    @check_loop.before_loop
    async def _before_check(self) -> None:
        await self._wait_ready_or_stop(self.check_loop)

    @flush_loop.before_loop
    async def _before_flush(self) -> None:
        await self._wait_ready_or_stop(self.flush_loop)

    async def _wait_ready_or_stop(self, loop: tasks.Loop) -> None:
        """Клиент вне логина (тесты) кидает RuntimeError — гасим цикл штатно."""
        try:
            await self.bot.wait_until_ready()
        except RuntimeError:
            loop.stop()  # до первой итерации stop() завершает цикл без ошибок

    async def _publish(self, guild: discord.Guild, day: datetime.date) -> None:
        start = datetime.combine(day, time.min, tzinfo=resolve_tz(self.bot.config.stream_quiet_tz))
        end = start + timedelta(days=1)
        counts = json.loads(await self.kv.get(self._counts_key(guild.id, day.isoformat())) or "{}")

        embed = embeds.neutral(
            f"📊 Дайджест за {day.strftime('%d.%m.%Y')}",
            f"Сутки по времени {self.bot.config.stream_quiet_tz}.",
        )

        embed.add_field(
            name="💬 Сообщений",
            value=str(int(counts.get("messages", 0))),
            inline=True,
        )
        joins = int(counts.get("joins", 0))
        leaves = int(counts.get("leaves", 0))
        embed.add_field(
            name="👋 Участники",
            value=f"+{joins} / −{leaves} (всего {guild.member_count})",
            inline=True,
        )

        moderation = await self._moderation_field(guild, start, end)
        embed.add_field(name="🛡 Модерация", value=moderation, inline=True)

        streams = await self._streams_field(start, end)
        embed.add_field(name="📺 Эфиры", value=streams, inline=False)

        await self.logging.send_embed(guild, embed)

    async def _moderation_field(self, guild: discord.Guild, start: datetime, end: datetime) -> str:
        services = getattr(self.bot, "services", None)
        if services is None or services.cases is None:
            return "нет данных"
        stats = await services.cases.daily_stats(
            guild.id, start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()
        )
        if not stats:
            return "чисто — действий не было"
        return "\n".join(
            f"{_ACTION_LABELS.get(action, action)}: **{n}**" for action, n in sorted(stats.items())
        )

    async def _streams_field(self, start: datetime, end: datetime) -> str:
        services = getattr(self.bot, "services", None)
        if services is None:
            return "нет данных"
        config = self.bot.config
        sources: list[tuple[str, Any]] = []
        for login in config.twitch_channels:
            sources.append(("Twitch", services.twitch.archive_store(login)))
        if config.kick_channel_slug:
            sources.append(("Kick", services.kick.archive_store(config.kick_channel_slug)))
        if config.vk_channel_slug:
            sources.append(("VK", services.vk_video.archive_store(config.vk_channel_slug)))

        total = 0
        minutes = 0
        peak = 0
        for platform, store in sources:
            for entry in await store.list():
                ended_raw = str(entry.get("ended_at") or "")
                try:
                    ended = datetime.fromisoformat(ended_raw.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if start <= ended.astimezone(UTC) < end:
                    total += 1
                    minutes += int(entry.get("seconds") or 0) // 60
                    peak = max(peak, int(entry.get("peak") or 0))
        if not total:
            return "эфиров не было"
        return f"завершено: **{total}**, суммарно **{minutes} мин**, пик зрителей **{peak}**"

    async def _trim(self, guild_id: int, today: datetime.date) -> None:
        """Удаляет протухшие KV-ключи по известным датам (без LIKE-сканов)."""
        for offset in range(_COUNTS_RETENTION_DAYS, _COUNTS_RETENTION_DAYS + 30):
            await self.kv.delete(self._counts_key(guild_id, (today - timedelta(days=offset)).isoformat()))
        for offset in range(_POSTED_RETENTION_DAYS, _POSTED_RETENTION_DAYS + 30):
            await self.kv.delete(self._posted_key(guild_id, (today - timedelta(days=offset)).isoformat()))
