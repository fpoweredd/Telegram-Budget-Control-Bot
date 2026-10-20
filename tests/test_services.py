from datetime import date, timedelta
from pathlib import Path

import pytest

from src.db.database import Database
from src.db.migrations import migrate
from src.db.repositories import ReceiptRepository
from src.domain.categories import Category
from src.domain.models import ParsedReceipt, Receipt, ReceiptStatus, TransactionType
from src.services.budget_service import BudgetService, TargetDateInPastError
from src.services.receipt_parser import ReceiptRecognitionError
from src.services.receipt_service import (
    ReceiptAlreadyHandledError,
    ReceiptNotFoundError,
    ReceiptService,
    ReceiptTotalMissingError,
)
from tests.conftest import ANNA, NIK, TODAY, FakeClock, FakeParser, item

GROCERY_RECEIPT = ParsedReceipt(
    "Mercadona",
    TODAY,
    1380,
    (
        item("Bread", 120, Category.GROCERIES, quantity="2"),
        item("Rioja", 750, Category.ALCOHOL),
        item("Batteries", 390, Category.HOUSEHOLD),
    ),
)


async def _register(receipts: ReceiptService, parser: FakeParser, parsed: ParsedReceipt, user_id: int = 1) -> Receipt:
    parser.results.append(parsed)
    return await receipts.register(
        user_id=user_id, chat_id=user_id, photo_file_id="photo", photo_message_id=99, image=b"img"
    )


async def test_new_database_gets_a_default_target_date(budget: BudgetService) -> None:
    assert await budget.target_date() == TODAY + timedelta(days=30)


async def test_add_manual_updates_balance_and_today(budget: BudgetService) -> None:
    await budget.add_manual(NIK, TransactionType.INCOME, 50000)
    snapshot = await budget.add_manual(ANNA, TransactionType.EXPENSE, 1250)

    assert snapshot.balance_cents == 48750
    assert snapshot.income_today_cents == 50000
    assert snapshot.expense_today_cents == 1250
    assert snapshot.daily_limit_cents == 1625  # 487.50 € / 30 days
    assert snapshot.weekly_limit_cents == 11375
    assert snapshot.days_left == 30


async def test_set_target_date_rejects_today_and_past(budget: BudgetService) -> None:
    with pytest.raises(TargetDateInPastError):
        await budget.set_target_date(TODAY)
    snapshot = await budget.set_target_date(date(2026, 4, 3))
    assert snapshot.days_left == 12


async def test_receipt_add_is_idempotent(receipts: ReceiptService, budget: BudgetService, parser: FakeParser) -> None:
    receipt = await _register(receipts, parser, GROCERY_RECEIPT)

    added = await receipts.add_as_expense(receipt.receipt_id, NIK)
    with pytest.raises(ReceiptAlreadyHandledError):
        await receipts.add_as_expense(receipt.receipt_id, NIK)

    assert added.status is ReceiptStatus.ADDED
    assert (await budget.snapshot()).expense_today_cents == 1380


async def test_receipt_actions_target_the_receipt_in_the_button(
    receipts: ReceiptService, budget: BudgetService, parser: FakeParser
) -> None:
    first = await _register(receipts, parser, GROCERY_RECEIPT)
    second = await _register(receipts, parser, ParsedReceipt("Bar", None, 500, ()))

    await receipts.add_as_expense(first.receipt_id, NIK)  # the older receipt, not "the latest one"
    await receipts.cancel(second.receipt_id, NIK.user_id)

    assert (await budget.snapshot()).expense_today_cents == 1380


async def test_receipt_of_another_user_is_not_found(receipts: ReceiptService, parser: FakeParser) -> None:
    receipt = await _register(receipts, parser, GROCERY_RECEIPT, user_id=NIK.user_id)

    with pytest.raises(ReceiptNotFoundError):
        await receipts.add_as_expense(receipt.receipt_id, ANNA)


async def test_failed_recognition_keeps_a_pending_receipt_that_can_be_retried(
    receipts: ReceiptService, parser: FakeParser
) -> None:
    parser.results.append(ReceiptRecognitionError("timeout"))
    receipt = await receipts.register(user_id=1, chat_id=1, photo_file_id="p", photo_message_id=5, image=b"x")
    assert receipt.parsed.is_empty
    with pytest.raises(ReceiptTotalMissingError):
        await receipts.add_as_expense(receipt.receipt_id, NIK)

    parser.results.append(GROCERY_RECEIPT)
    retried = await receipts.reprocess(receipt.receipt_id, NIK.user_id, b"x")

    assert retried.receipt_id == receipt.receipt_id  # updated in place, no duplicate row
    assert retried.parsed.total_cents == 1380
    assert len(retried.parsed.items) == 3


async def test_weekly_report_counts_only_added_receipts_with_quantities(
    receipts: ReceiptService, budget: BudgetService, parser: FakeParser, clock: FakeClock
) -> None:
    added = await _register(receipts, parser, GROCERY_RECEIPT)
    await receipts.add_as_expense(added.receipt_id, NIK)
    cancelled = await _register(
        receipts, parser, ParsedReceipt("Shop", None, 9900, (item("TV", 9900, Category.ELECTRONICS),))
    )
    await receipts.cancel(cancelled.receipt_id, NIK.user_id)
    await _register(receipts, parser, ParsedReceipt("Never added", None, 700, (item("X", 700, Category.CAFE),)))
    await budget.add_manual(ANNA, TransactionType.EXPENSE, 500)

    clock.today = TODAY - timedelta(days=7)  # last week: must not be counted
    await budget.add_manual(ANNA, TransactionType.EXPENSE, 10000)
    clock.today = TODAY

    report = await budget.weekly_report()

    assert report.week_start == date(2026, 3, 16)
    assert report.week_expense_cents == 1880
    assert report.by_category == (
        (Category.ALCOHOL, 750),
        (Category.OTHER, 500),
        (Category.HOUSEHOLD, 390),
        (Category.GROCERIES, 240),
    )


async def test_reset_clears_transactions_and_receipts_and_writes_a_backup(
    db: Database, receipts: ReceiptService, budget: BudgetService, parser: FakeParser
) -> None:
    receipt = await _register(receipts, parser, GROCERY_RECEIPT)
    await receipts.add_as_expense(receipt.receipt_id, NIK)

    target = await budget.reset()

    assert target == TODAY + timedelta(days=30)
    assert (await budget.snapshot()).balance_cents == 0
    assert await ReceiptRepository(db).get(receipt.receipt_id) is None
    assert list(db.path.parent.glob("budget.db.bak-reset-*"))


async def test_receipts_survive_a_restart(tmp_path: Path, clock: FakeClock, parser: FakeParser) -> None:
    path = tmp_path / "budget.db"
    async with Database(path) as db:
        await migrate(db, clock(), 30)
        repo = ReceiptRepository(db)
        async with db.transaction() as conn:
            receipt_id = await repo.create(conn, user_id=1, chat_id=1, photo_file_id="p", photo_message_id=1)

    async with Database(path) as db:
        await migrate(db, clock(), 30)
        assert await ReceiptRepository(db).get(receipt_id) is not None
