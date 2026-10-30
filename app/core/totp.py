"""RFC 6238 TOTP — второй фактор входа в веб-панель.

Стандартные параметры (Google Authenticator / Authy / 1Password):
SHA-1, 30 секунд, 6 цифр. Секрет — base32 без паддинга.

Только stdlib: ``hmac``+``hashlib`` вместо зависимости вида ``pyotp``.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets as _secrets
import struct
import time
from urllib.parse import quote, urlencode

_DIGITS = 6
_PERIOD = 30
#: Окно ±1 шаг: покрывает рассинхрон часов и ввод кода на грани периода.
_WINDOW = 1
_ALGORITHM = "SHA1"


def new_secret() -> str:
    """Случайный base32-секрет для PANEL_TOTP_SECRET (20 байт = 160 бит)."""
    return base64.b32encode(_secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _normalize(secret: str) -> bytes:
    cleaned = "".join(secret.split()).upper().rstrip("=")
    if not cleaned:
        raise ValueError("пустой TOTP-секрет")
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def generate(secret: str, timestamp: float | None = None) -> str:
    """Код на момент ``timestamp`` (по умолчанию — сейчас)."""
    key = _normalize(secret)
    counter = int((time.time() if timestamp is None else timestamp) // _PERIOD)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % (10 ** _DIGITS):0{_DIGITS}d}"


def verify(secret: str, code: str, *, timestamp: float | None = None, window: int = _WINDOW) -> bool:
    """True, если ``code`` совпал с текущим или соседним шагом.

    Сравнение через ``hmac.compare_digest`` — без раннего выхода по совпадению.
    Некорректный секрет/код — это False, а не исключение: опечатка в
    PANEL_TOTP_SECRET не должна ронять логин с traceback.
    """
    if not secret or not code:
        return False
    compact = "".join(code.split())
    if len(compact) != _DIGITS or not compact.isdigit():
        return False
    try:
        _normalize(secret)
    except Exception:
        return False
    now = time.time() if timestamp is None else timestamp
    matched = False
    for step in range(-window, window + 1):
        if hmac.compare_digest(generate(secret, now + step * _PERIOD), compact):
            matched = True  # не break: сравниваем все шаги окна
    return matched


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    """otpauth://-ссылка для QR в Authenticator (enroll-флоу)."""
    label = quote(f"{issuer}:{account}", safe="")
    query = urlencode(
        {
            "secret": "".join(secret.split()).upper(),
            "issuer": issuer,
            "algorithm": _ALGORITHM,
            "digits": str(_DIGITS),
            "period": str(_PERIOD),
        }
    )
    return f"otpauth://totp/{label}?{query}"
