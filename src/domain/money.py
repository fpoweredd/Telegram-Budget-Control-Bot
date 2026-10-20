"""Money helpers. Amounts are integer cents everywhere except in the UI."""

import re
from decimal import ROUND_HALF_UP, Decimal

__all__ = [
    "MAX_AMOUNT_CENTS",
    "InvalidAmountError",
    "decimal_to_cents",
    "div_round",
    "format_cents",
    "parse_amount",
]

MAX_AMOUNT_CENTS = 100_000_000  # 1,000,000.00

_CENT = Decimal("0.01")
_AMOUNT_RE = re.compile(r"^\d{1,9}(?:[.,]\d{1,2})?$")
_IGNORED_CHARS = str.maketrans("", "", "   €$+")


class InvalidAmountError(ValueError):
    """User input is not a positive amount with at most two decimals."""


def decimal_to_cents(value: Decimal) -> int:
    """Convert a decimal amount to cents, rounding half up."""
    return int(value.quantize(_CENT, rounding=ROUND_HALF_UP) * 100)


def parse_amount(text: str) -> int:
    """Parse user input like ``12.50``, ``12,50`` or ``1 250 €`` into cents."""
    cleaned = text.translate(_IGNORED_CHARS)
    if not _AMOUNT_RE.fullmatch(cleaned):
        raise InvalidAmountError(f"not an amount: {text!r}")
    cents = decimal_to_cents(Decimal(cleaned.replace(",", ".")))
    if not 0 < cents <= MAX_AMOUNT_CENTS:
        raise InvalidAmountError(f"amount out of range: {text!r}")
    return cents


def format_cents(cents: int) -> str:
    """Format cents as ``1234.50`` (``-1234.50`` for negatives)."""
    sign = "-" if cents < 0 else ""
    units, rest = divmod(abs(cents), 100)
    return f"{sign}{units}.{rest:02d}"


def div_round(numerator: int, denominator: int) -> int:
    """Integer division rounded half away from zero."""
    if denominator <= 0:
        raise ValueError(f"'denominator' must be positive, got {denominator}")
    quotient = (2 * abs(numerator) + denominator) // (2 * denominator)
    return quotient if numerator >= 0 else -quotient
