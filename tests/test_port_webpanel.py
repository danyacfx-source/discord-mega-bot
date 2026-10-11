"""Тесты webpanel: авторизация, API бота, загрузки, логи, CSP, rate-limit."""
from __future__ import annotations

import discord
import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.core.webpanel.payload import (
    _LOGIN_LIMIT,
    _components_from_raw,
    _embed_from_dict,
    _trim_components,
    _trim_embeds,
)
from app.core.webpanel.webpanel import WebPanel


def _fake_send_capture(target: list) -> discord.TextChannel:
    """Фейк-канал, проходящий isinstance(discord.TextChannel) и поймавший вызов send().

    TextChannel имеет __slots__ без __dict__, поэтому метод send нельзя подменить
    у экземпляра — берём ПОДКЛАСС с переопределённым классовым send().
    """

    class _CaptureChannel(discord.TextChannel):
        def __init__(self) -> None:
            self.id = 555
            self.name = "интеграционные-тесты"

        async def send(self, *args, **kwargs):  # type: ignore[method-assign,override]
            target.append((args, kwargs))
            return discord.Object(id=424242)  # реальный send() вернул бы Message с .id

    return _CaptureChannel()


@pytest.mark.asyncio
async def test_webpanel_api_bot_send_clicks_fake_channel(make_panel_bot):
    """КЛИК по кнопке отправки: POST /api/bot/send -> _api_bot_send -> channel.send()."""
    calls: list = []

    bot = make_panel_bot()
    channel = _fake_send_capture(calls)
    # H1-fix: резолв идёт через _primary_guild().get_channel, а не bot.get_channel.
    fake_guild = type("FakeGuild", (), {"get_channel": lambda self, cid: channel if int(cid or 0) == 555 else None})()

    panel = WebPanel(bot)
    panel._primary_guild = lambda: fake_guild  # type: ignore[method-assign]
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}
            resp = await client.post(
                "/api/bot/send",
                json={"channel_id": "555", "content": "привет из теста"},
                headers=headers,
            )
            assert resp.status == 200
            body = await resp.json()
            assert body.get("ok") is True
            assert body.get("message_id") == "424242"

    assert len(calls) == 1, "channel.send() должен быть вызван ровно один раз"
    _, kwargs = calls[0]
    assert kwargs.get("content") == "привет из теста"


@pytest.mark.asyncio
async def test_webpanel_api_bot_send_unknown_channel_400(make_panel_bot):
    """Чужой/несуществующий канал -> 400 «Канал не найден»."""
    bot = make_panel_bot()
    bot.get_channel = lambda cid: None

    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}
            resp = await client.post(
                "/api/bot/send",
                json={"channel_id": "999", "content": "х"},
                headers=headers,
            )
            assert resp.status == 400
            body = await resp.json()
            assert body.get("ok") is False
            assert "Канал" in body.get("error", "")


@pytest.mark.asyncio
async def test_embed_trims_to_limits():
    raw = _trim_embeds(
        [
            {
                "title": "t" * 400,
                "description": "d" * 5000,
                "color": 0x10102030,
                "fields": [{"name": f"n{i}", "value": "v", "inline": True} for i in range(30)],
            }
        ]
    )
    assert len(raw) == 1
    assert len(raw[0]["title"]) == 256
    assert len(raw[0]["description"]) == 4000
    assert raw[0]["color"] == 0x102030
    assert len(raw[0]["fields"]) == 25
    assert _trim_embeds([{}] * 20) == []
    assert len(_trim_embeds([{"title": "x"}] * 20)) == 10

    embed = _embed_from_dict({"title": "h", "color": 0xFFFFF0, "timestamp": "2026-01-01T12:00:00+00:00"})
    assert embed.title == "h"
    assert embed.color.value == 0xFFFFF0
    assert embed.timestamp is not None


