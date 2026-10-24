"""Regression checks: the OBS chat overlay remains available in the admin UI."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_admin_exposes_standalone_chat_even_without_layout() -> None:
    source = (ROOT / "panel-ui/src/sections/overlay.jsx").read_text(encoding="utf-8")
    no_layout = source.split("if (!layout) {", 1)[1]
    no_layout = no_layout.split("// ------------------------------------------------------------- редактор", 1)[0]
    assert "Лента чата для OBS" in no_layout
    assert "onClick={copyChatUrl}" in no_layout
    assert "/overlay/chat?token=" in source
    assert 'chat: { label: "Лента чата" }' in source


def test_chat_page_does_not_expose_messages_without_token() -> None:
    html = (ROOT / "app/core/overlay/chat.html").read_text(encoding="utf-8")
    assert '"X-Overlay-Token":TOKEN' in html
    assert "text.textContent=m.text" in html
    assert "name.textContent=m.name" in html
    assert "PCOLOR=" in html
