"""All user-facing strings. English is the default; LANGUAGE=ru switches to Russian."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from types import ModuleType

from src.config import Language
from src.domain.categories import Category
from src.texts import en, ru

__all__ = ["LOCALES", "Texts"]

LOCALES: dict[Language, ModuleType] = {"en": en, "ru": ru}


@dataclass(frozen=True, slots=True)
class Texts:
    messages: dict[str, str]
    category_labels: dict[Category, str]
    months_short: tuple[str, ...]
    days: Callable[[int], str]

    @classmethod
    def for_language(cls, language: Language) -> "Texts":
        module = LOCALES[language]
        return cls(module.MESSAGES, module.CATEGORY_LABELS, module.MONTHS_SHORT, module.days)

    def __call__(self, key: str, **values: object) -> str:
        return self.messages[key].format(**values)

    def category(self, category: Category) -> str:
        return self.category_labels[category]

    def short_date(self, day: date) -> str:
        """``22 Mar``"""
        return f"{day.day} {self.months_short[day.month - 1]}"

    def long_date(self, day: date) -> str:
        """``3 Apr 2026``"""
        return f"{self.short_date(day)} {day.year}"
