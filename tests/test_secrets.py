"""Секреты: маскирование в логах, Docker secrets (*_FILE), права на .env, сканер."""
from __future__ import annotations

import importlib.util
import logging
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest

from app.core.secrets import (
    RedactingFormatter,
    SecretRedactionFilter,
    attach_redaction,
    env_warnings,
    fix_env_permissions,
    load_file_secrets,
    looks_like_secret,
    redact,
)

ROOT = Path(__file__).resolve().parent.parent
#: Форма настоящего токена Discord: три части, длины выдержаны.
FAKE_DISCORD_TOKEN = "A" * 24 + "." + "B" * 6 + "." + "C" * 30
FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0." + "dGVzdF9zaWduYXR1cmVfdGVzdF9zaWdu"


def _load_scanner() -> Any:
    """Грузит scripts/check_secrets.py как модуль (scripts — не пакет)."""
    spec = importlib.util.spec_from_file_location("check_secrets", ROOT / "scripts" / "check_secrets.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("check_secrets", module)
    spec.loader.exec_module(module)
    return module


# --- redact ---


def test_redacts_discord_token() -> None:
    line = f"login failed for {FAKE_DISCORD_TOKEN} at gateway"
    assert FAKE_DISCORD_TOKEN not in redact(line)
    assert "***" in redact(line)


def test_redacts_webhook_url_keeping_path() -> None:
    line = "POST https://discord.com/api/webhooks/123456789012345678/AbCdEfGhIjKlMnOpQrStUvWxYz"  # secrets-allow
    cleaned = redact(line)
    assert "/api/webhooks/123456789012345678/" in cleaned
    assert "AbCdEfGhIjKlMnOpQrStUvWxYz" not in cleaned


def test_redacts_jwt() -> None:
    assert FAKE_JWT not in redact(f"bearer {FAKE_JWT}")


def test_redacts_key_value_assignments() -> None:
    assert "super-secret-value-9" not in redact("config BOT_TOKEN=super-secret-value-9 loaded")
    assert "hunter2hunter2hunter2" not in redact('client_secret: "hunter2hunter2hunter2"')


def test_redacts_authorization_header() -> None:
    cleaned = redact("Authorization: Bearer abcdefghijklmnop")
    assert "abcdefghijklmnop" not in cleaned
    assert cleaned.startswith("Authorization: Bearer")


def test_keeps_ordinary_config_lines() -> None:
    """False positive в логах = полезная информация пропала. Здесь её не должно."""
    for line in (
        "GUARD_BYPASS_ROLES=1,2,3",
        "загружено когов: 42, с ошибками: 0",
        "AUTOMOD_CAPS_THRESHOLD=0.8",
        "secrets.token_urlsafe(32)",
    ):
        assert redact(line) == line, line


def test_redact_tolerates_non_string() -> None:
    assert redact(123) == "123"


def test_looks_like_secret() -> None:
    assert looks_like_secret(FAKE_DISCORD_TOKEN)
    assert not looks_like_secret("short")
    assert not looks_like_secret(None)


# --- логирование ---


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


def test_formatter_masks_secret_in_message() -> None:
    handler = _Capture()
    handler.setFormatter(RedactingFormatter("%(message)s"))
    logger = logging.getLogger("test.secrets.formatter")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("токен бота: %s", FAKE_DISCORD_TOKEN)
    finally:
        logger.removeHandler(handler)

    assert handler.lines
    assert FAKE_DISCORD_TOKEN not in handler.lines[0]
    assert "***" in handler.lines[0]


def test_formatter_masks_secret_inside_traceback() -> None:
    handler = _Capture()
    handler.setFormatter(RedactingFormatter("%(message)s"))
    logger = logging.getLogger("test.secrets.traceback")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        try:
            raise RuntimeError(f"gateway rejected {FAKE_DISCORD_TOKEN}")
        except RuntimeError as exc:
            logger.error("сбой", exc_info=(type(exc), exc, exc.__traceback__))
    finally:
        logger.removeHandler(handler)

    assert handler.lines
    assert FAKE_DISCORD_TOKEN not in handler.lines[0]


def test_filter_rewrites_record_before_emit() -> None:
    """Кольцевой буфер читает getMessage() напрямую — ему нужен фильтр, не форматер."""
    handler = _Capture()
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(SecretRedactionFilter())
    logger = logging.getLogger("test.secrets.filter")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("ключ: %s", FAKE_DISCORD_TOKEN)
    finally:
        logger.removeHandler(handler)

    assert handler.lines
    assert FAKE_DISCORD_TOKEN not in handler.lines[0]


def test_attach_redaction_is_idempotent() -> None:
    handler = _Capture()
    handler.setFormatter(logging.Formatter("%(message)s"))
    attach_redaction(handler)
    attach_redaction(handler)

    assert sum(isinstance(item, SecretRedactionFilter) for item in handler.filters) == 1
    assert isinstance(handler.formatter, RedactingFormatter)
    # исходный формат не теряется
    assert handler.formatter._fmt == "%(message)s"


def test_attach_redaction_keeps_format_of_plain_handler() -> None:
    handler = _Capture()
    attach_redaction(handler)
    assert handler.formatter is None  # без своего формата фильтр всё равно работает
    logger = logging.getLogger("test.secrets.plain")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("token=%s", FAKE_DISCORD_TOKEN)
    finally:
        logger.removeHandler(handler)
    assert handler.lines and FAKE_DISCORD_TOKEN not in handler.lines[0]


# --- Docker secrets (*_FILE) ---


def test_load_file_secrets_reads_file(monkeypatch: pytest.MonkeyPatch) -> None:
    with TemporaryDirectory() as tmp:
        secret_path = Path(tmp) / "bot_token"
        secret_path.write_text(FAKE_DISCORD_TOKEN + "\n", encoding="utf-8")
        monkeypatch.setenv("TEST_ONLY_TOKEN_FILE", str(secret_path))
        monkeypatch.delenv("TEST_ONLY_TOKEN", raising=False)

        warnings = load_file_secrets()

        assert warnings == []
        assert os.environ["TEST_ONLY_TOKEN"] == FAKE_DISCORD_TOKEN  # \n срезан


def test_existing_env_wins_over_file(monkeypatch: pytest.MonkeyPatch) -> None:
    with TemporaryDirectory() as tmp:
        secret_path = Path(tmp) / "x"
        secret_path.write_text("from-file", encoding="utf-8")
        monkeypatch.setenv("TEST_ONLY_TOKEN_FILE", str(secret_path))
        monkeypatch.setenv("TEST_ONLY_TOKEN", "from-env")

        load_file_secrets()

        assert os.environ["TEST_ONLY_TOKEN"] == "from-env"


def test_load_file_secrets_reports_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ONLY_TOKEN_FILE", "/definitely/not/here")
    monkeypatch.delenv("TEST_ONLY_TOKEN", raising=False)

    warnings = load_file_secrets()

    assert warnings and "TEST_ONLY_TOKEN_FILE" in warnings[0]


def test_load_file_secrets_reports_empty_file(monkeypatch: pytest.MonkeyPatch) -> None:
    with TemporaryDirectory() as tmp:
        empty = Path(tmp) / "empty"
        empty.write_text("   \n", encoding="utf-8")
        monkeypatch.setenv("TEST_ONLY_TOKEN_FILE", str(empty))
        monkeypatch.delenv("TEST_ONLY_TOKEN", raising=False)

        warnings = load_file_secrets()

        assert warnings and "пуст" in warnings[0]


# --- права на .env ---


def test_env_permissions_check_is_noop_on_windows() -> None:
    if os.name == "posix":
        pytest.skip("проверка прав значима только на POSIX")
    assert env_warnings() == []
    assert fix_env_permissions() == []


def test_env_permissions_warns_when_readable(tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("chmod на Windows не даёт POSIX-прав")
    env_file = tmp_path / ".env"
    env_file.write_text("BOT_TOKEN=x", encoding="utf-8")
    env_file.chmod(0o644)

    warnings = env_warnings(env_file)

    assert warnings and "0o600" in warnings[0]

    fixed = fix_env_permissions(env_file)

    assert fixed and "0o600" in str(fixed[0])
    assert env_warnings(env_file) == []


# --- сканер ---


def test_scanner_catches_real_shaped_token() -> None:
    scanner = _load_scanner()
    hits = scanner._hits(f'config = "{FAKE_DISCORD_TOKEN}"')
    assert hits


def test_scanner_catches_literal_assignment() -> None:
    scanner = _load_scanner()
    hits = scanner._hits("DONATIONS_TOKEN=9f2b7c1d4e6a8b0c3d5e7f9a1b3c5d7e")  # secrets-allow
    assert hits


def test_scanner_ignores_source_expressions() -> None:
    scanner = _load_scanner()
    for line in (
        'token=os.environ["BOT_TOKEN"],',
        "panel_password: str | None = None",
        "value = os.getenv('AI_API_KEY') or None",
        "self._token = token",
        "def handler(token: str) -> None:",
    ):
        assert scanner._hits(line) == [], line


def test_scanner_ignores_placeholders() -> None:
    scanner = _load_scanner()
    for line in (
        '"OVERLAY_TOKEN=overlay-secret-token-32chars"',
        "PANEL_PASSWORD=changeme-please-12345",
        "BOT_TOKEN=",
        "AI_MAX_TOKENS=220",
        "POSTGRES_PASSWORD=<your-password-here>",
    ):
        assert scanner._hits(line) == [], line


def test_scanner_ignores_public_pusher_key() -> None:
    scanner = _load_scanner()
    hits = [v for v in scanner._hits('kick_pusher_app_key: str = "32cbd69e4b950bf97679"') if v not in scanner._ALLOWED_VALUES]
    assert hits == []


def test_scanner_finds_nothing_in_tracked_tree() -> None:
    scanner = _load_scanner()
    findings: list[dict[str, object]] = []
    for path in scanner._tracked_files():
        if path.suffix in scanner._SKIP_SUFFIXES or path.name in scanner._SKIP_NAMES:
            continue
        findings.extend(scanner.scan_file(path))
    assert findings == [], findings


def test_scanner_skips_lines_with_allow_marker(tmp_path: Path) -> None:
    scanner = _load_scanner()
    webhook = "https://discord.com/api/webhooks/" + "123456789012345678/" + "AbCdEfGhIjKlMnOpQrStUvWxYz"
    line = f'WEBHOOK = "{webhook}"'
    assert scanner._hits(line)  # без метки строка была бы находкой
    path = tmp_path / "fixture.py"
    path.write_text(line + "  # secrets-allow\n", encoding="utf-8")
    assert scanner.scan_file(path) == []
