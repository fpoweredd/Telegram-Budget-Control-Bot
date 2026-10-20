"""Manual entry: a member types an amount, then picks income or expense."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.domain.money import InvalidAmountError, parse_amount
from src.formatting import MessageFormatter
from src.handlers.common import PROMPT_MESSAGE_KEY
from src.handlers.utils import OnceGuard, author_of, safe_delete
from src.keyboards import EntryCallback, entry_keyboard
from src.services.budget_service import BudgetService
from src.services.notifier import Notifier

__all__ = ["build_router"]


async def amount_entered(message: Message, state: FSMContext, fmt: MessageFormatter) -> None:
    try:
        cents = parse_amount(message.text or "")
    except InvalidAmountError:
        await message.answer(fmt.texts("invalid_amount"))
        return

    if message.bot is not None:
        data = await state.get_data()
        await safe_delete(message.bot, message.chat.id, data.get(PROMPT_MESSAGE_KEY))
        await safe_delete(message.bot, message.chat.id, message.message_id)
    await state.update_data({PROMPT_MESSAGE_KEY: None})
    await message.answer(fmt.amount_question(cents), reply_markup=entry_keyboard(fmt.texts, cents))


async def entry_chosen(
    callback: CallbackQuery,
    callback_data: EntryCallback,
    budget: BudgetService,
    notifier: Notifier,
    fmt: MessageFormatter,
    entry_guard: OnceGuard,
) -> None:
    question = callback.message
    if question is None or not entry_guard.claim(question.chat.id, question.message_id):
        await callback.answer()
        return

    author = author_of(callback.from_user)
    snapshot = await budget.add_manual(author, callback_data.kind, callback_data.cents)
    await callback.answer()
    if callback.bot is not None:
        await safe_delete(callback.bot, question.chat.id, question.message_id)
    await notifier.broadcast(fmt.transaction(callback_data.kind, callback_data.cents, snapshot, author))


def build_router() -> Router:
    router = Router(name="manual_entry")
    router.message.register(amount_entered, F.text, ~F.text.startswith("/"))
    router.callback_query.register(entry_chosen, EntryCallback.filter())
    return router
