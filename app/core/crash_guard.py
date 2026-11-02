"""Диагностика падений: необработанные исключения, жёсткие краши и отпечаток сборки.

Хостинг часто показывает только stdout, поэтому всё, что роняет процесс, пишется
через logging (консоль и файл), а не только в stderr. Отпечаток сборки отличает
реально запущенный код от того, что лежит в репозитории: ``.git`` в образ не попадает.
"""
from __future__ import annotations

import faulthandler
import hashlib
import logging
import os
import sys
import threading
from pathlib import Path
from types import TracebackType
from typing import TextIO

logger = logging.getLogger("bot")

_ROOT = Path(__file__).resolve().parent.parent.parent
_COMMIT_ENV_VARS = ("GIT_COMMIT", "SOURCE_COMMIT", "COMMIT_SHA", "GITHUB_SHA")
_crash_file: TextIO | None = None


def code_fingerprint(root: Path = _ROOT) -> tuple[str, int]:
    """Хеш всех .py в app/ и main.py: меняется при любой правке кода.

    Возвращает (первые 12 символов sha1, число файлов).
    """
    files = sorted((root / "app").rglob("*.py"))
    entry = root / "main.py"
    if entry.exists():
        files.append(entry)
    digest = hashlib.sha1()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        # CRLF и LF дают один отпечаток: репозиторий и образ могут отличаться окончаниями строк.
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:12], len(files)


def build_description(version: str, root: Path = _ROOT) -> str:
    """Строка для лога старта: версия, коммит (если хост его передал) и отпечаток кода."""
    fingerprint, count = code_fingerprint(root)
    commit = next((os.environ[name][:12] for name in _COMMIT_ENV_VARS if os.environ.get(name)), "неизвестен")
    return f"версия {version}, коммит {commit}, отпечаток кода {fingerprint} ({count} файлов)"


def log_startup_banner(version: str) -> None:
    logger.info("Запуск: %s, Python %s", build_description(version), sys.version.split()[0])


def _log_unhandled(
    exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None, where: str
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        return
    logger.critical("Необработанное исключение (%s)", where, exc_info=(exc_type, exc, tb))
    for handler in logging.getLogger().handlers:
        handler.flush()


def _excepthook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
    _log_unhandled(exc_type, exc, tb, "главный поток")
    sys.__excepthook__(exc_type, exc, tb)


def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread else "?"
    _log_unhandled(args.exc_type, args.exc_value or args.exc_type(), args.exc_traceback, f"поток {name}")


def install(log_dir: Path | None = None) -> None:
    """Подключает логирование необработанных исключений и дамп жёстких крашей.

    faulthandler пишет трейсбеки всех потоков при SIGSEGV и подобных (например, из-за
    libopus), когда Python уже не может ничего залогировать. Повторные вызовы безопасны.
    """
    global _crash_file
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    if _crash_file is not None:
        return
    directory = log_dir or (_ROOT / "logs")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _crash_file = open(directory / "crash.log", "a", encoding="utf-8")  # noqa: SIM115 - живёт до конца процесса
        faulthandler.enable(file=_crash_file, all_threads=True)
    except OSError:
        logger.warning("Не удалось открыть crash.log, faulthandler пишет в stderr", exc_info=True)
        faulthandler.enable(all_threads=True)
