"""Data access. Write methods must run inside ``Database.transaction()``."""

from datetime import date
from decimal import Decimal

import aiosqlite

from src.db.database import Database
from src.domain.categories import category_from_legacy
from src.domain.models import Author, ExpenseLine, ParsedReceipt, Receipt, ReceiptItem, ReceiptStatus, TransactionType

__all__ = [
    "ReceiptRepository",
    "SettingsRepository",
    "TransactionRepository",
    "UserRepository",
]

_TARGET_DATE_KEY = "target_date"


class UserRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, conn: aiosqlite.Connection, author: Author) -> None:
        await conn.execute(
            "INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?) "
            "ON CONFLICT (user_id) DO UPDATE SET username = excluded.username, "
            "first_name = excluded.first_name, updated_at = CURRENT_TIMESTAMP",
            (author.user_id, author.username, author.first_name),
        )


class SettingsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_target_date(self) -> date | None:
        async with self._db.conn.execute("SELECT value FROM settings WHERE key = ?", (_TARGET_DATE_KEY,)) as cursor:
            row = await cursor.fetchone()
        return date.fromisoformat(row["value"]) if row else None

    async def set_target_date(self, conn: aiosqlite.Connection, target: date) -> None:
        await conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (_TARGET_DATE_KEY, target.isoformat()),
        )


class TransactionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(
        self,
        conn: aiosqlite.Connection,
        *,
        user_id: int,
        kind: TransactionType,
        amount_cents: int,
        on: date,
        receipt_id: int | None = None,
    ) -> int:
        cursor = await conn.execute(
            "INSERT INTO transactions (user_id, date, amount_cents, type, receipt_id) VALUES (?, ?, ?, ?, ?)",
            (user_id, on.isoformat(), amount_cents, kind.value, receipt_id),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return the new transaction id")
        return cursor.lastrowid

    async def balance(self) -> int:
        return await self._scalar(
            "SELECT COALESCE(SUM(CASE type WHEN 'income' THEN amount_cents ELSE -amount_cents END), 0) "
            "FROM transactions"
        )

    async def totals_on(self, day: date) -> tuple[int, int]:
        """Income and expense totals for one day."""
        income = await self._sum_between(TransactionType.INCOME, day, day)
        expense = await self._sum_between(TransactionType.EXPENSE, day, day)
        return income, expense

    async def expense_between(self, start: date, end: date) -> int:
        return await self._sum_between(TransactionType.EXPENSE, start, end)

    async def expense_lines_between(self, start: date, end: date) -> list[ExpenseLine]:
        """Expense rows joined with their receipt items, for the category breakdown."""
        async with self._db.conn.execute(
            "SELECT t.receipt_id, t.amount_cents, ri.category, ri.unit_price_cents, ri.quantity "
            "FROM transactions AS t LEFT JOIN receipt_items AS ri ON ri.receipt_id = t.receipt_id "
            "WHERE t.type = 'expense' AND t.date BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        ) as cursor:
            rows = await cursor.fetchall()
        lines: list[ExpenseLine] = []
        for row in rows:
            if row["category"] is None:
                lines.append(ExpenseLine(row["receipt_id"], row["amount_cents"]))
                continue
            item = ReceiptItem(
                "", row["unit_price_cents"], Decimal(row["quantity"]), category_from_legacy(row["category"])
            )
            lines.append(ExpenseLine(row["receipt_id"], row["amount_cents"], item.category, item.line_total_cents))
        return lines

    async def delete_all(self, conn: aiosqlite.Connection) -> None:
        await conn.execute("DELETE FROM transactions")

    async def _sum_between(self, kind: TransactionType, start: date, end: date) -> int:
        return await self._scalar(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM transactions WHERE type = ? AND date BETWEEN ? AND ?",
            (kind.value, start.isoformat(), end.isoformat()),
        )

    async def _scalar(self, sql: str, params: tuple[object, ...] = ()) -> int:
        async with self._db.conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0


class ReceiptRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        conn: aiosqlite.Connection,
        *,
        user_id: int,
        chat_id: int,
        photo_file_id: str,
        photo_message_id: int,
    ) -> int:
        cursor = await conn.execute(
            "INSERT INTO receipts (user_id, chat_id, photo_file_id, photo_message_id) VALUES (?, ?, ?, ?)",
            (user_id, chat_id, photo_file_id, photo_message_id),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return the new receipt id")
        return cursor.lastrowid

    async def save_parsed(
        self, conn: aiosqlite.Connection, receipt_id: int, parsed: ParsedReceipt, raw_json: str | None
    ) -> None:
        await conn.execute(
            "UPDATE receipts SET store = ?, purchase_date = ?, total_cents = ?, raw_json = ? WHERE receipt_id = ?",
            (
                parsed.store,
                parsed.purchase_date.isoformat() if parsed.purchase_date else None,
                parsed.total_cents,
                raw_json,
                receipt_id,
            ),
        )
        await conn.execute("DELETE FROM receipt_items WHERE receipt_id = ?", (receipt_id,))
        await conn.executemany(
            "INSERT INTO receipt_items (receipt_id, name, unit_price_cents, quantity, category) VALUES (?, ?, ?, ?, ?)",
            [
                (receipt_id, item.name, item.unit_price_cents, str(item.quantity), item.category.value)
                for item in parsed.items
            ],
        )

    async def change_status(
        self, conn: aiosqlite.Connection, receipt_id: int, *, expected: ReceiptStatus, new: ReceiptStatus
    ) -> bool:
        """Compare-and-set the status. Returns False if the receipt was not in ``expected`` state."""
        cursor = await conn.execute(
            "UPDATE receipts SET status = ? WHERE receipt_id = ? AND status = ?",
            (new.value, receipt_id, expected.value),
        )
        return cursor.rowcount == 1

    async def get(self, receipt_id: int) -> Receipt | None:
        async with self._db.conn.execute(
            "SELECT receipt_id, user_id, chat_id, status, store, purchase_date, total_cents, "
            "photo_file_id, photo_message_id FROM receipts WHERE receipt_id = ?",
            (receipt_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        async with self._db.conn.execute(
            "SELECT name, unit_price_cents, quantity, category FROM receipt_items WHERE receipt_id = ? "
            "ORDER BY item_id",
            (receipt_id,),
        ) as cursor:
            item_rows = await cursor.fetchall()
        items = tuple(
            ReceiptItem(r["name"], r["unit_price_cents"], Decimal(r["quantity"]), category_from_legacy(r["category"]))
            for r in item_rows
        )
        parsed = ParsedReceipt(
            store=row["store"],
            purchase_date=date.fromisoformat(row["purchase_date"]) if row["purchase_date"] else None,
            total_cents=row["total_cents"],
            items=items,
        )
        return Receipt(
            receipt_id=row["receipt_id"],
            user_id=row["user_id"],
            chat_id=row["chat_id"],
            status=ReceiptStatus(row["status"]),
            photo_file_id=row["photo_file_id"],
            photo_message_id=row["photo_message_id"],
            parsed=parsed,
        )

    async def delete_all(self, conn: aiosqlite.Connection) -> None:
        await conn.execute("DELETE FROM receipt_items")
        await conn.execute("DELETE FROM receipts")