@pytest.mark.asyncio
async def test_webpanel_auth_and_status(make_panel_bot):
    bot = make_panel_bot()
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            page = await client.get("/admin/embed-constructor")
            assert page.status == 200
            page_text = await page.text()
            assert "window.__PANEL__" in page_text
            assert 'id="app"' in page_text

            admin_page = await client.get("/admin")
            assert admin_page.status == 200
            assert "window.__PANEL__" in await admin_page.text()

            rejected = await client.get("/api/status")
            assert rejected.status == 401

            headers = {"X-Panel-Token": panel._static_token or ""}
            status_resp = await client.get("/api/status", headers=headers)
            assert status_resp.status == 200
            data = await status_resp.json()
            assert data["bot_online"] is False

            same_origin = await client.get(
                "/api/status",
                headers={**headers, "Origin": "https://panel.example.com", "Host": "panel.example.com"},
            )
            assert same_origin.status == 200

            foreign_origin = await client.get("/api/status", headers={**headers, "Origin": "https://evil.example.com"})
            assert foreign_origin.status == 401

            channels_resp = await client.get("/api/bot/channels", headers=headers)
            assert (await channels_resp.json())["channels"] == []

            overview_resp = await client.get("/api/overview", headers=headers)
            assert overview_resp.status == 200
            overview = await overview_resp.json()
            assert overview["ok"] is True and overview["bot_online"] is False
            assert overview["latency_ms"] == 0 and overview["uptime_seconds"] >= 0

            settings_resp = await client.get("/api/settings", headers=headers)
            assert settings_resp.status == 400
            assert (await settings_resp.json())["ok"] is False

            bad_url = await client.post("/api/webhook/send", headers=headers, json={"webhook_url": "https://example.com/1/2"})
            assert bad_url.status == 400
            assert (await bad_url.json())["ok"] is False


@pytest.mark.asyncio
async def test_webpanel_requires_password_when_public(make_panel_bot):
    bot = make_panel_bot(panel_host="0.0.0.0")
    panel = WebPanel(bot)
    with pytest.raises(RuntimeError, match="PANEL_PASSWORD"):
        await panel.start()
    assert panel._runner is None
    assert panel._http is None


@pytest.mark.asyncio
async def test_webpanel_components_trim():
    assert _trim_components(None) == []
    assert _trim_components({"label": "x"}) == []
    rows = _trim_components(
        [
            [
                {"label": "Вход", "style": 3},
                {"label": "Правила", "style": 5, "url": "https://example.com"},
                {"label": "Плохая ссылка", "style": 5, "url": "ftp://bad"},
                {"label": "", "style": 1},
                {"label": "Лишняя", "style": 1},
                {"label": "Шестая", "style": 1},
            ],
            [{"label": "Без URL", "style": 2, "url": "https://no"}],
        ]
    )
    assert len(rows) == 2
    assert rows[0]["type"] == 1 and len(rows[0]["components"]) == 3
    styles = {c["style"] for c in rows[0]["components"]}
    assert styles == {3, 5, 1}
    assert {c["style"] for c in rows[1]["components"]} == {2}
    assert {c["url"] for c in rows[1]["components"]} == {""}

    raw = [
        {"type": 1, "components": [{"type": 2, "label": "Кнопка", "style": 4, "url": ""}, {"type": 3, "label": "селект"}]},
        {"type": 1, "components": []},
    ]
    parsed = _components_from_raw(raw)
    assert parsed == [[{"label": "Кнопка", "style": "4", "url": ""}]]


@pytest.mark.asyncio
async def test_webpanel_logs_endpoint(make_panel_bot):
    bot = make_panel_bot()
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}
            resp = await client.get("/api/logs?n=50", headers=headers)
            assert resp.status == 200
            body = await resp.json()
            assert body["ok"] is True and body["logs"] == []


