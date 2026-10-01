"""Тесты scripts/healthcheck.py — логика Docker healthcheck."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "healthcheck.py"
_spec = importlib.util.spec_from_file_location("healthcheck_script", _SCRIPT)
assert _spec and _spec.loader
healthcheck = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(healthcheck)


def _clear_ports(monkeypatch) -> None:
    monkeypatch.delenv("PANEL_PORT", raising=False)
    monkeypatch.delenv("OVERLAY_PORT", raising=False)


def test_no_web_servers_is_healthy(monkeypatch) -> None:
    _clear_ports(monkeypatch)
    assert healthcheck.main() == 0


def test_panel_200_is_healthy(monkeypatch) -> None:
    _clear_ports(monkeypatch)
    monkeypatch.setenv("PANEL_PORT", "3000")
    monkeypatch.setattr(healthcheck, "probe", lambda url, token: 200)
    assert healthcheck.main() == 0


def test_panel_503_is_unhealthy(monkeypatch) -> None:
    _clear_ports(monkeypatch)
    monkeypatch.setenv("PANEL_PORT", "3000")
    monkeypatch.setattr(healthcheck, "probe", lambda url, token: 503)
    assert healthcheck.main() == 1


def test_panel_no_response_is_unhealthy(monkeypatch) -> None:
    _clear_ports(monkeypatch)
    monkeypatch.setenv("PANEL_PORT", "3000")
    monkeypatch.setattr(healthcheck, "probe", lambda url, token: 0)
    assert healthcheck.main() == 1


def test_panel_401_is_alive(monkeypatch) -> None:
    """Режим пароля: сервер отвечает, но токен не подходит — не валим контейнер."""
    _clear_ports(monkeypatch)
    monkeypatch.setenv("PANEL_PORT", "3000")
    monkeypatch.setattr(healthcheck, "probe", lambda url, token: 401)
    assert healthcheck.main() == 0


def test_panel_token_read_beside_db(tmp_path, monkeypatch) -> None:
    """Токен берётся из data/.panel-token рядом с DB_PATH."""
    _clear_ports(monkeypatch)
    db_path = tmp_path / "bot.db"
    (tmp_path / ".panel-token").write_text("secret-token", encoding="utf-8")
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("PANEL_PORT", "3000")
    seen: dict[str, object] = {}

    def fake_probe(url: str, token: str | None) -> int:
        seen["url"] = url
        seen["token"] = token
        return 200

    monkeypatch.setattr(healthcheck, "probe", fake_probe)
    assert healthcheck.main() == 0
    assert seen["url"] == "http://127.0.0.1:3000/api/health"
    assert seen["token"] == "secret-token"


def test_overlay_fallback_when_no_panel(monkeypatch) -> None:
    _clear_ports(monkeypatch)
    monkeypatch.setenv("OVERLAY_PORT", "8765")
    seen: dict[str, object] = {}

    def fake_probe(url: str, token: str | None) -> int:
        seen["url"] = url
        return 200

    monkeypatch.setattr(healthcheck, "probe", fake_probe)
    assert healthcheck.main() == 0
    assert seen["url"] == "http://127.0.0.1:8765/overlay/health"


def test_overlay_not_ok_is_unhealthy(monkeypatch) -> None:
    _clear_ports(monkeypatch)
    monkeypatch.setenv("OVERLAY_PORT", "8765")
    monkeypatch.setattr(healthcheck, "probe", lambda url, token: 500)
    assert healthcheck.main() == 1


def test_probe_http_error_returns_status(monkeypatch) -> None:
    """HTTPError (404/500) — это ответ сервера, а не сетевой сбой."""
    import urllib.error

    def fake_urlopen(request, timeout):  # noqa: ANN001
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", None, None)

    monkeypatch.setattr(healthcheck.urllib.request, "urlopen", fake_urlopen)
    assert healthcheck.probe("http://127.0.0.1:1/x", None) == 404


def test_probe_connection_error_returns_zero(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # noqa: ANN001
        raise ConnectionRefusedError

    monkeypatch.setattr(healthcheck.urllib.request, "urlopen", fake_urlopen)
    assert healthcheck.probe("http://127.0.0.1:1/x", None) == 0
