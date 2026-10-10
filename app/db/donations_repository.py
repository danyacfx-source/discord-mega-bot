"""Репозиторий обработанных донатов DonationAlerts (предотвращает повторную выдачу)."""
from __future__ import annotations

from typing import Any

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

    async def top_donors(self, limit: int = 10) -> list[dict[str, Any]]:
        """Топ доноров по сумме (для публичной витрины)."""
        rows = await self.db.fetchall(
            "SELECT user_name, SUM(amount) AS total, currency FROM donations "
            "GROUP BY user_name, currency ORDER BY total DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "name": str(row["user_name"] or "Аноним")[:50],
                "total": round(float(row["total"] or 0), 2),
                "currency": str(row["currency"] or "")[:8],
            }
            for row in rows
        ]

    async def get_history(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        """История донатов (новые первыми)."""
        rows = await self.db.fetchall(
            "SELECT da_id, user_name, amount, currency, message, vip, created_at "
            "FROM donations ORDER BY created_at DESC, da_id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [
            {
                "da_id": int(row["da_id"]),
                "user_name": str(row["user_name"] or "Аноним")[:50],
                "amount": float(row["amount"] or 0),
                "currency": str(row["currency"] or "")[:8],
                "message": str(row["message"] or "")[:500],
                "vip": bool(row["vip"]),
                "created_at": str(row["created_at"] or ""),
            }
            for row in rows
        ]

    async def get_stats(self) -> dict[str, Any]:
        """Суммарная статистика донатов."""
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS cnt, SUM(amount) AS total, MAX(created_at) AS last_at "
            "FROM donations WHERE currency = 'RUB'"
        )
        row_all = await self.db.fetchone("SELECT COUNT(*) AS cnt FROM donations")
        return {
            "total_rub": round(float(row["total"] or 0), 2) if row else 0,
            "count_rub": int(row["cnt"] or 0) if row else 0,
            "count_all": int(row_all["cnt"] or 0) if row_all else 0,
            "last_at": str(row["last_at"] or "") if row else "",
        }
