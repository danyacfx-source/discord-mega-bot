"""Репозиторий обработанных донатов DonationAlerts (предотвращает повторную выдачу)."""
from __future__ import annotations

from app.db.base_repository import BaseRepository


class DonationsRepository(BaseRepository):
    async def is_known(self, da_id: int) -> bool:
        row = await self.db.fetchone("SELECT 1 FROM donations WHERE da_id = ?", (da_id,))
        return row is not None

    async def record(
        self,
        da_id: int,
        user_name: str,
        amount: float,
        currency: str,
        message: str,
        vip: bool,
    ) -> bool:
        cursor = await self.db.execute(
            "INSERT OR IGNORE INTO donations (da_id, user_name, amount, currency, message, vip, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (da_id, user_name, amount, currency, message, int(vip)),
        )
        return cursor.rowcount > 0
