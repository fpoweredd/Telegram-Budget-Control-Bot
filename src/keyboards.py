"""Inline keyboards and their typed callback data."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.domain.models import Receipt, TransactionType
from src.texts import Texts

__all__ = [
    "EntryCallback",
    "ReceiptAction",
    "ReceiptCallback",
    "ResetCallback",
    "entry_keyboard",
    "receipt_keyboard",
    "reset_keyboard",
]


class ReceiptAction(StrEnum):
    ADD = "add"
    RETRY = "retry"
    CANCEL = "cancel"


class EntryCallback(CallbackData, prefix="entry"):
    kind: TransactionType
    cents: int


class ReceiptCallback(CallbackData, prefix="receipt"):
    action: ReceiptAction
    receipt_id: int


class ResetCallback(CallbackData, prefix="reset"):
    confirm: bool


def _button(text: str, data: CallbackData) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data.pack())


def entry_keyboard(texts: Texts, cents: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(texts("button_income"), EntryCallback(kind=TransactionType.INCOME, cents=cents)),
                _button(texts("button_expense"), EntryCallback(kind=TransactionType.EXPENSE, cents=cents)),
            ]
        ]
    )


def receipt_keyboard(texts: Texts, receipt: Receipt) -> InlineKeyboardMarkup:
    def action(name: ReceiptAction) -> ReceiptCallback:
        return ReceiptCallback(action=name, receipt_id=receipt.receipt_id)

    rows = []
    if receipt.can_be_added:
        rows.append([_button(texts("button_receipt_add"), action(ReceiptAction.ADD))])
    rows.append(
        [
            _button(texts("button_receipt_retry"), action(ReceiptAction.RETRY)),
            _button(texts("button_receipt_cancel"), action(ReceiptAction.CANCEL)),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reset_keyboard(texts: Texts) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button(texts("button_reset_confirm"), ResetCallback(confirm=True)),
                _button(texts("button_reset_cancel"), ResetCallback(confirm=False)),
            ]
        ]
    )
