"""Overlay, расписание, бэкапы, вебхуки, логи и аудит."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp
import discord
from aiohttp import web

from app.core.overlay.layout import (
    CANVAS_PRESETS,
    WIDGET_TYPES,
    default_layout,
    delete_layout,
    list_layouts,
    load_layout,
    new_id,
    save_layout,
    save_layouts,
)
from app.core.webpanel.payload import (
    _WEBHOOK_RE,
    _raw_to_client,
    _trim_components,
    _trim_embeds,
    overlay_url_base,
)

logger = logging.getLogger("bot.webpanel")

class _ToolsApiMixin:
    """Overlay, расписание, бэкапы, вебхуки, логи и аудит."""

    def _overlay_url_base(self) -> str:
        return overlay_url_base(self.bot.config)

    async def _overlay_proxy(self, request: web.Request) -> web.StreamResponse:
        """Проксирует ``/overlay*`` на локальный оверлей-сервер.

        Оба сервиса живут в одном контейнере и слушают разные порты, но
        хостинг пропускает трафик домена только на один порт панели.
        Панель выступает шлюзом: запрос уходит на ``127.0.0.1:OVERLAY_PORT``,
        ответ потоково возвращается клиенту без аутентификации (та же
        проверка токена остаётся на стороне оверлея).
        """
        config = self.bot.config
        if not config.overlay_port:
            return web.Response(status=404, text="Overlay disabled")
        url = f"http://127.0.0.1:{int(config.overlay_port)}{request.raw_path}"
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in {"host", "content-length", "connection", "keep-alive"}
        }
        try:
            async with self._require_http().get(url, headers=headers, allow_redirects=False) as resp:
                out = web.StreamResponse(status=resp.status)
                for key, value in resp.headers.items():
                    # тело декомпрессируется сессией — заголовки кодирования устаревают
                    if key.lower() in {"connection", "keep-alive", "transfer-encoding", "content-length", "content-encoding"}:
                        continue
                    out.headers[key] = value
                await out.prepare(request)
                async for chunk in resp.content.iter_chunked(65536):
                    await out.write(chunk)
                await out.write_eof()
                return out
        except (aiohttp.ClientError, TimeoutError):
            logger.debug("Оверлей недоступен: %s", url, exc_info=True)
            return web.Response(status=502, text="Overlay offline")

    async def _api_overlay_get(self, request: web.Request) -> web.Response:
        config = self.bot.config
        overlay = getattr(self.bot, "overlay", None)
        return self._json(
            {
                "ok": True,
                "enabled": bool(config.overlay_port),
                "host": config.overlay_host,
                "port": config.overlay_port,
                "url_base": self._overlay_url_base(),
                "token": overlay.token if overlay is not None else "",
                "layouts": await list_layouts(self.services.kv),
                "canvas_presets": [list(p) for p in CANVAS_PRESETS],
                "widget_types": list(WIDGET_TYPES),
            }
        )

    async def _api_overlay_layouts_create(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        kv = self.services.kv
        layouts = await list_layouts(kv)
        layout_id = new_id()
        name = str(payload.get("name") or "").strip()[:60] or f"Раскладка {len(layouts) + 1}"
        layout = default_layout(layout_id)
        layout["name"] = name
        layout = await save_layout(kv, layout)
        layouts.append({"id": layout_id, "name": name})
        await save_layouts(kv, layouts)
        return self._json({"ok": True, "layout": layout, "layouts": layouts})

    async def _api_overlay_layout_save(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        raw_layout = payload.get("layout") if isinstance(payload.get("layout"), dict) else {}
        kv = self.services.kv
        layout = await save_layout(kv, raw_layout)
        layouts = await list_layouts(kv)
        entry = {"id": layout["id"], "name": layout["name"]}
        known = next((item for item in layouts if item["id"] == layout["id"]), None)
        if known is None:
            layouts.append(entry)
        else:
            known["name"] = entry["name"]
        await save_layouts(kv, layouts)
        return self._json({"ok": True, "layout": layout, "layouts": layouts})

    async def _api_overlay_layout_load(self, request: web.Request) -> web.Response:
        layout_id = str(request.query.get("id") or "")
        layout = await load_layout(self.services.kv, layout_id)
        if layout is None:
            return self._json({"ok": False, "error": "Раскладка не найдена"}, status=404)
        return self._json({"ok": True, "layout": layout})

    async def _api_overlay_layout_delete(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        layout_id = str(payload.get("id") or "")
        deleted = await delete_layout(self.services.kv, layout_id)
        return self._json({"ok": deleted, "layouts": await list_layouts(self.services.kv)})

    async def _api_overlay_layout_rename(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        layout_id = str(payload.get("id") or "")
        name = str(payload.get("name") or "").strip()[:60]
        kv = self.services.kv
        layouts = await list_layouts(kv)
        entry = next((item for item in layouts if item["id"] == layout_id), None)
        if entry is None or not name:
            return self._json({"ok": False, "error": "Раскладка не найдена"}, status=404)
        entry["name"] = name
        await save_layouts(kv, layouts)
        stored = await load_layout(kv, layout_id)
        if stored is not None:
            stored["name"] = name
            await save_layout(kv, stored)
        return self._json({"ok": True, "layouts": layouts})

    async def _api_schedule(self, request: web.Request) -> web.Response:
        service = self.services.scheduled
        rows = await service.recent(200)
        guild = self._primary_guild()
        upcoming: list[dict[str, Any]] = []
        done: list[dict[str, Any]] = []
        for row in rows:
            embed_schema: dict[str, Any] = {}
            try:
                embed_schema = json.loads(row.get("embed_json") or "{}") or {}
            except (TypeError, ValueError):
                embed_schema = {}
            item = {
                "id": row["id"],
                "guild_id": str(row["guild_id"]),
                "channel_id": str(row["channel_id"]),
                "channel_name": (
                    self._channel_name(guild, row["channel_id"]) if guild is not None else str(row["channel_id"])
                ),
                "content": (row["content"] or "")[:120],
                "title": (embed_schema.get("title") or "")[:120],
                "send_at": row["send_at"],
                "created_at": row["created_at"],
                "done": bool(row["done"]),
            }
            (done if row["done"] else upcoming).append(item)
        upcoming.sort(key=lambda item: item["send_at"])
        # Актуальный канал ищем по всем гильдиям бота, не только primary.
        for item in upcoming:
            ch = self.bot.get_channel(int(item["channel_id"]))
            if ch is not None:
                item["channel_name"] = f"{'🔊' if isinstance(ch, discord.VoiceChannel) else '#'} {ch.name}"
        return self._json({"ok": True, "upcoming": upcoming, "done": done})

    async def _api_schedule_create(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        channel = self._resolve_channel(payload.get("channel_id") or "")
        if channel is None or not isinstance(channel, discord.TextChannel):
            return self._json({"ok": False, "error": "Канал не найден"}, status=400)
        send_at = None
        raw_at = str(payload.get("send_at") or "")
        if raw_at:
            try:
                send_at = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
            except ValueError:
                return self._json({"ok": False, "error": "Некорректная дата отправки"}, status=400)
        if send_at is None:
            return self._json({"ok": False, "error": "Укажите дату отправки"}, status=400)
        content = str(payload.get("content") or "").strip()
        embed = payload.get("embed")
        embed = embed if isinstance(embed, dict) else {}
        if not content and not (embed.get("title") or embed.get("description")):
            return self._json({"ok": False, "error": "Укажите текст или эмбед"}, status=400)
        service = self.services.scheduled
        try:
            scheduled_id = await service.create(
                channel.guild.id, channel.id, self.bot.user.id, send_at, content=content[:2000], embed=embed
            )
        except ValueError as exc:
            return self._json({"ok": False, "error": str(exc)}, status=400)
        return self._json({"ok": True, "id": scheduled_id, "channel": channel.name, "send_at": send_at.isoformat()})

    async def _api_schedule_delete(self, request: web.Request) -> web.Response:
        message_id = self._parse_id(request.match_info.get("schedule_id"))
        if message_id is None:
            return self._json({"ok": False, "error": "Неверный ID"}, status=400)
        service = self.services.scheduled
        deleted = await service.delete(message_id)
        if not deleted:
            return self._json({"ok": False, "error": "Запись не найдена"}, status=404)
        return self._json({"ok": True, "id": message_id})

    async def _api_backup(self, request: web.Request) -> web.Response:
        guild = self._primary_guild()
        if guild is None:
            return self._json({"ok": False, "error": "Бот не подключён ни к одному серверу"}, status=400)
        settings_service = self.services.settings
        settings = await settings_service.get(guild.id)
        moderation = self.services.moderation
        giveaways = self.services.giveaways
        scheduled = self.services.scheduled
        data = {
            "generated_at": datetime.now(UTC).isoformat(),
            "bot": {
                "name": self.bot.user.name if self.bot.user else None,
                "guild_id": str(guild.id),
                "guild_name": guild.name,
            },
            "modules": self._modules_status(),
            "settings": dict(settings),
            "blocked_words": await settings_service.blocked_words(guild.id),
            "warns": await moderation.all_warns(guild.id, 2000),
            "giveaways": await giveaways.recent_for_guild(guild.id, 200),
            "scheduled": await scheduled.recent(200),
        }
        return self._attachment(
            json_data=data, filename=f"backup-{guild.name}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
        )

    async def _api_backup_db(self, request: web.Request) -> web.Response:
        db_path = Path(self.bot.config.db_path)
        if not db_path.is_file():
            return self._json({"ok": False, "error": "Файл БД не найден"}, status=404)
        snapshot_path = db_path.with_suffix(f".snapshot-{int(time.time())}.db")
        try:
            if self.bot.db is None:
                return self._json({"ok": False, "error": "База данных не подключена"}, status=503)
            await self.bot.db.backup(snapshot_path)
            if not snapshot_path.is_file():
                return self._json({"ok": False, "error": "Не удалось создать снапшот"}, status=500)
            body = snapshot_path.read_bytes()
            snapshot_path.unlink(missing_ok=True)
            return web.Response(
                body=body,
                content_type="application/octet-stream",
                headers={
                    "Content-Disposition": f'attachment; filename="db-snapshot-{datetime.now(UTC).strftime("%Y%m%d-%H%M%S")}.db"'
                },
            )
        except Exception as exc:
            snapshot_path.unlink(missing_ok=True)
            return self._json({"ok": False, "error": f"Ошибка снапшота: {exc}"[:200]}, status=500)

    def _attachment(self, *, data: bytes | None = None, json_data: dict[str, Any] | None = None, filename: str) -> web.Response:
        if json_data is not None:
            data = json.dumps(json_data, ensure_ascii=False, indent=2).encode("utf-8")
        # Guild names and other user-controlled labels must not be copied
        # directly into a response header.
        safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or "download"
        return web.Response(
            body=data,
            content_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{safe_filename}"', "Cache-Control": "no-store"},
        )

    # --- API: прокси вебхуков ---

    @staticmethod
    def _parse_id(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _webhook_base(self, url: Any) -> str | None:
        match = _WEBHOOK_RE.match(str(url or ""))
        if match is None:
            return None
        return f"https://discord.com/api/webhooks/{match.group(1)}/{match.group(2)}"

    async def _read_json(self, request: web.Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _webhook_body(self, payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "content": str(payload.get("content") or "")[:2000] or "",
            "embeds": _trim_embeds(payload.get("embeds")),
            "allowed_mentions": {"parse": []},
        }
        components = _trim_components(payload.get("components"))
        if components:
            body["components"] = components
        return body

    async def _api_webhook_send(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        base = self._webhook_base(payload.get("webhook_url"))
        if base is None:
            return self._json({"ok": False, "error": "Неверный Webhook URL"}, status=400)
        try:
            async with self._require_http().post(
                f"{base}?wait=true", json=self._webhook_body(payload), allow_redirects=False
            ) as response:
                data = await self._read_remote_json(response)
                if response.status >= 400:
                    return self._json(
                        {"ok": False, "error": data.get("message") or str(response.status), "data": data},
                        status=response.status,
                    )
                return self._json({"ok": True, "data": {"id": str(data.get("id"))}})
        except (aiohttp.ClientError, TimeoutError):
            logger.warning("Не удалось отправить сообщение через webhook", exc_info=True)
            return self._json({"ok": False, "error": "Discord Webhook недоступен"}, status=502)

    async def _api_webhook_edit(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        base = self._webhook_base(payload.get("webhook_url"))
        message_id = self._parse_id(payload.get("message_id"))
        if base is None or message_id is None:
            return self._json({"ok": False, "error": "Неверный Webhook URL или ID сообщения"}, status=400)
        try:
            async with self._require_http().patch(
                f"{base}/messages/{message_id}", json=self._webhook_body(payload), allow_redirects=False
            ) as response:
                data = await self._read_remote_json(response)
                if response.status >= 400:
                    return self._json(
                        {"ok": False, "error": data.get("message") or str(response.status), "data": data},
                        status=response.status,
                    )
                return self._json({"ok": True, "data": {"id": str(data.get("id"))}})
        except (aiohttp.ClientError, TimeoutError):
            logger.warning("Не удалось изменить сообщение через webhook", exc_info=True)
            return self._json({"ok": False, "error": "Discord Webhook недоступен"}, status=502)

    async def _api_webhook_fetch(self, request: web.Request) -> web.Response:
        payload = await self._read_json(request)
        base = self._webhook_base(payload.get("webhook_url"))
        message_id = self._parse_id(payload.get("message_id"))
        if base is None or message_id is None:
            return self._json({"ok": False, "error": "Неверный Webhook URL или ID сообщения"}, status=400)
        try:
            async with self._require_http().get(f"{base}/messages/{message_id}", allow_redirects=False) as response:
                data = await self._read_remote_json(response)
                if response.status >= 400:
                    return self._json(
                        {"ok": False, "error": data.get("message") or str(response.status), "data": data},
                        status=response.status,
                    )
                return self._json({"ok": True, "data": _raw_to_client(data)})
        except (aiohttp.ClientError, TimeoutError):
            logger.warning("Не удалось получить сообщение через webhook", exc_info=True)
            return self._json({"ok": False, "error": "Discord Webhook недоступен"}, status=502)

    async def _api_logs(self, request: web.Request) -> web.Response:
        limit = request.query.get("n", "200")
        try:
            limit = max(1, min(int(limit), 1000))
        except (TypeError, ValueError):
            limit = 200
        level = request.query.get("level", "")
        cat = request.query.get("cat", "")
        audit_raw = request.query.get("audit", "").lower()
        audit = "1" if audit_raw in ("1", "true", "yes") else ("0" if audit_raw in ("0", "false", "no") else "")
        entries = (
            self._ring.snapshot(limit, level=level, cat=cat, audit=audit)
            if self._ring is not None
            else []
        )
        return self._json({"ok": True, "count": len(entries), "logs": entries})

    async def _api_admin_audit(self, request: web.Request) -> web.Response:
        if self.bot.db is None:
            return self._json({"ok": False, "error": "База данных недоступна"}, status=503)
        raw_limit = request.query.get("n", "200")
        try:
            limit = max(1, min(int(raw_limit), 1000))
        except (TypeError, ValueError):
            limit = 200
        return self._json({"ok": True, "audit": await self.bot.db.list_admin_audit(limit)})

    @staticmethod
    async def _read_remote_json(response: aiohttp.ClientResponse) -> dict[str, Any]:
        """Read Discord responses even when a proxy returns non-JSON content."""
        try:
            data = await response.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError):
            text = await response.text()
            return {"message": text[:200]}
        return data if isinstance(data, dict) else {"data": data}

    def _require_http(self) -> aiohttp.ClientSession:
        if self._http is None:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15, connect=5))
        return self._http
