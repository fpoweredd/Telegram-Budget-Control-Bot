from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src.db.database import Database
from src.db.migrations import migrate
from src.db.repositories import ReceiptRepository, SettingsRepository, TransactionRepository, UserRepository
from src.domain.categories import Category
from src.domain.models import Author, ParsedReceipt, ReceiptItem
from src.formatting import MessageFormatter
from src.services.budget_service import BudgetService
from src.services.receipt_parser import ReceiptRecognitionError, RecognizedReceipt
from src.services.receipt_service import ReceiptService
from src.texts import Texts

TODAY = date(2026, 3, 22)  # a Sunday
NIK = Author(user_id=1, username="nik", first_name="Nik")
ANNA = Author(user_id=2, username=None, first_name="Anna")


class FakeClock:
    def __init__(self, today: date = TODAY) -> None:
        self.today = today

    def __call__(self) -> date:
        return self.today


@dataclass
class FakeParser:
    """Stands in for Gemini: returns queued results, or raises when the queue holds an error."""

    results: list[ParsedReceipt | ReceiptRecognitionError] = field(default_factory=list)
    calls: int = 0

    async def parse(self, image: bytes, mime_type: str = "image/jpeg") -> RecognizedReceipt:
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, ReceiptRecognitionError):
            raise result
        return RecognizedReceipt(parsed=result, raw_json="{}")


def item(name: str, price_cents: int, category: Category, quantity: str = "1") -> ReceiptItem:
    return ReceiptItem(name, price_cents, Decimal(quantity), category)


@pytest.fixture
def texts() -> Texts:
    return Texts.for_language("en")


@pytest.fixture
def fmt(texts: Texts) -> MessageFormatter:
    return MessageFormatter(texts, "€")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def db(tmp_path: Path, clock: FakeClock) -> AsyncIterator[Database]:
    async with Database(tmp_path / "budget.db") as database:
        await migrate(database, clock(), default_target_days=30)
        yield database


@pytest.fixture
def parser() -> FakeParser:
    return FakeParser()


@pytest.fixture
def budget(db: Database, clock: FakeClock) -> BudgetService:
    return BudgetService(
        db,
        UserRepository(db),
        TransactionRepository(db),
        ReceiptRepository(db),
        SettingsRepository(db),
        clock,
        default_target_days=30,
    )


@pytest.fixture
def receipts(db: Database, clock: FakeClock, parser: FakeParser) -> ReceiptService:
    return ReceiptService(db, ReceiptRepository(db), TransactionRepository(db), UserRepository(db), parser, clock)
