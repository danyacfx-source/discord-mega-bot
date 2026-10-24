"""Brand identity tests for the Gemini AI chat persona."""

from __future__ import annotations

import pytest

from app.cogs.ai.chat_ai import DEFAULT_PROMPT, resolve_ai_system_prompt


def test_default_ai_character_is_dendich_control_radio_silence() -> None:
    assert "DendichControl" in DEFAULT_PROMPT
    assert "RADIO SILENCE" in DEFAULT_PROMPT
    assert "Arma Reforger" in DEFAULT_PROMPT
    assert "Squad" in DEFAULT_PROMPT
    assert "WARDOGS" in DEFAULT_PROMPT
    assert "Ты —" in DEFAULT_PROMPT
    assert "\\n" not in DEFAULT_PROMPT
    assert "\n\n" in DEFAULT_PROMPT
    assert "Милый Килла" not in DEFAULT_PROMPT
    assert "Асуна Юки" not in DEFAULT_PROMPT


@pytest.mark.parametrize(
    "configured",
    [
        None,
        "",
        "   ",
        "Ты — Милый Килла, твой стиль общения дружелюбный.",
        "Ты — МИЛЫЙ КИЛЛА, общаешься с участниками сервера.",
        "Ты — Милый   Килла, ИИ-бот.",
        "Милый Килла",
    ],
)
def test_old_or_missing_persona_gets_brand_replacement(configured: str | None) -> None:
    assert resolve_ai_system_prompt(configured) == DEFAULT_PROMPT


def test_explicit_custom_system_prompt_is_preserved() -> None:
    custom = "Отвечай в формате сводки и не делай лишних предположений."
    assert resolve_ai_system_prompt(custom) == custom


def test_identity_instruction_is_in_active_system_message() -> None:
    identity = resolve_ai_system_prompt("Милый Килла")
    assert "Если тебя спрашивают, кто ты" in identity
    assert "DendichControl — ИИ-радист" in identity
