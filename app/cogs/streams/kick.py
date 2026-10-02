"""Kick: уведомления о стримах, модерация через Dev API и автомод чата (Pusher)."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

from app.cogs.streams.abort_alert import abort_alert
from app.cogs.streams.archive import needs_seal, seal_archive
from app.cogs.streams.poll_guard import PollGuard
from app.cogs.streams.quiet import is_quiet
from app.cogs.streams.stream_announce import pin_sticky, post_rsvp, unpin_sticky
from app.cogs.streams.stream_cards import live_card, offline_card
from app.cogs.streams.stream_role import update_stream_role
from app.core import embeds
from app.core.base import MegaCog, wait_ready_or_stop
from app.core.stream_state import stream_activity
from app.services.chat_commands_service import ChatCommandsService, ChatMessage
from app.services.kick_service import KickService, truncate_chat_content
from app.services.viewer_sessions import OFFLINE_AFTER_SECONDS
from app.utils.format import plural

if TYPE_CHECKING:
    from app.core.bot import MegaBot

logger = logging.getLogger("bot.cogs")


def _can_moderate(interaction: discord.Interaction) -> bool:
    user = interaction.user
    perms = getattr(user, "guild_permissions", None)
    if perms is not None and (perms.administrator or perms.manage_messages):
        return True
    config = getattr(interaction.client, "config", None)
    owner_id = getattr(config, "owner_id", None)
    return owner_id is not None and user.id == owner_id


class KickCog(MegaCog, name="Kick"):
    def __init__(self, bot: MegaBot, kick: KickService, chat_commands: ChatCommandsService) -> None:
        super().__init__(bot)
        self.kick = kick
        self.chat_commands = chat_commands
        self._chat_task: asyncio.Task[None] | None = None
        self._guard = PollGuard()
        self._stream_key: str | None = None

    async def cog_load(self) -> None:
        if self.bot.config.kick_channel_slug:
            self.poll_loop.change_interval(seconds=self.bot.config.kick_poll_seconds)
            self.poll_loop.start()
        if self.bot.config.kick_access_token and self.bot.config.kick_channel_slug:
            if self.bot.config.kick_mod_channel_id:
                logger.warning(
                    "KICK_MOD_CHANNEL_ID больше не используется — chatroom определяется из KICK_CHANNEL_SLUG через API"
                )
            self._chat_task = self.bot.loop.create_task(self._chat_watcher())
        if self.bot.config.chat_commands_enabled and self.bot.config.kick_channel_slug:
            self.chat_commands.register_platform(
                "kick",
                reply=self._reply_chat,
                live=self._live_status,
            )

    async def cog_unload(self) -> None:
        self.poll_loop.cancel()
        if self._chat_task is not None:
            self._chat_task.cancel()
        self.chat_commands.unregister_platform("kick")
        await self.kick.aclose()

    # ---------------------------------------------------------------- стримы

    @tasks.loop(seconds=300.0)
    async def poll_loop(self) -> None:
        slug = self.bot.config.kick_channel_slug
        if not slug:
            return
        try:
            status = await self.kick.channel_status(slug)
            if status is not None:
                await self._sticky_live(status)
                await self._set_presence(status["title"], int(status.get("viewers") or 0))
                # Табло живёт быстрее базового поллинга, пока стрим идёт.
                self.poll_loop.change_interval(seconds=self.bot.config.stream_sticky_poll_seconds)
            else:
                await self._sticky_offline(slug)
                await self._set_presence(None, 0)
                self.poll_loop.change_interval(seconds=self.bot.config.kick_poll_seconds)
            await self._sweep_viewers()
            self._guard.ok("kick")
        except Exception:
            self._guard.fail("kick", f"Kick: ошибка проверки стрима {slug}")

    async def _sweep_viewers(self) -> None:
        """Закрывает сессии зрителей, молчащих дольше порога (не валит поллинг)."""
        try:
            closed = await self.kick.viewer_store().sweep()
        except Exception:
            logger.debug("Kick: не удалось обновить сессии зрителей", exc_info=True)
            return
        if closed:
            names = ", ".join(str(s.get("name") or "?") for s in closed[:5])
            logger.debug("Kick: зрители вышли из эфира (%d): %s", len(closed), names)

    @poll_loop.before_loop
    async def _before_poll(self) -> None:
        await wait_ready_or_stop(self.bot, self.poll_loop)

    async def _set_presence(self, title: str | None, viewers: int = 0) -> None:
        try:
            await self.bot.change_presence(activity=stream_activity(title, viewers))
        except Exception:
            logger.debug("Kick: не удалось сменить присутствие", exc_info=True)

    async def _sticky_live(self, status: dict[str, Any]) -> None:
        await update_stream_role(self.bot, enable=True)
        # Ключ текущего эфира — для сброса счётчика топа говорящих.
        self._stream_key = str(status.get("started_at") or "") or None
        config = self.bot.config
        channel = self._notify_channel()
        if channel is None:
            return
        slug = str(status["slug"])
        url = f"https://kick.com/{slug}"
        session = await self.kick.session_store(slug).capture(status, url=url)
        embed = live_card("kick", url=url, status=status, session=session)
        message_id = await self.kick.sticky_message_id()
        if message_id is not None:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed)
                return
            except discord.HTTPException:
                pass
        content = ""
        if config.kick_ping_role_id and not is_quiet(config):  # ночью — без пинга
            role = channel.guild.get_role(config.kick_ping_role_id)
            if role is not None:
                content = role.mention
        message = await channel.send(content, embed=embed)
        await self.kick.set_sticky_message(message.id)
        await pin_sticky(message)
        await post_rsvp(
            channel,
            store=self.kick.rsvp_store(),
            title=str(status.get("title") or ""),
            url=url,
        )
        await self._announce_chat_live(status)

    async def _announce_chat_live(self, status: dict[str, Any]) -> None:
        """Кидает ссылку на стрим в чат Kick, если включено KICK_CHAT_AUTO_LINK.

        Вызывается только когда sticky-сообщение пришлось создать заново, то есть
        ровно один раз на старт эфира.
        """
        config = self.bot.config
        if not config.kick_chat_auto_link:
            return
        text = config.kick_chat_link_text.strip()
        if not text:
            return
        if "{url}" in text or "{title}" in text or "{viewers}" in text:
            text = text.format(
                url=f"https://kick.com/{status['slug']}",
                title=status.get("title") or "",
                viewers=status.get("viewers") or 0,
            )
        await self.kick.send_chat_message(text, as_user=config.kick_chat_send_as_user)

    async def _sticky_offline(self, slug: str) -> None:
        await update_stream_role(self.bot, enable=False)
        store = self.kick.session_store(slug)
        session = await store.load()
        url = f"https://kick.com/{slug}"
        vod_url = f"{url}/videos"
        archive = self.kick.archive_store(slug)
        if await needs_seal(archive, session):
            await seal_archive(
                archive,
                session,
                platform="kick",
                url=url,
                vod_url=vod_url,
                max_age_days=self.bot.config.stream_archive_days,
            )
        channel = self._notify_channel()
        message_id = await self.kick.sticky_message_id()
        if channel is None or message_id is None:
            return
        top = await self.kick.viewer_store().top_talkers()
        try:
            message = await channel.fetch_message(message_id)
            await message.edit(
                embed=offline_card("kick", url=url, session=session, vod_url=vod_url, top_talkers=top),
                content="",
            )
            await unpin_sticky(message)
        except discord.HTTPException:
            pass
        await self.kick.clear_sticky_message()
        # Сессию не чистим — это «последний эфир» для карточек и оверлея.
        await abort_alert(
            channel,
            session=session,
            label="Kick",
            url=url,
            threshold_minutes=self.bot.config.stream_abort_alert_minutes,
        )

    def _notify_channel(self) -> discord.TextChannel | None:
        channel_id = self.bot.config.kick_notify_channel_id
        if not channel_id:
            return None
        for guild in self.bot.guilds:
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                return channel
        return None

    @app_commands.command(name="kick_status", description="Статус Kick-стрима")
    @app_commands.guild_only()
    async def kick_status(self, interaction: discord.Interaction) -> None:
        slug = self.bot.config.kick_channel_slug
        if not slug:
            await interaction.response.send_message(
                embed=embeds.error("Не настроено", "Укажите KICK_CHANNEL_SLUG в конфигурации."),
                ephemeral=True,
            )
            return
        status = await self.kick.channel_status(slug)
        url = f"https://kick.com/{slug}"
        session = await self.kick.session_store(slug).load()
        if status is None:
            embed = offline_card("kick", url=url, session=session, vod_url=f"{url}/videos")
        else:
            embed = live_card("kick", url=url, status=status, session=session)
        await interaction.response.send_message(embed=embed)

    # ---------------------------------------------------------------- отправка в чат

    @app_commands.command(name="kick_say", description="Отправить сообщение в чат Kick")
    @app_commands.describe(message="Текст сообщения (до 500 символов)")
    @app_commands.guild_only()
    @app_commands.check(_can_moderate)
    async def kick_say(self, interaction: discord.Interaction, message: str) -> None:
        config = self.bot.config
        if not config.kick_access_token:
            await interaction.response.send_message(
                embed=embeds.error("Не настроено", "Не задан KICK_ACCESS_TOKEN."),
                ephemeral=True,
            )
            return
        sent_id = await self.kick.send_chat_message(
            message, as_user=config.kick_chat_send_as_user
        )
        if sent_id is None:
            embed = embeds.error(
                "Kick: ошибка",
                "Не удалось отправить. Проверьте scope `chat:write` у токена.",
            )
        else:
            preview = truncate_chat_content(message)
            embed = embeds.success("Kick: отправлено", f"Сообщение в чат Kick:\n```{preview}```")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ---------------------------------------------------------------- модерация

    async def _mod_target(self, interaction: discord.Interaction, username: str) -> dict[str, Any] | None:
        user = await self.kick.resolve_user(username)
        if user is None:
            await interaction.response.send_message(
                embed=embeds.error("Не найден", f"Kick-пользователь `{username}` не найден."),
                ephemeral=True,
            )
            return None
        return user

    @app_commands.command(name="kick_ban", description="Забанить пользователя на Kick")
    @app_commands.describe(username="Ник на Kick", reason="Причина бана")
    @app_commands.guild_only()
    @app_commands.check(_can_moderate)
    async def kick_ban(self, interaction: discord.Interaction, username: str, reason: str = "") -> None:
        user = await self._mod_target(interaction, username)
        if user is None:
            return
        ok = await self.kick.ban(user["id"], reason=reason)
        if ok:
            embed = embeds.success("Kick: бан", f"Пользователь **{user['username']}** забанен.")
        else:
            embed = embeds.error("Kick: ошибка", "Не удалось забанить. Проверьте токен KICK_ACCESS_TOKEN.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="kick_timeout", description="Таймаут пользователя на Kick")
    @app_commands.describe(username="Ник на Kick", minutes="Длительность, 1–10080 минут", reason="Причина")
    @app_commands.guild_only()
    @app_commands.check(_can_moderate)
    async def kick_timeout(
        self,
        interaction: discord.Interaction,
        username: str,
        minutes: app_commands.Range[int, 1, 10080] = 10,
        reason: str = "",
    ) -> None:
        user = await self._mod_target(interaction, username)
        if user is None:
            return
        ok = await self.kick.ban(user["id"], minutes=minutes, reason=reason)
        if ok:
            embed = embeds.success("Kick: таймаут", f"**{user['username']}** замьючен на {minutes} мин.")
        else:
            embed = embeds.error("Kick: ошибка", "Не удалось выдать таймаут.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="kick_unban", description="Снять бан на Kick")
    @app_commands.describe(username="Ник на Kick")
    @app_commands.guild_only()
    @app_commands.check(_can_moderate)
    async def kick_unban(self, interaction: discord.Interaction, username: str) -> None:
        user = await self._mod_target(interaction, username)
        if user is None:
            return
        ok = await self.kick.unban(user["id"])
        if ok:
            embed = embeds.success("Kick: разбан", f"С **{user['username']}** снят бан.")
        else:
            embed = embeds.error("Kick: ошибка", "Не удалось снять бан.")
        await interaction.response.send_message(embed=embed)

    # ---------------------------------------------------------------- зрители

    @app_commands.command(name="kick_watchers", description="Кто сейчас смотрит Kick-стрим (онлайн-сессии из чата)")
    @app_commands.guild_only()
    async def kick_watchers(self, interaction: discord.Interaction) -> None:
        """Сессии зрителей из Pusher-чата: участники сервера отдельным списком."""
        from datetime import UTC, datetime

        store = self.kick.viewer_store()
        try:
            await store.sweep()
            active = await store.active()
        except Exception:
            await interaction.response.send_message(
                embed=embeds.error("Kick: ошибка", "Не удалось прочитать сессии зрителей."),
                ephemeral=True,
            )
            return
        if not active:
            await interaction.response.send_message(
                embed=embeds.info("Kick: зрители", "Сейчас в чате никого — сессий нет."),
                ephemeral=True,
            )
            return

        lookup: dict[str, discord.Member] = {}
        if interaction.guild is not None:
            for member in interaction.guild.members:
                for candidate in (member.nick, member.display_name, member.name):
                    if candidate:
                        lookup.setdefault(candidate.casefold(), member)

        now = datetime.now(UTC)
        mine: list[str] = []
        others: list[str] = []
        for session in sorted(active.values(), key=lambda s: str(s.get("first_seen") or ""), reverse=True):
            name = str(session.get("name") or "?")
            member = lookup.get(name.casefold())
            try:
                first = datetime.fromisoformat(str(session.get("first_seen") or "").replace("Z", "+00:00"))
                minutes = max(0, round((now - first).total_seconds() / 60))
            except ValueError:
                minutes = 0
            messages = int(session.get("messages") or 0)
            line = f"**{name}**" + (f" · {member.mention}" if member else "") + f" — {minutes} мин · {messages} сообщ."
            if member is not None:
                mine.append(line)
            else:
                others.append(line)

        embed = embeds.info(
            "Kick: зрители онлайн",
            f"Активных сессий: **{len(active)}** (сводка раз в {OFFLINE_AFTER_SECONDS // 60} мин молчания)",
        )
        if mine:
            embed.add_field(name=f"С нашего сервера • {len(mine)}", value="\n".join(mine)[:1024], inline=False)
        if others:
            embed.add_field(name=f"Остальные • {len(others)}", value="\n".join(others)[:1024], inline=False)
        await interaction.response.send_message(embed=embed)

    # ---------------------------------------------------------------- автомод чата

    async def _chat_watcher(self) -> None:
        if not await wait_ready_or_stop(self.bot):
            return
        pause = 10
        while True:
            try:
                await self._chat_cycle()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Kick: автомод оборвался, переподключение через %d сек", pause)
            await asyncio.sleep(pause)

    async def _chat_cycle(self) -> None:
        config = self.bot.config
        slug = config.kick_channel_slug or ""
        if not slug:
            return
        chatroom_id = await self.kick.resolve_chatroom_id(slug)
        if chatroom_id is None:
            return
        channel = f"chatrooms.{chatroom_id}.v2"
        url = f"wss://{config.kick_pusher_host}/app/{config.kick_pusher_app_key}?protocol=7&client=js&version=8.0.0&flash=false"
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, heartbeat=25) as ws:
                await ws.send_json(
                    {"event": "pusher:subscribe", "data": {"auth": "", "channel": channel}}
                )
                async for message in ws:
                    if message.type != aiohttp.WSMsgType.TEXT:
                        continue
                    if message.data == "pusher:connection_established":
                        continue
                    try:
                        payload = json.loads(message.data)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if payload.get("event") != "App\\Events\\ChatMessageEvent":
                        continue
                    data = payload.get("data")
                    if isinstance(data, str):
                        try:
                            data = json.loads(data)
                        except (TypeError, json.JSONDecodeError):
                            continue
                    if isinstance(data, dict):
                        await self._handle_chat_message(data)

    async def _handle_chat_message(self, data: dict[str, Any]) -> None:
        sender = data.get("sender") or data.get("user") or {}
        username = str(sender.get("username") or sender.get("slug") or "")
        if username:
            try:
                # Сессия зрителя живёт независимо от автомода: любое сообщение
                # в чате продлевает онлайн-окно и копится в топе говорящих.
                await self.kick.viewer_store().touch(username, stream_id=self._stream_key)
            except Exception:
                logger.debug("Kick: не удалось обновить сессию зрителя %s", username, exc_info=True)
            await self._dispatch_command(sender, username, data)
        content = (data.get("content") or "")[:200].lower()
        ban_words = self.bot.config.kick_ban_words
        if not ban_words or not any(word.lower() in content for word in ban_words):
            return
        user_id = sender.get("id")
        if not user_id:
            return
        message_id = data.get("id") or data.get("message_id")
        ok_delete = await self.kick.delete_message(message_id) if message_id is not None else False
        ok_ban = await self.kick.ban(int(user_id), minutes=10, reason="Автомод: бан-слово")
        words = plural(len(ban_words), "слово", "слова", "слов")
        logger.info(
            "Kick: автомод %s (%s) — удаление=%s, бан=%s, совпадение среди %s: %s",
            sender.get("username"), user_id, ok_delete, ok_ban, words, content[:60],
        )

    async def _dispatch_command(self, sender: dict[str, Any], username: str, data: dict[str, Any]) -> None:
        """Передаёт сообщение чата в диспетчер команд (не роняет автомод)."""
        if not self.bot.config.chat_commands_enabled:
            return
        identity = sender.get("identity") or {}
        try:
            await self.chat_commands.handle(
                ChatMessage(
                    platform="kick",
                    username=username.lower(),
                    display_name=str(sender.get("username") or username),
                    content=str(data.get("content") or ""),
                    is_mod=bool(identity.get("is_moderator") or identity.get("is_owner")),
                    reply_to="",
                )
            )
        except Exception:
            logger.debug("Kick: сбой диспетчера команд чата", exc_info=True)

    async def _reply_chat(self, reply_to: str, text: str) -> None:
        await self.kick.send_chat_message(text, as_user=self.bot.config.kick_chat_send_as_user)

    async def _live_status(self) -> dict[str, Any] | None:
        slug = self.bot.config.kick_channel_slug
        if not slug:
            return None
        return await self.kick.channel_status(slug)
