"""CLDR plural categories for the four locales this product ships.

Only integer counts are supported, because every countable thing in this bot is a
whole number: rewrites left, greetings in a kit, kits made today.

Per-language notes:

* **English** and **Uzbek** (both scripts) use ``one`` / ``other``. Uzbek does not
  inflect a noun after a numeral (``1 ta toʻplam`` / ``5 ta toʻplam``), so the two
  Uzbek forms are frequently identical strings. That is correct, not copy-paste: the
  catalogue still carries both categories so a future phrasing that *does* differ has
  somewhere to go, and so the shape of every catalogue matches.
* **Russian** uses ``one`` / ``few`` / ``many``. For integers the CLDR ``other``
  category is unreachable (it exists only for fractional counts), so the catalogues
  do not carry it and ``plural_category`` never returns it for Russian.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from hbd.contracts import Language

__all__ = [
    "PluralCategory",
    "REQUIRED_PLURAL_CATEGORIES",
    "plural_category",
]

#: Russian ``few`` covers a numeral ending in 2-4 …
_RU_FEW_MIN: Final[int] = 2
_RU_FEW_MAX: Final[int] = 4
#: … except in the teens, which are all ``many``.
_RU_TEEN_MIN: Final[int] = 12
_RU_TEEN_MAX: Final[int] = 14
_RU_ELEVEN: Final[int] = 11


class PluralCategory(StrEnum):
    """The CLDR categories this product needs. ``two``/``zero`` are unused here."""

    ONE = "one"
    FEW = "few"
    MANY = "many"
    OTHER = "other"


#: The exact set of forms a plural catalogue entry must define, per language.
#: A catalogue entry with a different set is a load-time ``ConfigError``.
REQUIRED_PLURAL_CATEGORIES: Final[Mapping[Language, frozenset[PluralCategory]]] = MappingProxyType(
    {
        Language.UZ_LATN: frozenset({PluralCategory.ONE, PluralCategory.OTHER}),
        Language.UZ_CYRL: frozenset({PluralCategory.ONE, PluralCategory.OTHER}),
        Language.EN: frozenset({PluralCategory.ONE, PluralCategory.OTHER}),
        Language.RU: frozenset({PluralCategory.ONE, PluralCategory.FEW, PluralCategory.MANY}),
    }
)


def _russian_category(count: int) -> PluralCategory:
    """CLDR ``ru`` rule restricted to integers (``v = 0``)."""
    mod_10 = count % 10
    mod_100 = count % 100
    if mod_10 == 1 and mod_100 != _RU_ELEVEN:
        return PluralCategory.ONE
    if _RU_FEW_MIN <= mod_10 <= _RU_FEW_MAX and not (_RU_TEEN_MIN <= mod_100 <= _RU_TEEN_MAX):
        return PluralCategory.FEW
    return PluralCategory.MANY


def plural_category(language: Language, count: int) -> PluralCategory:
    """Return the CLDR plural category for ``count`` in ``language``.

    Negative counts are categorised by magnitude, matching CLDR behaviour.
    """
    magnitude = abs(count)
    if language is Language.RU:
        return _russian_category(magnitude)
    return PluralCategory.ONE if magnitude == 1 else PluralCategory.OTHER
