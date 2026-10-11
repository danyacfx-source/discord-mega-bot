"""Отправка/редактирование/получение сообщений через бота и опции гильдии."""
from __future__ import annotations

from typing import Any

import discord
from aiohttp import web

from app.core.webpanel.base_api import _BaseApi
from app.core.webpanel.payload import (
    _MAX_EMBEDS,
    _embed_from_dict,
    _message_to_client,
    _view_from_components,
)


class _BotApiMixin(_BaseApi):
    """Отправка/редактирование/получение сообщений через бота и опции гильдии."""

    async def _api_bot_channels(self, request: web.Request) -> web.Response:
        return self._json({"ok": True, "channels": self._channel_options()})

    async def _api_bot_send(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        channel = self._resolve_channel(payload.get("channel_id") or "")
        if channel is None:
            return self._json({"ok": False, "error": "Канал не найден"}, status=400)
        try:
            message = await channel.send(
                content=str(payload.get("content") or "")[:2000] or None,
                embeds=[_embed_from_dict(item) for item in (payload.get("embeds") or [])[:_MAX_EMBEDS] if isinstance(item, dict)],
                view=_view_from_components(payload.get("components")),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.HTTPException, discord.Forbidden) as exc:
            return self._json({"ok": False, "error": str(exc)}, status=400)
        return self._json({"ok": True, "message_id": str(message.id)})

    async def _api_bot_edit(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        channel = self._resolve_channel(payload.get("channel_id") or "")
        message_id = self._parse_id(payload.get("message_id"))
        if channel is None or message_id is None:
            return self._json({"ok": False, "error": "Канал или ID сообщения неверны"}, status=400)
        try:
            message = await channel.fetch_message(message_id)
        except discord.HTTPException:
            return self._json({"ok": False, "error": "Сообщение не найдено"}, status=404)
        try:
            await message.edit(
                content=str(payload.get("content") or "")[:2000] or None,
                embeds=[_embed_from_dict(item) for item in (payload.get("embeds") or [])[:_MAX_EMBEDS] if isinstance(item, dict)],
                view=_view_from_components(payload.get("components")),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.HTTPException, discord.Forbidden) as exc:
            return self._json({"ok": False, "error": str(exc)}, status=400)
        return self._json({"ok": True})

    async def _api_bot_fetch(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        channel = self._resolve_channel(payload.get("channel_id") or "")
        message_id = self._parse_id(payload.get("message_id"))
        if channel is None or message_id is None:
            return self._json({"ok": False, "error": "Канал или ID сообщения неверны"}, status=400)
        try:
            message = await channel.fetch_message(message_id)
        except discord.HTTPException:
            return self._json({"ok": False, "error": "Сообщение не найдено"}, status=404)
        return self._json({"ok": True, "data": _message_to_client(message)})

    def _channel_options(self) -> list[dict[str, Any]]:
        channels: list[dict[str, Any]] = []
        for guild in self.bot.guilds:
            me = guild.me
            for channel in guild.text_channels:
                if me is not None and not channel.permissions_for(me).send_messages:
                    continue
                channels.append(
                    {
                        "id": str(channel.id),
                        "name": channel.name,
                        "category": channel.category.name if channel.category else "",
                        "nsfw": channel.nsfw,
                    }
                )
        channels.sort(key=lambda item: (item["category"], item["name"]))
        return channels

    def _category_options(self) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = []
        for guild in self.bot.guilds:
            for category in guild.categories:
                options.append({"id": str(category.id), "name": category.name})
        options.sort(key=lambda item: item["name"])
        return options

    def _role_options(self) -> list[dict[str, Any]]:
        guild = self._primary_guild()
        if guild is None:
            return []
        roles = []
        for role in guild.roles:
            if role.is_default():
                continue
            roles.append({"id": str(role.id), "name": role.name})
        roles.sort(key=lambda item: item["name"])
        return roles
