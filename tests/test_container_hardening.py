"""Hardening контейнера: compose и Dockerfile не ослабляются молча."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
ENTRYPOINT = (ROOT / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8")


def _service_block(text: str, name: str) -> str:
    """Возвращает тело сервиса до следующего ключа верхнего уровня сервиса."""
    start = text.index(f"  {name}:")
    rest = text[start:]
    lines = rest.splitlines()[1:]
    block: list[str] = []
    for line in lines:
        if line and not line[0].isspace() and not line.startswith("  "):
            break
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
            break
        block.append(line)
    return "\n".join(block)


def test_root_filesystem_is_read_only() -> None:
    assert "read_only: true" in _service_block(COMPOSE, "bot"), "корень ФС контейнера должен быть read_only"
    assert "/tmp" in _service_block(COMPOSE, "bot"), "read_only требует tmpfs на /tmp"


def test_capabilities_are_dropped() -> None:
    bot = _service_block(COMPOSE, "bot")
    assert "cap_drop:" in bot, "все capabilities должны сбрасываться"
    assert "- ALL" in bot
    # entrypoint работает от root: chown томов и переход через gosu.
    assert "- CHOWN" in bot
    assert "- SETUID" in bot
    assert "- SETGID" in bot
    for denied in ("- NET_RAW", "- SYS_PTRACE", "- MKNOD"):
        assert denied not in bot, f"лишняя capability: {denied}"


def test_resource_limits_present() -> None:
    bot = _service_block(COMPOSE, "bot")
    assert "pids_limit:" in bot, "нет лимита процессов — возможна fork-бомба"
    assert "mem_limit:" in bot, "нет потолка памяти"
    assert "ulimits:" in bot


def test_privilege_boundary_kept() -> None:
    assert "no-new-privileges:true" in COMPOSE
    # Бот не работает от root: entrypoint чинит владельца томов и через gosu
    # уходит на непривилегированного пользователя.
    assert "gosu bot" in ENTRYPOINT
    assert 'adduser --system --ingroup bot' in DOCKERFILE


def test_volumes_stay_writable_under_read_only() -> None:
    bot = _service_block(COMPOSE, "bot")
    assert "./data:/app/data" in bot, "data — bind-mount, единственный источник состояния"
    assert "./logs:/app/logs" in bot
    # Кеш службы кладём во временный раздел, иначе read_only его убьёт.
    assert "XDG_CACHE_HOME: /tmp/xdg-cache" in bot
