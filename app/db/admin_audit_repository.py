"""Аудит действий веб-панели: кто, когда и что трогал через админку."""
from __future__ import annotations

from typing import Any

from app.db.base_repository import BaseRepository


class AdminAuditRepository(BaseRepository):
    async def record(
        self,
        actor_role: str,
        action: str,
        method: str,
        path: str,
        remote: str = "",
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO admin_audit(actor_role, action, method, path, remote, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (actor_role, action[:200], method[:16], path[:500], remote[:120]),
        )

    async def list_recent(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = await self.db.fetchall(
            """
            SELECT id, actor_role, action, method, path, remote, created_at
            FROM admin_audit
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 1000)),),
        )
        return [dict(row) for row in rows]
