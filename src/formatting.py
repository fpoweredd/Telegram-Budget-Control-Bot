"""Builds every bot message. Pure functions of domain data, so they are easy to test."""

from collections.abc import Iterable
from decimal import Decimal
from html import escape

from src.domain.categories import CATEGORY_EMOJI, Category
from src.domain.models import Author, BudgetSnapshot, Receipt, ReceiptItem, TransactionType, WeeklyReport
from src.domain.money import div_round, format_cents
from src.services.budget_math import category_shares
from src.texts import Texts

__all__ = ["MessageFormatter", "display_name"]

MAX_PREVIEW_ITEMS = 25
MAX_PREVIEW_NAME = 40
DATE_INPUT_FORMAT = "%d.%m.%Y"


def display_name(author: Author) -> str:
    """``@username``, else the first name, else the numeric id. HTML-escaped."""
    if author.username:
        return f"@{escape(author.username, quote=False)}"
    if author.first_name:
        return escape(author.first_name, quote=False)
    return f"id{author.user_id}"


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _quantity(value: Decimal) -> str:
    return format(value.normalize(), "f")


class MessageFormatter:
    def __init__(self, texts: Texts, currency: str) -> None:
        self._t = texts
        self._currency = currency

    @property
    def texts(self) -> Texts:
        return self._t

    def money(self, cents: int) -> str:
        return f"{format_cents(cents)} {self._currency}"

    def whole_money(self, cents: int) -> str:
        return f"{div_round(cents, 100)} {self._currency}"

    # Manual entry

    def amount_question(self, cents: int) -> str:
        return self._t("amount_question", amount=self.money(cents))

    # Transactions

    def transaction(
        self,
        kind: TransactionType,
        amount_cents: int,
        snapshot: BudgetSnapshot,
        author: Author,
        receipt: Receipt | None = None,
    ) -> str:
        """The message every member gets when someone adds income or an expense."""
        key = "income_line" if kind is TransactionType.INCOME else "expense_line"
        headline = self._t(key, amount=self.money(amount_cents))
        if receipt is not None and receipt.parsed.store:
            headline += f" · {escape(receipt.parsed.store, quote=False)}"
        lines = [headline]

        if receipt is not None:
            shares = category_shares(amount_cents, receipt.parsed.items)
            if shares:
                categories = " · ".join(f"{self._t.category(c)} {pct}%" for c, pct in shares)
                lines.append(self._t("categories_line", categories=categories))
        lines.append(self._today_line(snapshot))
        if kind is TransactionType.INCOME:
            lines.append(self._t("balance_line", balance=self.money(snapshot.balance_cents)))
        lines.append(self._t("author_line", author=display_name(author)))
        return "\n".join(lines)

    def _today_line(self, snapshot: BudgetSnapshot) -> str:
        line = self._t(
            "today_line",
            spent=format_cents(snapshot.expense_today_cents),
            limit=self.money(snapshot.daily_limit_cents),
        )
        return line + " ⚠️" if snapshot.expense_today_cents > snapshot.daily_limit_cents else line

    # Status and reports

    def _days_left_line(self, snapshot: BudgetSnapshot) -> str:
        target = self._t.short_date(snapshot.target_date)
        if snapshot.target_passed:
            return self._t("target_passed_line", target=target)
        return self._t("days_left_line", days=self._t.days(snapshot.days_left), target=target)

    def status(self, snapshot: BudgetSnapshot) -> str:
        return "\n".join(
            [
                self._t("status_title", date=self._t.short_date(snapshot.today)),
                self._days_left_line(snapshot),
                "",
                self._t("income_today_line", amount=self.money(snapshot.income_today_cents)),
                self._t("spent_today_line", amount=self.money(snapshot.expense_today_cents)),
                self._t("balance_line", balance=self.money(snapshot.balance_cents)),
                "",
                self._t("daily_limit_line", amount=self.money(snapshot.daily_limit_cents)),
                self._t("weekly_limit_line", amount=self.money(snapshot.weekly_limit_cents)),
            ]
        )

    def weekly_report(self, report: WeeklyReport) -> str:
        snapshot = report.snapshot
        lines = [
            self._t("report_title", date=self._t.short_date(snapshot.today)),
            self._days_left_line(snapshot),
            self._t(
                "week_spent_line",
                spent=format_cents(report.week_expense_cents),
                limit=self.money(snapshot.weekly_limit_cents),
            ),
        ]
        if report.by_category:
            lines.append(self.category_totals(report.by_category))
        lines.append(self._t("balance_line", balance=self.money(snapshot.balance_cents)))
        return "\n".join(lines)

    def category_totals(self, totals: Iterable[tuple[Category, int]]) -> str:
        return " · ".join(f"{CATEGORY_EMOJI[c]} {self._t.category(c)} {self.whole_money(cents)}" for c, cents in totals)

    # Receipts

    def receipt_preview(self, receipt: Receipt) -> str:
        parsed = receipt.parsed
        if parsed.is_empty:
            return self._t("receipt_failed")

        store = escape(parsed.store, quote=False) if parsed.store else self._t("receipt_unknown_store")
        if parsed.purchase_date:
            lines = [self._t("receipt_title_dated", store=store, date=self._t.long_date(parsed.purchase_date))]
        else:
            lines = [self._t("receipt_title", store=store)]

        if parsed.total_cents is not None:
            lines.append(self._t("receipt_total_line", amount=self.money(parsed.total_cents)))

        if parsed.items:
            lines.append("")
            lines.extend(self._receipt_item(item) for item in parsed.items[:MAX_PREVIEW_ITEMS])
            hidden = len(parsed.items) - MAX_PREVIEW_ITEMS
            if hidden > 0:
                lines.append(self._t("receipt_more_items", count=hidden))

        if not receipt.can_be_added:
            lines.extend(["", self._t("receipt_no_total")])
        return "\n".join(lines)

    def _receipt_item(self, item: ReceiptItem) -> str:
        name = escape(_shorten(item.name, MAX_PREVIEW_NAME), quote=False)
        emoji = CATEGORY_EMOJI[item.category]
        if item.quantity == 1:
            return self._t("receipt_item", emoji=emoji, name=name, amount=self.money(item.line_total_cents))
        return self._t(
            "receipt_item_quantity",
            emoji=emoji,
            name=name,
            quantity=_quantity(item.quantity),
            price=format_cents(item.unit_price_cents),
            amount=self.money(item.line_total_cents),
        )

    # Admin

    def date_prompt(self, snapshot: BudgetSnapshot) -> str:
        return self._t(
            "date_prompt",
            today=snapshot.today.strftime(DATE_INPUT_FORMAT),
            target=snapshot.target_date.strftime(DATE_INPUT_FORMAT),
        )

    def date_set(self, snapshot: BudgetSnapshot) -> str:
        return self._t(
            "date_set",
            target=self._t.long_date(snapshot.target_date),
            days=self._t.days(snapshot.days_left),
        )
