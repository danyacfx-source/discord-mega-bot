"""Розыгрыши, тикеты, автомод и опросы."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import discord
from aiohttp import web

from app.core import embeds
from app.core.webpanel.payload import (
    _TICKET_DEFAULTS,
    _TICKET_TEXT_FIELDS,
)

if TYPE_CHECKING:
    from app.types import GiveawayRow


class _CommunityApiMixin:
    """Розыгрыши, тикеты, автомод и опросы."""

    async def _api_giveaways(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        service = self.services.giveaways
        rows = await service.recent_for_guild(guild.id, 60)
        active: list[dict[str, Any]] = []
        finished: list[dict[str, Any]] = []
        for row in rows:
            item = {
                "id": row["id"],
                "prize": row["prize"],
                "winners": row["winners"],
                "active": bool(row["active"]),
                "message_id": str(row["message_id"]) if row.get("message_id") else None,
                "ends_at": row["ends_at"],
                "created_at": row["created_at"],
                "author_name": self._member_name(guild, row["author_id"]),
                "channel_name": self._channel_name(guild, row["channel_id"]),
                "entries": len(await service.entries(row["id"])),
                "min_days": row.get("min_days", 0),
            }
            (active if row["active"] else finished).append(item)
        return self._json(
            {
                "ok": True,
                "active_total": len(active),
                "finished_total": len(finished),
                "active": active,
                "finished": finished,
            }
        )

    def _channel_name(self, guild: discord.Guild, channel_id: int) -> str:
        channel = guild.get_channel(channel_id)
        if channel is None:
            channel = self.bot.get_channel(channel_id)
        if channel is None:
            return str(channel_id)
        prefix = "🔊" if isinstance(channel, discord.VoiceChannel) else "#"
        return f"{prefix} {channel.name}"

    async def _api_giveaway_create(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        payload = await self._read_json(request)
        channel = self._resolve_channel(payload.get("channel_id") or "")
        if channel is None or channel.guild.id != guild.id:
            return self._json({"ok": False, "error": "Канал не найден на этом сервере"}, status=400)
        prize = str(payload.get("prize") or "").strip()
        if not prize:
            return self._json({"ok": False, "error": "Укажите приз"}, status=400)
        try:
            winners = int(payload.get("winners") or 1)
            minutes = int(payload.get("duration_minutes") or 60)
        except (TypeError, ValueError):
            return self._json({"ok": False, "error": "Количество победителей/длительность — числа"}, status=400)
        if not (1 <= winners <= 20):
            return self._json({"ok": False, "error": "Победителей: от 1 до 20"}, status=400)
        if not (1 <= minutes <= 43200):
            return self._json({"ok": False, "error": "Длительность: от 1 минуты до 30 дней"}, status=400)
        try:
            min_days = max(0, int(payload.get("min_days") or 0))
        except (TypeError, ValueError):
            min_days = 0
        service = self.services.giveaways
        ends_at = datetime.now(UTC) + timedelta(minutes=minutes)
        if self.bot.user is None:
            return self._json({"ok": False, "error": "Бот ещё не готов"}, status=503)
        giveaway_id = await service.create(guild.id, channel.id, self.bot.user.id, prize[:256], winners, ends_at, min_days)
        giveaway = await service.get(giveaway_id)
        if giveaway is None:
            await service.finish(giveaway_id)
            return self._json({"ok": False, "error": "Не удалось загрузить созданный розыгрыш"}, status=500)
        embed = await service.embed(giveaway)
        view = self._giveaway_view()
        try:
            message = await channel.send(embed=embed, view=view)
        except discord.HTTPException as exc:
            await service.finish(giveaway_id)
            return self._json({"ok": False, "error": f"Не удалось отправить: {exc.status}"}, status=400)
        await service.bind_message(giveaway_id, message.id)
        self.bot.add_view(view, message_id=message.id)
        return self._json(
            {
                "ok": True,
                "id": giveaway_id,
                "message_id": str(message.id),
                "channel": channel.name,
                "jump_url": message.jump_url,
                "ends_at": ends_at.isoformat(),
            }
        )

    def _giveaway_view(self) -> Any:
        from app.core.views import GiveawayView

        return GiveawayView()

    async def _finish_giveaway(self, giveaway: GiveawayRow, *, reroll: bool = False) -> str:
        """Завершает розыгрыш: розыгрыш победителей, анонс, обновление сообщения."""
        service = self.services.giveaways
        entries = await service.entries(giveaway["id"])
        winners = service.draw(entries, int(giveaway["winners"]))
        await service.finish(giveaway["id"])
        channel = self.bot.get_channel(giveaway["channel_id"])
        if isinstance(channel, discord.TextChannel):
            header = "Перерозыгрыш" if reroll else "Приз"
            announce = embeds.success("🎉 Розыгрыш завершён", f"{header}: **{giveaway['prize']}**")
            announce.add_field(
                name="Победители",
                value=", ".join(f"<@{uid}>" for uid in winners) if winners else "Недостаточно участников",
                inline=False,
            )
            try:
                await channel.send(embed=announce)
            except discord.HTTPException:
                pass
            message_id = giveaway.get("message_id")
            if message_id is not None:
                try:
                    message = await channel.fetch_message(message_id)
                    embed = await service.embed(giveaway)
                    embed.set_footer(text="Розыгрыш завершён")
                    await message.edit(embed=embed, view=None)
                except discord.HTTPException:
                    pass
        return ", ".join(f"<@{uid}>" for uid in winners) if winners else "нет победителей"

    async def _api_giveaway_end(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        payload = await self._read_json(request)
        message_id = self._parse_id(payload.get("message_id"))
        if guild is None or message_id is None:
            return self._json({"ok": False, "error": "Сервер или ID сообщения неверны"}, status=400)
        service = self.services.giveaways
        giveaway = await service.get_by_message(message_id)
        if giveaway is None or giveaway["guild_id"] != guild.id:
            return self._json({"ok": False, "error": "Розыгрыш не найден"}, status=404)
        if not giveaway["active"]:
            return self._json({"ok": False, "error": "Розыгрыш уже завершён"}, status=400)
        winners = await self._finish_giveaway(giveaway)
        return self._json({"ok": True, "winners": winners, "message_id": str(message_id)})

    async def _api_giveaway_reroll(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        payload = await self._read_json(request)
        message_id = self._parse_id(payload.get("message_id"))
        if guild is None or message_id is None:
            return self._json({"ok": False, "error": "Сервер или ID сообщения неверны"}, status=400)
        service = self.services.giveaways
        giveaway = await service.get_by_message(message_id)
        if giveaway is None or giveaway["guild_id"] != guild.id:
            return self._json({"ok": False, "error": "Розыгрыш не найден"}, status=404)
        winners = await self._finish_giveaway(giveaway, reroll=True)
        return self._json({"ok": True, "winners": winners, "message_id": str(message_id)})

    async def _api_tickets_panel_get(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        settings = await self.services.settings.get(guild.id)
        category_id = settings.get("ticket_category_id")
        categories = [
            {"id": str(c.id), "name": c.name}
            for c in sorted(guild.categories, key=lambda c: c.position)
        ]
        texts = {field: (settings.get(field) or _TICKET_DEFAULTS[field]) for field in _TICKET_TEXT_FIELDS}
        return self._json(
            {
                "ok": True,
                "category_id": str(category_id) if category_id else "",
                "categories": categories,
                "channels": self._channel_options(),
                "texts": texts,
            }
        )

    async def _api_tickets_panel_post(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        payload = await self._read_json(request)
        service = self.services.tickets
        settings_service = self.services.settings

        made: list[str] = []
        raw_category = payload.get("category_id")
        if raw_category not in (None, ""):
            category_id = self._parse_id(raw_category)
            if category_id is None or not isinstance(guild.get_channel(category_id), discord.CategoryChannel):
                return self._json({"ok": False, "error": "Категория не найдена"}, status=400)
            await settings_service.update(guild.id, ticket_category_id=category_id)
            made.append("category")

        settings = await settings_service.get(guild.id)
        text_updates = {f: payload[f] for f in _TICKET_TEXT_FIELDS if f in payload}
        if text_updates:
            updates = {}
            for field, value in text_updates.items():
                value = str(value).strip()
                updates[field] = value if value else _TICKET_DEFAULTS[field]
            if updates:
                await settings_service.update(guild.id, **updates)
                made.append("texts")
            settings = await settings_service.get(guild.id)

        panel_sent = False
        raw_channel = payload.get("channel_id")
        if raw_channel not in (None, ""):
            channel = self._resolve_channel(raw_channel)
            if channel is None or channel.guild.id != guild.id:
                return self._json({"ok": False, "error": "Канал не найден на этом сервере"}, status=400)
            from app.core.views import TicketOpenView

            embed = embeds.info(
                settings.get("ticket_panel_title") or _TICKET_DEFAULTS["ticket_panel_title"],
                settings.get("ticket_panel_description") or _TICKET_DEFAULTS["ticket_panel_description"],
            )
            embed.set_footer(text=settings.get("ticket_panel_footer") or _TICKET_DEFAULTS["ticket_panel_footer"])
            try:
                await channel.send(
                    embed=embed,
                    view=TicketOpenView(
                        service,
                        label=settings.get("ticket_open_label") or _TICKET_DEFAULTS["ticket_open_label"],
                        emoji=settings.get("ticket_open_emoji"),
                    ),
                )
            except (discord.HTTPException, discord.Forbidden) as exc:
                return self._json({"ok": False, "error": str(exc)}, status=400)
            panel_sent = True
            made.append("panel")

        if not made:
            return self._json({"ok": False, "error": "Не указано, что обновить"}, status=400)
        return self._json({"ok": True, "made": made, "panel_sent": panel_sent})

    async def _api_tickets(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        service = self.services.tickets
        rows = await service.list_tickets(guild.id, 300)
        open_items: list[dict[str, Any]] = []
        closed_items: list[dict[str, Any]] = []
        for row in rows:
            channel = guild.get_channel(row["channel_id"])
            item: dict[str, Any] = {
                "id": row["ticket_id"],
                "creator_id": str(row["creator_id"]),
                "creator_name": self._member_name(guild, row["creator_id"]),
                "channel_id": str(row["channel_id"]),
                "channel_name": channel.name if channel else None,
                "channel_mention": f"<#{row['channel_id']}>",
                "status": row["status"],
                "created_at": row["created_at"],
                "closed_at": row.get("closed_at"),
                "has_transcript": bool(row.get("transcript")),
                "message_count": (row.get("transcript") or "").count("\n") if row.get("transcript") else 0,
            }
            (closed_items if row["status"] != "open" else open_items).append(item)
        return self._json(
            {
                "ok": True,
                "open_total": len(open_items),
                "closed_total": len(closed_items),
                "open": open_items,
                "closed": closed_items,
            }
        )

    async def _api_ticket_close(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        ticket_id = self._parse_id(request.match_info.get("ticket_id"))
        if ticket_id is None:
            return self._json({"ok": False, "error": "Неверный № тикета"}, status=400)
        service = self.services.tickets
        closer: discord.Member | discord.ClientUser = guild.me or self.bot.user
        if closer is None:
            return self._json({"ok": False, "error": "Бот не авторизован на сервере"}, status=400)
        result = await service.close_by_id(guild, ticket_id, closer)
        if result.error:
            return self._json({"ok": False, "error": result.error}, status=400)
        return self._json({"ok": True, "transcript_channel_mention": result.transcript_channel_mention})

    async def _api_ticket_transcript(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        ticket_id = self._parse_id(request.match_info.get("ticket_id"))
        if ticket_id is None:
            return self._json({"ok": False, "error": "Неверный № тикета"}, status=400)
        service = self.services.tickets
        ticket = await service.get_ticket(ticket_id)
        if ticket is None or ticket["guild_id"] != guild.id:
            return self._json({"ok": False, "error": "Тикет не найден"}, status=404)
        text = ticket.get("transcript") or ""
        return web.Response(
            text=text,
            content_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="ticket-{ticket_id}.txt"',
                "Cache-Control": "no-store",
            },
        )

    # --- API: автомод ---

    async def _api_automod_get(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        service = self.services.settings
        settings = await service.get(guild.id)
        config = self.bot.config
        ignored_channels = [
            {"id": str(cid), "name": self._channel_name(guild, cid)}
            for cid in config.automod_ignored_channels
        ]
        return self._json(
            {
                "ok": True,
                "enabled": bool(config.automod_enabled and settings.get("automod_enabled", True)),
                "config_enabled": bool(config.automod_enabled),
                "db_enabled": bool(settings.get("automod_enabled", True)),
                "blocked_words": await service.blocked_words(guild.id),
                "env": {
                    "banned_words": config.automod_banned_words or "",
                    "block_links": bool(config.automod_block_links),
                    "allowed_links": config.automod_allowed_links or "",
                    "caps_threshold": config.automod_caps_threshold,
                    "caps_min_len": config.automod_caps_min_len,
                    "max_messages": config.automod_max_messages_in_window,
                    "timeout_seconds": config.automod_timeout_seconds,
                    "ban_after": config.automod_ban_after_timeouts,
                    "ban_window": config.automod_ban_window_seconds,
                    "ignore_roles": list(config.automod_ignore_roles),
                    "ignored_channels": ignored_channels,
                    "anti_raid": {
                        "enabled": config.automod_antiraid_enabled,
                        "window_seconds": config.automod_antiraid_window_seconds,
                        "join_threshold": config.automod_antiraid_join_threshold,
                        "slowmode_seconds": config.automod_antiraid_slowmode_seconds,
                        "cooldown_seconds": config.automod_antiraid_cooldown_seconds,
                    },
                    "exempt_regex": config.automod_exempt_regex,
                    "lockdown_seconds": config.automod_lockdown_seconds,
                },
            }
        )

    async def _api_automod_post(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        payload = await self._read_json(request)
        service = self.services.settings
        updates: dict[str, Any] = {}
        if "enabled" in payload:
            updates["automod_enabled"] = 1 if payload.get("enabled") else 0
        if updates:
            await service.update(guild.id, **updates)
        if "words" in payload:
            raw = payload.get("words")
            words = raw if isinstance(raw, list) else re.split(r"[\n,]+", str(raw or ""))
            await service.set_blocked_words(guild.id, list(words))
        settings = await service.get(guild.id)
        return self._json(
            {
                "ok": True,
                "enabled": bool(self.bot.config.automod_enabled and settings.get("automod_enabled", True)),
                "db_enabled": bool(settings.get("automod_enabled", True)),
                "blocked_words": await service.blocked_words(guild.id),
            }
        )

    async def _api_automod_lockdown(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        cog = self.bot.get_cog("AutoMod")
        if cog is None or not hasattr(cog, "activate_lockdown"):
            return self._json({"ok": False, "error": "Ког AutoMod не загружен"}, status=503)
        payload = await self._read_json(request)
        try:
            seconds = max(30, min(int(payload.get("seconds") or self.bot.config.automod_lockdown_seconds), 3600))
        except (TypeError, ValueError):
            seconds = self.bot.config.automod_lockdown_seconds
        changed = await cog.activate_lockdown(guild, seconds)
        return self._json({"ok": True, "seconds": seconds, "channels": changed})

    # --- API: опросы ---

    async def _api_polls(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        service = self.services.polls
        rows = await service.list_for_guild(guild.id, 200)
        items: list[dict[str, Any]] = []
        for row in rows:
            options = json.loads(row["options"] or "[]")
            counts = await service.vote_counts(row["id"])
            items.append(
                {
                    "id": row["id"],
                    "channel_id": str(row["channel_id"]),
                    "channel_name": self._channel_name(guild, row["channel_id"]),
                    "author_name": self._member_name(guild, row["author_id"]),
                    "question": row["question"],
                    "options": options,
                    "counts": {str(k): v for k, v in counts.items()},
                    "total": sum(counts.values()),
                    "created_at": row["created_at"],
                    "active": bool(row["active"]),
                    "message_id": str(row["message_id"]) if row.get("message_id") else "",
                }
            )
        return self._json({"ok": True, "polls": items, "channels": self._channel_options()})

    async def _api_polls_create(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        payload = await self._read_json(request)
        channel = self._resolve_channel(payload.get("channel_id"))
        if channel is None or channel.guild.id != guild.id:
            return self._json({"ok": False, "error": "Канал не найден на этом сервере"}, status=400)
        question = str(payload.get("question") or "").strip()[:256]
        raw_options = payload.get("options") or []
        options = [str(opt).strip()[:100] for opt in raw_options if str(opt).strip() and str(opt).strip().lower() != "нет"]
        if not question:
            return self._json({"ok": False, "error": "Укажите вопрос опроса"}, status=400)
        if len(options) < 2:
            return self._json({"ok": False, "error": "Минимум 2 варианта ответа"}, status=400)
        options = options[:5]

        service = self.services.polls
        poll_id = await service.create(guild.id, channel.id, guild.me.id if guild.me else 0, question, options)
        embed = await service.embed(poll_id)
        from app.core.views import PollView

        view = PollView(poll_id, len(options))
        try:
            message = await channel.send(embed=embed, view=view)
        except (discord.HTTPException, discord.Forbidden) as exc:
            return self._json({"ok": False, "error": str(exc)}, status=400)
        await service.bind_message(poll_id, message.id)
        self.bot.add_view(view, message_id=message.id)
        return self._json({"ok": True, "poll_id": poll_id, "message_id": message.id, "channel_name": channel.name})

    async def _api_polls_end(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        poll_id = self._parse_id(request.match_info.get("poll_id"))
        if poll_id is None:
            return self._json({"ok": False, "error": "Неверный ID опроса"}, status=400)
        service = self.services.polls
        poll = await service.get(poll_id)
        if poll is None or poll["guild_id"] != guild.id:
            return self._json({"ok": False, "error": "Опрос не найден"}, status=404)
        if not poll["active"]:
            return self._json({"ok": True, "already": True})
        question, options, counts = await service.end(poll_id)
        result = embeds.info(f"📊 Итоги: {question}")
        total = sum(counts.values())
        for index, option in enumerate(options):
            votes = counts.get(index, 0)
            percent = round(votes / total * 100) if total else 0
            result.add_field(name=option, value=f"**{votes}** голосов ({percent}%)", inline=False)
        result.set_footer(text=f"ID опроса: {poll_id} • Всего голосов: {total}")
        if poll.get("message_id"):
            channel = self.bot.get_channel(poll["channel_id"])
            if isinstance(channel, discord.TextChannel):
                try:
                    message = await channel.fetch_message(poll["message_id"])
                    await message.edit(embed=result, view=None)
                except discord.HTTPException:
                    pass
        return self._json({"ok": True, "question": question, "counts": {str(k): v for k, v in counts.items()}, "total": total})

    # --- API: дни рождения ---
