"""/start, /help and /status."""

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.formatting import MessageFormatter
from src.handlers.utils import safe_delete
from src.services.budget_service import BudgetService

__all__ = ["PROMPT_MESSAGE_KEY", "build_router"]

PROMPT_MESSAGE_KEY = "prompt_message_id"


async def start(message: Message, state: FSMContext, fmt: MessageFormatter) -> None:
    await state.set_state(None)
    data = await state.get_data()
    if message.bot is not None:
        await safe_delete(message.bot, message.chat.id, data.get(PROMPT_MESSAGE_KEY))
    prompt = await message.answer(fmt.texts("start"))
    await state.update_data({PROMPT_MESSAGE_KEY: prompt.message_id})


async def help_command(message: Message, state: FSMContext, fmt: MessageFormatter) -> None:
    await state.set_state(None)
    await message.answer(fmt.texts("help"))


async def status(message: Message, state: FSMContext, budget: BudgetService, fmt: MessageFormatter) -> None:
    await state.set_state(None)
    await message.answer(fmt.status(await budget.snapshot()))


def build_router() -> Router:
    router = Router(name="common")
    router.message.register(start, CommandStart())
    router.message.register(help_command, Command("help"))
    router.message.register(status, Command("status"))
    return router
