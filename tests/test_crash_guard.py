from __future__ import annotations

import logging
import sys
import threading

from app.core import crash_guard


def _make_tree(root, body: bytes = b"x = 1\n") -> None:
    (root / "app").mkdir()
    (root / "app" / "a.py").write_bytes(body)
    (root / "main.py").write_bytes(b"pass\n")


def test_fingerprint_stable_and_changes(tmp_path):
    _make_tree(tmp_path)
    first = crash_guard.code_fingerprint(tmp_path)
    assert crash_guard.code_fingerprint(tmp_path) == first
    assert first[1] == 2
    (tmp_path / "app" / "a.py").write_bytes(b"x = 2\n")
    assert crash_guard.code_fingerprint(tmp_path)[0] != first[0]


def test_fingerprint_ignores_line_endings(tmp_path):
    _make_tree(tmp_path, b"x = 1\ny = 2\n")
    lf = crash_guard.code_fingerprint(tmp_path)
    (tmp_path / "app" / "a.py").write_bytes(b"x = 1\r\ny = 2\r\n")
    assert crash_guard.code_fingerprint(tmp_path) == lf


def test_build_description_uses_commit_env(tmp_path, monkeypatch):
    _make_tree(tmp_path)
    for name in crash_guard._COMMIT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    assert "неизвестен" in crash_guard.build_description("1.2.3", tmp_path)
    monkeypatch.setenv("GIT_COMMIT", "abcdef1234567890")
    text = crash_guard.build_description("1.2.3", tmp_path)
    assert "версия 1.2.3" in text and "abcdef123456" in text


def test_excepthooks_log_critical(caplog, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(sys, "__excepthook__", lambda *a: None)
    crash_guard.install()
    with caplog.at_level(logging.CRITICAL, logger="bot"):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
    assert any("boom" in (r.exc_text or "") or r.exc_info for r in caplog.records)
    assert caplog.records[0].levelno == logging.CRITICAL
