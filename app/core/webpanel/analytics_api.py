"""Аналитика сообщений, live-лента событий, WebSocket-каналы и экспорт CSV."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import aiohttp
import discord
from aiohttp import web

from app.core.webpanel.base_api import _BaseApi
from app.db.activity_repository import ActivityRepository

logger = logging.getLogger("bot.webpanel")


class _AnalyticsApiMixin(_BaseApi):
    """Аналитика сообщений, live-лента событий, WebSocket-каналы и экспорт CSV."""

    async def _on_message_hook(self, message: discord.Message) -> None:
        """Корутина дяди discord.py: add_listener требует async-функцию, не обёртку."""
        await self._msg_counter(message)

    async def _msg_counter(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        now = datetime.now(UTC)
        hour_key = now.replace(minute=0, second=0, microsecond=0)
        day_key = now.date().isoformat()
        self._msg_total += 1
        if self._msg_by_hour and self._msg_by_hour[-1]["t"] == hour_key.timestamp():
            self._msg_by_hour[-1]["n"] += 1
        else:
            self._msg_by_hour.append({"t": hour_key.timestamp(), "n": 1})
        if self._msg_by_day and self._msg_by_day[-1].get("d") == day_key:
            self._msg_by_day[-1]["n"] += 1
        else:
            self._msg_by_day.append({"d": day_key, "n": 1})
        self._pending_activity[(message.guild.id, hour_key.isoformat())] += 1

    async def _analytics_flush_loop(self) -> None:
        while True:
            await asyncio.sleep(10)
            await self._flush_activity()

    async def _flush_activity(self) -> None:
        if self.bot.db is None or not self._pending_activity:
            return
        pending = self._pending_activity
        self._pending_activity = defaultdict(int)
        for (guild_id, bucket), amount in pending.items():
            try:
                await ActivityRepository(self.bot.db).increment(guild_id, bucket, amount)
            except Exception:
                self._pending_activity[(guild_id, bucket)] += amount
                logger.exception("Не удалось сохранить activity metric")
        if self._analytics_clients:
            payload = await self._analytics_payload()
            dead: list[web.WebSocketResponse] = []
            for websocket in self._analytics_clients:
                try:
                    await websocket.send_json({"type": "analytics", "data": payload})
                except (ConnectionResetError, RuntimeError, aiohttp.ClientConnectionError):
                    dead.append(websocket)
            for websocket in dead:
                self._analytics_clients.discard(websocket)

    async def _analytics_payload(self) -> dict[str, Any]:
        guild = self._primary_guild()
        if guild is None or self.bot.db is None:
            return {"guild_id": None, "rows": []}
        rows = await ActivityRepository(self.bot.db).list_hourly(guild.id, 1000)
        return {"guild_id": str(guild.id), "rows": rows}

    async def _api_analytics(self, request: web.Request) -> web.Response:
        await self._flush_activity()
        return self._json({"ok": True, **(await self._analytics_payload())})

    async def _api_analytics_export(self, request: web.Request) -> web.Response:
        await self._flush_activity()
        payload = await self._analytics_payload()
        rows = payload["rows"]
        if request.query.get("format", "json").lower() == "csv":
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=["bucket", "messages"])
            writer.writeheader()
            writer.writerows(rows)
            return web.Response(
                text=output.getvalue(),
                content_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=activity.csv"},
            )
        return self._json({"ok": True, **payload})

    async def _api_streams_archive_csv(self, request: web.Request) -> web.Response:
        """Экспорт архива завершённых эфиров всех настроенных каналов (CSV; BOM, разделитель ;)."""
        config = self.bot.config
        services = self.services
        sources: list[tuple[str, str, Any]] = []
        for login in config.twitch_channels:
            sources.append(("twitch", login, services.twitch.archive_store(login)))
        if config.kick_channel_slug:
            sources.append(("kick", config.kick_channel_slug, services.kick.archive_store(config.kick_channel_slug)))
        if config.vk_channel_slug:
            sources.append(("vk_video", config.vk_channel_slug, services.vk_video.archive_store(config.vk_channel_slug)))

        rows: list[list[Any]] = []
        for platform, name, store in sources:
            for entry in await store.list():
                rows.append(
                    [
                        platform,
                        name,
                        entry.get("title") or "",
                        entry.get("category") or "",
                        entry.get("url") or "",
                        entry.get("vod") or "",
                        entry.get("started_at") or "",
                        entry.get("ended_at") or "",
                        int(entry.get("seconds") or 0) // 60,
                        int(entry.get("peak") or 0),
                    ]
                )
        rows.sort(key=lambda row: str(row[7]), reverse=True)

        output = io.StringIO()
        writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
        writer.writerow(
            ["платформа", "канал", "название", "категория", "ссылка", "запись", "начало", "конец", "минуты", "пик"]
        )
        writer.writerows(rows)
        filename = f"streams-archive-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.csv"
        return web.Response(
            text="﻿" + output.getvalue(),
            content_type="text/csv",
            charset="utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    async def _ws_analytics(self, request: web.Request) -> web.StreamResponse:
        if not self._rate_ok(request) or not self._allowed_origin(request):
            return self._json({"ok": False, "error": "Unauthorized"}, status=401)
        websocket = web.WebSocketResponse(heartbeat=30)
        await websocket.prepare(request)
        try:
            first = await websocket.receive(timeout=5)
        except TimeoutError:
            await websocket.close(code=4401, message=b"Unauthorized")
            return websocket
        token = ""
        if first.type == web.WSMsgType.TEXT:
            try:
                token = str(json.loads(first.data).get("token") or "")
            except (TypeError, ValueError):
                token = ""
        role = self._check_token_value(token)
        if role is None or self._role_rank(role) < self._role_rank("viewer"):
            await websocket.close(code=4401, message=b"Unauthorized")
            return websocket
        self._analytics_clients.add(websocket)
        try:
            await websocket.send_json({"type": "analytics", "data": await self._analytics_payload()})
            async for message in websocket:
                if message.type in (web.WSMsgType.CLOSE, web.WSMsgType.ERROR):
                    break
        finally:
            self._analytics_clients.discard(websocket)
        return websocket

    def _on_ring_record(self, entry: dict[str, str]) -> None:
        """WARNING+ и аудит-записи уходят в шину живой ленты (из любого потока)."""
        if entry.get("audit") != "1" and entry.get("level") not in ("WARNING", "ERROR", "CRITICAL"):
            return
        services = getattr(self.bot, "services", None)
        events = getattr(services, "events", None) if services is not None else None
        if events is None:
            return
        events.publish(
            "log",
            {
                "level": entry.get("level", "INFO"),
                "msg": entry.get("msg", ""),
                "cat": entry.get("cat", "sys"),
                "t": entry.get("t", ""),
            },
        )

    async def _events_loop(self) -> None:
        """Раздаёт события шины подключённым ws-клиентам живой ленты."""
        while True:
            await asyncio.sleep(0.4)
            try:
                services = getattr(self.bot, "services", None)
                events = getattr(services, "events", None) if services is not None else None
                if events is None:
                    continue
                if not self._event_clients:
                    # клиентов нет — не копим буфер, новое только после подключения
                    self._events_seq = events.seq
                    continue
                batch = events.drain(self._events_seq)
                if not batch:
                    continue
                self._events_seq = batch[-1]["seq"]
                for queue in tuple(self._event_clients):
                    for event in batch:
                        if queue.full():
                            try:
                                queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                        try:
                            queue.put_nowait(event)
                        except asyncio.QueueFull:
                            pass
            except asyncio.CancelledError:
                return
            except Exception:
                logger.debug("Живая лента: сбой рассылки событий", exc_info=True)

    async def _ws_events(self, request: web.Request) -> web.StreamResponse:
        if not self._rate_ok(request) or not self._allowed_origin(request):
            return self._json({"ok": False, "error": "Unauthorized"}, status=401)
        websocket = web.WebSocketResponse(heartbeat=30)
        await websocket.prepare(request)
        try:
            first = await websocket.receive(timeout=5)
        except TimeoutError:
            await websocket.close(code=4401, message=b"Unauthorized")
            return websocket
        token = ""
        if first.type == web.WSMsgType.TEXT:
            try:
                token = str(json.loads(first.data).get("token") or "")
            except (TypeError, ValueError):
                token = ""
        role = self._check_token_value(token)
        if role is None or self._role_rank(role) < self._role_rank("viewer"):
            await websocket.close(code=4401, message=b"Unauthorized")
            return websocket
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._event_clients.add(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    if websocket.closed:
                        break
                    await websocket.send_json({"type": "ping"})
                    continue
                await websocket.send_json(event)
        except (ConnectionResetError, ConnectionError, RuntimeError):
            pass
        finally:
            self._event_clients.discard(queue)
        return websocket
