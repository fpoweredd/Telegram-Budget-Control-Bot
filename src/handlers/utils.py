"""Small helpers shared by handlers."""

from collections import OrderedDict
from io import BytesIO

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import User
from loguru import logger

from src.domain.models import Author

__all__ = ["OnceGuard", "author_of", "download_photo", "safe_delete"]


def author_of(user: User) -> Author:
    return Author(user_id=user.id, username=user.username, first_name=user.first_name)


async def safe_delete(bot: Bot, chat_id: int, message_id: int | None) -> None:
    """Delete a message to keep the chat clean; it is fine if it is already gone."""
    if message_id is None:
        return
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramAPIError as e:
        logger.debug("Could not delete message {} in chat {}: {}", message_id, chat_id, type(e).__name__)


async def download_photo(bot: Bot, file_id: str) -> bytes:
    """Raises TelegramAPIError if the file cannot be fetched."""
    buffer = BytesIO()
    await bot.download(file_id, destination=buffer)
    return buffer.getvalue()


class OnceGuard:
    """Remembers recently used keys so a double tap on a button is handled only once."""

    def __init__(self, capacity: int = 1000) -> None:
        self._seen: OrderedDict[tuple[int, int], None] = OrderedDict()
        self._capacity = capacity

    def claim(self, chat_id: int, message_id: int) -> bool:
        """True the first time a key is seen. Synchronous, so it is atomic under asyncio."""
        key = (chat_id, message_id)
        if key in self._seen:
            return False
        self._seen[key] = None
        if len(self._seen) > self._capacity:
            self._seen.popitem(last=False)
        return True
