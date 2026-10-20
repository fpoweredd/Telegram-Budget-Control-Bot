"""Pure budget math: limits, week boundaries and category splits."""

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta

from src.domain.categories import Category
from src.domain.models import ExpenseLine, ReceiptItem
from src.domain.money import div_round

__all__ = [
    "allocate_by_category",
    "category_shares",
    "daily_limit_cents",
    "days_left",
    "week_bounds",
    "weekly_category_totals",
    "weekly_limit_cents",
]

DAYS_IN_WEEK = 7


def days_left(today: date, target: date) -> int:
    """Days from today until the target date (the target day itself is not counted)."""
    return (target - today).days


def _budget_days(today: date, target: date) -> int:
    # On or after the target date the whole balance belongs to today.
    return max(days_left(today, target), 1)


def daily_limit_cents(balance_cents: int, today: date, target: date) -> int:
    """Balance spread evenly over the days left. Never negative."""
    if balance_cents <= 0:
        return 0
    return div_round(balance_cents, _budget_days(today, target))


def weekly_limit_cents(balance_cents: int, today: date, target: date) -> int:
    """Daily limit times seven, or times the days left if fewer than a week remain."""
    if balance_cents <= 0:
        return 0
    days = _budget_days(today, target)
    return div_round(balance_cents * min(DAYS_IN_WEEK, days), days)


def week_bounds(today: date) -> tuple[date, date]:
    """Monday and Sunday of the week that contains ``today``."""
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=DAYS_IN_WEEK - 1)


def allocate_by_category(total_cents: int, items: Iterable[ReceiptItem]) -> dict[Category, int]:
    """Split a receipt total across item categories proportionally to item line totals.

    The parts always sum to ``total_cents`` (largest remainder method), so discounts,
    rounding and missing items never make the categories disagree with the total.
    """
    weights: dict[Category, int] = defaultdict(int)
    for item in items:
        weights[item.category] += max(item.line_total_cents, 0)
    return _allocate(total_cents, weights)


def weekly_category_totals(lines: Iterable[ExpenseLine]) -> list[tuple[Category, int]]:
    """Sum expenses per category, largest first.

    Receipt expenses are split by their items; manual expenses and receipts without
    items count as OTHER, so the categories add up to the week's spending.
    """
    amounts: dict[int | None, int] = {}
    weights: dict[int | None, dict[Category, int]] = defaultdict(lambda: defaultdict(int))
    totals: dict[Category, int] = defaultdict(int)
    for line in lines:
        if line.receipt_id is None or line.category is None:
            totals[Category.OTHER] += line.amount_cents
            continue
        amounts[line.receipt_id] = line.amount_cents
        weights[line.receipt_id][line.category] += max(line.line_total_cents, 0)
    for receipt_id, amount in amounts.items():
        for category, cents in _allocate(amount, weights[receipt_id]).items():
            totals[category] += cents
    return sorted(((c, cents) for c, cents in totals.items() if cents > 0), key=lambda t: t[1], reverse=True)


def _allocate(total_cents: int, weights: dict[Category, int]) -> dict[Category, int]:
    if total_cents <= 0:
        return {}
    weight_sum = sum(weights.values())
    if weight_sum == 0:
        return {Category.OTHER: total_cents}

    parts = {category: total_cents * weight // weight_sum for category, weight in weights.items()}
    leftover = total_cents - sum(parts.values())
    by_remainder = sorted(weights, key=lambda c: (total_cents * weights[c]) % weight_sum, reverse=True)
    for category in by_remainder[:leftover]:
        parts[category] += 1
    return {category: cents for category, cents in parts.items() if cents > 0}


def category_shares(total_cents: int, items: Iterable[ReceiptItem]) -> list[tuple[Category, int]]:
    """Whole-number percentage per category, largest first. Empty when the total is unknown or zero."""
    parts = allocate_by_category(total_cents, items)
    shares = [(category, div_round(cents * 100, total_cents)) for category, cents in parts.items()]
    return sorted(shares, key=lambda share: share[1], reverse=True)
