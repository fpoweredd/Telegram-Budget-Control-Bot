from decimal import Decimal

import pytest

from src.domain.money import InvalidAmountError, decimal_to_cents, div_round, format_cents, parse_amount


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("12", 1200),
        ("12.5", 1250),
        ("12.50", 1250),
        ("12,50", 1250),
        (" 7.06 ", 706),
        ("7,06 €", 706),
        ("1 250,50", 125050),
        ("0.01", 1),
    ],
)
def test_parse_amount_with_valid_input_returns_cents(text: str, cents: int) -> None:
    assert parse_amount(text) == cents


@pytest.mark.parametrize(
    "text",
    ["", "abc", "-5", "0", "0.00", "nan", "inf", "1e9", "12.345", "1.2.3", "10000000000", "12.50.", "€"],
)
def test_parse_amount_with_invalid_input_raises(text: str) -> None:
    with pytest.raises(InvalidAmountError):
        parse_amount(text)


@pytest.mark.parametrize(("cents", "text"), [(0, "0.00"), (706, "7.06"), (-706, "-7.06"), (123456, "1234.56")])
def test_format_cents(cents: int, text: str) -> None:
    assert format_cents(cents) == text


def test_decimal_to_cents_rounds_half_up() -> None:
    assert decimal_to_cents(Decimal("0.125")) == 13
    assert decimal_to_cents(Decimal(str(0.1 + 0.2))) == 30


@pytest.mark.parametrize(("num", "den", "expected"), [(7, 2, 4), (5, 3, 2), (-7, 2, -4), (0, 5, 0)])
def test_div_round_rounds_half_away_from_zero(num: int, den: int, expected: int) -> None:
    assert div_round(num, den) == expected


def test_div_round_with_zero_denominator_raises() -> None:
    with pytest.raises(ValueError):
        div_round(1, 0)
