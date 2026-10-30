"""Симметричное шифрование секретов at-rest.

Защита в глубину: даже если диск/БД/бэкап утекли целиком, сами токены
бесполезны без ключа. Ключ живёт вне зашифрованных данных:

- ``PANEL_ENCRYPTION_KEY`` (env / Docker secret) — предпочтительный путь;
- иначе файл ``data/.panel-key`` (chmod 600) создаётся автоматически.

Два формата:

- **строки** (KV-токены) — Fernet, префикс ``enc:v1:``;
- **файлы** (backup в Discord) — AES-256-GCM, заголовок ``MGBENC1``.

Всё без префикса/заголовка возвращается как есть (обратная совместимость со
старыми plaintext-записями): старые базы не ломаются, шифрование
подхватывается при следующей записи.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path

logger = logging.getLogger("bot.crypto")

_PREFIX = "enc:v1:"
_KEY_ENV = "PANEL_ENCRYPTION_KEY"
_DEFAULT_KEY_FILE = "data/.panel-key"

#: Заголовок шифрованного файла: магия + версия. SQLite начинается с
#: "SQLite format 3", так что коллизия с настоящей базой исключена.
_FILE_MAGIC = b"MGBENC1"
_NONCE_LEN = 12  # GCM: 96-битный nonce обязателен для безопасности режима
#: Доменное разделение: подключ файлов и Fernet не должны делить ключ.
_FILE_KDF = b"mgb-file-v1\x00"

_raw_key: bytes | None = None
_fernet = None
_init_attempted = False
_warned_no_key = False


def _load_raw_key() -> bytes | None:
    """Возвращает 32-байтный ключ из env, иначе из файла (создав его)."""
    env_key = (os.getenv(_KEY_ENV) or "").strip()
    if env_key:
        try:
            raw = base64.urlsafe_b64decode(env_key.encode("ascii"))
            if len(raw) != 32:
                raise ValueError("длина не 32 байта")
            return raw
        except Exception:
            logger.error("%s некорректен — ожидается urlsafe-base64 из 32 байт", _KEY_ENV)
            return None

    path = Path(os.getenv("PANEL_KEY_FILE") or _DEFAULT_KEY_FILE)
    try:
        if path.is_file():
            raw = base64.urlsafe_b64decode(path.read_text(encoding="utf-8").strip().encode("ascii"))
            if len(raw) == 32:
                return raw
            logger.error("Файл ключа %s повреждён (не 32 байта)", path)
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(key)
        logger.info("Создан ключ шифрования at-rest: %s (храни его вне БД и бэкапов)", path)
        return base64.urlsafe_b64decode(key)
    except OSError as exc:
        logger.error("Не удалось создать файл ключа шифрования %s: %s", path, exc)
        return None


def _key() -> bytes | None:
    """Ленивая инициализация; None — если ключ недоступен."""
    global _raw_key, _fernet, _init_attempted, _warned_no_key
    if _init_attempted:
        return _raw_key
    _init_attempted = True
    raw = _load_raw_key()
    if raw is None or len(raw) != 32:
        if not _warned_no_key:
            logger.warning(
                "Ключ шифрования at-rest недоступен — секреты хранятся открытым текстом. "
                "Задай %s или разреши создание %s.",
                _KEY_ENV,
                _DEFAULT_KEY_FILE,
            )
            _warned_no_key = True
        return None
    from cryptography.fernet import Fernet

    _raw_key = raw
    _fernet = Fernet(base64.urlsafe_b64encode(raw))
    return raw


def _reset_for_tests() -> None:
    """Сбрасывает кэш ключа (только для тестов, меняющих env/файл ключа)."""
    global _raw_key, _fernet, _init_attempted, _warned_no_key
    _raw_key = None
    _fernet = None
    _init_attempted = False
    _warned_no_key = False


# ------------------------------------------------------------------- строки

def encrypt_text(plain: str) -> str:
    """Шифрует строку; при отсутствии ключа возвращает её же (degrade)."""
    if not plain or plain.startswith(_PREFIX):
        return plain
    if _key() is None:
        return plain
    return _PREFIX + _fernet.encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_text(value: str) -> str:
    """Расшифровывает ``enc:v1:...``; всё остальное возвращает как есть."""
    if not value or not value.startswith(_PREFIX):
        return value
    if _key() is None:
        logger.error("Зашифрованное значение, но ключ недоступен — пропускаем")
        return value
    try:
        return _fernet.decrypt(value[len(_PREFIX) :].encode("ascii")).decode("utf-8")
    except Exception:
        logger.error("Не удалось расшифровать значение (смена ключа?)")
        return value


def encrypt_bytes(data: bytes) -> bytes:
    """Шифрует байты (Fernet); без ключа — как есть."""
    if _key() is None:
        return data
    return _fernet.encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    """Расшифровывает байты :func:`encrypt_bytes`; без ключа — как есть."""
    if _key() is None:
        return data
    try:
        return _fernet.decrypt(data)
    except Exception:
        logger.error("Не удалось расшифровать байты (смена ключа?)")
        return data


# ------------------------------------------------------------------- файлы

def is_encrypted_file(data: bytes) -> bool:
    """True, если байты — шифрованный файл (заголовок ``MGBENC1``)."""
    return data.startswith(_FILE_MAGIC)


def encrypt_file(data: bytes) -> bytes | None:
    """AES-256-GCM поверх домен-разделённого ключа.

    Overhead ровно 35 байт (7 магия + 12 nonce + 16 тег), поэтому backup не
    раздувается за лимит Discord на 4/3, как было бы с Fernet/base64.

    None — если ключа нет: вызывающий код решает, что делать (в бэкапе это
    деградация в plaintext, но доступность важнее секретности копии).
    """
    raw = _key()
    if raw is None:
        return None
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    subkey = hashlib.sha256(_FILE_KDF + raw).digest()
    nonce = os.urandom(_NONCE_LEN)
    # AAD = магия: подделать заголовок нельзя, расшифровка его же и требует.
    sealed = AESGCM(subkey).encrypt(nonce, data, _FILE_MAGIC)
    return _FILE_MAGIC + nonce + sealed


def decrypt_file(data: bytes) -> bytes | None:
    """Расшифровывает :func:`encrypt_file`; нешифрованные байты возвращает как есть.

    None — если данные помечены как шифрованные, но ключа нет или тег не сошёлся
    (подмена/порча файла — это не то же самое, что legacy-plaintext).
    """
    if not is_encrypted_file(data):
        return data
    raw = _key()
    if raw is None:
        logger.error("Зашифрованный файл, но ключ недоступен")
        return None
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    subkey = hashlib.sha256(_FILE_KDF + raw).digest()
    body = data[len(_FILE_MAGIC) :]
    if len(body) < _NONCE_LEN + 16:
        logger.error("Зашифрованный файл обрезан")
        return None
    try:
        return AESGCM(subkey).decrypt(body[:_NONCE_LEN], body[_NONCE_LEN:], _FILE_MAGIC)
    except Exception:
        logger.error("Не удалось расшифровать файл (смена ключа или файл подменён?)")
        return None


# ------------------------------------------------------------- диагностика

def is_encrypted(value: str) -> bool:
    return bool(value) and value.startswith(_PREFIX)


def key_available() -> bool:
    """True, если шифрование at-rest активно (ключ загрузился)."""
    return _key() is not None


def key_fingerprint() -> str:
    """Короткий отпечаток ключа для диагностики (не сам ключ)."""
    raw = _key()
    if raw is None:
        return "none"
    return hashlib.sha256(raw).hexdigest()[:8]
