"""Персистентный счётчик неудачных логинов веб-панели (переживает рестарт).

In-memory ``_login_attempts`` в auth.py сбрасывается при рестарте процесса —
брутфорс обходился перезапуском контейнера. Эта таблица — durable-слой:
пока ключ заблокирован в БД, рестарт ему не помогает.
"""
from __future__ import annotations

from app.db.base_repository import BaseRepository


class PanelLoginLockRepository(BaseRepository):
    """Блокировки входа по ключу (обычно — реальный клиентский IP)."""

    async def locked_until(self, key: str, now: float) -> float:
        """Момент разблокировки; 0 — блокировки нет или она истекла."""
        row = await self.db.fetchone(
            "SELECT locked_until FROM panel_login_attempts WHERE key = ?",
            (key,),
        )
        if not row:
            return 0.0
        locked_until = float(row["locked_until"])
        return locked_until if locked_until > now else 0.0

    async def record_failure(
        self,
        key: str,
        now: float,
        *,
        limit: int,
        window: float,
        lock_seconds: float,
    ) -> float:
        """Чинит неудачу и возвращает момент разблокировки (0 — ещё не лочим).

        Окно ``window`` считается от первой неудачи цикла. При достижении
        ``limit`` ключ лочится на ``lock_seconds``, а счётчик цикла сбрасывается —
        после истечения блокировки брутфорсер получает свежую квоту, и цикл
        повторяется.
        """
        row = await self.db.fetchone(
            "SELECT first_failure_at, failures, locked_until FROM panel_login_attempts WHERE key = ?",
            (key,),
        )
        if row is None or now - float(row["first_failure_at"]) > window:
            first_failure_at, failures = now, 1
        else:
            first_failure_at = float(row["first_failure_at"])
            failures = int(row["failures"]) + 1

        locked_until = 0.0
        if failures >= max(1, limit):
            locked_until = now + lock_seconds
            # Счётчик цикла чист: после разблокировки квота начинается заново.
            first_failure_at, failures = now, 0

        await self.db.execute(
            """
            INSERT INTO panel_login_attempts(key, first_failure_at, failures, locked_until)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                first_failure_at = excluded.first_failure_at,
                failures = excluded.failures,
                locked_until = excluded.locked_until
            """,
            (key, first_failure_at, failures, locked_until),
        )
        return locked_until

    async def clear(self, key: str) -> None:
        """Успех входа сбрасывает блокировку и счётчик."""
        await self.db.execute("DELETE FROM panel_login_attempts WHERE key = ?", (key,))

    async def prune(self, now: float, window: float) -> int:
        """Удаляет протухшие записи — сканер не должен раздувать таблицу."""
        cursor = await self.db.execute(
            "DELETE FROM panel_login_attempts WHERE locked_until < ? AND first_failure_at < ?",
            (now, now - window),
        )
        return int(cursor.rowcount or 0)
