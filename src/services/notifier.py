"""Send one message to several chats without letting one failure stop the rest."""

import asyncio
from collections.abc import Iterable

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from loguru import logger

__all__ = ["Notifier"]


class Notifier:
    def __init__(self, bot: Bot, members: Iterable[int]) -> None:
        self._bot = bot
        self._members = tuple(dict.fromkeys(members))

    async def broadcast(self, text: str, recipients: Iterable[int] | None = None) -> int:
        """Send ``text`` to every recipient (all members by default). Returns the number delivered."""
        targets = tuple(dict.fromkeys(recipients)) if recipients is not None else self._members
        results = await asyncio.gather(*(self._send(chat_id, text) for chat_id in targets))
        return sum(results)

    async def _send(self, chat_id: int, text: str) -> bool:
        try:
            await self._bot.send_message(chat_id, text)
        except TelegramAPIError as e:
            logger.warning("Could not send a message to chat {}: {}", chat_id, type(e).__name__)
            return False
        return True
