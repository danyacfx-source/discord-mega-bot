#!/usr/bin/env python3
"""Расшифровывает зашифрованный backup (MGBENC1) в читаемый SQLite-файл.

Ключ берётся оттуда же, откуда при отправке: PANEL_ENCRYPTION_KEY или
data/.panel-key. Плоские файлы просто копируются — скрипт работает и со
старыми нешифрованными backup'ами.

    python scripts/decrypt_backup.py --source data/backups/bot-20260101.db.enc
    python scripts/decrypt_backup.py --source bot.db.enc --dest /tmp/bot.db
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.crypto import decrypt_file, is_encrypted_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Путь к backup (зашифрованному или нет)")
    parser.add_argument("--dest", help="Куда записать результат (по умолчанию рядом, без .enc)")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.is_file():
        parser.error(f"файл не найден: {source}")

    raw = source.read_bytes()
    if not is_encrypted_file(raw):
        print(f"{source} не зашифрован — копируем как есть")
        payload = raw
    else:
        payload = decrypt_file(raw)
        if payload is None:
            print(
                "Не удалось расшифровать: нужен PANEL_ENCRYPTION_KEY или data/.panel-key, "
                "и файл должен быть не подменён",
                file=sys.stderr,
            )
            return 1

    if args.dest:
        dest = Path(args.dest)
    else:
        name = source.name[:-4] if source.name.endswith(".enc") else source.name + ".dec"
        dest = source.with_name(name)
    dest.write_bytes(payload)
    print(f"OK: {source} -> {dest} ({len(payload)} байт)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
