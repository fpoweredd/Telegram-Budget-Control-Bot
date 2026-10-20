from dataclasses import replace
from datetime import date

from src.domain.categories import Category
from src.domain.models import (
    Author,
    BudgetSnapshot,
    ParsedReceipt,
    Receipt,
    ReceiptStatus,
    TransactionType,
    WeeklyReport,
)
from src.formatting import MessageFormatter, display_name
from src.texts import Texts
from tests.conftest import NIK, item

SNAPSHOT = BudgetSnapshot(
    today=date(2026, 3, 22),
    target_date=date(2026, 4, 3),
    days_left=12,
    balance_cents=26720,
    income_today_cents=0,
    expense_today_cents=706,
    daily_limit_cents=3000,
    weekly_limit_cents=15587,
)


def _receipt(parsed: ParsedReceipt, status: ReceiptStatus = ReceiptStatus.PENDING) -> Receipt:
    return Receipt(1, 1, 1, status, "file", 10, parsed)


def test_expense_from_receipt_matches_the_style_guide(fmt: MessageFormatter) -> None:
    receipt = _receipt(ParsedReceipt("McDonald's", None, 706, (item("Big Mac", 706, Category.FAST_FOOD),)))

    text = fmt.transaction(TransactionType.EXPENSE, 706, SNAPSHOT, NIK, receipt)

    assert text == ("🔴 <b>−7.06 €</b> · McDonald's\n🧾 Fast food 100%\n🎯 Today: 7.06 / 30.00 €\n👤 @nik")


def test_manual_income_shows_balance_and_no_categories(fmt: MessageFormatter) -> None:
    text = fmt.transaction(TransactionType.INCOME, 50000, SNAPSHOT, NIK)

    assert text == "🟢 <b>+500.00 €</b>\n🎯 Today: 7.06 / 30.00 €\n💰 Balance: <b>267.20 €</b>\n👤 @nik"


def test_today_line_warns_when_over_the_daily_limit(fmt: MessageFormatter) -> None:
    snapshot = replace(SNAPSHOT, expense_today_cents=3500)
    assert "🎯 Today: 35.00 / 30.00 € ⚠️" in fmt.transaction(TransactionType.EXPENSE, 3500, snapshot, NIK)


def test_weekly_report_matches_the_style_guide(fmt: MessageFormatter) -> None:
    report = WeeklyReport(
        snapshot=SNAPSHOT,
        week_start=date(2026, 3, 16),
        week_expense_cents=3280,
        by_category=(
            (Category.GROCERIES, 3000),
            (Category.ALCOHOL, 1600),
            (Category.CAFE, 1600),
            (Category.HOUSEHOLD, 200),
        ),
    )

    assert fmt.weekly_report(report) == (
        "📊 <b>Weekly report</b> · 22 Mar\n"
        "⏳ 12 days left until 3 Apr\n"
        "💸 Spent <b>32.80</b> / 155.87 € this week\n"
        "🍎 Groceries 30 € · 🍷 Alcohol 16 € · ☕ Cafe 16 € · 🏠 Household 2 €\n"
        "💰 Balance: <b>267.20 €</b>"
    )


def test_status_lists_today_balance_and_limits(fmt: MessageFormatter) -> None:
    assert fmt.status(SNAPSHOT) == (
        "📋 <b>Status</b> · 22 Mar\n"
        "⏳ 12 days left until 3 Apr\n"
        "\n"
        "🟢 Income today: 0.00 €\n"
        "🔴 Spent today: 7.06 €\n"
        "💰 Balance: <b>267.20 €</b>\n"
        "\n"
        "🎯 Daily limit: <b>30.00 €</b>\n"
        "📅 Weekly limit: 155.87 €"
    )


def test_status_after_target_date_asks_for_a_new_one(fmt: MessageFormatter) -> None:
    passed = BudgetSnapshot(date(2026, 4, 5), date(2026, 4, 3), -2, 1000, 0, 0, 1000, 1000)
    assert "⚠️ Target date 3 Apr has passed · set a new one with /date" in fmt.status(passed)


def test_one_day_left_is_singular(fmt: MessageFormatter) -> None:
    last_day = BudgetSnapshot(date(2026, 4, 2), date(2026, 4, 3), 1, 1000, 0, 0, 1000, 1000)
    assert "⏳ 1 day left until 3 Apr" in fmt.status(last_day)


def test_display_name_falls_back_to_first_name_then_id() -> None:
    assert display_name(Author(1, "nik", "Nik")) == "@nik"
    assert display_name(Author(2, None, "Anna <3")) == "Anna &lt;3"
    assert display_name(Author(3, None, None)) == "id3"


def test_receipt_preview_shows_items_with_quantities_and_escapes_html(fmt: MessageFormatter) -> None:
    parsed = ParsedReceipt(
        "Bar <Tapas>",
        date(2026, 3, 22),
        596,
        (item("Bread", 120, Category.GROCERIES, quantity="2"), item("Beer & co", 356, Category.ALCOHOL)),
    )

    assert fmt.receipt_preview(_receipt(parsed)) == (
        "🧾 <b>Bar &lt;Tapas&gt;</b> · 22 Mar 2026\n"
        "💶 Total: <b>5.96 €</b>\n"
        "\n"
        "🍎 Bread · 2 × 1.20 = 2.40 €\n"
        "🍷 Beer &amp; co · 3.56 €"
    )


def test_receipt_preview_without_total_explains_what_to_do(fmt: MessageFormatter) -> None:
    parsed = ParsedReceipt("Lidl", None, None, (item("Milk", 99, Category.GROCERIES),))

    text = fmt.receipt_preview(_receipt(parsed))

    assert text.startswith("🧾 <b>Lidl</b>\n")
    assert text.endswith("⚠️ Couldn't read the total · retry or send the amount manually")


def test_receipt_preview_when_nothing_was_recognized(fmt: MessageFormatter) -> None:
    assert fmt.receipt_preview(_receipt(ParsedReceipt(None, None, None))).startswith("❌ Couldn't read this receipt")


def test_russian_locale_uses_russian_plurals_and_months() -> None:
    fmt = MessageFormatter(Texts.for_language("ru"), "€")
    assert "⏳ До 3 апр осталось 12 дней" in fmt.status(SNAPSHOT)
    assert Texts.for_language("ru").days(21) == "21 день"
    assert Texts.for_language("ru").days(3) == "3 дня"
