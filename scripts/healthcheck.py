#!/usr/bin/env python3
"""Docker healthcheck: проверяет, что веб-сервер бота жив и бот здоров.

Приоритет:
1. Панель: GET /api/health с токеном из data/.panel-token —
   200 = discord ready + БД прошла integrity, 503 = нездоров, 401 = жив,
   но авторизация иначе (режим пароля) — контейнер не валим.
2. Оверлей (если панели нет): GET /overlay/health — 200 = жив.
3. Без веб-серверов: выход 0 — падения процесса ловит restart policy.

Коды выхода: 0 — здоров, 1 — нездоров (сервер не отвечает или 503).
"""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

TIMEOUT_SECONDS = 5.0
PANEL_TOKEN_FILE = ".panel-token"


def probe(url: str, token: str | None) -> int:
    """HTTP GET; возвращает статус, 0 — нет ответа (сеть/таймаут/прочее)."""
    request = urllib.request.Request(url)
    if token:
        request.add_header("X-Panel-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except Exception:
        return 0


def _panel_token() -> str | None:
    db_path = Path(os.getenv("DB_PATH", "data/bot.db"))
    token_path = db_path.parent / PANEL_TOKEN_FILE
    try:
        return token_path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _check_panel(port: str) -> int:
    status = probe(f"http://127.0.0.1:{port}/api/health", _panel_token())
    if status == 503:
        return 1  # бот не готов или БД не прошла integrity
    if status == 0:
        return 1  # сервер не отвечает
    return 0  # 200, 401 (жив, авторизация не подошла) и прочие ответы


def _check_overlay(port: str) -> int:
    status = probe(f"http://127.0.0.1:{port}/overlay/health", None)
    return 0 if status == 200 else 1


def main() -> int:
    panel_port = os.getenv("PANEL_PORT", "").strip()
    if panel_port:
        return _check_panel(panel_port)
    overlay_port = os.getenv("OVERLAY_PORT", "").strip()
    if overlay_port:
        return _check_overlay(overlay_port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