@pytest.mark.asyncio
async def test_webpanel_modules_status(make_panel_bot):
    bot = make_panel_bot()
    panel = WebPanel(bot)
    modules = panel._modules_status()
    assert "welcome" in modules and "role_menu" in modules and "temp_voices" in modules
    assert isinstance(modules["donations"]["bonuses"], list)
    assert modules["welcome"]["channel_enabled"] is False
    eff = panel._effective_log_channels({"member_log_channel_id": 123})
    assert eff["log"] is None and eff["member"] == 123
    assert list(panel._role_options()) == []


@pytest.mark.asyncio
async def test_webpanel_prometheus_metrics(make_panel_bot):
    bot = make_panel_bot()
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            response = await client.get("/metrics", headers={"X-Panel-Token": panel._static_token or ""})
            assert response.status == 200
            body = await response.text()
            assert "megabot_panel_sessions_active" in body
            assert "megabot_api_requests_total" in body


@pytest.mark.asyncio
async def test_webpanel_password_login(make_panel_bot):
    bot = make_panel_bot(panel_password="hunter2")
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            wrong = await client.post("/api/login", json={"password": "nope"})
            assert wrong.status == 401

            ok = await client.post("/api/login", json={"password": "hunter2"})
            body = await ok.json()
            assert body["ok"] is True and body["token"]

            headers = {"X-Panel-Token": body["token"]}
            status_resp = await client.get("/api/status", headers=headers)
            assert status_resp.status == 200


@pytest.mark.asyncio
async def test_webpanel_argon2_password_hash_login(make_panel_bot):
    from argon2 import PasswordHasher

    password_hash = PasswordHasher().hash("hunter2")
    bot = make_panel_bot(panel_admin_password_hash=password_hash)
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            wrong = await client.post("/api/login", json={"password": "nope"})
            assert wrong.status == 401
            ok = await client.post("/api/login", json={"password": "hunter2"})
            body = await ok.json()
            assert ok.status == 200 and body["ok"] is True and body["role"] == "admin"


@pytest.mark.asyncio
async def test_webpanel_oauth_redirect(make_panel_bot):
    bot = make_panel_bot(
        panel_oauth_client_id="client-id",
        panel_oauth_client_secret="client-secret",
        panel_oauth_redirect_url="https://panel.example/oauth/discord/callback",
    )
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            response = await client.get("/oauth/discord", allow_redirects=False)
            assert response.status == 302
            location = response.headers["Location"]
            assert location.startswith("https://discord.com/oauth2/authorize?")
            assert panel._oauth_states


@pytest.mark.asyncio
async def test_webpanel_upload(make_panel_bot):
    import aiohttp

    bot = make_panel_bot()
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}

            fd = aiohttp.FormData()
            png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
            fd.add_field("file", png, filename="kartinka.png", content_type="image/png")
            resp = await client.post("/api/upload", data=fd, headers=headers)
            assert resp.status == 200
            body = await resp.json()
            assert body["ok"] is True and body["name"].endswith(".png")
            assert body["absolute_url"].endswith("/uploads/" + body["name"])

            got = await client.get("/uploads/" + body["name"])
            assert got.status == 200
            assert "image/png" in got.headers.get("Content-Type", "")

            bad = aiohttp.FormData()
            bad.add_field("file", b"hello", filename="a.txt", content_type="text/plain")
            rejected = await client.post("/api/upload", data=bad, headers=headers)
            assert rejected.status == 400


@pytest.mark.asyncio
async def test_webpanel_security_headers(make_panel_bot):
    bot = make_panel_bot()
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            page = await client.get("/admin")
            assert page.status == 200
            assert page.headers.get("X-Content-Type-Options") == "nosniff"
            assert page.headers.get("X-Frame-Options") == "DENY"
            assert page.headers.get("Referrer-Policy") == "no-referrer"
            assert page.headers.get("Cache-Control") == "no-store"
            csp = page.headers.get("Content-Security-Policy", "")
            assert "default-src 'self'" in csp
            assert "script-src 'self'" in csp
            assert "frame-ancestors 'none'" in csp
            assert "style-src 'self' 'unsafe-inline'" in csp


