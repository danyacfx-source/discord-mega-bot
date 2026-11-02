"""Персистентные сессии веб-панели: переживают рестарт процесса.

В БД хранится SHA-256 ключ сессии (не сам bearer-токен), роль, CSRF-токен и срок жизни.
"""
from __future__ import annotations

from app.db.base_repository import BaseRepository


class PanelSessionRepository(BaseRepository):
    """Сессии панели по ключу токена."""

    async def save(self, key: str, role: str, csrf: str, expires: float) -> None:
        await self.db.execute(
            """
            INSERT INTO panel_sessions(token_key, role, csrf, expires)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(token_key) DO UPDATE SET
                role = excluded.role,
                csrf = excluded.csrf,
                expires = excluded.expires
            """,
            (key, role, csrf, expires),
        )

    async def delete(self, key: str) -> None:
        await self.db.execute("DELETE FROM panel_sessions WHERE token_key = ?", (key,))

    async def load_active(self, now: float) -> list[tuple[str, str, str, float]]:
        rows = await self.db.fetchall(
            "SELECT token_key, role, csrf, expires FROM panel_sessions WHERE expires > ?",
            (now,),
        )
        return [
            (str(row["token_key"]), str(row["role"]), str(row["csrf"]), float(row["expires"]))
            for row in rows
        ]

    async def prune(self, now: float) -> int:
        """Удаляет протухшие сессии — таблица не должна расти бесконечно."""
        cursor = await self.db.execute("DELETE FROM panel_sessions WHERE expires <= ?", (now,))
        return int(cursor.rowcount or 0)
