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

from app.core import embeds
from app.core.base import MegaCog
from app.core.stream_state import stream_activity
from app.services.kick_service import KickService
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
    def __init__(self, bot: MegaBot, kick: KickService) -> None:
        super().__init__(bot)
        self.kick = kick
        self._chat_task: asyncio.Task[None] | None = None

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

    async def cog_unload(self) -> None:
        self.poll_loop.cancel()
        if self._chat_task is not None:
            self._chat_task.cancel()
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
            else:
                await self._sticky_offline(slug)
                await self._set_presence(None, 0)
        except Exception:
            logger.exception("Kick: ошибка проверки стрима %s", slug)

    @poll_loop.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()

    async def _set_presence(self, title: str | None, viewers: int = 0) -> None:
        try:
            await self.bot.change_presence(activity=stream_activity(title, viewers))
        except Exception:
            logger.debug("Kick: не удалось сменить присутствие", exc_info=True)

    async def _sticky_live(self, status: dict[str, Any]) -> None:
        config = self.bot.config
        channel = self._notify_channel()
        if channel is None:
            return
        embed = self._status_embed(status)
        message_id = await self.kick.sticky_message_id()
        if message_id is not None:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed)
                return
            except discord.HTTPException:
                pass
        content = ""
        if config.kick_ping_role_id:
            role = channel.guild.get_role(config.kick_ping_role_id)
            if role is not None:
                content = role.mention
        message = await channel.send(content, embed=embed)
        await self.kick.set_sticky_message(message.id)

    async def _sticky_offline(self, slug: str) -> None:
        channel = self._notify_channel()
        message_id = await self.kick.sticky_message_id()
        if channel is None or message_id is None:
            return
        try:
            message = await channel.fetch_message(message_id)
            embed = embeds.info("Стрим завершён", f"Канал `{slug}` офлайн. Спасибо за просмотр!")
            await message.edit(embed=embed, content="")
        except discord.HTTPException:
            pass
        await self.kick.clear_sticky_message()

    def _notify_channel(self) -> discord.TextChannel | None:
        channel_id = self.bot.config.kick_notify_channel_id
        if not channel_id:
            return None
        for guild in self.bot.guilds:
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                return channel
        return None

    @staticmethod
    def _status_embed(status: dict[str, Any]) -> discord.Embed:
        embed = embeds.info("🔴 Kick: стрим начался", f"**[{status['title']}](https://kick.com/{status['slug']})**")
        if status["thumbnail"]:
            embed.set_thumbnail(url=status["thumbnail"])
        embed.add_field(name="Зрители", value=str(status["viewers"]), inline=True)
        embed.add_field(name="Категория", value=status["category"], inline=True)
        return embed

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
        if status is None:
            embed = embeds.info(f"Kick: {slug}", "Канал сейчас **офлайн**.")
        else:
            embed = self._status_embed(status)
        await interaction.response.send_message(embed=embed)

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

    # ---------------------------------------------------------------- автомод чата

    async def _chat_watcher(self) -> None:
        await self.bot.wait_until_ready()
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
        content = (data.get("content") or "")[:200].lower()
        ban_words = self.bot.config.kick_ban_words
        if not ban_words or not any(word.lower() in content for word in ban_words):
            return
        sender = data.get("sender") or data.get("user") or {}
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
