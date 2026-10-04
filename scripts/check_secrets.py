#!/usr/bin/env python3
"""Ищет секреты, попавшие в отслеживаемые файлы репозитория.

Секрет опознаётся по форме, а не по имени переменной: трёхчастный токен
Discord, JWT, вебхук и литеральные присваивания вида ``BOT_TOKEN=...``.
Выражения (``os.getenv(...)``), аннотации (``token: str``) и заглушки
(``overlay-secret-token-32chars``) отфильтровываются — на выходе только то,
что действительно похоже на утёкший ключ. Строки с меткой ``# secrets-allow``
пропускаются: так тесты держат фикстуры реальной формы.

Запуск из корня проекта::

    python scripts/check_secrets.py            # сканирует, код возврата 1 при находках
    python scripts/check_secrets.py --fix-env  # плюс чинит права на .env
    python scripts/check_secrets.py --json     # отчёт в JSON (для CI)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess  # noqa: S403 — обходится доверенный git из PATH
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.secrets import env_warnings, fix_env_permissions  # noqa: E402

#: Файлы/каталоги, где секретов по определению быть не может или они бинарные.
_SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "logs",
    "data",
    "backups",
    "dist",
}
_SKIP_SUFFIXES = {".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".db", ".sqlite", ".woff", ".woff2", ".ttf"}
_SKIP_NAMES = {".env", "bot_out.log", "bot_err.log", "panel_out.log", "panel_err.log"}

#: Значения по умолчанию, которые выглядят как секреты, но публичны by design
#: (Pusher app key кладётся в клиентский JS и без secret ничего не даёт).
_ALLOWED_VALUES = {"32cbd69e4b950bf97679"}
_MAX_BYTES = 2 * 1024 * 1024
_MIN_SECRET_LEN = 16

#: Строка с этой меткой пропускается: фикстуры тестов намеренно похожи на секреты.
_ALLOW_MARKER = "# secrets-allow"

# Точные паттерны: секрет узнаётся по форме, а не по имени переменной.
_DISCORD_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{23,28}\.[A-Za-z0-9_-]{6,7}\.[A-Za-z0-9_-]{25,110}(?![A-Za-z0-9_-])")
_JWT_RE = re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])")
_WEBHOOK_RE = re.compile(r"discord(?:app)?\.com/api/webhooks/\d+/[A-Za-z0-9_-]{16,}", re.I)
#: ``BOT_TOKEN=<литерал>`` — литерал, а не ``os.getenv(...)`` и не ``str``.
_ASSIGN_RE = re.compile(
    r"(?i)\b[a-z0-9_]*(?:token|secret|password|passwd|api[_-]?key|private[_-]?key|app[_-]?key)[a-z0-9_]*\s*[=:]\s*([^\s,;)\]}'\"`]+)"
)

#: Слова, по которым значение опознаётся заглушкой, а не секретом: режутся по
#: отдельным «словам» значения, чтобы поймать и ``xxx``, и тест-фикстуры вида
#: ``overlay-secret-token-32chars``.
_PLACEHOLDER_WORDS = frozenset(
    {
        "your",
        "change",
        "changeme",
        "example",
        "placeholder",
        "sample",
        "dummy",
        "fake",
        "test",
        "demo",
        "redacted",
        "secret",
        "local",
        "xxx",
    }
)


def _is_placeholder(value: str) -> bool:
    """Заглушка или тест-фикстура: ``xxx``, ``<...>``, ``overlay-secret-token-32chars``."""
    if re.fullmatch(r"[xX*.\-]+", value):
        return True
    if value.startswith("<") and value.endswith(">"):
        return True
    words = re.split(r"[^a-z]+", value.lower())
    return any(word in _PLACEHOLDER_WORDS for word in words)


def _plausible_secret(value: str) -> bool:
    """Отсекает выражения, аннотации и заглушки: остаются только литералы."""
    stripped = value.strip().strip("\"'")
    if len(stripped) < _MIN_SECRET_LEN:
        return False
    if any(char in value for char in "([{") or "=" in value:
        return False  # вызов вида os.getenv(...) / f-string
    if _is_placeholder(stripped):
        return False
    if not re.search(r"\d", stripped) or not re.search(r"[A-Za-z]", stripped):
        return False  # секрет почти всегда буквы + цифры
    if len(set(stripped)) < 8:
        return False  # "aaaaaaaaaaaaaaaa"
    return True


def _hits(line: str) -> list[str]:
    """Какие именно куски строки выдают секрет."""
    found: list[str] = []
    for pattern in (_DISCORD_TOKEN_RE, _JWT_RE, _WEBHOOK_RE):
        found.extend(match.group(0) for match in pattern.finditer(line))
    for match in _ASSIGN_RE.finditer(line):
        if _plausible_secret(match.group(1)):
            found.append(match.group(1))
    return found


def _marked(line: str) -> bool:
    """Фикстура с разрешением: строка по форме секрет, но это не утечка."""
    return _ALLOW_MARKER in line


def _tracked_files() -> list[Path]:
    """Список файлов из git; без git — обычный обход с теми же исключениями."""
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            capture_output=True,
            check=True,
        )
        names = [name for name in out.stdout.decode("utf-8", errors="ignore").split("\0") if name]
        return [ROOT / name for name in names if (ROOT / name).is_file()]
    except (OSError, subprocess.CalledProcessError):
        return _walk()


def _walk() -> list[Path]:
    found: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in _SKIP_DIRS for part in relative.parts):
            continue
        if path.name in _SKIP_NAMES or path.suffix in _SKIP_SUFFIXES:
            continue
        found.append(path)
    return found


def scan_file(path: Path) -> list[dict[str, object]]:
    try:
        if path.stat().st_size > _MAX_BYTES:
            return []
        raw = path.read_bytes()
    except OSError:
        return []
    if b"\0" in raw[:8192]:
        return []  # бинарник
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return []

    findings: list[dict[str, object]] = []
    for number, line in enumerate(text.splitlines(), 1):
        secrets = [value for value in _hits(line) if value not in _ALLOWED_VALUES]
        if not secrets or _marked(line):
            continue
        snippet = line.strip()
        for value in secrets:
            snippet = snippet.replace(value, "***")
        findings.append(
            {
                "file": str(path.relative_to(ROOT)),
                "line": number,
                "text": snippet[:200],
            }
        )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Поиск секретов в отслеживаемых файлах")
    parser.add_argument("--fix-env", action="store_true", help="плюс выставить .env права 0600")
    parser.add_argument("--json", action="store_true", help="отчёт в JSON")
    args = parser.parse_args()

    warnings = list(env_warnings())
    if args.fix_env:
        warnings.extend(fix_env_permissions())

    findings: list[dict[str, object]] = []
    for path in _tracked_files():
        if path.suffix in _SKIP_SUFFIXES or path.name in _SKIP_NAMES:
            continue
        findings.extend(scan_file(path))

    if args.json:
        print(json.dumps({"findings": findings, "warnings": warnings}, ensure_ascii=False, indent=2))
        return 1 if findings else 0

    for warning in warnings:
        print(f"WARNING  {warning}")
    if findings:
        print(f"Найдено утечек: {len(findings)}")
        for item in findings:
            print(f"  {item['file']}:{item['line']}: {item['text']}")
        return 1
    print(f"Секретов не найдено (проверено файлов: {len(_tracked_files())})" if not warnings else "Секретов не найдено")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