@pytest.mark.asyncio
async def test_webpanel_upload_magic_mismatch(make_panel_bot):
    import aiohttp

    bot = make_panel_bot()
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}
            fd = aiohttp.FormData()
            fd.add_field("file", b"etot file ne png", filename="fake.png", content_type="image/png")
            resp = await client.post("/api/upload", data=fd, headers=headers)
            assert resp.status == 400

            ok = aiohttp.FormData()
            ok.add_field("file", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, filename="real.png", content_type="image/png")
            good = await client.post("/api/upload", data=ok, headers=headers)
            assert good.status == 200


@pytest.mark.asyncio
async def test_webpanel_logout_revokes_session(make_panel_bot):
    bot = make_panel_bot(panel_password="hunter2")
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            login = await client.post("/api/login", json={"password": "hunter2"})
            login_body = await login.json()
            token = login_body["token"]
            headers = {"X-Panel-Token": token}
            before = await client.get("/api/status", headers=headers)
            assert before.status == 200

            blocked = await client.post("/api/logout", headers=headers)
            assert blocked.status == 403

            headers["X-Panel-CSRF"] = login_body["csrf"]
            out = await client.post("/api/logout", headers=headers)
            assert out.status == 200

            after = await client.get("/api/status", headers=headers)
            assert after.status == 401


@pytest.mark.asyncio
async def test_webpanel_login_rate_limit(make_panel_bot):
    bot = make_panel_bot(panel_password="hunter2")
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            for _ in range(_LOGIN_LIMIT):
                resp = await client.post("/api/login", json={"password": "wrong"})
                assert resp.status == 401
            limited = await client.post("/api/login", json={"password": "hunter2"})
            assert limited.status == 429


@pytest.mark.asyncio
async def test_webpanel_login_lockout_isolated_by_forwarded_ip(make_panel_bot):
    """За доверенным прокси лок-аут считается по X-Forwarded-For:
    чужие неудачи не блокируют вход другого клиента."""
    bot = make_panel_bot(panel_password="hunter2")
    panel = WebPanel(bot)
    panel._trusted_proxy = True
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            for _ in range(_LOGIN_LIMIT):
                resp = await client.post(
                    "/api/login", json={"password": "nope"}, headers={"X-Forwarded-For": "203.0.113.7"}
                )
                assert resp.status == 401
            locked = await client.post(
                "/api/login", json={"password": "hunter2"}, headers={"X-Forwarded-For": "203.0.113.7"}
            )
            assert locked.status == 429
            other = await client.post(
                "/api/login", json={"password": "hunter2"}, headers={"X-Forwarded-For": "198.51.100.9"}
            )
            assert other.status == 200


@pytest.mark.asyncio
async def test_webpanel_login_success_resets_attempts(make_panel_bot):
    """Успешный вход сбрасывает счётчик неудач — старые опечатки не блокируют."""
    bot = make_panel_bot(panel_password="hunter2")
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            for _ in range(_LOGIN_LIMIT - 1):
                resp = await client.post("/api/login", json={"password": "wrong"})
                assert resp.status == 401
            first = await client.post("/api/login", json={"password": "hunter2"})
            assert first.status == 200
            miss = await client.post("/api/login", json={"password": "wrong"})
            assert miss.status == 401
            second = await client.post("/api/login", json={"password": "hunter2"})
            assert second.status == 200


@pytest.mark.asyncio
async def test_webpanel_csp_hashes_inline_scripts(make_panel_bot):
    """HTML-страницы получают CSP с sha256-хэшами инлайн-скриптов
    и без script-src 'unsafe-inline'; не-HTML — статичный CSP."""
    bot = make_panel_bot()
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            page = await client.get("/admin")
            csp = page.headers.get("Content-Security-Policy", "")
            assert "sha256-" in csp
            assert "script-src 'self' 'unsafe-inline'" not in csp
            assert "script-src 'self' 'sha256-" in csp
            assert "style-src 'self' 'unsafe-inline'" in csp

            logs = await client.get("/logs")
            logs_csp = logs.headers.get("Content-Security-Policy", "")
            assert "sha256-" in logs_csp

            api = await client.get("/api/public/showcase")
            api_csp = api.headers.get("Content-Security-Policy", "")
            assert "sha256-" not in api_csp
            assert "script-src 'self' 'unsafe-inline'" in api_csp


