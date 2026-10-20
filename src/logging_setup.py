"""Loguru configuration. Call ``configure_logging`` once, at startup."""

import inspect
import logging
import sys
from pathlib import Path

from loguru import logger

__all__ = ["LOG_DIR", "configure_logging"]

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan> - <level>{message}</level>"
)


class _InterceptHandler(logging.Handler):
    """Route stdlib logging from aiogram, APScheduler and httpx into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = inspect.currentframe(), 0
        while frame is not None and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def configure_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(sys.stderr, level=level, format=_CONSOLE_FORMAT, diagnose=False)
    LOG_DIR.mkdir(exist_ok=True)
    logger.add(
        LOG_DIR / "bot.log",
        level=level,
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    # httpx logs every request URL at INFO; keep third-party noise out of the bot log.
    for noisy in ("httpx", "httpcore", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
