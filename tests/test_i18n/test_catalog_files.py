"""The four shipped catalogues, checked as data: parity, orthography, plural shape."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Final

import pytest

from hbd.contracts import Language
from hbd.i18n.catalog import (
    SUPPORTED_LANGUAGES,
    Catalog,
    Entry,
    key_parity_report,
    load_catalog,
    load_catalogs,
    locale_path,
)
from hbd.i18n.orthography import (
    FORBIDDEN_UZ_LATN_CHARS,
    UZ_LATN_TURNED_COMMA,
    describe_chars,
    find_forbidden_chars,
)
from hbd.i18n.plurals import REQUIRED_PLURAL_CATEGORIES

#: Keys the error hierarchy promises every catalogue defines. Mirrors errors.py.
REQUIRED_ERROR_KEYS: Final[frozenset[str]] = frozenset(
    {
        "error.generic",
        "error.service_unavailable",
        "error.invalid_input",
        "error.content_not_allowed",
        "error.provider_generic",
        "error.provider_slow",
        "error.provider_busy",
        "error.name_pronunciation_best_effort",
        "error.delivery_failed",
        "error.payment_failed",
    }
)

#: Russian words that look illiterate — or change meaning — when ё loses its diaeresis.
#: Compared against the case-folded file, so capitalisation cannot slip one past.
#: A catalogue edit that drops the diaeresis fails here, not in front of a customer.
RU_YO_DROPPED_SPELLINGS: Final[tuple[str, ...]] = (
    "еще",
    "займет",
    "платеж",
    "все верно",
    "придет",
    "зайдет",
    "прошел",
    "зачет",
    "тяжелый",
)


@pytest.fixture(scope="module")
def catalogs() -> Mapping[Language, Catalog]:
    return load_catalogs()


def _iter_templates(catalog: Catalog) -> Iterator[tuple[str, str]]:
    """Yield ``(key, template)`` for every string in a catalogue, plurals expanded."""
    for key, entry in catalog.entries.items():
        if isinstance(entry, str):
            yield key, entry
            continue
        for category, form in entry.items():
            yield f"{key}.{category}", form


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------
def test_all_four_locales_ship_and_load() -> None:
    # Arrange / Act
    loaded = load_catalogs()

    # Assert
    assert set(loaded) == set(Language)
    assert SUPPORTED_LANGUAGES == (
        Language.UZ_LATN,
        Language.UZ_CYRL,
        Language.RU,
        Language.EN,
    )
    for language in Language:
        assert locale_path(language).is_file()


def test_no_key_is_missing_or_orphaned_in_any_locale(
    catalogs: Mapping[Language, Catalog],
) -> None:
    # Arrange / Act
    report = key_parity_report(catalogs)

    # Assert — an entry here is either a key one locale forgot or a key only one has.
    assert {language: sorted(missing) for language, missing in report.items() if missing} == {}


def test_a_key_is_a_plural_entry_in_every_locale_or_none(
    catalogs: Mapping[Language, Catalog],
) -> None:
    # Arrange
    plural_key_sets = {language: catalog.plural_keys for language, catalog in catalogs.items()}

    # Act
    reference = plural_key_sets[Language.EN]

    # Assert
    assert all(keys == reference for keys in plural_key_sets.values())
    assert reference, "at least one key must exercise the plural machinery"


def test_every_error_hierarchy_key_is_defined_everywhere(
    catalogs: Mapping[Language, Catalog],
) -> None:
    for language, catalog in catalogs.items():
        missing = REQUIRED_ERROR_KEYS - catalog.keys
        assert not missing, f"{language.value} is missing error keys {sorted(missing)}"


def test_every_language_and_genre_enum_member_has_a_button_label(
    catalogs: Mapping[Language, Catalog],
) -> None:
    # Arrange
    from hbd.contracts import Genre, Occasion, VoiceGender

    expected = (
        {f"language.{member.value}" for member in Language}
        | {f"genre.{member.value}" for member in Genre}
        | {f"occasion.{member.value}" for member in Occasion}
        | {f"voice.{member.value}" for member in VoiceGender}
    )

    # Act / Assert
    for language, catalog in catalogs.items():
        missing = expected - catalog.keys
        assert not missing, f"{language.value} is missing enum labels {sorted(missing)}"


# ---------------------------------------------------------------------------
# Orthography
# ---------------------------------------------------------------------------
def test_uz_latn_catalogue_never_uses_an_apostrophe_look_alike() -> None:
    # Arrange — read the raw file so a bad character in a KEY fails too, not only in a
    # value the loader happens to validate.
    raw = locale_path(Language.UZ_LATN).read_text(encoding="utf-8")

    # Act
    found = find_forbidden_chars(raw)

    # Assert
    assert found == (), (
        f"uz_latn.json contains {describe_chars(found)}; "
        f"use U+02BB for oʻ/gʻ and U+02BC for the tutuq belgisi"
    )


def test_uz_latn_catalogue_actually_uses_the_turned_comma() -> None:
    # Arrange
    catalog = load_catalog(Language.UZ_LATN)

    # Act
    with_diacritic = [
        key for key, template in _iter_templates(catalog) if UZ_LATN_TURNED_COMMA in template
    ]

    # Assert — guards against "fixing" the previous test by stripping the character.
    assert len(with_diacritic) > 20


@pytest.mark.parametrize("forbidden", FORBIDDEN_UZ_LATN_CHARS)
def test_uz_latn_guard_would_catch_each_look_alike(forbidden: str) -> None:
    # Arrange — a mutation of real copy, to prove the guard is not vacuous.
    mutated = f"Toʻgʻri{forbidden}"

    # Act / Assert
    assert find_forbidden_chars(mutated) == (forbidden,)


def test_russian_catalogue_preserves_the_yo_vowel() -> None:
    # Arrange
    raw = locale_path(Language.RU).read_text(encoding="utf-8").casefold()

    # Act
    offenders = [word for word in RU_YO_DROPPED_SPELLINGS if word in raw]

    # Assert
    assert offenders == [], f"ru.json spells {offenders} without ё"


def test_cyrillic_catalogues_are_written_in_cyrillic() -> None:
    # Arrange
    cyrillic_range = range(0x0400, 0x0500)

    for language in (Language.RU, Language.UZ_CYRL):
        catalog = load_catalog(language)
        # Act — language self-names are deliberately written in their own script, so
        # they are excluded from the sweep.
        body = "".join(
            template
            for key, template in _iter_templates(catalog)
            if not key.startswith("language.")
        )
        # Assert
        assert any(ord(char) in cyrillic_range for char in body)


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------
def test_plural_entries_define_exactly_the_categories_their_language_needs(
    catalogs: Mapping[Language, Catalog],
) -> None:
    for language, catalog in catalogs.items():
        required = {category.value for category in REQUIRED_PLURAL_CATEGORIES[language]}
        for key in catalog.plural_keys:
            entry = catalog.get(key)
            assert not isinstance(entry, str)
            assert entry is not None
            assert set(entry) == required, f"{language.value}:{key}"


def test_a_template_placeholder_set_matches_across_locales(
    catalogs: Mapping[Language, Catalog],
) -> None:
    # Arrange
    from string import Formatter

    formatter = Formatter()

    def fields(entry: Entry) -> frozenset[str]:
        templates = (entry,) if isinstance(entry, str) else tuple(entry.values())
        return frozenset(
            field for template in templates for _, field, _, _ in formatter.parse(template) if field
        )

    reference = {key: fields(entry) for key, entry in catalogs[Language.EN].entries.items()}

    # Act / Assert — a translator who drops {name} would ship a sentence with a hole.
    for language, catalog in catalogs.items():
        for key, entry in catalog.entries.items():
            assert fields(entry) == reference[key], f"{language.value}:{key} placeholders differ"


def test_no_template_is_blank_and_none_leaks_a_python_repr(
    catalogs: Mapping[Language, Catalog],
) -> None:
    for language, catalog in catalogs.items():
        for key, template in _iter_templates(catalog):
            assert template.strip(), f"{language.value}:{key} is blank"
            assert "{'" not in template, f"{language.value}:{key} looks like a dict repr"


def test_locale_files_are_utf8_json_objects_of_strings_or_plural_maps() -> None:
    for language in Language:
        parsed = json.loads(locale_path(language).read_text(encoding="utf-8"))
        assert isinstance(parsed, dict)
        for key, value in parsed.items():
            assert isinstance(key, str)
            assert isinstance(value, str | dict), key