@pytest.mark.asyncio
async def test_webpanel_logs_page(make_panel_bot):
    """Страница /logs отдаёт HTML, содержит фильтры и JS-токен-подстановку."""
    bot = make_panel_bot()
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            page = await client.get("/logs")
            assert page.status == 200
            text = await page.text()
            assert "Технические логи" in text
            assert "__PANEL_TOKEN__" not in text or panel._static_token in text


@pytest.mark.asyncio
async def test_webpanel_audit_page(make_panel_bot):
    """Страница /audit отдаёт HTML с лентами Discord-событий."""
    bot = make_panel_bot()
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            page = await client.get("/audit")
            assert page.status == 200
            text = await page.text()
            assert "Логи Discord" in text
            assert "audit=1" in text


@pytest.mark.asyncio
async def test_webpanel_backup_db_postgres_uses_pg_dump(make_panel_bot):
    """На PostgreSQL бэкап-эндпоинт не падает на отсутствии файла sqlite,
    а отдаёт дамп из Database.backup() (pg_dump) с расширением .dump."""
    from pathlib import Path as _Path

    bot = make_panel_bot()
    panel = WebPanel(bot)

    class _FakeDb:
        path = "postgresql://user:pass@localhost:5432/bot"
        is_postgres = True

        async def backup(self, destination):
            target = _Path(destination)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"PGDUMP")
            return target

    bot.db = _FakeDb()
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}
            resp = await client.get("/api/backup/db", headers=headers)
            assert resp.status == 200
            assert await resp.read() == b"PGDUMP"
            disposition = resp.headers.get("Content-Disposition", "")
            assert disposition.endswith('.dump"')


def test_webhook_body_multiple_embeds(make_panel_bot):
    """_webhook_body сохраняет массив из нескольких эмбедов и обрезает лишние."""
    bot = make_panel_bot()
    panel = WebPanel(bot)
    body = panel._webhook_body(
        {
            "content": "много эмбедов",
            "embeds": [{"title": f"Эмбед {i}", "description": f"текст {i}"} for i in range(3)],
        }
    )
    assert body["content"] == "много эмбедов"
    assert len(body["embeds"]) == 3
    assert [e["title"] for e in body["embeds"]] == ["Эмбед 0", "Эмбед 1", "Эмбед 2"]


@pytest.mark.asyncio
async def test_logging_service_writes_to_web_ring(make_panel_bot):
    """Аудит-события LoggingService попадают в веб-ленту (а не в Discord-канал)."""
    import logging

    from app.core.webpanel.log_ring import RingBufferHandler
    from app.services.logging_service import LoggingService

    ring = RingBufferHandler(50)
    root = logging.getLogger()
    root.addHandler(ring)
    try:
        bot = make_panel_bot()
        # LoggingService требует SettingsService + bot; подменяем settings простым объектом.
        class _FakeSettings:
            async def get(self, guild_id):
                return {}

        svc = LoggingService(_FakeSettings(), bot)
        guild = discord.Object(id=111)
        guild.name = "Тест-сервер"
        embed = discord.Embed(title="Сообщение удалено", description="text")
        await svc.send_embed(guild, embed, category="message")

        entries = ring.snapshot()
        assert len(entries) >= 1
        entry = entries[-1]
        assert entry["cat"] == "message"
        assert entry["audit"] == "1"
        assert "Сообщение удалено" in entry["msg"]
    finally:
        root.removeHandler(ring)


