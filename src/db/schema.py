"""Current database schema (version 1).

Money is stored as integer cents, dates as ISO ``YYYY-MM-DD`` text in the bot's
time zone, receipt item quantities as decimal text.
"""

__all__ = ["SCHEMA_STATEMENTS", "SCHEMA_VERSION"]

SCHEMA_VERSION = 1

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE users (
        user_id     INTEGER PRIMARY KEY,
        username    TEXT,
        first_name  TEXT,
        updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE settings (
        key    TEXT PRIMARY KEY,
        value  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE receipts (
        receipt_id        INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id           INTEGER NOT NULL,
        chat_id           INTEGER NOT NULL,
        status            TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'added', 'cancelled')),
        store             TEXT,
        purchase_date     TEXT,
        total_cents       INTEGER CHECK (total_cents IS NULL OR total_cents >= 0),
        raw_json          TEXT,
        photo_file_id     TEXT,
        photo_message_id  INTEGER,
        created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX idx_receipts_user_id ON receipts (user_id)",
    """
    CREATE TABLE receipt_items (
        item_id           INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_id        INTEGER NOT NULL REFERENCES receipts (receipt_id) ON DELETE CASCADE,
        name              TEXT NOT NULL,
        unit_price_cents  INTEGER NOT NULL CHECK (unit_price_cents >= 0),
        quantity          TEXT NOT NULL,
        category          TEXT NOT NULL
    )
    """,
    "CREATE INDEX idx_receipt_items_receipt_id ON receipt_items (receipt_id)",
    """
    CREATE TABLE transactions (
        transaction_id  INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        date            TEXT NOT NULL,
        amount_cents    INTEGER NOT NULL CHECK (amount_cents >= 0),
        type            TEXT NOT NULL CHECK (type IN ('income', 'expense')),
        receipt_id      INTEGER UNIQUE REFERENCES receipts (receipt_id) ON DELETE SET NULL,
        created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX idx_transactions_date ON transactions (date)",
)
