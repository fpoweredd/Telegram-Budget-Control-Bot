"""Shared budget: transactions, target date, status and weekly report."""

from collections.abc import Callable
from datetime import date, timedelta

from loguru import logger

from src.db.database import Database
from src.db.repositories import ReceiptRepository, SettingsRepository, TransactionRepository, UserRepository
from src.domain.models import Author, BudgetSnapshot, TransactionType, WeeklyReport
from src.services import budget_math

__all__ = ["BudgetService", "TargetDateInPastError"]


class TargetDateInPastError(ValueError):
    """The requested target date is today or earlier."""


class BudgetService:
    def __init__(
        self,
        db: Database,
        users: UserRepository,
        transactions: TransactionRepository,
        receipts: ReceiptRepository,
        settings: SettingsRepository,
        clock: Callable[[], date],
        default_target_days: int,
    ) -> None:
        self._db = db
        self._users = users
        self._transactions = transactions
        self._receipts = receipts
        self._settings = settings
        self._clock = clock
        self._default_target_days = default_target_days

    def today(self) -> date:
        return self._clock()

    async def add_manual(self, author: Author, kind: TransactionType, amount_cents: int) -> BudgetSnapshot:
        async with self._db.transaction() as conn:
            await self._users.upsert(conn, author)
            tx_id = await self._transactions.add(
                conn, user_id=author.user_id, kind=kind, amount_cents=amount_cents, on=self.today()
            )
        logger.info("Transaction {} added: {} {} cents by user {}", tx_id, kind, amount_cents, author.user_id)
        return await self.snapshot()

    async def snapshot(self) -> BudgetSnapshot:
        today = self.today()
        target = await self.target_date()
        balance = await self._transactions.balance()
        income_today, expense_today = await self._transactions.totals_on(today)
        return BudgetSnapshot(
            today=today,
            target_date=target,
            days_left=budget_math.days_left(today, target),
            balance_cents=balance,
            income_today_cents=income_today,
            expense_today_cents=expense_today,
            daily_limit_cents=budget_math.daily_limit_cents(balance, today, target),
            weekly_limit_cents=budget_math.weekly_limit_cents(balance, today, target),
        )

    async def weekly_report(self) -> WeeklyReport:
        snapshot = await self.snapshot()
        week_start, week_end = budget_math.week_bounds(snapshot.today)
        lines = await self._transactions.expense_lines_between(week_start, week_end)
        return WeeklyReport(
            snapshot=snapshot,
            week_start=week_start,
            week_expense_cents=await self._transactions.expense_between(week_start, week_end),
            by_category=tuple(budget_math.weekly_category_totals(lines)),
        )

    async def target_date(self) -> date:
        target = await self._settings.get_target_date()
        if target is None:  # only possible if the settings row was removed by hand
            target = self.today() + timedelta(days=self._default_target_days)
            async with self._db.transaction() as conn:
                await self._settings.set_target_date(conn, target)
        return target

    async def set_target_date(self, target: date) -> BudgetSnapshot:
        if target <= self.today():
            raise TargetDateInPastError(f"target date {target} must be after {self.today()}")
        async with self._db.transaction() as conn:
            await self._settings.set_target_date(conn, target)
        logger.info("Target date set to {}", target)
        return await self.snapshot()

    async def reset(self) -> date:
        """Delete all transactions and receipts (after a backup) and restart the period."""
        await self._db.backup("reset")
        target = self.today() + timedelta(days=self._default_target_days)
        async with self._db.transaction() as conn:
            await self._transactions.delete_all(conn)
            await self._receipts.delete_all(conn)
            await self._settings.set_target_date(conn, target)
        logger.warning("All budget data was reset; new target date {}", target)
        return target
