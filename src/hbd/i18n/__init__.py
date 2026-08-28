"""Interface localisation for the four locales this product ships complete.

Copy lives in ``locales/*.json`` — data files, not Python literals — so a wording change
is a one-line diff and no module owns a sentence. Code here loads, validates and renders
them.

The one thing to import:

    from hbd.i18n import t
    t("name.prompt", Language.UZ_LATN)
    t("status.orders_found", Language.RU, count=3)          # plural-aware
    translate_error(error, Language.EN)                     # HbdError -> friendly text

Two hard rules this package enforces for itself:

* An ``uz_latn`` string may never contain an apostrophe look-alike (U+0027, U+0060,
  U+00B4, U+2018, U+2019). The oʻ/gʻ diacritic is U+02BB and the tutuq belgisi is
  U+02BC. A file that breaks this is a ``ConfigError`` the moment it loads.
* A key that is missing, a plural form that is absent, a format parameter that was not
  passed: **loud** under pytest (``ValidationError``), logged at ERROR and degraded to
  the key name in production. Never silent, never fatal to a delivery.
"""

from __future__ import annotations

from hbd.i18n.catalog import (
    LOCALE_DIR,
    SUPPORTED_LANGUAGES,
    Catalog,
    Entry,
    PluralForms,
    key_parity_report,
    load_catalog,
    load_catalog_file,
    load_catalogs,
    locale_path,
)
from hbd.i18n.orthography import (
    FORBIDDEN_UZ_LATN_CHARS,
    UZ_LATN_MODIFIER_APOSTROPHE,
    UZ_LATN_TURNED_COMMA,
    describe_chars,
    find_forbidden_chars,
)
from hbd.i18n.plurals import (
    REQUIRED_PLURAL_CATEGORIES,
    PluralCategory,
    plural_category,
)
from hbd.i18n.translator import (
    COUNT_PARAM,
    STRICT_ENV_VAR,
    Translator,
    get_translator,
    is_strict_by_default,
    t,
    translate_error,
)

__all__ = [
    # Rendering
    "t",
    "translate_error",
    "Translator",
    "get_translator",
    "is_strict_by_default",
    "COUNT_PARAM",
    "STRICT_ENV_VAR",
    # Catalogues
    "Catalog",
    "Entry",
    "PluralForms",
    "LOCALE_DIR",
    "SUPPORTED_LANGUAGES",
    "locale_path",
    "load_catalog",
    "load_catalog_file",
    "load_catalogs",
    "key_parity_report",
    # Plurals
    "PluralCategory",
    "REQUIRED_PLURAL_CATEGORIES",
    "plural_category",
    # Uzbek Latin orthography guard
    "UZ_LATN_TURNED_COMMA",
    "UZ_LATN_MODIFIER_APOSTROPHE",
    "FORBIDDEN_UZ_LATN_CHARS",
    "find_forbidden_chars",
    "describe_chars",
]
