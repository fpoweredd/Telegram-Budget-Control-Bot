"""Receipt recognition with Gemini structured output (google-genai SDK)."""

import asyncio
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

import httpx
from google import genai
from google.genai import errors, types
from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

from src.domain.categories import Category, category_from_legacy
from src.domain.models import ParsedReceipt, ReceiptItem
from src.domain.money import decimal_to_cents

__all__ = [
    "GeminiReceiptParser",
    "ReceiptParser",
    "ReceiptRecognitionError",
    "RecognizedReceipt",
    "parse_receipt_json",
]

MAX_ITEM_NAME_LENGTH = 120
MAX_STORE_LENGTH = 80

PROMPT = f"""You are reading a photo of a shop receipt or invoice.
Return the purchase as JSON that matches the response schema:

- total: the final amount paid, as a number.
- date: the purchase date as YYYY-MM-DD.
- store: the shop, venue or company name, e.g. "Mercadona", "Burger King", "MediaMarkt", "Amazon".
- items: every product or service line with
  - name: the item name as printed (translate nothing),
  - price: the unit price,
  - quantity: the quantity or weight (1 if not printed),
  - category: one of {", ".join(c.value for c in Category)}.

Category hints:
- groceries: food and drinks bought in a supermarket or grocery shop.
- fast_food: fast-food chains; cafe: cafes, bars and restaurants.
- "T-Usual" or "T-Jove" items are public transport tickets: category transport, store "BCN Metro".
- Anything bought in a "Tabacs" / "Estanc" shop or a vape shop (e-liquids, cartridges,
  smoking accessories) is smoking.
- Use other only when nothing else fits.

Use null for anything you cannot read. Do not invent items or amounts."""


class ReceiptRecognitionError(RuntimeError):
    """The receipt could not be recognized (API error, timeout or invalid response)."""


class _GeminiItem(BaseModel):
    name: str | None = None
    price: float | None = None
    quantity: float | None = None
    category: Category = Category.OTHER

    @field_validator("category", mode="before")
    @classmethod
    def _tolerant_category(cls, value: object) -> Category:
        return category_from_legacy(value)


class _GeminiReceipt(BaseModel):
    """Response schema sent to Gemini and used to validate its answer."""

    total: float | None = None
    date: str | None = None
    store: str | None = None
    items: list[_GeminiItem] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RecognizedReceipt:
    """Validated recognition result plus the raw JSON (kept in the database, never logged)."""

    parsed: ParsedReceipt
    raw_json: str


class ReceiptParser(Protocol):
    async def parse(self, image: bytes, mime_type: str = "image/jpeg") -> RecognizedReceipt: ...


def _money(value: float | None) -> int | None:
    if value is None:
        return None
    cents = decimal_to_cents(Decimal(str(value)))
    return cents if cents >= 0 else None


def _iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _clean_text(value: str | None, limit: int) -> str | None:
    if value is None or not value.strip():
        return None
    text = " ".join(value.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _to_item(raw: _GeminiItem) -> ReceiptItem | None:
    price = _money(raw.price)
    if price is None:
        return None
    quantity = Decimal(str(raw.quantity)) if raw.quantity and raw.quantity > 0 else Decimal(1)
    return ReceiptItem(
        name=_clean_text(raw.name, MAX_ITEM_NAME_LENGTH) or "?",
        unit_price_cents=price,
        quantity=quantity.normalize(),
        category=raw.category,
    )


def parse_receipt_json(text: str) -> ParsedReceipt:
    """Validate Gemini's JSON answer and convert it to a ParsedReceipt.

    Invalid items (no price) are dropped; unreadable fields become None.

    Raises:
        ReceiptRecognitionError: the text is not JSON or does not match the schema.
    """
    try:
        raw = _GeminiReceipt.model_validate_json(text)
    except ValidationError as e:
        raise ReceiptRecognitionError(f"invalid receipt JSON: {e.error_count()} error(s)") from e
    items = tuple(item for item in map(_to_item, raw.items) if item is not None)
    return ParsedReceipt(
        store=_clean_text(raw.store, MAX_STORE_LENGTH),
        purchase_date=_iso_date(raw.date),
        total_cents=_money(raw.total),
        items=items,
    )


class GeminiReceiptParser:
    def __init__(self, client: genai.Client, model: str, timeout_seconds: float) -> None:
        self._client = client
        self._model = model
        self._timeout = timeout_seconds
        self._config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_GeminiReceipt,
            temperature=0,
        )

    async def parse(self, image: bytes, mime_type: str = "image/jpeg") -> RecognizedReceipt:
        """Send the photo to Gemini and return the validated result.

        Raises:
            ReceiptRecognitionError: on API errors, timeouts, empty or invalid answers.
        """
        contents: list[types.Part | str] = [types.Part.from_bytes(data=image, mime_type=mime_type), PROMPT]
        try:
            async with asyncio.timeout(self._timeout):
                response = await self._client.aio.models.generate_content(
                    model=self._model, contents=contents, config=self._config
                )
        except TimeoutError as e:
            raise ReceiptRecognitionError(f"Gemini did not answer within {self._timeout:.0f}s") from e
        except errors.APIError as e:
            raise ReceiptRecognitionError(f"Gemini request failed: {e.code} {e.status}: {e.message}") from e
        except httpx.HTTPError as e:
            raise ReceiptRecognitionError(f"Gemini request failed: {type(e).__name__}") from e

        text = response.text
        if not text:
            raise ReceiptRecognitionError("Gemini returned an empty answer")
        parsed = parse_receipt_json(text)
        logger.info(
            "Receipt recognized: {} items, total {}",
            len(parsed.items),
            "missing" if parsed.total_cents is None else "present",
        )
        return RecognizedReceipt(parsed=parsed, raw_json=text)
