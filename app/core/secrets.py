"""Защита секретов: маскирование в логах, Docker secrets (*_FILE), права на .env.

Три независимых входа, одна цель — токен не должен дотянуться до файла лога,
до веб-ленты и до чужих глаз на диске:

- :func:`redact` режет секреты из любой строки (лог, traceback, embed);
- :class:`RedactingFormatter` применяет его к финальному выводу хендлера;
- :class:`SecretRedactionFilter` переформатирует запись до ``emit`` — нужен
  хендлам, которые читают ``record.getMessage()`` напрямую (кольцевой буфер);
- :func:`load_file_secrets` материализует ``SOMETHING_FILE=/run/secrets/x`` в
  стандартные переменные окружения (Docker/K8s secrets);
- :func:`fix_env_permissions` закрывает ``.env`` от группы и мира.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

_MASK = "***"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

#: Строка вида ``mfa.``/``MTA...`` — токен бота Discord.
_DISCORD_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{23,28}\.[A-Za-z0-9_-]{6,7}\.[A-Za-z0-9_-]{25,110}(?![A-Za-z0-9_-])")
#: Вебхук Discord: путь остаётся, секретная часть — вебхук-токен в хвосте.
_WEBHOOK_RE = re.compile(r"((?:https?://)?(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\d+/)[A-Za-z0-9_-]+", re.I)
#: JWT (DonationAlerts и прочие провайдеры).
_JWT_RE = re.compile(r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])")
#: ``Authorization: Bearer ...`` / ``Basic ...``.
_AUTH_RE = re.compile(r"(\b(?:authorization|proxy-authorization)\s*[:=]\s*(?:bearer|basic|token|jwt)\s+)[^\s'\"]+", re.I)
#: ``BOT_TOKEN=...``, ``client_secret: "..."``, ``x-panel-token ...`` и подобное.
#: Кавычки значения сохраняются — в логе остаётся читаемая структура, но не ключ.
_KEYVAL_RE = re.compile(
    r"(?P<key>\b[a-z0-9_]*(?:token|secret|password|passwd|api[_-]?key|private[_-]?key|app[_-]?key|salt|signature)"
    r"[a-z0-9_]*\s*[=:]\s*)(?P<quote>['\"]?)(?P<value>[^\s,;)\]}'\"]+)",
    re.I,
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_WEBHOOK_RE, rf"\1{_MASK}"),
    (_DISCORD_TOKEN_RE, _MASK),
    (_JWT_RE, _MASK),
    (_AUTH_RE, rf"\1{_MASK}"),
    (_KEYVAL_RE, r"\g<key>\g<quote>" + _MASK),
)


def redact(text: object) -> str:
    """Возвращает строку с вырезанными секретами. Нечто секретное — всегда ``***``."""
    if not isinstance(text, str):
        text = str(text)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def looks_like_secret(value: object) -> bool:
    """True, если строка целиком похожа на токен (для проверки конфигурации)."""
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if len(candidate) < 16:
        return False
    return redact(candidate) != candidate


class SecretRedactionFilter(logging.Filter):
    """Переписывает запись до emit: закрывает хендлы, читающие ``getMessage()``."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — лог не должен падать из-за битых args
            return True
        clean = redact(message)
        if clean != message:
            record.msg = clean
            record.args = None
        return True


class RedactingFormatter(logging.Formatter):
    """Режет секреты в готовом выводе — включая traceback из ``exc_info``."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def attach_redaction(handler: logging.Handler) -> logging.Handler:
    """Ставит на хендл и фильтр, и редактор: надёжно при любом способе формата.

    Без собственного формата (кольцевой буфер) редактируется запись до emit —
    он читает ``getMessage()`` напрямую.
    """
    if not any(isinstance(item, SecretRedactionFilter) for item in handler.filters):
        handler.addFilter(SecretRedactionFilter())
    if handler.formatter is not None and not isinstance(handler.formatter, RedactingFormatter):
        handler.setFormatter(RedactingFormatter(handler.formatter._fmt))
    return handler


# --- Docker / Kubernetes secrets ---

_SECRET_SUFFIX = "_FILE"


def load_file_secrets() -> list[str]:
    """Превращает ``NAME_FILE=/run/secrets/name`` в ``name=<содержимое файла>``.

    Уже заданные ``NAME`` имеет приоритет: локальная разработка не должна
    терять настройки из-за случайного суффикса. Возвращает предупреждения.
    """
    warnings: list[str] = []
    for key in sorted(os.environ):
        if not key.endswith(_SECRET_SUFFIX):
            continue
        base = key[: -len(_SECRET_SUFFIX)]
        if not base or os.environ.get(base):
            continue
        raw = os.environ[key].strip()
        if not raw:
            continue
        try:
            value = Path(raw).read_text(encoding="utf-8").strip()
        except OSError as exc:
            warnings.append(f"{key}: не удалось прочитать {raw!r} — {exc}")
            continue
        if not value:
            warnings.append(f"{key}: файл {raw!r} пуст — переменная {base} не задана")
            continue
        os.environ[base] = value
    return warnings


# --- права на .env ---

def fix_env_permissions(path: str | os.PathLike[str] | None = None) -> list[str]:
    """Закрывает ``.env`` от группы и мира (POSIX). Возвращает, что было сделано."""
    if os.name != "posix":
        return []
    target = Path(path) if path else _PROJECT_ROOT / ".env"
    if not target.is_file():
        return []
    try:
        mode = target.stat().st_mode & 0o777
    except OSError:
        return []
    if not mode & 0o077:
        return []
    try:
        target.chmod(0o600)
    except OSError as exc:
        return [f"{target}: права {oct(mode)}, исправить не удалось ({exc})"]
    return [f"{target}: права {oct(mode)} → 0o600 (доступ только у владельца)"]


def env_warnings(env_path: str | os.PathLike[str] | None = None) -> list[str]:
    """Проверка без изменения файла: список замечаний по правам на ``.env``."""
    if os.name != "posix":
        return []
    target = Path(env_path) if env_path else _PROJECT_ROOT / ".env"
    if not target.is_file():
        return []
    try:
        mode = target.stat().st_mode & 0o777
    except OSError:
        return []
    if mode & 0o077:
        return [f"{target}: права {oct(mode)} позволяют читать группе и всем — нужно 0o600"]
    return []


def config_secret_warnings(**values: object) -> list[str]:
    """Гудит, если секрет в конфигурации выглядит утечкой (короткий, пустой, явный)."""
    warnings: list[str] = []
    for name, value in values.items():
        if value is None or value == "":
            continue
        if looks_like_secret(value):
            warnings.append(f"{name}: значение похоже на настоящий секрет — проверьте, не попадает ли оно в логи")
    return warnings
