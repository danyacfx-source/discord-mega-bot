"""Команды чата стримов: Twitch IRC (чтение всегда, запись с токеном) и тикер опросов.

Kick подключается своим когом (Pusher уже слушает чат); этот ког закрывает
Twitch: анонимное чтение работает без токена (команды и голосование живы),
для ответов нужен TWITCH_CHAT_TOKEN (scope chat:edit, логин = первый канал).
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import aiohttp
from discord.ext import tasks

from app.core.base import MegaCog, wait_ready_or_stop
from app.services.chat_commands_service import ChatCommandsService, ChatMessage
from app.services.twitch_service import TwitchService

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")

_IRC_URL = "wss://irc-ws.chat.twitch.tv:443"
#: Twitch rate limit записи — 20 сообщений / 30 секунд
_SEND_INTERVAL = 1.7


@dataclass(slots=True)
class IrcPrivmsg:
    channel: str
    login: str
    display_name: str
    text: str
    is_mod: bool
    is_bot: bool


def parse_privmsg(line: str) -> IrcPrivmsg | None:
    """Разбирает строку IRC-приватного сообщения Twitch (с тегами или без)."""
    tags: dict[str, str] = {}
    rest = line
    if rest.startswith("@"):
        try:
            raw_tags, rest = rest[1:].split(" ", 1)
        except ValueError:
            return None
        for pair in raw_tags.split(";"):
            key, _, value = pair.partition("=")
            tags[key] = value
    if not rest.startswith(":"):
        return None
    source, _, rest = rest.partition(" ")
    command, _, rest = rest.partition(" ")
    if command != "PRIVMSG" or not rest:
        return None
    target, sep, text = rest.partition(" :")
    if not sep:
        return None
    channel = target.strip().lstrip("#").lower()
    if not channel:
        return None
    login = (tags.get("login") or source[1:].split("!")[0]).lower()
    if not login:
        return None
    display = tags.get("display-name") or login
    badges = tags.get("badges") or ""
    is_mod = tags.get("mod") == "1" or "broadcaster/" in badges or "moderator/" in badges
    return IrcPrivmsg(
        channel=channel,
        login=login,
        display_name=display,
        text=text,
        is_mod=is_mod,
        is_bot=tags.get("bot") == "1",
    )


class TwitchIrc:
    """Одно подключение IRC Twitch: чтение + rate-limited запись."""

    def __init__(self, *, nick: str, token: str, channels: tuple[str, ...], write_login: str) -> None:
        self._nick = nick
        self._token = token
        self._channels = tuple(c.lower() for c in channels)
        self._write_login = write_login
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._send_lock = asyncio.Lock()
        self._last_send = 0.0
        self.auth_failed = False

    @property
    def can_write(self) -> bool:
        return bool(self._token) and self._ws is not None and not self.auth_failed

    async def run(self, on_message: Any) -> None:
        """Читает входящие до обрыва соединения; авторизационная ошибка — выходим."""
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(_IRC_URL, heartbeat=30) as ws:
                self._ws = ws
                if self._token:
                    token = self._token if self._token.startswith("oauth:") else f"oauth:{self._token}"
                    await ws.send_str(f"PASS {token}")
                    await ws.send_str(f"NICK {self._write_login or self._nick}")
                else:
                    await ws.send_str(f"NICK {self._nick}")
                await ws.send_str("CAP REQ :twitch.tv/tags")
                await ws.send_str("CAP REQ :twitch.tv/commands")
                for channel in self._channels:
                    await ws.send_str(f"JOIN #{channel}")
                buffer = ""
                async for frame in ws:
                    if frame.type is aiohttp.WSMsgType.TEXT:
                        buffer += frame.data
                        while "\r\n" in buffer:
                            line, buffer = buffer.split("\r\n", 1)
                            if await self._dispatch(line, ws, on_message):
                                return
                    elif frame.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        return

    async def _dispatch(self, line: str, ws: aiohttp.ClientWebSocketResponse, on_message: Any) -> bool:
        """Обрабатывает одну строку; True — выйти из цикла (auth failed)."""
        if line.startswith("PING"):
            await ws.send_str("PONG :tmi.twitch.tv")
            return False
        if "Login authentication failed" in line or "Improperly formatted auth" in line:
            self.auth_failed = True
            logger.error("Twitch IRC: авторизация отклонена — проверь TWITCH_CHAT_TOKEN/NICK")
            return True
        if " NOTICE " in line:
            return False
        privmsg = parse_privmsg(line)
        if privmsg is None:
            return False
        try:
            await on_message(
                ChatMessage(
                    platform="twitch",
                    username=privmsg.login,
                    display_name=privmsg.display_name,
                    content=privmsg.text,
                    is_mod=privmsg.is_mod,
                    is_bot=privmsg.is_bot,
                    reply_to=privmsg.channel,
                )
            )
        except Exception:
            logger.exception("Twitch IRC: сбой обработки сообщения от %s", privmsg.login)
        return False

    async def send(self, channel: str, text: str) -> bool:
        if not self.can_write or not channel:
            return False
        async with self._send_lock:
            wait = _SEND_INTERVAL - (asyncio.get_running_loop().time() - self._last_send)
            if wait > 0:
                await asyncio.sleep(wait)
            await self._ws.send_str(f"PRIVMSG #{channel} :{text[:450]}")  # type: ignore[union-attr]
            self._last_send = asyncio.get_running_loop().time()
        return True

    def close(self) -> None:
        ws = self._ws
        if ws is not None and not ws.closed:
            ws.close()


class StreamChatCog(MegaCog, name="StreamChat"):
    def __init__(self, bot: MegaBot, chat_commands: ChatCommandsService, twitch: TwitchService) -> None:
        super().__init__(bot)
        self.chat = chat_commands
        self.twitch = twitch
        self._irc: TwitchIrc | None = None
        self._irc_task: asyncio.Task[None] | None = None
        self._stream_key: str | None = None
        self._stream_key_at = 0.0
        self._sweep_tick = 0

    async def cog_load(self) -> None:
        config = self.bot.config
        if not config.chat_commands_enabled:
            return
        self.tick_loop.start()
        if config.twitch_channels:
            self.chat.register_platform(
                "twitch",
                reply=self._reply,
                live=self._live,
                schedule=self._schedule,
            )
            self._irc_task = self.bot.loop.create_task(self._irc_runner())

    async def cog_unload(self) -> None:
        self.tick_loop.cancel()
        if self._irc_task is not None:
            self._irc_task.cancel()
            self._irc_task = None
        if self._irc is not None:
            self._irc.close()
            self._irc = None
        self.chat.unregister_platform("twitch")

    # ------------------------------------------------------------- задачи

    @tasks.loop(seconds=5.0)
    async def tick_loop(self) -> None:
        await self.chat.tick()
        self._sweep_tick += 1
        if self._sweep_tick % 12 == 0:  # раз в минуту: закрыть сессии без сообщений
            try:
                await self.twitch.viewer_store().sweep()
            except Exception:
                logger.debug("Twitch: не удалось закрыть устаревшие сессии зрителей", exc_info=True)

    @tick_loop.before_loop
    async def _before_tick(self) -> None:
        await wait_ready_or_stop(self.bot, self.tick_loop)

    async def _irc_runner(self) -> None:
        """Подключение к Twitch IRC с реконнектом; auth-ошибка — выход навсегда."""
        if not await wait_ready_or_stop(self.bot):
            return
        config = self.bot.config
        pause = 10
        while True:
            if not config.twitch_channels:
                return
            irc = TwitchIrc(
                nick=f"justinfan{random.randint(10000, 99999)}",
                token=config.twitch_chat_token,
                channels=config.twitch_channels,
                write_login=config.twitch_channels[0],
            )
            self._irc = irc
            try:
                await irc.run(self._on_message)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.warning("Twitch IRC: обрыв, переподключение через %d сек", pause, exc_info=True)
            finally:
                self._irc = None
            if irc.auth_failed:
                return
            await asyncio.sleep(pause)

    # --------------------------------------------------------- сессии зрителей

    async def _on_message(self, message: ChatMessage) -> None:
        """Каждое сообщение чата продлевает сессию зрителя (для раздела «Зрители»)."""
        try:
            key = await self._current_stream_key()
            await self.twitch.viewer_store().touch(
                message.display_name or message.username, stream_id=key
            )
        except Exception:
            logger.debug("Twitch: не удалось обновить сессию зрителя", exc_info=True)
        await self.chat.handle(message)

    async def _current_stream_key(self) -> str | None:
        """Ключ эфира (started_at сессии) для сброса топа говорящих.

        Кэш на 30 с — KV не читается на каждое сообщение чата.
        """
        now = asyncio.get_running_loop().time()
        if now - self._stream_key_at < 30.0:
            return self._stream_key
        channels = self.bot.config.twitch_channels
        if channels:
            session = await self.twitch.session_store(channels[0]).load()
            self._stream_key = str((session or {}).get("started_at") or "") or None
        else:
            self._stream_key = None
        self._stream_key_at = now
        return self._stream_key

    # ------------------------------------------------------------- платформа

    async def _reply(self, reply_to: str, text: str) -> None:
        irc = self._irc
        if irc is None or not reply_to:
            return
        sent = await irc.send(reply_to, text)
        if not sent and not self.bot.config.twitch_chat_token:
            logger.debug("Twitch IRC: ответ пропущен (нет TWITCH_CHAT_TOKEN, read-only режим)")

    async def _live(self) -> dict[str, Any] | None:
        channels = self.bot.config.twitch_channels
        if not channels:
            return None
        return await self.twitch.channel_status(channels[0])

    async def _schedule(self) -> list[dict[str, Any]] | None:
        channels = self.bot.config.twitch_channels
        if not channels:
            return None
        return await self.twitch.schedule(channels[0])
