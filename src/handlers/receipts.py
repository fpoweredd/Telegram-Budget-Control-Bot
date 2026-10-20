"""Receipt photos: recognize, preview, then Add / Retry / Cancel."""

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from loguru import logger

from src.domain.models import Receipt, TransactionType
from src.formatting import MessageFormatter
from src.handlers.utils import author_of, download_photo, safe_delete
from src.keyboards import ReceiptAction, ReceiptCallback, receipt_keyboard
from src.services.budget_service import BudgetService
from src.services.notifier import Notifier
from src.services.receipt_service import (
    ReceiptAlreadyHandledError,
    ReceiptNotFoundError,
    ReceiptService,
    ReceiptTotalMissingError,
)

__all__ = ["build_router"]


async def receipt_photo(message: Message, bot: Bot, receipts: ReceiptService, fmt: MessageFormatter) -> None:
    if not message.photo or message.from_user is None:
        return
    photo = message.photo[-1]  # largest size
    progress = await message.answer(fmt.texts("receipt_reading"))
    try:
        image = await download_photo(bot, photo.file_id)
    except TelegramAPIError:
        logger.exception("Could not download a receipt photo")
        await safe_delete(bot, message.chat.id, progress.message_id)
        await message.answer(fmt.texts("receipt_download_failed"))
        return

    receipt = await receipts.register(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        photo_file_id=photo.file_id,
        photo_message_id=message.message_id,
        image=image,
    )
    await safe_delete(bot, message.chat.id, progress.message_id)
    await message.answer(fmt.receipt_preview(receipt), reply_markup=receipt_keyboard(fmt.texts, receipt))


async def add_receipt(
    callback: CallbackQuery,
    callback_data: ReceiptCallback,
    bot: Bot,
    receipts: ReceiptService,
    budget: BudgetService,
    notifier: Notifier,
    fmt: MessageFormatter,
) -> None:
    author = author_of(callback.from_user)
    try:
        receipt = await receipts.add_as_expense(callback_data.receipt_id, author)
    except (ReceiptNotFoundError, ReceiptAlreadyHandledError, ReceiptTotalMissingError) as e:
        await _answer_error(callback, fmt, e)
        return

    await callback.answer()
    await _clean_up(bot, receipt, callback)
    total = receipt.parsed.total_cents or 0
    snapshot = await budget.snapshot()
    await notifier.broadcast(fmt.transaction(TransactionType.EXPENSE, total, snapshot, author, receipt))


async def retry_receipt(
    callback: CallbackQuery,
    callback_data: ReceiptCallback,
    bot: Bot,
    receipts: ReceiptService,
    fmt: MessageFormatter,
) -> None:
    user_id = callback.from_user.id
    try:
        pending = await receipts.get_pending(callback_data.receipt_id, user_id)
    except (ReceiptNotFoundError, ReceiptAlreadyHandledError) as e:
        await _answer_error(callback, fmt, e)
        return
    if pending.photo_file_id is None:
        await callback.answer(fmt.texts("receipt_not_found"), show_alert=True)
        return

    await callback.answer(fmt.texts("receipt_retrying"))
    try:
        image = await download_photo(bot, pending.photo_file_id)
    except TelegramAPIError:
        logger.exception("Could not download receipt {} again", pending.receipt_id)
        if callback.message is not None:
            await callback.message.answer(fmt.texts("receipt_download_failed"))
        return

    receipt = await receipts.reprocess(pending.receipt_id, user_id, image)
    if callback.message is None:
        return
    try:
        await bot.edit_message_text(
            fmt.receipt_preview(receipt),
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            reply_markup=receipt_keyboard(fmt.texts, receipt),
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
        await callback.message.answer(fmt.texts("receipt_unchanged"))


async def cancel_receipt(
    callback: CallbackQuery,
    callback_data: ReceiptCallback,
    bot: Bot,
    receipts: ReceiptService,
    fmt: MessageFormatter,
) -> None:
    try:
        receipt = await receipts.cancel(callback_data.receipt_id, callback.from_user.id)
    except (ReceiptNotFoundError, ReceiptAlreadyHandledError) as e:
        await _answer_error(callback, fmt, e)
        return
    await callback.answer(fmt.texts("receipt_cancelled"))
    await _clean_up(bot, receipt, callback)


async def _clean_up(bot: Bot, receipt: Receipt, callback: CallbackQuery) -> None:
    """Remove the preview and the photo so only the shared summary stays in the chat."""
    if callback.message is not None:
        await safe_delete(bot, callback.message.chat.id, callback.message.message_id)
    await safe_delete(bot, receipt.chat_id, receipt.photo_message_id)


async def _answer_error(callback: CallbackQuery, fmt: MessageFormatter, error: Exception) -> None:
    key = {
        ReceiptAlreadyHandledError: "receipt_already_handled",
        ReceiptTotalMissingError: "receipt_no_total",
    }.get(type(error), "receipt_not_found")
    logger.info("Receipt action rejected: {}", error)
    await callback.answer(fmt.texts(key), show_alert=True)


def build_router() -> Router:
    router = Router(name="receipts")
    router.message.register(receipt_photo, F.photo)
    router.callback_query.register(add_receipt, ReceiptCallback.filter(F.action == ReceiptAction.ADD))
    router.callback_query.register(retry_receipt, ReceiptCallback.filter(F.action == ReceiptAction.RETRY))
    router.callback_query.register(cancel_receipt, ReceiptCallback.filter(F.action == ReceiptAction.CANCEL))
    return router
