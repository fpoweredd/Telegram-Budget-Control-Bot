"""Receipt lifecycle: recognize → preview → add as expense, retry or cancel."""

from collections.abc import Callable
from datetime import date

from loguru import logger

from src.db.database import Database
from src.db.repositories import ReceiptRepository, TransactionRepository, UserRepository
from src.domain.models import Author, ParsedReceipt, Receipt, ReceiptStatus, TransactionType
from src.services.receipt_parser import ReceiptParser, ReceiptRecognitionError

__all__ = [
    "ReceiptAlreadyHandledError",
    "ReceiptNotFoundError",
    "ReceiptService",
    "ReceiptTotalMissingError",
]


class ReceiptNotFoundError(LookupError):
    """No receipt with this id belongs to this user."""


class ReceiptAlreadyHandledError(RuntimeError):
    """The receipt was already added or cancelled (e.g. a double tap)."""


class ReceiptTotalMissingError(ValueError):
    """The receipt has no readable total, so it cannot become an expense."""


class ReceiptService:
    def __init__(
        self,
        db: Database,
        receipts: ReceiptRepository,
        transactions: TransactionRepository,
        users: UserRepository,
        parser: ReceiptParser,
        clock: Callable[[], date],
    ) -> None:
        self._db = db
        self._receipts = receipts
        self._transactions = transactions
        self._users = users
        self._parser = parser
        self._clock = clock

    async def register(
        self, *, user_id: int, chat_id: int, photo_file_id: str, photo_message_id: int, image: bytes
    ) -> Receipt:
        """Store a new pending receipt and try to recognize it.

        A failed recognition still creates the receipt, so the user can retry or cancel it.
        """
        async with self._db.transaction() as conn:
            receipt_id = await self._receipts.create(
                conn,
                user_id=user_id,
                chat_id=chat_id,
                photo_file_id=photo_file_id,
                photo_message_id=photo_message_id,
            )
        logger.info("Receipt {} created by user {}", receipt_id, user_id)
        return await self._recognize(receipt_id, image)

    async def reprocess(self, receipt_id: int, user_id: int, image: bytes) -> Receipt:
        receipt = await self.get_pending(receipt_id, user_id)
        return await self._recognize(receipt.receipt_id, image)

    async def get_pending(self, receipt_id: int, user_id: int) -> Receipt:
        receipt = await self._receipts.get(receipt_id)
        if receipt is None or receipt.user_id != user_id:
            raise ReceiptNotFoundError(f"receipt {receipt_id} not found for user {user_id}")
        if receipt.status is not ReceiptStatus.PENDING:
            raise ReceiptAlreadyHandledError(f"receipt {receipt_id} is {receipt.status}")
        return receipt

    async def add_as_expense(self, receipt_id: int, author: Author) -> Receipt:
        """Turn a pending receipt into an expense exactly once."""
        receipt = await self.get_pending(receipt_id, author.user_id)
        total = receipt.parsed.total_cents
        if total is None or total <= 0:
            raise ReceiptTotalMissingError(f"receipt {receipt_id} has no total")

        async with self._db.transaction() as conn:
            changed = await self._receipts.change_status(
                conn, receipt_id, expected=ReceiptStatus.PENDING, new=ReceiptStatus.ADDED
            )
            if not changed:
                raise ReceiptAlreadyHandledError(f"receipt {receipt_id} was handled concurrently")
            await self._users.upsert(conn, author)
            await self._transactions.add(
                conn,
                user_id=author.user_id,
                kind=TransactionType.EXPENSE,
                amount_cents=total,
                on=self._clock(),
                receipt_id=receipt_id,
            )
        logger.info("Receipt {} added as expense of {} cents", receipt_id, total)
        return await self._require(receipt_id)

    async def cancel(self, receipt_id: int, user_id: int) -> Receipt:
        await self.get_pending(receipt_id, user_id)
        async with self._db.transaction() as conn:
            changed = await self._receipts.change_status(
                conn, receipt_id, expected=ReceiptStatus.PENDING, new=ReceiptStatus.CANCELLED
            )
        if not changed:
            raise ReceiptAlreadyHandledError(f"receipt {receipt_id} was handled concurrently")
        logger.info("Receipt {} cancelled", receipt_id)
        return await self._require(receipt_id)

    async def _recognize(self, receipt_id: int, image: bytes) -> Receipt:
        try:
            recognized = await self._parser.parse(image)
            parsed, raw_json = recognized.parsed, recognized.raw_json
        except ReceiptRecognitionError as e:
            logger.warning("Receipt {} not recognized: {}", receipt_id, e)
            parsed, raw_json = ParsedReceipt(None, None, None), None
        async with self._db.transaction() as conn:
            await self._receipts.save_parsed(conn, receipt_id, parsed, raw_json)
        return await self._require(receipt_id)

    async def _require(self, receipt_id: int) -> Receipt:
        receipt = await self._receipts.get(receipt_id)
        if receipt is None:
            raise ReceiptNotFoundError(f"receipt {receipt_id} disappeared")
        return receipt
