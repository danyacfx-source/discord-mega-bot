"""Защита в глубину: шифрование at-rest, TOTP, персистентный лок входа."""
from __future__ import annotations

import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from app.core import totp as totp_module
from app.core.crypto import (
    decrypt_file,
    decrypt_text,
    encrypt_file,
    encrypt_text,
    is_encrypted,
    is_encrypted_file,
    key_fingerprint,
)
from app.core.webpanel.payload import _LOGIN_LIMIT
from app.core.webpanel.webpanel import WebPanel
from app.db.database import Database


def _code_outside_window(secret: str, now: float) -> str:
    """Код, гарантированно не входящий в окно ±1 шага — без вероятностных флаков."""
    valid = {totp_module.generate(secret, now + step * 30) for step in (-1, 0, 1)}
    return next(f"{index:06d}" for index in range(10**6) if f"{index:06d}" not in valid)


# --------------------------------------------------------------- шифрование

def test_crypto_text_roundtrip_and_legacy_passthrough(at_rest_key):
    assert key_fingerprint() != "none"
    token = "super-secret-panel-token"
    sealed = encrypt_text(token)
    assert is_encrypted(sealed)
    assert token not in sealed
    assert decrypt_text(sealed) == token
    # Старые plaintext-записи читаются как есть — миграция не ломает базу.
    assert decrypt_text("legacy-plain-value") == "legacy-plain-value"
    # Повторное шифрование уже зашифрованного значения не «матрёшит».
    assert encrypt_text(sealed) == sealed


def test_crypto_file_roundtrip_and_tamper_detection(at_rest_key):
    payload = b"SQLite format 3\x00" + b"x" * 4096
    sealed = encrypt_file(payload)
    assert is_encrypted_file(sealed)
    # Overhead ровно 35 байт: иначе backup раздулся бы за лимит Discord.
    assert len(sealed) - len(payload) == 35
    assert decrypt_file(sealed) == payload
    # Нешифрованный файл проходит без изменений (legacy).
    assert decrypt_file(payload) == payload
    # Подмена байта ломает тег GCM — расшифровка отказывает, а не отдаёт мусор.
    broken = sealed[:-1] + bytes([sealed[-1] ^ 1])
    assert decrypt_file(broken) is None
    assert decrypt_file(sealed[: len(sealed) - 4]) is None


async def test_encrypted_backup_restores(tmp_path, at_rest_key):
    """Backup, зашифрованный для Discord, возвращается в рабочую базу целиком."""
    from app.db.restore import restore_backup

    source = tmp_path / "source.db"
    database = Database(str(source))
    await database.connect()
    await database.execute("INSERT INTO kv(key, value) VALUES ('marker', 'secret')")
    backup = tmp_path / "backup.db"
    await database.backup(backup)
    await database.close()

    encrypted = tmp_path / "backup.db.enc"
    encrypted.write_bytes(encrypt_file(backup.read_bytes()))
    backup.unlink()

    target = tmp_path / "target.db"
    restore_backup(encrypted, target)
    restored = Database(str(target))
    await restored.connect()
    row = await restored.fetchone("SELECT value FROM kv WHERE key = ?", ("marker",))
    assert row is not None and row["value"] == "secret"
    await restored.close()

    # Подделанный шифрованный backup не должен затирать цель.
    tampered = tmp_path / "tampered.db.enc"
    raw = encrypted.read_bytes()
    tampered.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(RuntimeError, match="расшифровать"):
        restore_backup(tampered, target)


@pytest.mark.asyncio
async def test_backup_upload_to_discord_is_encrypted(make_panel_bot, tmp_path, at_rest_key):
    """Дамп БД, уходящий в канал Discord, не должен быть открытым текстом."""
    bot = make_panel_bot(db_backup_discord_channel_id=123)
    db_file = tmp_path / "bot.db"
    db_file.write_bytes(b"SQLite format 3\x00" + b"\x01" * 2048)

    captured: dict[str, object] = {}

    class _Channel:
        async def send(self, content=None, file=None, **kwargs):
            captured["content"] = content
            captured["filename"] = file.filename
            captured["data"] = file.fp.read()

    bot.get_channel = lambda channel_id: _Channel()  # type: ignore[method-assign]
    await bot._upload_backup_to_discord(db_file)

    data = captured["data"]
    assert captured["filename"] == "bot.db.enc"
    assert isinstance(data, bytes) and is_encrypted_file(data)
    assert b"SQLite format 3" not in data
    assert decrypt_file(data) == db_file.read_bytes()
    assert "зашифрован" in str(captured["content"])


# ----------------------------------------------------------------------- TOTP

