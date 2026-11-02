"""Общие фикстуры: фабрика MegaBot с config-оверрайдами для panel-тестов."""
from __future__ import annotations

import asyncio
import itertools
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from app.config import Config
from app.core import crypto
from app.core.bot import MegaBot
from app.db.database import Database

_TEMPLATE_DB = "megabot_template"
_db_counter = itertools.count(1)


def _with_database(url: str, name: str) -> str:
    """Тот же сервер, другая база: подменяет путь DSN."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))


async def _admin_exec(url: str, *statements: str) -> None:
    connection = await asyncpg.connect(url)
    try:
        for statement in statements:
            await connection.execute(statement)
    finally:
        await connection.close()


async def _build_template(admin_url: str) -> None:
    """Создаёт шаблонную БД с применённой схемой: CREATE DATABASE ... TEMPLATE дёшев."""
    await _admin_exec(admin_url, f'DROP DATABASE IF EXISTS "{_TEMPLATE_DB}" WITH (FORCE)', f'CREATE DATABASE "{_TEMPLATE_DB}"')
    database = Database(_with_database(admin_url, _TEMPLATE_DB))
    await database.connect()
    await database.close()


@pytest.fixture(scope="session")
def _pg_admin_url(tmp_path_factory):
    """Один PostgreSQL на сессию: TEST_DATABASE_URL либо встроенный pgserver."""
    external = os.getenv("TEST_DATABASE_URL", "").strip()
    if external:
        admin_url = external
    else:
        import pgserver

        server = pgserver.get_server(tmp_path_factory.mktemp("pgdata"))
        admin_url = server.get_uri()
    asyncio.run(_build_template(admin_url))
    yield admin_url


@pytest.fixture
def pg_url(_pg_admin_url):
    """DSN свежей изолированной БД (копия шаблона со схемой); удаляется после теста."""
    name = f"t_{os.getpid()}_{next(_db_counter)}"
    asyncio.run(_admin_exec(_pg_admin_url, f'CREATE DATABASE "{name}" TEMPLATE "{_TEMPLATE_DB}"'))
    try:
        yield _with_database(_pg_admin_url, name)
    finally:
        asyncio.run(_admin_exec(_pg_admin_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture(autouse=True)
def _pg_dump_on_path(monkeypatch):
    """pg_dump из комплекта pgserver, если системного нет в PATH (backup-тесты)."""
    if shutil.which("pg_dump"):
        return
    try:
        import pgserver
    except ImportError:
        return
    bin_dir = Path(pgserver.__file__).parent / "pginstall" / "bin"
    if bin_dir.is_dir():
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


@pytest.fixture(autouse=True)
def _default_database_url(monkeypatch):
    """Config.from_env требует DATABASE_URL: по умолчанию подставляем заглушку (без подключения)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")


@pytest.fixture
def at_rest_key(tmp_path, monkeypatch):
    """Изолирует ключ шифрования at-rest в tmp_path.

    Без этого тесты создавали бы ``data/.panel-key`` в репозитории и опирались
    на ключ, доставшийся от соседнего теста.
    """
    monkeypatch.delenv("PANEL_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("PANEL_KEY_FILE", str(tmp_path / ".panel-key"))
    crypto._reset_for_tests()
    yield tmp_path / ".panel-key"
    crypto._reset_for_tests()


@pytest.fixture
def make_panel_bot(tmp_path, at_rest_key, pg_url):
    """Бот с тестовой конфигурацией; kwargs переопределяют поля Config."""

    def _make(**kwargs) -> MegaBot:
        value = {"panel_port": 17890, **kwargs}
        config = Config(
            token="x",
            prefix="!",
            data_dir=str(tmp_path),
            database_url=pg_url,
            log_level="ERROR",
            status_activity="s",
            owner_id=None,
            **value,
        )
        return MegaBot(config)

    return _make
