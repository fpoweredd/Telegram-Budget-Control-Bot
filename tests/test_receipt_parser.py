import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from google.genai import errors

from src.domain.categories import Category
from src.services.receipt_parser import GeminiReceiptParser, ReceiptRecognitionError, parse_receipt_json

VALID = {
    "total": 29.9,
    "date": "2025-06-01",
    "store": "Carrefour",
    "items": [
        {"name": "Rioja wine", "price": 7.5, "quantity": 1, "category": "alcohol"},
        {"name": "Bread", "price": 1.2, "quantity": 2, "category": "groceries"},
        {"name": "Batteries AAA", "price": 3.9, "quantity": None, "category": "household"},
    ],
}


def test_parse_receipt_json_with_valid_answer_returns_cents_and_categories() -> None:
    parsed = parse_receipt_json(json.dumps(VALID))

    assert parsed.store == "Carrefour"
    assert parsed.purchase_date == date(2025, 6, 1)
    assert parsed.total_cents == 2990
    assert [(i.name, i.unit_price_cents, i.quantity, i.category) for i in parsed.items] == [
        ("Rioja wine", 750, Decimal(1), Category.ALCOHOL),
        ("Bread", 120, Decimal(2), Category.GROCERIES),
        ("Batteries AAA", 390, Decimal(1), Category.HOUSEHOLD),
    ]


def test_parse_receipt_json_with_nulls_keeps_what_is_readable() -> None:
    parsed = parse_receipt_json(json.dumps({"total": None, "date": "01.06.2025", "store": "  ", "items": []}))

    assert parsed.total_cents is None
    assert parsed.purchase_date is None  # not ISO: treated as unreadable, not guessed
    assert parsed.store is None
    assert parsed.is_empty


def test_parse_receipt_json_drops_items_without_price_and_maps_unknown_categories() -> None:
    answer = {
        "total": 5,
        "items": [
            {"name": "Mystery", "price": None, "category": "groceries"},
            {"name": "Хлеб", "price": 1, "quantity": 0, "category": "еда"},
            {"name": "Gadget", "price": 4, "category": "toys"},
        ],
    }
    parsed = parse_receipt_json(json.dumps(answer))

    assert [(i.name, i.quantity, i.category) for i in parsed.items] == [
        ("Хлеб", Decimal(1), Category.GROCERIES),
        ("Gadget", Decimal(1), Category.OTHER),
    ]


def test_parse_receipt_json_rejects_negative_total() -> None:
    assert parse_receipt_json(json.dumps({"total": -3})).total_cents is None


@pytest.mark.parametrize("text", ["", "not json", "```json\n{}\n```", '{"total": "lots"}', "[]"])
def test_parse_receipt_json_with_invalid_answer_raises(text: str) -> None:
    with pytest.raises(ReceiptRecognitionError):
        parse_receipt_json(text)


def _client(generate: AsyncMock) -> MagicMock:
    client = MagicMock()
    client.aio.models.generate_content = generate
    return client


async def test_gemini_parser_requests_json_with_schema_and_returns_receipt() -> None:
    generate = AsyncMock(return_value=SimpleNamespace(text=json.dumps(VALID)))
    parser = GeminiReceiptParser(_client(generate), "gemini-test", timeout_seconds=5)

    result = await parser.parse(b"jpeg-bytes")

    assert result.parsed.total_cents == 2990
    assert generate.await_args is not None
    kwargs = generate.await_args.kwargs
    assert kwargs["model"] == "gemini-test"
    assert kwargs["config"].response_mime_type == "application/json"
    assert kwargs["config"].response_schema is not None


@pytest.mark.parametrize(
    "error",
    [
        errors.APIError(503, {"error": {"message": "overloaded"}}),
        httpx.ConnectError("offline"),
        TimeoutError(),
    ],
)
async def test_gemini_parser_wraps_transport_errors(error: Exception) -> None:
    parser = GeminiReceiptParser(_client(AsyncMock(side_effect=error)), "gemini-test", timeout_seconds=5)

    with pytest.raises(ReceiptRecognitionError):
        await parser.parse(b"jpeg-bytes")


async def test_gemini_parser_with_empty_answer_raises() -> None:
    parser = GeminiReceiptParser(_client(AsyncMock(return_value=SimpleNamespace(text=None))), "m", timeout_seconds=5)

    with pytest.raises(ReceiptRecognitionError):
        await parser.parse(b"jpeg-bytes")
