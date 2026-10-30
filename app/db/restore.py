"""Безопасное восстановление SQLite backup при остановленном приложении.

Понимает шифрованные backup'ы (``MGBENC1``, см. ``app/core/crypto.py``): файл,
отправленный в Discord, расшифровывается на лету тем же ключом, что и при
отправке. Нешифрованные файлы ведут себя как раньше — без лишних копий.
"""
from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.core.crypto import decrypt_file, is_encrypted_file


def _check_sqlite(path: Path) -> None:
    """PRAGMA integrity_check по файлу базы."""
    connection = sqlite3.connect(str(path))
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"SQLite backup повреждён: {result[0] if result else 'unknown'}")
    finally:
        connection.close()


def _check_payload(payload: bytes) -> None:
    """integrity_check для байтов, которые ещё не лежат постоянным файлом.

    ``sqlite3.connect(':memory:') + deserialize`` на этом чеке падает с
    «unable to open database file», поэтому кладём во временный файл — так же,
    как это делает сам restore.
    """
    handle = NamedTemporaryFile(delete=False, suffix=".db")
    temp_path = Path(handle.name)
    try:
        handle.write(payload)
        handle.close()
        _check_sqlite(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _decrypt_or_raise(data: bytes, source_path: Path) -> bytes:
    plain = decrypt_file(data)
    if plain is None:
        raise RuntimeError(
            f"Зашифрованный backup {source_path.name}: не удалось расшифровать "
            "(нужен PANEL_ENCRYPTION_KEY или data/.panel-key, файл должен быть не подменён)"
        )
    return plain


def validate_backup(source: str | Path) -> None:
    """Проверяет backup через SQLite integrity_check до замены рабочего файла."""
    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    data = source_path.read_bytes()
    if not is_encrypted_file(data):
        # Нешифрованный файл проверяем по месту: смысла копировать нет.
        _check_sqlite(source_path)
        return
    _check_payload(_decrypt_or_raise(data, source_path))


def restore_backup(source: str | Path, target: str | Path, keep_backup: bool = True) -> Path | None:
    """Атомарно заменяет target проверенным backup и возвращает путь старого файла."""
    source_path = Path(source)
    target_path = Path(target)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    # Сначала расшифровка + проверка исходника: не трогаем цель, пока не знаем,
    # что payload валиден (иначе битый ключ или кривой файл затёрли бы базу).
    raw = source_path.read_bytes()
    encrypted = is_encrypted_file(raw)
    data = _decrypt_or_raise(raw, source_path) if encrypted else raw
    if encrypted:
        _check_payload(data)
    else:
        _check_sqlite(source_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    old_backup: Path | None = None
    if target_path.exists() and keep_backup:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        old_backup = target_path.with_name(f"{target_path.name}.before-restore-{stamp}.bak")
        shutil.copy2(target_path, old_backup)
    temporary = target_path.with_suffix(target_path.suffix + ".restore.tmp")
    temporary.write_bytes(data)
    # Повторная проверка уже записанного файла ловит сбой диска при копировании.
    _check_sqlite(temporary)
    temporary.replace(target_path)
    # Убираем stale WAL/SHM от предыдущей (упавшей) базы: иначе SQLite
    # проиграет их кадры поверх нового файла при следующем открытии.
    for suffix in ("-wal", "-shm"):
        target_path.with_name(target_path.name + suffix).unlink(missing_ok=True)
    return old_backup
