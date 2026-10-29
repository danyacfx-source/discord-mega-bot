"""Персистентные настройки встроенных команд Twitch-чата."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

TWITCH_COMMANDS_KEY = "panel.twitch.commands.v1"
TWITCH_COMMAND_RESPONSE_MAX = 450
TWITCH_COMMAND_ALIASES_MAX = 12
_ALIAS_RE = re.compile(r"^[0-9a-zа-яё_]+$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class TwitchCommandDefinition:
    id: str
    label: str
    aliases: tuple[str, ...]
    description: str
    moderator_only: bool = False


TWITCH_COMMAND_DEFINITIONS = (
    TwitchCommandDefinition("discord", "Discord", ("discord", "дискорд", "дс"), "Ссылка на Discord"),
    TwitchCommandDefinition("donate", "Донат", ("donate", "донат"), "Ссылка на донат"),
    TwitchCommandDefinition("youtube", "YouTube", ("youtube", "ютуб"), "Ссылка на YouTube"),
    TwitchCommandDefinition("game", "Игра", ("game", "игра"), "Текущая категория стрима"),
    TwitchCommandDefinition("signals", "Сигналы", ("signals", "сигналы"), "Описание баллов канала"),
    TwitchCommandDefinition("rewards", "Награды", ("rewards", "награды"), "Список наград канала"),
    TwitchCommandDefinition("callsign", "Позывной", ("callsign", "позывной"), "Случайный позывной зрителя"),
    TwitchCommandDefinition("ping", "Ping", ("ping", "пинг"), "Проверка ответа бота"),
    TwitchCommandDefinition("help", "Помощь", ("help", "помощь", "хелп", "команды"), "Список команд"),
    TwitchCommandDefinition("uptime", "Время эфира", ("uptime", "аптайм", "эфир", "live"), "Длительность текущего эфира"),
    TwitchCommandDefinition("links", "Все ссылки", ("links", "ссылки", "ссылка"), "Список социальных ссылок"),
    TwitchCommandDefinition("schedule", "Расписание", ("schedule", "расписание"), "Ближайшие эфиры"),
    TwitchCommandDefinition("bal", "Баланс", ("bal", "balance", "баланс", "монеты", "coins", "кэш"), "Баланс монет зрителя"),
    TwitchCommandDefinition("top", "Топ", ("top", "топ", "лидерборд"), "Лидерборд монет"),
    TwitchCommandDefinition("slots", "Слоты", ("slots", "слоты", "слот", "казино"), "Игра на монеты"),
    TwitchCommandDefinition("flip", "Монетка", ("flip", "монетка", "coin", "флип"), "Орёл или решка на монеты"),
    TwitchCommandDefinition("8ball", "Шар предсказаний", ("8ball", "шар", "шарик"), "Случайный ответ на вопрос"),
    TwitchCommandDefinition("so", "Шоуаут", ("so", "shoutout"), "Упоминание другого канала", True),
    TwitchCommandDefinition("poll", "Опрос в чате", ("poll",), "Внутренний опрос с голосованием цифрами", True),
    TwitchCommandDefinition("twitch_poll", "Twitch Poll", ("опрос",), "Настоящий опрос Twitch через Helix", True),
)

_DEFINITIONS_BY_ID = {definition.id: definition for definition in TWITCH_COMMAND_DEFINITIONS}


def clean_command_alias(value: Any) -> str:
    alias = str(value or "").strip().lower().lstrip("!")[:32]
    return alias if _ALIAS_RE.fullmatch(alias) else ""


def clean_command_response(value: Any) -> str:
    return " ".join(str(value or "").split())[:TWITCH_COMMAND_RESPONSE_MAX]


def default_twitch_command_settings() -> dict[str, dict[str, Any]]:
    return {
        definition.id: {
            "enabled": True,
            "aliases": list(definition.aliases),
            "moderator_only": definition.moderator_only,
            "response": "",
        }
        for definition in TWITCH_COMMAND_DEFINITIONS
    }


def normalize_twitch_command_settings(raw: Any) -> dict[str, dict[str, Any]]:
    defaults = default_twitch_command_settings()
    if not isinstance(raw, dict):
        return defaults
    commands = raw.get("commands", raw)
    if not isinstance(commands, dict):
        return defaults
    for command_id, default in defaults.items():
        stored = commands.get(command_id)
        if not isinstance(stored, dict):
            continue
        aliases_raw = stored.get("aliases")
        aliases = []
        if isinstance(aliases_raw, list):
            for value in aliases_raw[:TWITCH_COMMAND_ALIASES_MAX]:
                alias = clean_command_alias(value)
                if alias and alias not in aliases:
                    aliases.append(alias)
        default["enabled"] = stored.get("enabled", True) is not False
        default["aliases"] = aliases or default["aliases"]
        default["moderator_only"] = bool(
            stored.get("moderator_only", default["moderator_only"])
        )
        default["response"] = clean_command_response(stored.get("response"))
    return defaults


def command_settings_payload(settings: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": definition.id,
            "label": definition.label,
            "description": definition.description,
            "default_aliases": list(definition.aliases),
            "default_moderator_only": definition.moderator_only,
            **settings[definition.id],
        }
        for definition in TWITCH_COMMAND_DEFINITIONS
    ]


def validate_aliases(settings: dict[str, dict[str, Any]]) -> str | None:
    owner: dict[str, str] = {}
    for command_id, command in settings.items():
        if not command["aliases"]:
            return f"У команды {_DEFINITIONS_BY_ID[command_id].label} должен быть хотя бы один алиас"
        for alias in command["aliases"]:
            previous = owner.get(alias)
            if previous is not None and previous != command_id:
                return f"Алиас !{alias} назначен нескольким командам"
            owner[alias] = command_id
    return None


async def load_twitch_command_settings(kv: Any) -> dict[str, dict[str, Any]]:
    try:
        raw = await kv.get(TWITCH_COMMANDS_KEY, "{}")
        data = json.loads(raw or "{}")
    except (TypeError, ValueError, AttributeError):
        data = {}
    return normalize_twitch_command_settings(data)


async def save_twitch_command_settings(
    kv: Any, payload: Any
) -> tuple[dict[str, dict[str, Any]], str | None]:
    settings = normalize_twitch_command_settings({"commands": payload})
    error = validate_aliases(settings)
    if error is not None:
        return settings, error
    await kv.set(
        TWITCH_COMMANDS_KEY,
        json.dumps({"commands": settings}, ensure_ascii=False, separators=(",", ":")),
    )
    return settings, None


def twitch_command_alias_map(settings: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {
        alias: command_id
        for command_id, command in settings.items()
        for alias in command["aliases"]
    }
