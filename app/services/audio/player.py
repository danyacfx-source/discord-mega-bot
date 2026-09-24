"""Плеер: очередь, управление воспроизведением голосового клиента."""
from __future__ import annotations

import asyncio
import logging
import secrets
from collections import deque
from typing import TYPE_CHECKING

import discord

from app.services.audio.track import Track

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.audio")

_BEFORE_OPTIONS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
_AFTER_OPTIONS = "-vn"
_IDLE_DISCONNECT_SECONDS = 60


class GuildPlayer:
    """Очередь и воспроизведение в рамках одного сервера."""

    def __init__(self, bot: MegaBot, guild_id: int) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.loop = asyncio.get_running_loop()
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self.voice: discord.VoiceClient | None = None
        self.notify_channel_id: int | None = None
        self.volume = 1.0
        self.loop_one = False
        self.skip_votes: set[int] = set()
        self.position_seconds = 0
        self._seeking = False
        self._idle_task: asyncio.Task[None] | None = None

    @property
    def is_playing(self) -> bool:
        return self.voice is not None and self.voice.is_playing()

    def enqueue(self, track: Track) -> None:
        self.queue.append(track)

    def requeue(self, track: Track) -> None:
        self.queue.appendleft(track)

    def shuffle(self) -> None:
        entries = list(self.queue)
        secrets.SystemRandom().shuffle(entries)
        self.queue = deque(entries)

    def remove(self, position: int) -> Track | None:
        if position < 1 or position > len(self.queue):
            return None
        entries = list(self.queue)
        removed = entries.pop(position - 1)
        self.queue = deque(entries)
        return removed

    async def notify(self, text: str) -> None:
        if self.notify_channel_id is None:
            return
        channel = self.bot.get_channel(self.notify_channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            await channel.send(text)
        except discord.HTTPException:
            logger.debug("Не удалось отправить уведомление о музыке", exc_info=True)

    async def play(self, track: Track) -> None:
        self._cancel_idle()
        self.current = track
        await self._start(track)

    async def _start(self, track: Track) -> None:
        if self.voice is None or not self.voice.is_connected():
            return
        if self.voice.is_playing():
            return
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(
                track.stream_url,
                before_options=(
                    f"-ss {self.position_seconds} {_BEFORE_OPTIONS}" if self.position_seconds > 0 else _BEFORE_OPTIONS
                ),
                options=_AFTER_OPTIONS,
            ),
            volume=self.volume,
        )
        self.voice.play(source, after=self._on_finished)

    def _on_finished(self, error: Exception | None) -> None:
        if error and not isinstance(error, asyncio.CancelledError):
            logger.warning("Ошибка воспроизведения: %s", error)
        try:
            coroutine = self._restart_after_seek() if self._seeking else self.play_next()
            asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(10)
        except Exception:
            logger.exception("Сбой при переключении трека")

    async def _restart_after_seek(self) -> None:
        self._seeking = False
        if self.current is not None:
            await self._start(self.current)

    async def seek(self, seconds: int) -> bool:
        if self.current is None or self.voice is None or not self.voice.is_connected():
            return False
        duration = self.current.duration
        upper = max(0, (duration - 1) if duration else seconds)
        self.position_seconds = max(0, min(seconds, upper))
        if self.voice.is_playing() or self.voice.is_paused():
            self._seeking = True
            self.voice.stop()
        else:
            await self._start(self.current)
        return True

    async def play_next(self) -> None:
        if self.loop_one and self.current is not None:
            await self._start(self.current)
            await self.notify(f"🔁 Повтор: **{self.current}**")
            return
        if self.queue:
            self.position_seconds = 0
            await self.play(self.queue.popleft())
            return
        self.current = None
        self.position_seconds = 0
        await self._schedule_idle_disconnect()

    async def skip(self, amount: int = 1) -> Track | None:
        self.skip_votes.clear()
        skipped = self.current
        for _ in range(max(1, amount) - 1):
            if self.queue:
                self.queue.popleft()
        if self.loop_one:
            self.loop_one = False
        if self.voice is not None:
            self.voice.stop()
        await self.play_next()
        return skipped

    async def stop(self) -> None:
        self._cancel_idle()
        self.queue.clear()
        self.skip_votes.clear()
        self.current = None
        self.position_seconds = 0
        if self.voice is not None:
            self.voice.stop()

    def pause(self) -> bool:
        if self.voice is not None and self.voice.is_playing():
            self.voice.pause()
            return True
        return False

    def resume(self) -> bool:
        if self.voice is not None and self.voice.is_paused():
            self.voice.resume()
            return True
        return False

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(2.0, volume))
        if self.voice is not None and isinstance(self.voice.source, discord.PCMVolumeTransformer):
            self.voice.source.volume = self.volume

    async def disconnect(self) -> None:
        self._cancel_idle()
        self.queue.clear()
        self.current = None
        self.position_seconds = 0
        if self.voice is not None and self.voice.is_connected():
            await self.voice.disconnect()
        self.voice = None

    async def _schedule_idle_disconnect(self) -> None:
        if self.voice is None or not self.voice.is_connected():
            return
        self._cancel_idle()
        self._idle_task = asyncio.create_task(self._idle_disconnect())

    async def _idle_disconnect(self) -> None:
        await asyncio.sleep(_IDLE_DISCONNECT_SECONDS)
        if self.voice is not None and self.voice.is_connected() and not self.voice.is_playing():
            await self.disconnect()
            await self.notify("👋 Очередь пуста — вышел из голосового канала.")

    def _cancel_idle(self) -> None:
        if self._idle_task is not None and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = None
