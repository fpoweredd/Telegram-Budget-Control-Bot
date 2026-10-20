"""Access control: the bot only talks to configured members."""

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message, TelegramObject
from loguru import logger

__all__ = ["AdminFilter", "MembersOnlyMiddleware"]


class MembersOnlyMiddleware(BaseMiddleware):
    """Drop messages and button presses from anyone who is not in ADMIN_IDS or USER_IDS."""

    def __init__(self, member_ids: Iterable[int]) -> None:
        self._members = frozenset(member_ids)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user if isinstance(event, Message | CallbackQuery) else None
        if user is None or user.id not in self._members:
            logger.info("Ignored an update from non-member {}", user.id if user else "unknown")
            if isinstance(event, CallbackQuery):
                await event.answer()
            return None
        return await handler(event, data)


class AdminFilter(Filter):
    def __init__(self, admin_ids: Iterable[int]) -> None:
        self._admins = frozenset(admin_ids)

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return event.from_user is not None and event.from_user.id in self._admins