def test_totp_verify_covers_window_and_rejects_garbage():
    secret = totp_module.new_secret()
    now = 1_700_000_000.0
    for step in (-1, 0, 1):
        assert totp_module.verify(secret, totp_module.generate(secret, now + step * 30), timestamp=now)
    assert not totp_module.verify(secret, _code_outside_window(secret, now), timestamp=now)
    # Мусор не должен ронять проверку исключением.
    assert not totp_module.verify(secret, "12345", timestamp=now)
    assert not totp_module.verify(secret, "abcdef", timestamp=now)
    assert not totp_module.verify("", "123456", timestamp=now)
    assert not totp_module.verify("!!!не-base32!!!", "123456", timestamp=now)


def test_totp_provisioning_uri_is_standard():
    uri = totp_module.provisioning_uri("JBSWY3DPEHPK3PXP", "owner", "MegaBot")
    assert uri.startswith("otpauth://totp/MegaBot%3Aowner?")
    assert "secret=JBSWY3DPEHPK3PXP" in uri  # secrets-allow: RFC TOTP test fixture
    assert "algorithm=SHA1" in uri and "digits=6" in uri and "period=30" in uri


@pytest.mark.asyncio
async def test_login_requires_totp_appended_to_password(make_panel_bot):
    """2FA работает через существующую форму: «пароль:123456», фронт не меняем."""
    secret = totp_module.new_secret()
    bot = make_panel_bot(panel_password="hunter2", panel_totp_secret=secret)
    panel = WebPanel(bot)
    now = time.time()
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            # Пароль без кода — отказ.
            plain = await client.post("/api/login", json={"password": "hunter2"})
            assert plain.status == 401

            # Неверный код — отказ и тот же счётчик неудач.
            wrong = await client.post(
                "/api/login", json={"password": f"hunter2:{_code_outside_window(secret, now)}"}
            )
            assert wrong.status == 401

            # Верный код, дописанный к паролю — вход.
            good = await client.post(
                "/api/login", json={"password": f"hunter2:{totp_module.generate(secret)}"}
            )
            assert good.status == 200
            # PANEL_PASSWORD — это роль owner; PANEL_ADMIN_PASSWORD была бы admin.
            assert (await good.json())["role"] == "owner"

            # API-клиенты могут передать код отдельным полем.
            api = await client.post(
                "/api/login", json={"password": "hunter2", "totp": totp_module.generate(secret)}
            )
            assert api.status == 200


@pytest.mark.asyncio
async def test_login_without_totp_configured_ignores_colon_suffix(make_panel_bot):
    """Без PANEL_TOTP_SECRET двоеточие в пароле остаётся частью пароля."""
    bot = make_panel_bot(panel_password="hunter2:123456")
    panel = WebPanel(bot)
    async with TestServer(panel._create_app()) as server:
        async with TestClient(server) as client:
            ok = await client.post("/api/login", json={"password": "hunter2:123456"})
            assert ok.status == 200
            stripped = await client.post("/api/login", json={"password": "hunter2"})
            assert stripped.status == 401


# -------------------------------------------------- персистентный лок входа

@pytest.mark.asyncio
async def test_login_lockout_survives_panel_restart(make_panel_bot):
    """Счётчик неудач живёт в БД: «рестарт» (новый WebPanel) блокировку не сбрасывает."""
    bot = make_panel_bot(panel_password="hunter2")
    bot.db = Database(bot.config.db_path)
    await bot.db.connect()
    try:
        first = WebPanel(bot)
        async with TestServer(first._create_app()) as server:
            async with TestClient(server) as client:
                for _ in range(_LOGIN_LIMIT):
                    resp = await client.post("/api/login", json={"password": "wrong"})
                    assert resp.status == 401

        # Новый экземпляр панели = пустая in-memory таблица, но БД та же.
        second = WebPanel(bot)
        assert not second._login_attempts, "in-memory счётчик должен быть пуст после рестарта"
        async with TestServer(second._create_app()) as server:
            async with TestClient(server) as client:
                locked = await client.post("/api/login", json={"password": "hunter2"})
                assert locked.status == 429
                assert "попыток" in (await locked.json())["error"]
    finally:
        await bot.db.close()


@pytest.mark.asyncio
async def test_login_success_clears_persistent_counter(make_panel_bot):
    """Успешный вход убирает запись из durable-счётчика, а не копит её."""
    bot = make_panel_bot(panel_password="hunter2")
    bot.db = Database(bot.config.db_path)
    await bot.db.connect()
    try:
        panel = WebPanel(bot)
        async with TestServer(panel._create_app()) as server:
            async with TestClient(server) as client:
                for _ in range(_LOGIN_LIMIT - 1):
                    resp = await client.post("/api/login", json={"password": "wrong"})
                    assert resp.status == 401
                ok = await client.post("/api/login", json={"password": "hunter2"})
                assert ok.status == 200
                # Лимит не добит, блокировки нет — следующий проход не упирается в 429.
                again = await client.post("/api/login", json={"password": "hunter2"})
                assert again.status == 200
        rows = await bot.db.fetchall("SELECT * FROM panel_login_attempts")
        assert rows == []
    finally:
        await bot.db.close()
