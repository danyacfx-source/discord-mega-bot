#!/usr/bin/env python3
"""Аудит зависимостей против базы уязвимостей OSV (PyPI / OSV / GitHub).

Зачем: пиннинг в ``requirements.lock`` фиксирует версию, но не говорит, есть ли
в ней известная дыра. Этот скрипт — шлюз: он сверяет каждый пакет лока с
OSV и ненулевым кодом возвращает CI.

Использует только stdlib (urllib), новых зависимостей не нужно::

    python scripts/audit_deps.py                # аудит requirements.lock
    python scripts/audit_deps.py --json > out.json
    python scripts/audit_deps.py --file requirements.txt

Коды выхода: 0 — уязвимостей нет; 1 — найдены; 2 — не удалось опросить API.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OSV_ENDPOINT = "https://api.osv.dev/v1/querybatch"
OSV_DETAIL = "https://api.osv.dev/v1/vulns/"
_BATCH = 50
_TIMEOUT = 30.0

#: Строка пина ``name==version``. Диапазоны (``>=``, ``~=``) не считаются пином:
#: по ним нельзя спросить базу уязвимостей — нужна конкретная версия.
_PIN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*===?\s*([^\s;#\\,]+)")


def normalize(name: str) -> str:
    """Нормализация имени по PEP 503 (сравнение PyPI ↔ pip ↔ OSV)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_pins(path: Path) -> list[tuple[str, str]]:
    """Достаёт пары (имя, версия) из файла зависимостей.

    Принимает только точные пины ``name==version``; спеки с диапазонами
    молча пропускаются — в ``requirements.lock`` их быть не должно.
    """
    pins: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        line = line.split("\\")[0]
        match = _PIN.match(line)
        if match is None:
            continue
        name, version = match.group(1), match.group(2)
        key = normalize(name)
        if key in seen:
            continue
        seen.add(key)
        pins.append((name, version))
    return pins


def query_osv(pins: list[tuple[str, str]]) -> list[dict[str, object]]:
    """Опрашивает OSV батчами. Возвращает список находок."""
    findings: list[dict[str, object]] = []
    for start in range(0, len(pins), _BATCH):
        chunk = pins[start : start + _BATCH]
        payload = json.dumps(
            {
                "queries": [
                    {"package": {"name": name, "ecosystem": "PyPI"}, "version": version}
                    for name, version in chunk
                ]
            }
        ).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 — endpoint зашит константой
            OSV_ENDPOINT, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))

        for (name, version), result in zip(chunk, body.get("results", []), strict=True):
            # Батч возвращает ``{}`` (нет находок) или ``{"vulns": [{id, modified}]}``.
            # Полные описания в батче нет — их подтягивает _enrich().
            for vuln in (result or {}).get("vulns", []) if isinstance(result, dict) else (result or []):
                vuln_id = vuln.get("id", "")
                findings.append(
                    {
                        "package": name,
                        "version": version,
                        "id": vuln_id,
                        "aliases": [],
                        "summary": "",
                        "url": f"https://osv.dev/vulnerability/{vuln_id}",
                    }
                )
    return _enrich(findings)


def _enrich(findings: list[dict[str, object]]) -> list[dict[str, object]]:
    """Дозапрашивает описание каждой находки. Ошибки игнорируются — ID уже есть."""
    for item in findings:
        vuln_id = str(item["id"])
        try:
            with urllib.request.urlopen(  # noqa: S310 — endpoint зашит константой
                f"{OSV_DETAIL}{vuln_id}", timeout=_TIMEOUT
            ) as response:
                detail = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            continue
        summary = detail.get("summary") or detail.get("details") or ""
        item["aliases"] = detail.get("aliases") or []
        item["summary"] = str(summary).replace("\n", " ")[:200]
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Аудит зависимостей через OSV")
    parser.add_argument("--file", default=None, help="файл зависимостей (по умолчанию requirements.lock)")
    parser.add_argument("--json", action="store_true", help="вывод в JSON")
    args = parser.parse_args()

    target = Path(args.file) if args.file else ROOT / "requirements.lock"
    if not target.is_file():
        target = ROOT / "requirements.txt"
    if not target.is_file():
        print("не найден ни requirements.lock, ни requirements.txt", file=sys.stderr)
        return 2

    pins = parse_pins(target)
    if not pins:
        print(f"{target.name}: не найдено ни одного пина", file=sys.stderr)
        return 2

    try:
        findings = query_osv(pins)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"OSV недоступен: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"file": str(target), "packages": len(pins), "findings": findings}, ensure_ascii=False, indent=2))
    else:
        print(f"{target.name}: проверено пакетов {len(pins)}, уязвимостей {len(findings)}")
        for item in findings:
            print(f"  {item['package']}=={item['version']}  {item['id']}  {item['url']}")
            if item["summary"]:
                print(f"      {item['summary']}")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
