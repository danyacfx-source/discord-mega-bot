"""Точка входа в приложение."""
from __future__ import annotations

import logging
import os
import sys
import tracemalloc

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

if os.getenv("RAM_REPORT_TRACEMALLOC", "1").strip().lower() not in ("0", "false", "no", "off"):
    tracemalloc.start()

from app.config import Config  # noqa: E402
from app.core.bot import MegaBot  # noqa: E402
from app.core.logger import setup_logging  # noqa: E402
from app.core.secrets import fix_env_permissions, load_file_secrets  # noqa: E402

logger = logging.getLogger("bot")


def main() -> None:
    # Docker/Kubernetes secrets: BOT_TOKEN_FILE=/run/secrets/bot_token → BOT_TOKEN.
    # До Config.from_env, иначе токен из файла не подхватится.
    secret_warnings = load_file_secrets()
    config = Config.from_env()
    setup_logging(config.log_level)
    for warning in secret_warnings:
        logger.error("Secrets: %s", warning)
    for warning in fix_env_permissions():
        logger.warning("Secrets: %s", warning)

    bot = MegaBot(config)
    try:
        bot.run(config.token)
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    finally:
        logger.info("Завершение работы")


if __name__ == "__main__":
    main()
