#!/usr/bin/env python3
"""Собирает ``requirements.lock``: точные версии + sha256 каждого вина.

Что и зачем:

- ``requirements.txt`` остаётся живым описанием зависимостей (диапазоны) — его
  правит человек;
- ``requirements.lock`` — производный артефакт для ``pip install --require-hashes``.
  С ним установка принимает только вины с подписью из лока: подменённый или
  скомпрометированный пакет на этапе сборки не ставится;
- версии резолвятся под **linux / Python 3.11** — это целевая платформа Docker;
  хэши при этом берутся для **всех** артефактов версии, чтобы лок работал и под
  dev-машиной, и под любой другой целевой системой.

Запуск (нужна сеть)::

    python scripts/lock_requirements.py            # пересобрать lock
    python scripts/lock_requirements.py --verify   # проверить, что lock актуален
"""
from __future__ import annotations

import argparse
import json
import subprocess  # noqa: S403 — вызывается доверенный pip из окружения
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIREMENTS = ROOT / "requirements.txt"
LOCK = ROOT / "requirements.lock"
PYPI_JSON = "https://pypi.org/pypi/{name}/{version}/json"
_TIMEOUT = 30.0

#: Целевая платформа: Docker-образ python:3.11-slim. Версии резолвятся под неё —
#: это самая строгая из поддерживаемых (хэши при этом берутся для всех платформ).
_LINUX_ARGS = [
    "--platform", "manylinux_2_17_x86_64",
    "--platform", "manylinux2014_x86_64",
    "--platform", "manylinux_2_28_x86_64",
    "--platform", "linux_x86_64",
    "--python-version", "3.11",
    "--implementation", "cp",
    "--abi", "cp311",
    "--abi", "abi3",
    "--abi", "none",
]
_HEADER = """\
# requirements.lock — производный файл, НЕ редактировать руками.
# Пересборка: python scripts/lock_requirements.py
# Установка с проверкой: pip install --require-hashes -r requirements.lock
# Версии резолвятся под linux/py3.11 (Docker); хэши — все артефакты версии с PyPI.
"""


def _pip(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pip", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _resolve_linux_pins() -> dict[str, str]:
    """Резолвит дерево зависимостей под linux/py3.11 → {имя: версия}."""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        result = _pip(
            [
                "install",
                "--dry-run",
                "--ignore-installed",
                "--quiet",
                "--report",
                str(report),
                *_LINUX_ARGS,
                "--only-binary=:all:",
                "-r",
                str(REQUIREMENTS),
            ],
            check=False,
        )
        if not report.is_file():
            raise SystemExit(f"pip не собрал отчёт (код {result.returncode}):\n{result.stderr.strip()}")
        data = json.loads(report.read_text(encoding="utf-8"))

    pins: dict[str, str] = {}
    for item in data.get("install", []):
        metadata = item["metadata"]
        name = metadata["name"]
        version = metadata["version"]
        previous = pins.get(name)
        if previous is not None and previous != version:
            raise SystemExit(f"{name}: противоречивые версии {previous} и {version}")
        pins[name] = version
    if not pins:
        raise SystemExit("пустой отчёт — проверьте requirements.txt")
    return pins


def _release_hashes(name: str, version: str) -> list[str]:
    """Все sha256 артефактов версии из JSON API PyPI.

    Пайплайн ``pip download`` отдал бы ровно один вин под запрошенную платформу —
    а pip на целевой машине может выбрать другой тег (manylinux_2_17 против
    manylinux_2_28, musllinux, win32), и установка упадёт на несовпадении хэша.
    PyPI отдаёт дайджесты всех файлов версии сразу: лок покрывает любую
    платформу, на которую попадёт пакет.
    """
    url = PYPI_JSON.format(name=name, version=version)
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as response:  # noqa: S310 — endpoint зашит константой
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return []
    digests = {
        f"sha256:{entry['digests']['sha256']}"
        for entry in data.get("urls", [])
        if isinstance(entry.get("digests"), dict) and entry["digests"].get("sha256")
    }
    return sorted(digests)


def build_lock() -> tuple[str, list[str]]:
    """Возвращает текст лока и список предупреждений (пакеты без хэша)."""
    pins = _resolve_linux_pins()
    warnings: list[str] = []
    lines: list[str] = [_HEADER]

    for name in sorted(pins, key=str.lower):
        version = pins[name]
        hashes = _release_hashes(name, version)
        if not hashes:
            warnings.append(f"{name}=={version}: PyPI не отдал ни одного хэша — пакет пропущен")
            continue
        requirement = f"{name}=={version}"
        lines.append(f"{requirement} \\")
        for index, digest in enumerate(hashes):
            tail = "" if index == len(hashes) - 1 else " \\"
            lines.append(f"    --hash={digest}{tail}")

    return "\n".join(lines).rstrip() + "\n", warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Генерация requirements.lock с sha256")
    parser.add_argument("--verify", action="store_true", help="сверить существующий lock с пересборкой")
    args = parser.parse_args()

    text, warnings = build_lock()
    for warning in warnings:
        print(f"WARNING  {warning}")

    if args.verify:
        if not LOCK.is_file():
            print("requirements.lock отсутствует")
            return 1
        if LOCK.read_text(encoding="utf-8") != text:
            print("requirements.lock устарел — пересоберите: python scripts/lock_requirements.py")
            return 1
        print("requirements.lock актуален")
        return 0

    LOCK.write_text(text, encoding="utf-8", newline="\n")
    packages = sum(1 for line in text.splitlines() if "==" in line and not line.startswith("#"))
    digests = sum(1 for line in text.splitlines() if line.lstrip().startswith("--hash="))
    print(f"Записан {LOCK.name}: пакетов {packages}, хэшей {digests}, предупреждений {len(warnings)}")
    return 1 if warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
