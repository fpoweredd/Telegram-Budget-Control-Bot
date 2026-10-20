import json
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.db.database import Database
from src.db.migrations import MigrationError, migrate
from src.db.repositories import ReceiptRepository, SettingsRepository, TransactionRepository
from src.domain.categories import Category
from src.domain.models import ReceiptStatus

TODAY = date(2026, 3, 22)

# DDL copied from the single-file v1 bot.
LEGACY_SCHEMA = """
CREATE TABLE budget (user_id INTEGER PRIMARY KEY, username TEXT, income REAL DEFAULT 0, expenses REAL DEFAULT 0);
CREATE TABLE target_date (id INTEGER PRIMARY KEY, target_date TEXT);
CREATE TABLE transactions (
    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, date TEXT, amount REAL,
    type TEXT CHECK(type IN ('income', 'expense')), receipt_id INTEGER,
    FOREIGN KEY (user_id) REFERENCES budget (user_id), FOREIGN KEY (receipt_id) REFERENCES receipts (receipt_id)
);
CREATE TABLE receipts (
    receipt_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, date TEXT, store TEXT,
    total_amount REAL, receipt_json TEXT, photo_file_id TEXT, photo_message_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES budget (user_id)
);
"""

RECEIPT_JSON = {
    "total": 13.8,
    "date": "21.03.2026",
    "store": "Carrefour",
    "items": [
        {"name": "Вино Rioja", "price": 7.5, "quantity": 1, "category": "алкоголь"},
        {"name": "Хлеб", "price": 1.2, "quantity": 2, "category": "еда"},
        {"name": "Батарейки", "price": 3.9, "quantity": 1, "category": "бытовое"},
        {"name": "Сломанная строка", "price": None, "category": "другое"},
    ],
}


def _legacy_db(path: Path, extra_sql: str = "") -> None:
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    conn.executemany("INSERT INTO budget (user_id, username) VALUES (?, ?)", [(1, "user"), (2, "user")])
    conn.execute("INSERT INTO target_date VALUES (1, '03.04.2026')")
    conn.execute(
        "INSERT INTO receipts (receipt_id, user_id, username, date, store, total_amount, receipt_json, "
        "photo_file_id, photo_message_id) VALUES (1, 1, 'nik', '21.03.2026', 'Carrefour', 13.8, ?, 'f1', 10)",
        (json.dumps(RECEIPT_JSON, ensure_ascii=False),),
    )
    conn.execute(
        "INSERT INTO receipts (receipt_id, user_id, username, date, store, total_amount, receipt_json) "
        "VALUES (2, 1, 'nik', 'вчера', NULL, NULL, 'not json')"
    )
    conn.executemany(
        "INSERT INTO transactions (user_id, username, date, amount, type, receipt_id) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "nik", "20.03.2026", 500.0, "income", None),
            (1, "nik", "21.03.2026", 13.8, "expense", 1),
            (1, "nik", "21.03.2026", 13.8, "expense", 1),  # v1 double tap on "Add"
            (2, None, "22.03.2026", 0.1 + 0.2, "expense", None),
            (2, None, "22.03.2026", -5.0, "expense", None),  # v1 accepted negative amounts
            (2, None, "22.03.2026", 3.0, "expense", 77),  # receipt lost to DROP TABLE
        ],
    )
    if extra_sql:
        conn.execute(extra_sql)
    conn.commit()
    conn.close()


async def test_migrate_converts_a_legacy_database_without_losing_money(tmp_path: Path) -> None:
    path = tmp_path / "budget.db"
    _legacy_db(path)

    async with Database(path) as db:
        await migrate(db, TODAY, default_target_days=30)
        transactions = TransactionRepository(db)
        receipt = await ReceiptRepository(db).get(1)
        unreadable = await ReceiptRepository(db).get(2)

        # 500 - 13.80 - 13.80 - 0.30 + 5.00 - 3.00
        assert await transactions.balance() == 47410
        assert await transactions.totals_on(date(2026, 3, 22)) == (500, 330)
        assert await SettingsRepository(db).get_target_date() == date(2026, 4, 3)

        assert receipt is not None and receipt.status is ReceiptStatus.ADDED
        assert receipt.parsed.total_cents == 1380
        assert receipt.parsed.purchase_date == date(2026, 3, 21)
        assert [(i.category, i.quantity) for i in receipt.parsed.items] == [
            (Category.ALCOHOL, Decimal(1)),
            (Category.GROCERIES, Decimal(2)),
            (Category.HOUSEHOLD, Decimal(1)),
        ]
        assert unreadable is not None and unreadable.status is ReceiptStatus.PENDING

        async with db.conn.execute("SELECT COUNT(*), COUNT(receipt_id) FROM transactions") as cursor:
            counts = await cursor.fetchone()
        assert counts is not None and tuple(counts) == (6, 1)  # all rows kept, one link per receipt
        async with db.conn.execute("SELECT raw_json FROM receipts WHERE receipt_id = 1") as cursor:
            raw = await cursor.fetchone()
        assert raw is not None and "Сломанная строка" in raw[0]  # original JSON preserved

    assert list(tmp_path.glob("budget.db.bak-pre-v1-*"))


async def test_migrate_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "budget.db"
    _legacy_db(path)
    async with Database(path) as db:
        await migrate(db, TODAY, 30)
        await migrate(db, TODAY, 30)
        assert await TransactionRepository(db).balance() == 47410


async def test_migrate_with_unconvertible_row_changes_nothing(tmp_path: Path) -> None:
    path = tmp_path / "budget.db"
    _legacy_db(path, "INSERT INTO transactions (user_id, date, amount, type) VALUES (1, 'someday', 1.0, 'income')")

    async with Database(path) as db:
        with pytest.raises(MigrationError):
            await migrate(db, TODAY, 30)

    conn = sqlite3.connect(path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"budget", "target_date", "transactions", "receipts"} <= tables
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 7
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    conn.close()


async def test_migrate_refuses_a_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "budget.db"
    sqlite3.connect(path).execute("PRAGMA user_version = 99").connection.close()

    async with Database(path) as db:
        with pytest.raises(MigrationError):
            await migrate(db, TODAY, 30)
