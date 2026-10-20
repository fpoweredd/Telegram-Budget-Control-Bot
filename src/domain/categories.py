"""Expense categories: stable keys stored in the database, emoji for the UI."""

from enum import StrEnum

__all__ = ["CATEGORY_EMOJI", "Category", "category_from_legacy"]


class Category(StrEnum):
    GROCERIES = "groceries"
    FAST_FOOD = "fast_food"
    CAFE = "cafe"
    ALCOHOL = "alcohol"
    SMOKING = "smoking"
    PHARMACY = "pharmacy"
    CLOTHING = "clothing"
    HOUSEHOLD = "household"
    ELECTRONICS = "electronics"
    TRANSPORT = "transport"
    SERVICES = "services"
    OTHER = "other"


CATEGORY_EMOJI: dict[Category, str] = {
    Category.GROCERIES: "🍎",
    Category.FAST_FOOD: "🍔",
    Category.CAFE: "☕",
    Category.ALCOHOL: "🍷",
    Category.SMOKING: "🚬",
    Category.PHARMACY: "💊",
    Category.CLOTHING: "👕",
    Category.HOUSEHOLD: "🏠",
    Category.ELECTRONICS: "💻",
    Category.TRANSPORT: "🚌",
    Category.SERVICES: "🛠️",
    Category.OTHER: "📦",
}

# Russian labels that v1 of the bot asked Gemini to return and stored as-is.
_LEGACY_LABELS: dict[str, Category] = {
    "еда": Category.GROCERIES,
    "фастфуд": Category.FAST_FOOD,
    "кафе/ресторан": Category.CAFE,
    "алкоголь": Category.ALCOHOL,
    "курение": Category.SMOKING,
    "аптека": Category.PHARMACY,
    "одежда/обувь": Category.CLOTHING,
    "бытовое": Category.HOUSEHOLD,
    "техника/электроника": Category.ELECTRONICS,
    "транспорт": Category.TRANSPORT,
    "услуги": Category.SERVICES,
    "другое": Category.OTHER,
}


def category_from_legacy(label: object) -> Category:
    """Map a legacy (Russian) label or a current key to a category; unknown values become OTHER."""
    if not isinstance(label, str):
        return Category.OTHER
    normalized = label.strip().lower()
    if normalized in _LEGACY_LABELS:
        return _LEGACY_LABELS[normalized]
    try:
        return Category(normalized)
    except ValueError:
        return Category.OTHER
