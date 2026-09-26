"""CLDR plural selection for the four shipped locales."""

from __future__ import annotations

import pytest

from bayram.contracts import Language
from bayram.i18n.plurals import (
    REQUIRED_PLURAL_CATEGORIES,
    PluralCategory,
    plural_category,
)


@pytest.mark.parametrize("language", [Language.EN, Language.UZ_LATN, Language.UZ_CYRL])
@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, PluralCategory.OTHER),
        (1, PluralCategory.ONE),
        (2, PluralCategory.OTHER),
        (11, PluralCategory.OTHER),
        (21, PluralCategory.OTHER),
        (100, PluralCategory.OTHER),
    ],
)
def test_one_other_languages_only_single_out_exactly_one(
    language: Language, count: int, expected: PluralCategory
) -> None:
    assert plural_category(language, count) is expected


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, PluralCategory.MANY),
        (1, PluralCategory.ONE),
        (2, PluralCategory.FEW),
        (3, PluralCategory.FEW),
        (4, PluralCategory.FEW),
        (5, PluralCategory.MANY),
        (11, PluralCategory.MANY),
        (12, PluralCategory.MANY),
        (13, PluralCategory.MANY),
        (14, PluralCategory.MANY),
        (15, PluralCategory.MANY),
        (21, PluralCategory.ONE),
        (22, PluralCategory.FEW),
        (25, PluralCategory.MANY),
        (101, PluralCategory.ONE),
        (111, PluralCategory.MANY),
        (112, PluralCategory.MANY),
        (122, PluralCategory.FEW),
    ],
)
def test_russian_follows_cldr_one_few_many(count: int, expected: PluralCategory) -> None:
    assert plural_category(Language.RU, count) is expected


def test_russian_never_returns_other_for_integer_counts() -> None:
    # Arrange
    counts = range(0, 200)

    # Act
    categories = {plural_category(Language.RU, count) for count in counts}

    # Assert
    assert PluralCategory.OTHER not in categories


@pytest.mark.parametrize("language", list(Language))
def test_negative_counts_are_categorised_by_magnitude(language: Language) -> None:
    assert plural_category(language, -1) is plural_category(language, 1)
    assert plural_category(language, -22) is plural_category(language, 22)


def test_every_language_declares_its_required_categories() -> None:
    # Arrange / Act
    declared = set(REQUIRED_PLURAL_CATEGORIES)

    # Assert
    assert declared == set(Language)
    assert REQUIRED_PLURAL_CATEGORIES[Language.RU] == frozenset(
        {PluralCategory.ONE, PluralCategory.FEW, PluralCategory.MANY}
    )
    assert REQUIRED_PLURAL_CATEGORIES[Language.EN] == frozenset(
        {PluralCategory.ONE, PluralCategory.OTHER}
    )


@pytest.mark.parametrize("language", list(Language))
def test_selected_category_is_always_one_the_catalogue_must_define(language: Language) -> None:
    # Arrange
    required = REQUIRED_PLURAL_CATEGORIES[language]

    # Act
    selected = {plural_category(language, count) for count in range(0, 130)}

    # Assert — the renderer can never ask a catalogue for a form it was not obliged to
    # carry. If this fails, some count has no template anywhere.
    assert selected <= required
