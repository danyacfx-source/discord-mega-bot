"""Персистентные нарушения сканирования веб-панели (переживают рестарт).

Счётчик нарушений по IP никогда не сбрасывается: эскалация бана опирается на всю историю,
а бан с ``banned_until = inf`` — постоянный и хранится до ручной очистки.
"""
from __future__ import annotations

from app.db.base_repository import BaseRepository


class PanelScanRepository(BaseRepository):
    """Нарушители сканирования по IP."""

    async def save(self, ip: str, offenses: int, banned_until: float, location: str = "") -> None:
        # Пустая локация не затирает ранее известную.
        await self.db.execute(
            """
            INSERT INTO panel_scan_offenses(ip, offenses, banned_until, location)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(ip) DO UPDATE SET
                offenses = excluded.offenses,
                banned_until = excluded.banned_until,
                location = CASE WHEN excluded.location = '' THEN panel_scan_offenses.location
                                ELSE excluded.location END
            """,
            (ip, offenses, banned_until, location),
        )

    async def load_all(self) -> list[tuple[str, int, float, str]]:
        rows = await self.db.fetchall("SELECT ip, offenses, banned_until, location FROM panel_scan_offenses")
        return [
            (str(row["ip"]), int(row["offenses"]), float(row["banned_until"]), str(row["location"] or ""))
            for row in rows
        ]
