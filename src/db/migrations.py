"""Schema creation and the one-off migration from the single-file v1 bot.

The legacy database stored money as REAL, dates as ``dd.mm.yyyy`` strings, Russian
category labels inside a receipt JSON blob, and dropped the receipts table on every
start. The migration converts everything in one transaction after writing a backup;
if any row cannot be converted, nothing is changed and the bot refuses to start.
"""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import aiosqlite
from loguru import logger

from src.db.database import Database
from src.db.schema import SCHEMA_STATEMENTS, SCHEMA_VERSION
from src.domain.categories import category_from_legacy
from src.domain.models import ReceiptStatus, TransactionType
from src.domain.money import decimal_to_cents

__all__ = ["MigrationError", "migrate"]

# Drop order matters: children before the tables their foreign keys point to.
LEGACY_TABLES = ("transactions", "receipts", "budget", "target_date")
_LEGACY_DATE_FORMATS = ("%d.%m.%Y", "%Y-%m-%d")


class MigrationError(RuntimeError):
    """The database cannot be brought to the current schema. Data is left untouched."""


async def migrate(db: Database, today: date, default_target_days: int) -> None:
    """Bring the database to SCHEMA_VERSION: create it, or convert a legacy v1 database."""
    conn = db.conn
    version = await _user_version(conn)
    if version == SCHEMA_VERSION:
        return
    if version > SCHEMA_VERSION:
        raise MigrationError(f"database schema v{version} is newer than this bot (v{SCHEMA_VERSION})")

    tables = await _table_names(conn)
    is_legacy = "transactions" in tables
    if is_legacy:
        await db.backup("pre-v1")

    default_target = today + timedelta(days=default_target_days)
    async with db.transaction():
        if is_legacy:
            for table in LEGACY_TABLES:
                if table in tables:
                    await conn.execute(f"ALTER TABLE {table} RENAME TO legacy_{table}")
        for statement in SCHEMA_STATEMENTS:
            await conn.execute(statement)
        if is_legacy:
            await _copy_legacy_data(conn, tables, default_target)
            for table in LEGACY_TABLES:
                if table in tables:
                    await conn.execute(f"DROP TABLE legacy_{table}")
        else:
            await _set_target_date(conn, default_target)
        await conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    logger.info("Database {} at schema v{}", "migrated" if is_legacy else "created", SCHEMA_VERSION)


async def _user_version(conn: aiosqlite.Connection) -> int:
    async with conn.execute("PRAGMA user_version") as cursor:
        row = await cursor.fetchone()
    return int(row[0]) if row else 0


async def _table_names(conn: aiosqlite.Connection) -> set[str]:
    async with conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cursor:
        return {row[0] for row in await cursor.fetchall()}


async def _set_target_date(conn: aiosqlite.Connection, target: date) -> None:
    await conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('target_date', ?)",
        (target.isoformat(),),
    )


async def _copy_legacy_data(conn: aiosqlite.Connection, tables: set[str], default_target: date) -> None:
    await _copy_target_date(conn, tables, default_target)
    receipt_ids = await _copy_receipts(conn, tables)
    linked_receipts = await _copy_transactions(conn, receipt_ids)
    await _copy_users(conn, tables)
    for receipt_id in linked_receipts:
        await conn.execute(
            "UPDATE receipts SET status = ? WHERE receipt_id = ?",
            (ReceiptStatus.ADDED.value, receipt_id),
        )
    logger.info(
        "Legacy data converted: {} receipts ({} linked to transactions)",
        len(receipt_ids),
        len(linked_receipts),
    )


async def _copy_target_date(conn: aiosqlite.Connection, tables: set[str], default_target: date) -> None:
    target = None
    if "target_date" in tables:
        async with conn.execute("SELECT target_date FROM legacy_target_date WHERE id = 1") as cursor:
            row = await cursor.fetchone()
        target = _parse_legacy_date(row[0]) if row else None
    await _set_target_date(conn, target or default_target)


