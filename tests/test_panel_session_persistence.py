"""Сессии веб-панели переживают рестарт: лежат в БД по хэшу токена."""

from app.core.webpanel.payload import _token_key
from app.db.database import Database
from app.db.panel_session_repository import PanelSessionRepository


async def test_panel_sessions_survive_restart_and_expired_are_pruned(pg_url) -> None:
    db = Database(pg_url)
    await db.connect()
    repo = PanelSessionRepository(db)
    await repo.save(_token_key("live-token"), "owner", "csrf-live", 2_000_000_000.0)
    await repo.save(_token_key("dead-token"), "admin", "csrf-dead", 1.0)
    await db.close()

    restored = Database(pg_url)
    await restored.connect()
    repo = PanelSessionRepository(restored)
    rows = await repo.load_active(1_000.0)
    assert rows == [(_token_key("live-token"), "owner", "csrf-live", 2_000_000_000.0)]
    assert await repo.prune(1_000.0) == 1
    await repo.delete(_token_key("live-token"))
    assert await repo.load_active(1_000.0) == []
    await restored.close()


def test_token_key_never_equals_raw_token() -> None:
    assert _token_key("secret-token") != "secret-token"
    assert len(_token_key("secret-token")) == 64
