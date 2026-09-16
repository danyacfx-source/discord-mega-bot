"""Сервис тикетов: создание, закрытие, транскрипты."""
from __future__ import annotations

import asyncio
import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import discord

from app.core import embeds
from app.core.views import TicketCloseView

if TYPE_CHECKING:
    from app.data.tickets_repository import TicketsRepository
    from app.services.logging_service import LoggingService
    from app.services.settings_service import SettingsService

_MAX_TRANSCRIPT_MESSAGES = 300


@dataclass(slots=True)
class TicketCreateResult:
    channel: discord.TextChannel | None
    error: str | None = None


@dataclass(slots=True)
class TicketCloseResult:
    error: str | None = None
    transcript_channel_mention: str | None = None


class TicketService:
    def __init__(
        self,
        settings: SettingsService,
        tickets_repo: TicketsRepository,
        logging_service: LoggingService,
    ) -> None:
        self._settings = settings
        self._repo = tickets_repo
        self._logging = logging_service

    async def create(self, guild: discord.Guild, member: discord.Member) -> TicketCreateResult:
        if await self._repo.has_open_by_creator(guild.id, member.id):
            return TicketCreateResult(channel=None, error="У вас уже есть открытый тикет.")

        settings = await self._settings.get(guild.id)
        category_id = settings.get("ticket_category_id")
        category = guild.get_channel(category_id) if category_id else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, manage_messages=True
            ),
            member: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, attach_files=True
            ),
        }
        name = re.sub(r"[^a-z0-9-]", "-", member.name.lower()).strip("-") or "ticket"
        try:
            channel = await guild.create_text_channel(
                name=f"ticket-{name}",
                category=category if isinstance(category, discord.CategoryChannel) else None,
                overwrites=overwrites,
                reason=f"Тикет от {member}",
            )
        except discord.HTTPException as exc:
            return TicketCreateResult(channel=None, error=f"Discord API: {exc}")

        now = datetime.now(UTC)
        await self._repo.create(guild.id, channel.id, member.id, now)

        intro = embeds.info("Новый тикет", f"Опишите свою проблему, {member.mention}.")
        intro.add_field(name="Пользователь", value=member.mention, inline=True)
        intro.set_footer(text="Нажмите кнопку ниже, чтобы закрыть тикет по завершении.")
        await channel.send(embed=intro, view=TicketCloseView(self))
        return TicketCreateResult(channel=channel)

    async def get_open_ticket(self, guild_id: int, channel_id: int) -> dict | None:
        ticket = await self._repo.by_channel(channel_id)
        if ticket and ticket["status"] == "open":
            return ticket
        return None

    async def close(self, guild: discord.Guild, channel: discord.TextChannel | None, closer: discord.Member) -> TicketCloseResult:
        if channel is None:
            return TicketCloseResult(error="Не удалось определить канал тикета.")

        ticket = await self._repo.by_channel(channel.id)
        if ticket is None:
            return TicketCloseResult(error="Этот канал не является тикетом.")
        if ticket["status"] != "open":
            return TicketCloseResult(error="Тикет уже закрыт.")

        await self._repo.close(ticket["ticket_id"], datetime.now(UTC))

        transcript = await self._build_transcript(guild, channel)
        summary = embeds.info(
            "Тикет закрыт",
            f"Закрыл: {closer.mention}\nСистемный номер: `{ticket['ticket_id']}`",
        )
        if transcript is not None:
            await self._send_transcript(guild, channel, transcript.file, summary)
            transcript.cleanup()

        asyncio.create_task(self._delete_after(channel))

        target = await self._logging.target_channel(guild)
        mention = target.mention if target else channel.mention
        return TicketCloseResult(transcript_channel_mention=mention)

    async def _build_transcript(self, guild: discord.Guild, channel: discord.TextChannel):
        lines: list[str] = []
        try:
            async for message in channel.history(limit=_MAX_TRANSCRIPT_MESSAGES, oldest_first=True):
                content = message.clean_content.strip() or "(без текста)"
                lines.append(f"[{message.created_at:%Y-%m-%d %H:%M}] {message.author} ({message.author.id}): {content}")
        except discord.HTTPException:
            lines.append("(не удалось получить историю сообщений)")

        data = "\n".join(lines or ["(тикет без сообщений)"])

        class _Transcript:
            file: discord.File

            def __init__(self, file: discord.File) -> None:
                self.file = file

            def cleanup(self) -> None:
                self.file.fp.close()

        buffer = io.BytesIO(data.encode("utf-8"))
        return _Transcript(discord.File(buffer, filename=f"transcript-{channel.name}.txt"))

    async def _send_transcript(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel,
        file: discord.File,
        summary: discord.Embed,
    ) -> None:
        target = await self._logging.target_channel(guild) or channel
        try:
            await target.send(embed=summary, file=file)
        except discord.HTTPException:
            try:
                await channel.send(embed=summary, file=file)
            except discord.HTTPException:
                pass

    @staticmethod
    async def _delete_after(channel: discord.TextChannel, delay: float = 10.0) -> None:
        await asyncio.sleep(delay)
        try:
            await channel.delete(reason="Тикет закрыт")
        except discord.HTTPException:
            pass
