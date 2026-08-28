"""Localisation. Four complete catalogues, one never-raising lookup.

Two rules:

* ``translate`` NEVER raises. A missing key or a missing parameter degrades to something
  readable and logs the defect — a customer must never see a stack trace because a
  translator forgot a placeholder.
* Every interpolated value is HTML-escaped here, once, at the boundary. Every message the
  bot sends uses ``parse_mode=HTML``, and user-supplied text (names, notes, lyric bodies)
  flows into these templates. Escaping at the call site would be a rule nobody remembers.
"""

from __future__ import annotations

import html
from collections.abc import Mapping
from typing import Any, Final

from hbd.bot.locales import CATALOGUES, REFERENCE_LANGUAGE
from hbd.contracts import Genre, Language, Occasion, VoiceGender
from hbd.logging import get_logger

__all__ = [
    "translate",
    "escape_html",
    "language_label",
    "occasion_label",
    "genre_label",
    "vocal_gender_label",
    "parse_language",
    "FALLBACK_LANGUAGE",
    "SUPPORTED_LANGUAGES",
]

_LOG = get_logger(__name__)

#: Interface default when we have not asked the user yet, and the first fallback for a
#: key that a locale is missing.
FALLBACK_LANGUAGE: Final[Language] = Language.UZ_LATN

SUPPORTED_LANGUAGES: Final[tuple[Language, ...]] = (
    Language.UZ_LATN,
    Language.UZ_CYRL,
    Language.RU,
    Language.EN,
)


class _SafeParams(dict[str, object]):
    """A format mapping that renders an unknown placeholder instead of raising."""

    def __missing__(self, key: str) -> str:
        _LOG.error("i18n placeholder missing", extra={"placeholder": key})
        return "{" + key + "}"


def escape_html(value: object) -> str:
    """HTML-escape any value for safe interpolation into a ``parse_mode=HTML`` message."""
    return html.escape(str(value), quote=False)


def _lookup(key: str, language: Language) -> str | None:
    catalogue: Mapping[str, str] = CATALOGUES.get(language, {})
    return catalogue.get(key)


def _resolve_template(key: str, language: Language) -> str:
    for candidate in (language, FALLBACK_LANGUAGE, REFERENCE_LANGUAGE):
        template = _lookup(key, candidate)
        if template is not None:
            if candidate is not language:
                _LOG.warning(
                    "i18n key missing in requested locale",
                    extra={"i18n_key": key, "language": str(language), "used": str(candidate)},
                )
            return template
    _LOG.error("i18n key missing in every catalogue", extra={"i18n_key": key})
    return key


def translate(key: str, language: Language, **params: Any) -> str:
    """Return the localised string for ``key``. Never raises.

    Every value in ``params`` is HTML-escaped before interpolation.
    """
    template = _resolve_template(key, language)
    if not params:
        return template
    escaped = _SafeParams({name: escape_html(value) for name, value in params.items()})
    try:
        return template.format_map(escaped)
    except (IndexError, KeyError, ValueError) as exc:
        _LOG.error(
            "i18n template could not be formatted",
            extra={"i18n_key": key, "language": str(language), "reason": str(exc)},
        )
        return template


def language_label(value: Language, language: Language) -> str:
    return translate(f"language.{value.value}", language)


def occasion_label(value: Occasion, language: Language) -> str:
    return translate(f"occasion.{value.value}", language)


def genre_label(value: Genre, language: Language) -> str:
    return translate(f"genre.{value.value}", language)


def vocal_gender_label(value: VoiceGender, language: Language) -> str:
    return translate(f"vocal_gender.{value.value}", language)


def parse_language(code: str | None) -> Language:
    """Read a language code that came from FSM storage or a callback. Never raises."""
    if not code:
        return FALLBACK_LANGUAGE
    try:
        return Language(code)
    except ValueError:
        _LOG.warning("unknown language code, falling back", extra={"code": code})
        return FALLBACK_LANGUAGE
