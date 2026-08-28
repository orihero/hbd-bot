"""A catalogue file is external data. Every malformed shape must be a ConfigError."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hbd.contracts import Language
from hbd.errors import ConfigError, ErrorCode
from hbd.i18n.catalog import (
    Catalog,
    key_parity_report,
    load_catalog_file,
    locale_path,
)


def _write(tmp_path: Path, payload: Any, *, name: str = "uz_latn.json") -> Path:
    source = tmp_path / name
    source.write_text(
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return source


def test_loads_a_well_formed_file(tmp_path: Path) -> None:
    # Arrange
    source = _write(tmp_path, {"a.b": "Toʻgʻri", "a.c": {"one": "bitta", "other": "koʻp"}})

    # Act
    catalog = load_catalog_file(Language.UZ_LATN, source)

    # Assert
    assert catalog.language is Language.UZ_LATN
    assert catalog.get("a.b") == "Toʻgʻri"
    assert catalog.plural_keys == frozenset({"a.c"})
    assert catalog.keys == frozenset({"a.b", "a.c"})


def test_returns_none_for_an_absent_key(tmp_path: Path) -> None:
    # Arrange
    catalog = load_catalog_file(Language.EN, _write(tmp_path, {"a.b": "x"}, name="en.json"))

    # Act / Assert
    assert catalog.get("nope") is None


def test_rejects_a_file_that_is_not_json(tmp_path: Path) -> None:
    # Arrange
    source = _write(tmp_path, "{not json")

    # Act / Assert
    with pytest.raises(ConfigError) as caught:
        load_catalog_file(Language.UZ_LATN, source)
    assert caught.value.error_code is ErrorCode.CONFIG_INVALID
    assert "not valid JSON" in caught.value.operator_message


def test_rejects_a_top_level_that_is_not_an_object(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="top level must be an object"):
        load_catalog_file(Language.EN, _write(tmp_path, ["a"], name="en.json"))


def test_rejects_an_empty_catalogue(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="contains no keys"):
        load_catalog_file(Language.EN, _write(tmp_path, {}, name="en.json"))


def test_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot be read"):
        load_catalog_file(Language.EN, tmp_path / "absent.json")


def test_rejects_a_blank_template(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="empty template"):
        load_catalog_file(Language.EN, _write(tmp_path, {"a.b": "   "}, name="en.json"))


def test_rejects_an_entry_that_is_neither_string_nor_object(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="must be a string or an object"):
        load_catalog_file(Language.EN, _write(tmp_path, {"a.b": 7}, name="en.json"))


def test_rejects_a_plural_form_that_is_not_a_string(tmp_path: Path) -> None:
    # Arrange
    source = _write(tmp_path, {"a.b": {"one": "x", "other": 3}}, name="en.json")

    # Act / Assert
    with pytest.raises(ConfigError, match="is not a string"):
        load_catalog_file(Language.EN, source)


def test_rejects_english_plural_entry_missing_a_category(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="requires exactly"):
        load_catalog_file(Language.EN, _write(tmp_path, {"a.b": {"one": "x"}}, name="en.json"))


def test_rejects_russian_plural_entry_using_the_english_shape(tmp_path: Path) -> None:
    # Arrange — the classic mistake: copying en.json and translating it word for word.
    source = _write(tmp_path, {"a.b": {"one": "набор", "other": "наборы"}}, name="ru.json")

    # Act / Assert
    with pytest.raises(ConfigError) as caught:
        load_catalog_file(Language.RU, source)
    assert "'few'" in caught.value.operator_message


def test_rejects_uz_latn_copy_containing_an_apostrophe_look_alike(tmp_path: Path) -> None:
    # Arrange
    source = _write(tmp_path, {"a.b": "To'gʻri"})

    # Act / Assert
    with pytest.raises(ConfigError) as caught:
        load_catalog_file(Language.UZ_LATN, source)
    assert "U+0027" in caught.value.operator_message


def test_rejects_uz_latn_look_alike_inside_a_plural_form(tmp_path: Path) -> None:
    # Arrange
    source = _write(tmp_path, {"a.b": {"one": "bitta", "other": "ko‘p"}})

    # Act / Assert
    with pytest.raises(ConfigError) as caught:
        load_catalog_file(Language.UZ_LATN, source)
    assert "U+2018" in caught.value.operator_message
    assert "a.b.other" in caught.value.operator_message


def test_allows_an_apostrophe_look_alike_in_other_languages(tmp_path: Path) -> None:
    # Arrange — English copy legitimately uses a curly apostrophe.
    source = _write(tmp_path, {"a.b": "It’s ready"}, name="en.json")

    # Act
    catalog = load_catalog_file(Language.EN, source)

    # Assert
    assert catalog.get("a.b") == "It’s ready"


def test_error_context_names_the_offending_file(tmp_path: Path) -> None:
    # Arrange
    source = _write(tmp_path, {"a.b": ""}, name="en.json")

    # Act
    with pytest.raises(ConfigError) as caught:
        load_catalog_file(Language.EN, source)

    # Assert
    assert caught.value.context["locale_file"] == str(source)
    assert caught.value.is_retryable is False


def test_catalog_entries_cannot_be_mutated_through_the_public_mapping(tmp_path: Path) -> None:
    # Arrange
    catalog = load_catalog_file(Language.EN, _write(tmp_path, {"a.b": "x"}, name="en.json"))

    # Act / Assert
    with pytest.raises(TypeError):
        catalog.entries["a.b"] = "y"  # type: ignore[index]


def test_locale_path_is_named_after_the_language_value() -> None:
    assert locale_path(Language.UZ_CYRL).name == "uz_cyrl.json"


def test_key_parity_report_names_the_locale_that_is_short_a_key() -> None:
    # Arrange
    full = Catalog(language=Language.EN, entries={"a": "1", "b": "2"})
    short = Catalog(language=Language.RU, entries={"a": "1"})

    # Act
    report = key_parity_report({Language.EN: full, Language.RU: short})

    # Assert
    assert report[Language.EN] == frozenset()
    assert report[Language.RU] == frozenset({"b"})
