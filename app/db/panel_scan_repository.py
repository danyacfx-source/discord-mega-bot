"""Персистентные нарушения сканирования веб-панели (переживают рестарт).

Счётчик нарушений по IP никогда не сбрасывается: эскалация бана опирается на всю историю,
а бан с ``banned_until = inf`` — постоянный и хранится до ручной очистки.
"""
from __future__ import annotations

from app.db.base_repository import BaseRepository


class PanelScanRepository(BaseRepository):
    """Нарушители сканирования по IP."""

    async def save(self, ip: str, offenses: int, banned_until: float) -> None:
        await self.db.execute(
            """
            INSERT INTO panel_scan_offenses(ip, offenses, banned_until)
            VALUES (?, ?, ?)
            ON CONFLICT(ip) DO UPDATE SET
                offenses = excluded.offenses,
                banned_until = excluded.banned_until
            """,
            (ip, offenses, banned_until),
        )

    async def load_all(self) -> list[tuple[str, int, float]]:
        rows = await self.db.fetchall("SELECT ip, offenses, banned_until FROM panel_scan_offenses")
        return [(str(row["ip"]), int(row["offenses"]), float(row["banned_until"])) for row in rows]
