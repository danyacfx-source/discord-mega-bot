"""Supply chain: лок согласован с requirements.txt и подключён в сборку.

Все проверки офлайновые — по одному чтению файлов.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"
LOCK = ROOT / "requirements.lock"
DOCKERFILE = ROOT / "Dockerfile"


def _load_audit():
    """Грузит scripts/audit_deps.py как модуль (scripts — не пакет)."""
    spec = importlib.util.spec_from_file_location("audit_deps", ROOT / "scripts" / "audit_deps.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("audit_deps", module)
    spec.loader.exec_module(module)
    return module


parse_pins = _load_audit().parse_pins
normalize = _load_audit().normalize

_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})")
_RANGE = re.compile(r"[><=~!]")


def _direct_names() -> list[str]:
    """Имена прямых зависимостей из requirements.txt (правая часть спеки отбрасывается)."""
    names: list[str] = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[<>=~!]", line, maxsplit=1)[0].strip()
        names.append(name)
    return names


def _lock_entries() -> dict[str, tuple[str, list[str]]]:
    """Словарь «имя → (версия, хэши)» из requirements.lock."""
    entries: dict[str, tuple[str, list[str]]] = {}
    current: str | None = None
    for raw in LOCK.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "==" in line:
            name, _, rest = line.partition("==")
            current = name.strip()
            version = rest.rstrip(" \\").strip()
            entries[current] = (version, [])
        elif current is not None and line.startswith("--hash="):
            match = _HASH.search(line)
            assert match, f"некорректный хэш в строке: {line!r}"
            entries[current][1].append(match.group(1))
    return entries


def test_every_direct_dependency_is_pinned():
    lock = {normalize(name) for name in _lock_entries()}
    missing = [name for name in _direct_names() if normalize(name) not in lock]
    assert not missing, f"в requirements.lock не закреплены: {missing}"


def test_lock_pins_are_exact_versions():
    text = LOCK.read_text(encoding="utf-8-sig")
    specs = [line.split("==", 1)[1].split()[0] for line in text.splitlines() if "==" in line and not line.startswith("#")]
    ranges = [spec for spec in specs if _RANGE.search(spec)]
    assert not ranges, f"в локе допустимы только точные версии, найдено: {ranges}"


def test_lock_hashes_are_sha256():
    entries = _lock_entries()
    assert entries, "requirements.lock пуст"
    empty = [name for name, (_, hashes) in entries.items() if not hashes]
    assert not empty, f"пакеты без sha256-хэшей: {empty}"


def test_dockerfile_installs_with_hashes():
    content = DOCKERFILE.read_text(encoding="utf-8")
    assert "--require-hashes" in content, "Dockerfile должен ставить зависимости с проверкой хэшей"
    assert "requirements.lock" in content, "Dockerfile должен копировать requirements.lock"


def test_audit_parses_lock_into_pins():
    pins = parse_pins(LOCK)
    assert pins, "audit_deps.parse_pins не разобрал лок"
    assert all(version and not _RANGE.search(version) for _, version in pins)


def test_audit_skips_range_requirements():
    assert parse_pins(REQUIREMENTS) == [], "parse_pins не должна брать спеки с диапазонами"
