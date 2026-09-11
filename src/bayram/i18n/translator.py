"""``t(key, language, **params)`` and the object behind it.

Two behaviours, one code path, chosen by ``is_strict``:

* **In tests** a missing key, a missing plural count or a missing format parameter is a
  loud ``ValidationError``. A typo in a key must never reach review.
* **In production** the same situation is logged at ERROR with the key, the language and
  the reason, and degrades to something harmless — the key name, or the un-substituted
  template. A copy bug must never take down a delivery.

Strictness is decided once, at translator construction: ``BAYRAM_I18N_STRICT`` wins if it
is set, otherwise strict is on whenever pytest is running the process.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from string import Formatter
from typing import Any, Final

from bayram.contracts import Language
from bayram.errors import GENERIC_USER_MESSAGE_KEY, BayramError, ValidationError
from bayram.i18n.catalog import Catalog, Entry, load_catalogs
from bayram.i18n.plurals import plural_category
from bayram.logging import get_logger

__all__ = [
    "Translator",
    "get_translator",
    "t",
    "translate_error",
    "COUNT_PARAM",
    "STRICT_ENV_VAR",
]

_logger: Final = get_logger(__name__)

#: The parameter that selects a plural form. It is also available to the template,
#: so ``{count}`` interpolates without the caller passing it twice.
COUNT_PARAM: Final[str] = "count"
STRICT_ENV_VAR: Final[str] = "BAYRAM_I18N_STRICT"
_PYTEST_ENV_VAR: Final[str] = "PYTEST_CURRENT_TEST"
_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})

_FORMATTER: Final[Formatter] = Formatter()


def is_strict_by_default() -> bool:
    """Strict unless explicitly disabled; on automatically under pytest."""
    override = os.environ.get(STRICT_ENV_VAR)
    if override is not None:
        return override.strip().lower() in _TRUTHY
    return _PYTEST_ENV_VAR in os.environ


def _placeholders(template: str) -> frozenset[str]:
    """Named fields a template needs. ``{{`` literals and indexes are ignored."""
    return frozenset(
        field for _, field, _, _ in _FORMATTER.parse(template) if field and not field.isdigit()
    )


@dataclass(frozen=True, slots=True)
class Translator:
    """Resolves a locale key to a finished string. Holds no mutable state."""

    catalogs: Mapping[Language, Catalog]
    is_strict: bool = False

    # -- public surface -----------------------------------------------------
    def has(self, key: str, language: Language) -> bool:
        catalog = self.catalogs.get(language)
        return catalog is not None and catalog.get(key) is not None

    def translate(self, key: str, language: Language, /, **params: Any) -> str:
        """Return the localised string for ``key``.

        Pass ``count=`` for a pluralised key; it is used to pick the form *and* is
        available to the template as ``{count}``.
        """
        entry = self._entry(key, language)
        if entry is None:
            return key
        template = self._template(key, language, entry, params)
        if template is None:
            return key
        return self._format(key, language, template, params)

    def error_message(self, error: BayramError, language: Language) -> str:
        """The customer-facing side of an ``BayramError``.

        Falls back to ``error.generic`` when a subclass names a key no catalogue
        defines, so an operator-side mistake still produces a friendly sentence.
        """
        if self.has(error.user_message_key, language):
            return self.translate(error.user_message_key, language)
        self._fail(
            "unknown_error_key",
            key=error.user_message_key,
            language=language,
            detail=f"{type(error).__name__} names a key no catalogue defines",
        )
        return self.translate(GENERIC_USER_MESSAGE_KEY, language)

    # -- internals ----------------------------------------------------------
    def _entry(self, key: str, language: Language) -> Entry | None:
        catalog = self.catalogs.get(language)
        if catalog is None:
            self._fail("unknown_language", key=key, language=language)
            return None
        entry = catalog.get(key)
        if entry is None:
            self._fail("missing_key", key=key, language=language)
            return None
        return entry

    def _template(
        self, key: str, language: Language, entry: Entry, params: Mapping[str, Any]
    ) -> str | None:
        if isinstance(entry, str):
            return entry
        count = params.get(COUNT_PARAM)
        if not isinstance(count, int) or isinstance(count, bool):
            self._fail(
                "missing_count",
                key=key,
                language=language,
                detail=f"pluralised key needs an int {COUNT_PARAM}=, got {count!r}",
            )
            return None
        category = plural_category(language, count)
        form = entry.get(category.value)
        if form is None:
            self._fail(
                "missing_plural_form",
                key=key,
                language=language,
                detail=f"no {category.value!r} form for count={count}",
            )
            return None
        return form

    def _format(
        self, key: str, language: Language, template: str, params: Mapping[str, Any]
    ) -> str:
        missing = _placeholders(template) - set(params)
        if missing:
            self._fail(
                "missing_params",
                key=key,
                language=language,
                detail=f"template needs {sorted(missing)}",
            )
            return template
        try:
            return template.format(**params)
        except (IndexError, KeyError, ValueError) as exc:
            self._fail(
                "format_failed", key=key, language=language, detail=f"{type(exc).__name__}: {exc}"
            )
            return template

    def _fail(self, reason: str, *, key: str, language: Language, detail: str = "") -> None:
        """Raise in strict mode; log with full context otherwise. Never silent."""
        message = f"i18n {reason} for key {key!r} in {language.value}"
        if detail:
            message = f"{message}: {detail}"
        if self.is_strict:
            raise ValidationError(
                message, context={"i18n_reason": reason, "key": key, "language": language.value}
            )
        _logger.error(
            message,
            extra={"i18n_reason": reason, "key": key, "language": language.value, "detail": detail},
        )


@lru_cache(maxsize=1)
def get_translator() -> Translator:
    """The process-wide translator over the packaged catalogues."""
    return Translator(catalogs=load_catalogs(), is_strict=is_strict_by_default())


def t(key: str, language: Language, /, **params: Any) -> str:
    """Localise ``key`` into ``language``.

    ``t("status.orders_found", Language.RU, count=3)`` -> ``"3 набора."``
    """
    return get_translator().translate(key, language, **params)


def translate_error(error: BayramError, language: Language) -> str:
    """Friendly, localised text for an error the customer is about to be shown."""
    return get_translator().error_message(error, language)