async def _copy_receipts(conn: aiosqlite.Connection, tables: set[str]) -> set[int]:
    if "receipts" not in tables:
        return set()
    async with conn.execute(
        "SELECT receipt_id, user_id, date, store, total_amount, receipt_json, photo_file_id, "
        "photo_message_id, created_at FROM legacy_receipts"
    ) as cursor:
        rows = list(await cursor.fetchall())

    for row in rows:
        data = _load_json(row["receipt_json"])
        total = _to_cents(row["total_amount"])
        await conn.execute(
            "INSERT INTO receipts (receipt_id, user_id, chat_id, status, store, purchase_date, total_cents, "
            "raw_json, photo_file_id, photo_message_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))",
            (
                row["receipt_id"],
                row["user_id"],
                row["user_id"],  # v1 only worked in private chats, so chat id == user id
                ReceiptStatus.PENDING.value,
                row["store"],
                _iso_or_none(_parse_legacy_date(row["date"])),
                total if total is not None and total >= 0 else None,
                row["receipt_json"],
                row["photo_file_id"],
                row["photo_message_id"],
                row["created_at"],
            ),
        )
        for item in data.get("items") or []:
            await _copy_receipt_item(conn, row["receipt_id"], item)
    return {row["receipt_id"] for row in rows}


async def _copy_receipt_item(conn: aiosqlite.Connection, receipt_id: int, item: object) -> None:
    if not isinstance(item, dict):
        return
    price = _to_cents(item.get("price"))
    quantity = _to_decimal(item.get("quantity")) or Decimal(1)
    if price is None or price < 0 or quantity <= 0:
        return  # the original JSON stays in receipts.raw_json
    await conn.execute(
        "INSERT INTO receipt_items (receipt_id, name, unit_price_cents, quantity, category) VALUES (?, ?, ?, ?, ?)",
        (receipt_id, str(item.get("name") or "?"), price, str(quantity), category_from_legacy(item.get("category"))),
    )


async def _copy_transactions(conn: aiosqlite.Connection, receipt_ids: set[int]) -> set[int]:
    async with conn.execute(
        "SELECT transaction_id, user_id, date, amount, type, receipt_id FROM legacy_transactions "
        "ORDER BY transaction_id"
    ) as cursor:
        rows = list(await cursor.fetchall())

    linked: set[int] = set()
    for row in rows:
        tx_id = row["transaction_id"]
        tx_date = _parse_legacy_date(row["date"])
        amount = _to_cents(row["amount"])
        if tx_date is None or amount is None or row["type"] not in ("income", "expense"):
            raise MigrationError(f"legacy transaction {tx_id} cannot be converted; database left unchanged")

        tx_type = TransactionType(row["type"])
        if amount < 0:  # v1 accepted negative input; keep its effect on the balance
            amount = -amount
            tx_type = TransactionType.EXPENSE if tx_type is TransactionType.INCOME else TransactionType.INCOME
            logger.warning("Legacy transaction {} had a negative amount; stored as {}", tx_id, tx_type)

        # v1 dropped receipts on restart, so old ids may point to missing or reused receipts.
        receipt_id = row["receipt_id"]
        if receipt_id not in receipt_ids or receipt_id in linked:
            receipt_id = None
        else:
            linked.add(receipt_id)

        await conn.execute(
            "INSERT INTO transactions (transaction_id, user_id, date, amount_cents, type, receipt_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tx_id, row["user_id"], tx_date.isoformat(), amount, tx_type.value, receipt_id),
        )
    logger.info("Legacy transactions converted: {}", len(rows))
    return linked


async def _copy_users(conn: aiosqlite.Connection, tables: set[str]) -> None:
    # Latest username seen in transactions wins; the v1 'budget' table only had placeholders.
    await conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username) "
        "SELECT user_id, username FROM legacy_transactions "
        "WHERE transaction_id IN (SELECT MAX(transaction_id) FROM legacy_transactions GROUP BY user_id)"
    )
    if "budget" in tables:
        await conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username) SELECT user_id, username FROM legacy_budget"
        )


def _parse_legacy_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    for fmt in _LEGACY_DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _iso_or_none(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _to_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _to_cents(value: object) -> int | None:
    amount = _to_decimal(value)
    return decimal_to_cents(amount) if amount is not None else None


def _load_json(raw: object) -> dict[str, Any]:
    if not isinstance(raw, str):
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
