"""Domain data structures shared by services, handlers and formatting."""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from src.domain.categories import Category

__all__ = [
    "Author",
    "BudgetSnapshot",
    "ExpenseLine",
    "ParsedReceipt",
    "Receipt",
    "ReceiptItem",
    "ReceiptStatus",
    "TransactionType",
    "WeeklyReport",
]


class TransactionType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


class ReceiptStatus(StrEnum):
    PENDING = "pending"
    ADDED = "added"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Author:
    """The Telegram user who created a transaction."""

    user_id: int
    username: str | None
    first_name: str | None


@dataclass(frozen=True, slots=True)
class ReceiptItem:
    name: str
    unit_price_cents: int
    quantity: Decimal
    category: Category

    @property
    def line_total_cents(self) -> int:
        line = Decimal(self.unit_price_cents) * self.quantity
        return int(line.quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass(frozen=True, slots=True)
class ExpenseLine:
    """One expense, or one item of a receipt expense, for the category breakdown.

    Manual expenses have no receipt and no category.
    """

    receipt_id: int | None
    amount_cents: int
    category: Category | None = None
    line_total_cents: int = 0


@dataclass(frozen=True, slots=True)
class ParsedReceipt:
    """What the recognizer read from a receipt photo. Any field may be missing."""

    store: str | None
    purchase_date: date | None
    total_cents: int | None
    items: tuple[ReceiptItem, ...] = ()

    @property
    def is_empty(self) -> bool:
        return self.store is None and self.total_cents is None and not self.items


@dataclass(frozen=True, slots=True)
class Receipt:
    receipt_id: int
    user_id: int
    chat_id: int
    status: ReceiptStatus
    photo_file_id: str | None
    photo_message_id: int | None
    parsed: ParsedReceipt = field(default_factory=lambda: ParsedReceipt(None, None, None))

    @property
    def can_be_added(self) -> bool:
        total = self.parsed.total_cents
        return self.status is ReceiptStatus.PENDING and total is not None and total > 0


@dataclass(frozen=True, slots=True)
class BudgetSnapshot:
    """Budget state for one day, used by /status and transaction messages."""

    today: date
    target_date: date
    days_left: int
    balance_cents: int
    income_today_cents: int
    expense_today_cents: int
    daily_limit_cents: int
    weekly_limit_cents: int

    @property
    def target_passed(self) -> bool:
        return self.days_left <= 0


@dataclass(frozen=True, slots=True)
class WeeklyReport:
    snapshot: BudgetSnapshot
    week_start: date
    week_expense_cents: int
    by_category: tuple[tuple[Category, int], ...]