@pytest.mark.asyncio
async def test_webpanel_api_logs_filters(make_panel_bot):
    """/api/logs поддерживает фильтры по категории и аудиту."""
    import logging

    from app.core.webpanel.log_ring import RingBufferHandler

    bot = make_panel_bot()
    panel = WebPanel(bot)
    ring = RingBufferHandler(50)
    panel._ring = ring
    root = logging.getLogger()
    root.addHandler(ring)
    try:
        logging.getLogger("bot.services.audit.member").info("участник зашёл [Тест] x")
        logging.getLogger("bot.webpanel").warning("технический warning")

        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                headers = {"X-Panel-Token": panel._static_token or ""}
                all_resp = await client.get("/api/logs", headers=headers)
                body = await all_resp.json()
                assert body.get("ok") is True
                assert body["count"] >= 2

                audit_resp = await client.get("/api/logs?audit=1", headers=headers)
                audit_body = await audit_resp.json()
                assert all(e["audit"] == "1" for e in audit_body["logs"])
                assert len(audit_body["logs"]) == 1
                assert audit_body["logs"][0]["cat"] == "member"

                sys_resp = await client.get("/api/logs?audit=0", headers=headers)
                sys_body = await sys_resp.json()
                assert sys_body["count"] >= 1
                assert all(e["audit"] == "0" for e in sys_body["logs"])
                assert any("технический warning" in e["msg"] for e in sys_body["logs"])

                cat_resp = await client.get("/api/logs?cat=sys", headers=headers)
                cat_body = await cat_resp.json()
                assert all(e["cat"] == "sys" for e in cat_body["logs"])
                assert any("технический warning" in e["msg"] for e in cat_body["logs"])
    finally:
        root.removeHandler(ring)


@pytest.mark.asyncio
async def test_logging_service_channel_only_when_configured(make_panel_bot):
    """send_embed не шлёт в Discord-канал без настройки; с настройкой — шлёт."""
    from unittest.mock import AsyncMock, MagicMock

    from app.services.logging_service import LoggingService

    bot = make_panel_bot()

    class _Guild:
        name = "Тест-сервер"
        id = 111

        def __init__(self, channel_id: int | None) -> None:
            self._channel_id = channel_id
            self.channel = MagicMock(spec=discord.TextChannel)
            self.channel.send = AsyncMock()

        def get_channel(self, channel_id):
            if self._channel_id is not None and channel_id == self._channel_id:
                return self.channel
            return None

    class _NoChannels:
        async def get(self, guild_id):
            return {}

    svc = LoggingService(_NoChannels(), bot)
    embed = discord.Embed(title="Событие", description="описание")
    unconfigured = _Guild(None)
    await svc.send_embed(unconfigured, embed, category="mod")
    unconfigured.channel.send.assert_not_awaited()

    class _WithChannel:
        async def get(self, guild_id):
            return {"mod_log_channel_id": 555}

    svc = LoggingService(_WithChannel(), bot)
    configured = _Guild(555)
    await svc.send_embed(configured, embed, category="mod")
    configured.channel.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_webpanel_uploads_list_and_delete(make_panel_bot):
    import aiohttp

    bot = make_panel_bot()
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            headers = {"X-Panel-Token": panel._static_token or ""}
            list_resp = await client.get("/api/uploads", headers=headers)
            assert (await list_resp.json())["files"] == []

            fd = aiohttp.FormData()
            fd.add_field("file", b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, filename="del.png", content_type="image/png")
            up = await client.post("/api/upload", data=fd, headers=headers)
            name = (await up.json())["name"]

            listed = await client.get("/api/uploads", headers=headers)
            names = [f["name"] for f in (await listed.json())["files"]]
            assert name in names

            deleted = await client.delete("/api/uploads/" + name, headers=headers)
            assert (await deleted.json())["ok"] is True

            listed2 = await client.get("/api/uploads", headers=headers)
            assert name not in [f["name"] for f in (await listed2.json())["files"]]
            missing = await client.delete("/api/uploads/" + name, headers=headers)
            assert missing.status == 404
