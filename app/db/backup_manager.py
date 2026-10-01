"""Периодические консистентные backup-файлы SQLite."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from app.db.database import Database

logger = logging.getLogger("bot.db.backups")


class DatabaseBackupManager:
    """Создаёт backup при запуске и затем по расписанию.

    Каждый backup получает собственное имя. Это безопаснее, чем перезаписывать
    один файл: при повреждении или ручной ошибке остаётся несколько точек
    восстановления, а retention ограничивает рост диска.
    """

    def __init__(
        self,
        database: Database,
        directory: str | Path,
        interval_hours: float = 24.0,
        retention: int = 7,
    ) -> None:
        self.database = database
        self.directory = Path(directory)
        self.interval_seconds = max(60.0, interval_hours * 3600)
        self.retention = max(1, retention)
        self._task: asyncio.Task[None] | None = None
        self._last_backup: Path | None = None
        self._last_error: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict[str, str | int | float | bool | None]:
        """Безопасный для health endpoint статус планировщика."""
        return {
            "enabled": True,
            "running": self.running,
            "directory": str(self.directory),
            "interval_hours": round(self.interval_seconds / 3600, 2),
            "retention": self.retention,
            "last_backup": str(self._last_backup) if self._last_backup else None,
            "last_error": self._last_error,
        }

    def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.create_task(self._run(), name="sqlite-backups")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        done, _pending = await asyncio.wait({task}, timeout=10.0)
        if not done:
            logger.warning("SQLite backup-таск не завершился за 10с; продолжаем shutdown")

    async def backup_now(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        target = self.directory / f"bot-{timestamp}.db"
        # Секунда может совпасть при ручном вызове и старте; добавляем суффикс.
        if target.exists():
            target = self.directory / f"bot-{timestamp}-{datetime.now(UTC).microsecond:06d}.db"
        try:
            result = await self.database.backup(target)
        finally:
            # Чистим даже после ошибки: осиротевшие temp-файлы иначе копятся.
            self._prune()
        self._last_backup = result
        self._last_error = None
        logger.info("SQLite backup создан: %s", result)
        return result

    async def _run(self) -> None:
        try:
            await self.backup_now()
            while True:
                await asyncio.sleep(self.interval_seconds)
                await self.backup_now()
        except asyncio.CancelledError:
            raise
        except Exception:
            self._last_error = "backup failed; retry scheduled"
            logger.exception("Периодический SQLite backup завершился ошибкой; повтор через интервал")
            # Ошибка единичного backup не должна выключать бота.
            while True:
                await asyncio.sleep(self.interval_seconds)
                try:
                    await self.backup_now()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self._last_error = "backup failed; retry scheduled"
                    logger.exception("Не удалось создать периодический SQLite backup")

    def _prune(self) -> None:
        backups = sorted(
            (path for path in self.directory.glob("bot-*.db") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old_backup in backups[self.retention :]:
            try:
                old_backup.unlink()
            except OSError:
                logger.warning("Не удалось удалить старый SQLite backup: %s", old_backup, exc_info=True)
        self._prune_temp_files()

    def _prune_temp_files(self, max_age_seconds: float = 3600.0) -> None:
        """Удаляет осиротевшие .tmp отменённых backup'ов.

        На Windows unlink временного файла может проиграть гонку с хэндлом
        aiosqlite, и файл остаётся навсегда — glob их не видит, т.к. имя
        начинается с точки.
        """
        now = time.time()
        for temp_file in self.directory.glob(".*.tmp"):
            try:
                if not temp_file.is_file():
                    continue
                if now - temp_file.stat().st_mtime < max_age_seconds:
                    continue
                temp_file.unlink(missing_ok=True)
            except OSError:
                logger.warning("Не удалось удалить временный backup-файл: %s", temp_file, exc_info=True)
