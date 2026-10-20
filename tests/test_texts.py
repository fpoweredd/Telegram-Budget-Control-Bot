from string import Formatter

import pytest

from src.domain.categories import Category
from src.texts import LOCALES


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(template) if name}


@pytest.mark.parametrize("language", [lang for lang in LOCALES if lang != "en"])
def test_locale_has_the_same_keys_and_placeholders_as_english(language: str) -> None:
    english, other = LOCALES["en"].MESSAGES, LOCALES[language].MESSAGES  # type: ignore[index]

    assert set(other) == set(english)
    for key, template in english.items():
        assert _placeholders(other[key]) == _placeholders(template), key


@pytest.mark.parametrize("language", list(LOCALES))
def test_locale_labels_every_category_and_month(language: str) -> None:
    module = LOCALES[language]  # type: ignore[index]

    assert set(module.CATEGORY_LABELS) == set(Category)
    assert len(module.MONTHS_SHORT) == 12
