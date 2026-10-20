"""Entry point: ``python -m src``."""

import asyncio
import sys

from aiogram.exceptions import TelegramUnauthorizedError
from loguru import logger

from src.app import run
from src.config import ConfigError, load_settings
from src.db.migrations import MigrationError
from src.logging_setup import configure_logging


def main() -> None:
    configure_logging()
    try:
        settings = load_settings()
    except ConfigError as e:
        logger.critical("{}", e)
        sys.exit(1)
    configure_logging(settings.log_level)

    try:
        asyncio.run(run(settings))
    except MigrationError as e:
        logger.critical("Database migration failed: {}", e)
        sys.exit(1)
    except TelegramUnauthorizedError:
        logger.critical("Telegram rejected TELEGRAM_BOT_TOKEN; check the token from @BotFather")
        sys.exit(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
