"""Admin commands: /date sets the target date, /restore resets data after confirmation."""

from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from src.formatting import DATE_INPUT_FORMAT, MessageFormatter
from src.handlers.utils import OnceGuard
from src.keyboards import ResetCallback, reset_keyboard
from src.middlewares import AdminFilter
from src.services.budget_service import BudgetService, TargetDateInPastError
from src.services.notifier import Notifier

__all__ = ["AdminStates", "build_admin_router"]


class AdminStates(StatesGroup):
    waiting_for_target_date = State()


async def ask_target_date(message: Message, state: FSMContext, budget: BudgetService, fmt: MessageFormatter) -> None:
    await state.set_state(AdminStates.waiting_for_target_date)
    await message.answer(fmt.date_prompt(await budget.snapshot()))


async def target_date_entered(
    message: Message, state: FSMContext, budget: BudgetService, notifier: Notifier, fmt: MessageFormatter
) -> None:
    example = budget.today().replace(day=1).strftime(DATE_INPUT_FORMAT)
    try:
        target = datetime.strptime((message.text or "").strip(), DATE_INPUT_FORMAT).date()
    except ValueError:
        await message.answer(fmt.texts("date_invalid", example=example))
        return
    try:
        snapshot = await budget.set_target_date(target)
    except TargetDateInPastError:
        await message.answer(fmt.texts("date_in_past"))
        return
    await state.set_state(None)
    await notifier.broadcast(fmt.date_set(snapshot))


async def ask_reset(message: Message, state: FSMContext, fmt: MessageFormatter) -> None:
    await state.set_state(None)
    await message.answer(fmt.texts("reset_confirm"), reply_markup=reset_keyboard(fmt.texts))


async def reset_chosen(
    callback: CallbackQuery,
    callback_data: ResetCallback,
    bot: Bot,
    budget: BudgetService,
    fmt: MessageFormatter,
    entry_guard: OnceGuard,
) -> None:
    question = callback.message
    if question is None or not entry_guard.claim(question.chat.id, question.message_id):
        await callback.answer()
        return

    await callback.answer()
    if not callback_data.confirm:
        await bot.edit_message_text(
            fmt.texts("reset_cancelled"), chat_id=question.chat.id, message_id=question.message_id
        )
        return
    target = await budget.reset()
    await bot.edit_message_text(
        fmt.texts("reset_done", target=fmt.texts.long_date(target)),
        chat_id=question.chat.id,
        message_id=question.message_id,
    )


def build_admin_router(admin_ids: tuple[int, ...]) -> Router:
    router = Router(name="admin")
    is_admin = AdminFilter(admin_ids)
    router.message.filter(is_admin)
    router.callback_query.filter(is_admin)

    router.message.register(ask_target_date, Command("date"))
    router.message.register(target_date_entered, AdminStates.waiting_for_target_date, F.text, ~F.text.startswith("/"))
    router.message.register(ask_reset, Command("restore"))
    router.callback_query.register(reset_chosen, ResetCallback.filter())
    return router
