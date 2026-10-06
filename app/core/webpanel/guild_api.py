"""Сервер, участники, роли, варны и действия модерации."""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from aiohttp import web

_WARDOGS_CATEGORY_ID = 1534711415883956284
_WARDOGS_ROLE_NAME = "Wardogs"
_EDITABLE_PERMISSION_NAMES = (
    "view_channel",
    "send_messages",
    "read_message_history",
    "connect",
    "speak",
    "attach_files",
    "embed_links",
    "add_reactions",
    "send_messages_in_threads",
)


class _GuildApiMixin:
    """Сервер, участники, роли, варны и действия модерации."""

    def _resolve_member(self, guild: discord.Guild, value: Any) -> discord.Member | None:
        if value in (None, ""):
            return None
        raw = str(value).strip()
        match = re.match(r"^<@!?(\d+)>$", raw)
        if match:
            raw = match.group(1)
        if raw.isdigit():
            member = guild.get_member(int(raw))
            if member is not None:
                return member
        name = raw.lstrip("@").lower()
        candidates = [
            m
            for m in guild.members
            if m.display_name.lower() == name or m.name.lower() == name or f"{m.name}#{m.discriminator}".lower() == name
        ]
        return candidates[0] if len(candidates) == 1 else None

    def _resolve_role(self, guild: discord.Guild, value: Any) -> discord.Role | None:
        if value in (None, ""):
            return None
        raw = str(value).strip()
        match = re.match(r"^<@&(\d+)>$", raw)
        if match:
            raw = match.group(1)
        if raw.isdigit():
            role = guild.get_role(int(raw))
            if role is not None:
                return role
        name = raw.lstrip("@").lower()
        matching = [r for r in guild.roles if r.name.lower() == name]
        return matching[0] if len(matching) == 1 else None

    def _guard_mod_target(self, guild: discord.Guild, member: discord.Member) -> str | None:
        from app.core.checks import can_moderate

        me = guild.me
        if me is None:
            return "Бот недоступен на сервере"
        if member.id == guild.owner_id:
            return "Нельзя: владелец сервера"
        if member.top_role.position >= me.top_role.position:
            return "Бот не может модернировать: роли участника выше ролей бота"
        if not can_moderate(me, member):
            return "Бот не может модернировать этого участника"
        return None

    def _member_payload(self, guild: discord.Guild, member: discord.Member) -> dict[str, Any]:
        return {
            "id": str(member.id),
            "name": member.name,
            "display_name": member.display_name,
            "tag": str(member),
            "is_bot": member.bot,
            "status": str(member.status) if member.status is not None else "unknown",
            "top_role": member.top_role.name,
            "top_role_color": f"#{member.top_role.color.value:06x}" if member.top_role and member.top_role.color.value else "#99aab5",
            "avatar": member.display_avatar.url,
            "joined_at": member.joined_at.isoformat() if member.joined_at else None,
            "warnings": 0,
        }

    async def _api_server(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        me = guild.me
        categories: list[dict[str, Any]] = []
        for category in sorted(guild.categories, key=lambda c: c.position):
            channels: list[dict[str, Any]] = []
            for channel in sorted(category.channels, key=lambda c: c.position):
                if isinstance(channel, discord.VoiceChannel):
                    voice_users = [m for m in channel.members if not m.bot]
                    channels.append(
                        {
                            "id": str(channel.id),
                            "name": channel.name,
                            "type": "voice",
                            "topic": "",
                            "slowmode": 0,
                            "nsfw": False,
                            "voice_online": len(voice_users),
                            "voice_users": [self._member_payload(guild, m) for m in voice_users[:30]],
                        }
                    )
                elif isinstance(channel, discord.TextChannel):
                    channels.append(
                        {
                            "id": str(channel.id),
                            "name": channel.name,
                            "type": channel.type.name,
                            "topic": (channel.topic or "")[:200],
                            "slowmode": channel.slowmode_delay,
                            "nsfw": channel.nsfw,
                            "voice_online": 0,
                            "voice_users": [],
                        }
                    )
            categories.append(
                {
                    "id": str(category.id),
                    "name": category.name,
                    "position": category.position,
                    "channels": channels,
                }
            )
        uncategorized: list[dict[str, Any]] = []
        for channel in guild.channels:
            if isinstance(channel, discord.TextChannel) and channel.category_id is None:
                uncategorized.append(
                    {
                        "id": str(channel.id),
                        "name": channel.name,
                        "type": channel.type.name,
                        "topic": (channel.topic or "")[:200],
                        "slowmode": channel.slowmode_delay,
                        "nsfw": channel.nsfw,
                        "voice_online": 0,
                        "voice_users": [],
                    }
                )
        if uncategorized:
            categories.append(
                {"id": "", "name": "Без категории", "position": 9999, "channels": uncategorized}
            )
        roles = []
        for role in reversed(guild.roles):
            if role.is_default():
                continue
            roles.append(
                {
                    "id": str(role.id),
                    "name": role.name,
                    "color": f"#{role.color.value:06x}" if role.color.value else "#99aab5",
                    "position": role.position,
                    "member_count": len(role.members),
                    "hoist": role.hoist,
                    "mentionable": role.mentionable,
                    "managed": role.managed,
                    "bot_managed": role.is_bot_managed(),
                }
            )
        editable_roles = [
            role for role in guild.roles
            if not role.is_default() and not role.managed and me is not None and role.position < me.top_role.position
        ]
        for category in categories:
            category_channel = guild.get_channel(int(category["id"])) if category["id"] else None
            if isinstance(category_channel, discord.CategoryChannel):
                category["permission_overwrites"] = {
                    str(role.id): self._permission_state(category_channel.overwrites_for(role))
                    for role in editable_roles
                }
        wardogs_role = discord.utils.get(guild.roles, name=_WARDOGS_ROLE_NAME)
        wardogs_category = guild.get_channel(_WARDOGS_CATEGORY_ID)
        online = sum(1 for m in guild.members if m.status is not discord.Status.offline)
        return self._json(
            {
                "ok": True,
                "guild": {
                    "id": str(guild.id),
                    "name": guild.name,
                    "icon": guild.icon.url if guild.icon else None,
                    "description": guild.description,
                    "members": guild.member_count or len(guild.members),
                    "online": online,
                    "channels": len(guild.channels),
                    "roles": len(guild.roles),
                    "boosts": guild.premium_subscription_count or 0,
                    "level": f"Уровень {guild.premium_tier}",
                    "owner": guild.owner.display_name if guild.owner else None,
                    "created_at": guild.created_at.isoformat(),
                    "me_name": me.display_name if me else None,
                    "me_permissions": self._bot_permission_summary(guild),
                },
                "categories": categories,
                "roles": roles,
                "editable_roles": [
                    {"id": str(role.id), "name": role.name, "position": role.position}
                    for role in sorted(editable_roles, key=lambda item: (-item.position, item.name.casefold()))
                ],
                "wardogs": {
                    "role_id": str(wardogs_role.id) if wardogs_role else None,
                    "role_name": _WARDOGS_ROLE_NAME,
                    "category_id": str(_WARDOGS_CATEGORY_ID),
                    "category_name": wardogs_category.name if isinstance(wardogs_category, discord.CategoryChannel) else None,
                    "available": bool(wardogs_role and isinstance(wardogs_category, discord.CategoryChannel)),
                },
                "permission_names": list(_EDITABLE_PERMISSION_NAMES),
            }
        )

    @staticmethod
    def _permission_state(overwrite: discord.PermissionOverwrite) -> dict[str, bool | None]:
        return {name: getattr(overwrite, name) for name in _EDITABLE_PERMISSION_NAMES}

    def _editable_role(self, guild: discord.Guild, value: Any) -> discord.Role | None:
        try:
            role = guild.get_role(int(value))
        except (TypeError, ValueError):
            return None
        me = guild.me
        if role is None or role.is_default() or role.managed or me is None or role.position >= me.top_role.position:
            return None
        return role

    @staticmethod
    def _category(guild: discord.Guild, value: Any) -> discord.CategoryChannel | None:
        try:
            channel = guild.get_channel(int(value))
        except (TypeError, ValueError):
            return None
        return channel if isinstance(channel, discord.CategoryChannel) else None

    async def _apply_category_permissions(
        self, category: discord.CategoryChannel, role: discord.Role, raw: Any
    ) -> None:
        if not isinstance(raw, dict):
            raise ValueError("permissions должен быть объектом")
        overwrite = discord.PermissionOverwrite()
        for name in _EDITABLE_PERMISSION_NAMES:
            value = raw.get(name)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"Некорректное значение права: {name}")
            setattr(overwrite, name, value)
        await category.set_permissions(role, overwrite=overwrite, reason="Настройка прав через веб-админку")

    async def _api_server_permissions(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        payload = await request.json()
        role = self._editable_role(guild, payload.get("role_id"))
        category = self._category(guild, payload.get("category_id"))
        if role is None:
            return self._json({"ok": False, "error": "Роль не найдена или находится выше роли бота"}, status=400)
        if category is None:
            return self._json({"ok": False, "error": "Категория не найдена"}, status=400)
        me = guild.me
        if me is None or not category.permissions_for(me).manage_channels:
            return self._json({"ok": False, "error": "Боту нужно право Manage Channels"}, status=403)
        try:
            await self._apply_category_permissions(category, role, payload.get("permissions"))
        except (ValueError, discord.Forbidden, discord.HTTPException) as exc:
            return self._json({"ok": False, "error": str(exc)}, status=400)
        return self._json({"ok": True})

    async def _api_wardogs_permissions(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        role = discord.utils.get(guild.roles, name=_WARDOGS_ROLE_NAME)
        category = self._category(guild, _WARDOGS_CATEGORY_ID)
        if role is None or category is None:
            return self._json({"ok": False, "error": "Роль Wardogs или целевая категория не найдена"}, status=404)
        if self._editable_role(guild, role.id) is None:
            return self._json({"ok": False, "error": "Роль Wardogs находится выше роли бота"}, status=403)
        me = guild.me
        if me is None or not category.permissions_for(me).manage_channels:
            return self._json({"ok": False, "error": "Боту нужно право Manage Channels"}, status=403)
        permissions = {name: True for name in _EDITABLE_PERMISSION_NAMES}
        try:
            await self._apply_category_permissions(category, role, permissions)
        except (discord.Forbidden, discord.HTTPException) as exc:
            return self._json({"ok": False, "error": str(exc)}, status=400)
        return self._json({"ok": True, "category_id": str(_WARDOGS_CATEGORY_ID), "role": _WARDOGS_ROLE_NAME})

    def _bot_permission_summary(self, guild: discord.Guild) -> list[str]:
        if guild.me is None:
            return []
        perms = guild.me.guild_permissions
        mapping = {
            "kick_members": "Кик",
            "ban_members": "Бан",
            "moderate_members": "Тайм-ауты",
            "manage_roles": "Роли",
            "manage_channels": "Каналы",
            "manage_messages": "Сообщения",
            "manage_guild": "Управление сервером",
            "administrator": "Администратор",
        }
        return [label for flag, label in mapping.items() if getattr(perms, flag, False)]

    async def _api_server_members(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        query = (request.query.get("q") or "").strip().lower()
        members = list(guild.members)
        if query:
            if query.isdigit():
                member = guild.get_member(int(query))
                members = [member] if member else []
            else:
                members = [
                    m
                    for m in members
                    if query in m.name.lower() or query in m.display_name.lower() or query in str(m).lower()
                ]
        members.sort(key=lambda m: (m.bot, m.display_name.lower()))
        service = self.services.moderation
        payload = []
        for member in members[:25]:
            item = self._member_payload(guild, member)
            item["warnings"] = await service.warn_count(guild.id, member.id)
            payload.append(item)
        return self._json({"ok": True, "total": len(payload), "members": payload})

    async def _api_server_members_roles(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        payload = await self._read_json(request)
        member = self._resolve_member(guild, payload.get("member"))
        role = self._resolve_role(guild, payload.get("role_id"))
        if member is None or role is None:
            return self._json({"ok": False, "error": "Участник или роль не найдены"}, status=400)
        action = str(payload.get("action") or "add")
        if guild.me is None or not guild.me.guild_permissions.manage_roles:
            return self._json({"ok": False, "error": "У бота нет права manage_roles"}, status=400)
        if not role.is_assignable():
            return self._json({"ok": False, "error": "Роль нельзя выдавать (интегрированная или выше ролей бота)"}, status=400)
        try:
            if action == "remove" and role in member.roles:
                await member.remove_roles(role, reason="Вебпанель: снятие роли")
                applied = False
            elif action == "remove":
                applied = False
            elif action == "add" and role not in member.roles:
                await member.add_roles(role, reason="Вебпанель: выдача роли")
                applied = True
            else:
                applied = role in member.roles
        except discord.HTTPException as exc:
            return self._json({"ok": False, "error": f"Discord: {exc.status} {exc.text}"[:200]}, status=400)
        return self._json(
            {
                "ok": True,
                "member_id": str(member.id),
                "member_name": member.display_name,
                "role_id": str(role.id),
                "role_name": role.name,
                "action": action,
                "applied": applied,
                "has_role": role in member.roles,
            }
        )

    async def _api_warns(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        service = self.services.moderation
        user_value = request.query.get("user_id") or (request.query.get("q") or "")
        warns = await service.all_warns(guild.id, 300)
        if user_value:
            member = self._resolve_member(guild, user_value)
            if member is None:
                return self._json({"ok": False, "error": "Участник не найден"}, status=404)
            warns = [w for w in warns if w["user_id"] == member.id]
        enriched = [
            {
                "id": w["id"],
                "user_id": str(w["user_id"]),
                "user_name": self._member_name(guild, w["user_id"]),
                "moderator_id": str(w["moderator_id"]),
                "moderator_name": self._member_name(guild, w["moderator_id"]),
                "reason": w["reason"],
                "created_at": w["created_at"],
            }
            for w in warns
        ]
        return self._json({"ok": True, "total": len(enriched), "warns": enriched})

    async def _api_moderation_cases(self, request: web.Request) -> web.Response:
        """История moderation cases: всего по серверу или по конкретному участнику."""
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        service = self.services.cases
        user_value = (request.query.get("user_id") or "").strip()
        if user_value:
            member = self._resolve_member(guild, user_value)
            if member is None:
                return self._json({"ok": False, "error": "Участник не найден"}, status=404)
            rows = await service.list_for_user(guild.id, member.id, 200)
        else:
            rows = await service.list_for_guild(guild.id, 200)
        cases = [
            {
                "case_id": int(row["case_id"]),
                "user_id": str(row["user_id"]),
                "user_name": self._member_name(guild, int(row["user_id"])),
                "moderator_id": str(row["moderator_id"]),
                "moderator_name": self._member_name(guild, int(row["moderator_id"])),
                "action": str(row["action"]),
                "reason": row["reason"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
                "active": bool(row.get("active")),
            }
            for row in rows
        ]
        return self._json({"ok": True, "total": len(cases), "cases": cases})

    def _member_name(self, guild: discord.Guild, user_id: int) -> str:
        member = guild.get_member(user_id)
        if member is not None:
            return member.display_name
        if user_id == self.bot.user.id:
            return "Бот (панель)"
        return str(user_id)

    def _member_options(self, guild: discord.Guild, limit: int = 0) -> list[dict[str, Any]]:
        members = [member for member in guild.members if not member.bot]
        members.sort(key=lambda member: member.display_name.lower())
        if limit and len(members) > limit:
            members = members[:limit]
        return [{"id": str(member.id), "name": member.display_name} for member in members]

    async def _api_warn_add(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        payload = await self._read_json(request)
        member = self._resolve_member(guild, payload.get("member"))
        if member is None:
            return self._json({"ok": False, "error": "Участник не найден"}, status=404)
        guard = self._guard_mod_target(guild, member)
        if guard:
            return self._json({"ok": False, "error": guard}, status=400)
        reason = str(payload.get("reason") or "Без причины")[:500]
        service = self.services.moderation
        count = await service.warn(guild.id, member.id, self.bot.user.id, reason)
        if guild.me is not None:
            await self.services.logging.log_mod_action(
                guild, "warn", member, guild.me, reason, description=f"{member.mention} получил предупреждение {count} (панель)"
            )
        return self._json({"ok": True, "count": count, "member": self._member_payload(guild, member)})

    async def _api_warn_delete(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        warn_id = self._parse_id(request.match_info.get("warn_id"))
        service = self.services.moderation
        if warn_id is None or (warn := await service.get_warn(guild.id, warn_id)) is None:
            return self._json({"ok": False, "error": "Предупреждение не найдено"}, status=404)
        await service.remove_warn(guild.id, warn_id)
        return self._json(
            {
                "ok": True,
                "warn_id": warn_id,
                "user_id": str(warn["user_id"]),
                "action": "removed",
                "next_count": await service.warn_count(guild.id, warn["user_id"]),
            }
        )

    async def _api_warn_clear(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        payload = await self._read_json(request)
        member = self._resolve_member(guild, payload.get("member"))
        if member is None:
            return self._json({"ok": False, "error": "Участник не найден"}, status=404)
        service = self.services.moderation
        cleared = await service.clear_warns(guild.id, member.id)
        return self._json({"ok": True, "cleared": cleared, "member_id": str(member.id)})

    async def _api_mod_kick(self, request: web.Request) -> web.Response:
        return await self._mod_action(request, "kick")

    async def _api_mod_ban(self, request: web.Request) -> web.Response:
        return await self._mod_action(request, "ban", delete_days=True)

    async def _api_mod_unban(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        payload = await self._read_json(request)
        if guild.me is None or not guild.me.guild_permissions.ban_members:
            return self._json({"ok": False, "error": "У бота нет права ban_members"}, status=400)
        user_id = self._parse_id(payload.get("user_id"))
        if user_id is None:
            return self._json({"ok": False, "error": "Неверный ID пользователя"}, status=400)
        try:
            ban_entry = await guild.fetch_ban(discord.Object(id=user_id))
        except discord.NotFound:
            return self._json({"ok": False, "error": "Пользователь не в бане"}, status=404)
        reason = str(payload.get("reason") or "Разбан из вебпанели")
        await guild.unban(ban_entry.user, reason=f"Вебпанель | {reason}")
        if guild.me is not None:
            await self.services.logging.log_mod_action(
                guild, "unban", ban_entry.user, guild.me, reason, description=f"{ban_entry.user} разбанен (панель)"
            )
        return self._json({"ok": True, "user_id": str(user_id), "user_name": str(ban_entry.user)})

    async def _api_mod_timeout(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        payload = await self._read_json(request)
        if guild.me is None or not guild.me.guild_permissions.moderate_members:
            return self._json({"ok": False, "error": "У бота нет права moderate_members"}, status=400)
        member = self._resolve_member(guild, payload.get("member"))
        if member is None:
            return self._json({"ok": False, "error": "Участник не найден"}, status=404)
        guard = self._guard_mod_target(guild, member)
        if guard:
            return self._json({"ok": False, "error": guard}, status=400)
        try:
            seconds = int(payload.get("duration_seconds") or 600)
        except (TypeError, ValueError):
            seconds = 600
        seconds = max(30, min(seconds, 28 * 86400))
        reason = str(payload.get("reason") or "Тайм-аут из вебпанели")
        end = datetime.now(UTC) + timedelta(seconds=seconds)
        await member.timeout(end, reason=f"Вебпанель | {reason}")
        if guild.me is not None:
            await self.services.logging.log_mod_action(
                guild, "timeout", member, guild.me, reason,
                description=f"{member.mention} получил тайм-аут {seconds // 60} мин (панель)",
            )
        return self._json(
            {"ok": True, "member_id": str(member.id), "member_name": member.display_name, "until": end.isoformat()}
        )

    async def _mod_action(self, request: web.Request, action: str, *, delete_days: bool = False) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        payload = await self._read_json(request)
        if guild.me is None or not getattr(guild.me.guild_permissions, f"{action}_members"):
            return self._json({"ok": False, "error": f"У бота нет права {action}_members"}, status=400)
        member = self._resolve_member(guild, payload.get("member"))
        if member is None:
            return self._json({"ok": False, "error": "Участник не найден"}, status=404)
        guard = self._guard_mod_target(guild, member)
        if guard:
            return self._json({"ok": False, "error": guard}, status=400)
        reason = str(payload.get("reason") or "")
        fmt = "кикнут"
        extra: dict[str, Any] = {}
        if action == "kick":
            await member.kick(reason=f"Вебпанель{': ' + reason if reason else ''}")
        else:
            fmt = "забанен"
            delete_days_int = 0
            if delete_days:
                try:
                    delete_days_int = max(0, min(int(payload.get("delete_days") or 0), 7))
                except (TypeError, ValueError):
                    delete_days_int = 0
            await member.ban(reason=f"Вебпанель{': ' + reason if reason else ''}", delete_message_seconds=delete_days_int * 86400)
            extra["delete_days"] = delete_days_int
        if guild.me is not None:
            await self.services.logging.log_mod_action(
                guild, action, member, guild.me, reason, description=f"{member.mention} {fmt} (панель)"
            )
        return self._json(
            {"ok": True, "action": action, "member_id": str(member.id), "member_name": member.display_name, **extra}
        )
