from datetime import date

import pytest

from src.domain.categories import Category
from src.domain.models import ExpenseLine
from src.services.budget_math import (
    allocate_by_category,
    category_shares,
    daily_limit_cents,
    days_left,
    week_bounds,
    weekly_category_totals,
    weekly_limit_cents,
)
from tests.conftest import item

TODAY = date(2026, 3, 22)
PAYDAY = date(2026, 4, 3)


def test_days_left_does_not_count_the_target_day() -> None:
    assert days_left(TODAY, PAYDAY) == 12


def test_limits_match_the_weekly_report_example() -> None:
    # 267.20 € for 12 days -> 22.27 € a day, 155.87 € a week
    assert daily_limit_cents(26720, TODAY, PAYDAY) == 2227
    assert weekly_limit_cents(26720, TODAY, PAYDAY) == 15587


@pytest.mark.parametrize(
    ("today", "expected_daily", "expected_weekly"),
    [
        (date(2026, 4, 1), 5000, 10000),  # 2 days left: weekly limit covers only those 2 days
        (date(2026, 4, 2), 10000, 10000),  # last day before payday: everything is for today
        (date(2026, 4, 3), 10000, 10000),  # on the target day the balance still belongs to today
        (date(2026, 4, 10), 10000, 10000),  # target date passed: no division by zero or negatives
    ],
)
def test_limits_in_the_last_days_before_target(today: date, expected_daily: int, expected_weekly: int) -> None:
    assert daily_limit_cents(10000, today, PAYDAY) == expected_daily
    assert weekly_limit_cents(10000, today, PAYDAY) == expected_weekly


@pytest.mark.parametrize("balance", [0, -500])
def test_limits_with_empty_or_negative_balance_are_zero(balance: int) -> None:
    assert daily_limit_cents(balance, TODAY, PAYDAY) == 0
    assert weekly_limit_cents(balance, TODAY, PAYDAY) == 0


@pytest.mark.parametrize(
    ("today", "monday", "sunday"),
    [
        (date(2026, 3, 16), date(2026, 3, 16), date(2026, 3, 22)),  # Monday
        (date(2026, 3, 22), date(2026, 3, 16), date(2026, 3, 22)),  # Sunday
        (date(2026, 1, 1), date(2025, 12, 29), date(2026, 1, 4)),  # across a year boundary
        (date(2028, 3, 1), date(2028, 2, 28), date(2028, 3, 5)),  # across Feb 29 in a leap year
    ],
)
def test_week_bounds_are_monday_to_sunday(today: date, monday: date, sunday: date) -> None:
    assert week_bounds(today) == (monday, sunday)


def test_allocate_by_category_uses_quantity_and_sums_to_total() -> None:
    items = [
        item("Bread", 120, Category.GROCERIES, quantity="2"),
        item("Rioja", 750, Category.ALCOHOL),
        item("Batteries", 390, Category.HOUSEHOLD),
    ]
    parts = allocate_by_category(1380, items)

    assert parts == {Category.GROCERIES: 240, Category.ALCOHOL: 750, Category.HOUSEHOLD: 390}
    assert sum(parts.values()) == 1380


def test_allocate_by_category_spreads_a_discount_and_keeps_the_total() -> None:
    items = [item("A", 1000, Category.GROCERIES), item("B", 1000, Category.ALCOHOL), item("C", 1000, Category.CAFE)]
    parts = allocate_by_category(2000, items)  # 1000 € discount over three equal lines

    assert sum(parts.values()) == 2000
    assert sorted(parts.values()) == [666, 667, 667]


@pytest.mark.parametrize("total", [0, -100])
def test_allocate_by_category_with_no_total_is_empty(total: int) -> None:
    assert allocate_by_category(total, [item("A", 100, Category.GROCERIES)]) == {}


def test_allocate_by_category_without_items_is_other() -> None:
    assert allocate_by_category(500, []) == {Category.OTHER: 500}


def test_category_shares_are_percentages_largest_first() -> None:
    items = [item("Fries", 156, Category.FAST_FOOD), item("Water", 52, Category.GROCERIES)]
    assert category_shares(208, items) == [(Category.FAST_FOOD, 75), (Category.GROCERIES, 25)]


def test_category_shares_with_zero_total_does_not_divide_by_zero() -> None:
    assert category_shares(0, [item("A", 100, Category.GROCERIES)]) == []


def test_weekly_category_totals_split_receipts_and_put_manual_expenses_in_other() -> None:
    lines = [
        ExpenseLine(receipt_id=1, amount_cents=1000, category=Category.GROCERIES, line_total_cents=600),
        ExpenseLine(receipt_id=1, amount_cents=1000, category=Category.ALCOHOL, line_total_cents=400),
        ExpenseLine(receipt_id=None, amount_cents=250),
        ExpenseLine(receipt_id=2, amount_cents=300),  # receipt without items
    ]
    totals = weekly_category_totals(lines)

    assert totals == [(Category.GROCERIES, 600), (Category.OTHER, 550), (Category.ALCOHOL, 400)]
    assert sum(cents for _, cents in totals) == 1550
