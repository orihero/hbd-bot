"""Loading and validating the four message catalogues.

The catalogues are **data files** (``locales/*.json``), not Python literals, so a
translator can edit copy without touching code and a diff of a wording change is one
line. Every file is validated as it loads, because a file on disk is external data:

* top level must be an object of ``str -> str`` or ``str -> {plural category: str}``
* a plural entry must define exactly the categories its language needs
* an ``uz_latn`` string may not contain an apostrophe look-alike (see ``orthography``)

A malformed file is a ``ConfigError`` at startup, naming the file and the key. What is
*not* enforced here is key parity across the four locales: that is a cross-file
invariant, it is asserted by the test suite, and a single missing key must degrade to
the key name at runtime rather than take the bot down.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Final

from hbd.contracts import Language
from hbd.errors import ConfigError
from hbd.i18n.orthography import describe_chars, find_forbidden_chars
from hbd.i18n.plurals import REQUIRED_PLURAL_CATEGORIES

__all__ = [
    "Entry",
    "PluralForms",
    "Catalog",
    "LOCALE_DIR",
    "SUPPORTED_LANGUAGES",
    "locale_path",
    "load_catalog_file",
    "load_catalog",
    "load_catalogs",
    "key_parity_report",
]

#: Plural entry: category value ("one", "few", …) -> template.
type PluralForms = Mapping[str, str]
#: A catalogue value is either a single template or a set of plural forms.
type Entry = str | PluralForms

LOCALE_DIR: Final[Path] = Path(__file__).resolve().parent / "locales"

#: Every language the interface ships complete. There are no stub locales.
SUPPORTED_LANGUAGES: Final[tuple[Language, ...]] = (
    Language.UZ_LATN,
    Language.UZ_CYRL,
    Language.RU,
    Language.EN,
)


@dataclass(frozen=True, slots=True)
class Catalog:
    """One immutable locale's worth of message templates."""

    language: Language
    entries: Mapping[str, Entry]

    def get(self, key: str) -> Entry | None:
        """Return the entry, or ``None`` when the key is absent. Never raises."""
        return self.entries.get(key)

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(self.entries)

    @property
    def plural_keys(self) -> frozenset[str]:
        return frozenset(key for key, entry in self.entries.items() if not isinstance(entry, str))


def locale_path(language: Language) -> Path:
    """Path of the catalogue file for ``language``. The value is the file stem."""
    return LOCALE_DIR / f"{language.value}.json"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _config_error(source: Path, detail: str) -> ConfigError:
    return ConfigError(
        f"Locale catalogue {source.name} is invalid: {detail}",
        context={"locale_file": str(source)},
    )


def _validate_template(language: Language, source: Path, key: str, value: str) -> str:
    if not value.strip():
        raise _config_error(source, f"key {key!r} has an empty template")
    if language is not Language.UZ_LATN:
        return value
    forbidden = find_forbidden_chars(value)
    if forbidden:
        raise _config_error(
            source,
            f"key {key!r} uses apostrophe look-alikes {describe_chars(forbidden)}; "
            f"Uzbek Latin display copy must use U+02BB (oʻ, gʻ) or U+02BC (tutuq belgisi)",
        )
    return value


def _validate_plural_forms(
    language: Language, source: Path, key: str, value: Mapping[str, object]
) -> PluralForms:
    required = {category.value for category in REQUIRED_PLURAL_CATEGORIES[language]}
    present = set(value)
    if present != required:
        raise _config_error(
            source,
            f"key {key!r} defines plural forms {sorted(present)} "
            f"but {language.value} requires exactly {sorted(required)}",
        )
    forms: dict[str, str] = {}
    for category, template in value.items():
        if not isinstance(template, str):
            raise _config_error(source, f"key {key!r} form {category!r} is not a string")
        forms[category] = _validate_template(language, source, f"{key}.{category}", template)
    return MappingProxyType(forms)


def _validate_entry(language: Language, source: Path, key: str, value: object) -> Entry:
    if isinstance(value, str):
        return _validate_template(language, source, key, value)
    if isinstance(value, dict):
        return _validate_plural_forms(language, source, key, value)
    raise _config_error(
        source,
        f"key {key!r} must be a string or an object of plural forms, got {type(value).__name__}",
    )


def _read_json_object(source: Path) -> Mapping[str, object]:
    try:
        raw = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise _config_error(source, f"cannot be read ({exc})") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _config_error(source, f"is not valid JSON ({exc})") from exc
    if not isinstance(parsed, dict):
        raise _config_error(source, f"top level must be an object, got {type(parsed).__name__}")
    return parsed


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_catalog_file(language: Language, source: Path) -> Catalog:
    """Load and validate one catalogue from an explicit path.

    Raises ``ConfigError`` — and nothing else — when the file is unusable.
    """
    parsed = _read_json_object(source)
    entries = {key: _validate_entry(language, source, key, value) for key, value in parsed.items()}
    if not entries:
        raise _config_error(source, "contains no keys")
    return Catalog(language=language, entries=MappingProxyType(entries))


def load_catalog(language: Language) -> Catalog:
    """Load the packaged catalogue for ``language``."""
    return load_catalog_file(language, locale_path(language))


@lru_cache(maxsize=1)
def load_catalogs() -> Mapping[Language, Catalog]:
    """All four packaged catalogues, loaded once per process."""
    return MappingProxyType({language: load_catalog(language) for language in SUPPORTED_LANGUAGES})


def key_parity_report(catalogs: Mapping[Language, Catalog]) -> Mapping[Language, frozenset[str]]:
    """Keys missing from each catalogue, relative to the union of all of them.

    An empty set for every language means no missing and no orphaned keys. Used by the
    test suite; deliberately not enforced at load time.
    """
    all_keys = frozenset().union(*(catalog.keys for catalog in catalogs.values()))
    return MappingProxyType(
        {language: all_keys - catalog.keys for language, catalog in catalogs.items()}
    )
