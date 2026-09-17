"""Entry point rewrite: `python -m rewrite.main`.

Эквивалент запуска основного бота, но сборка графа — composition root
(rewrite.composition.assemble) вместо DI-контейнеров.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import Config
from app.db.database import Database
from rewrite.composition import assemble


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    config = Config.from_env()
    db = Database(config.db_path)
    await db.connect()
    root = assemble(config=config, db=db)
    try:
        await root.bot.start(config.token)
    finally:
        await root.bot.close()


if __name__ == "__main__":
    asyncio.run(run())
