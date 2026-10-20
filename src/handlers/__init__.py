"""Telegram handlers. Router order matters: admin state handlers run before plain amount entry."""

from aiogram import Router
from aiogram.types import CallbackQuery

from src.formatting import MessageFormatter
from src.handlers import common, manual_entry, receipts
from src.handlers.admin import build_admin_router

__all__ = ["build_router"]


async def outdated_button(callback: CallbackQuery, fmt: MessageFormatter) -> None:
    """Buttons from old messages (including the v1 bot) that no handler understands anymore."""
    await callback.answer(fmt.texts("button_outdated"))


def build_router(admin_ids: tuple[int, ...]) -> Router:
    root = Router(name="root")
    fallback = Router(name="fallback")
    fallback.callback_query.register(outdated_button)
    root.include_routers(
        build_admin_router(admin_ids),
        common.build_router(),
        receipts.build_router(),
        manual_entry.build_router(),
        fallback,
    )
    return root
