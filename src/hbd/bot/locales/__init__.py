"""The four complete catalogues. No stub locales.

Each module exposes a plain ``CATALOGUE: dict[str, str]``. ``hbd.bot.i18n`` freezes them
into read-only mappings at import time, so nothing downstream can mutate a catalogue.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from hbd.bot.locales import en, ru, uz_cyrl, uz_latn
from hbd.contracts import Language

__all__ = ["CATALOGUES", "REFERENCE_LANGUAGE"]

#: English is the reference key set: every other catalogue must define exactly these keys.
REFERENCE_LANGUAGE: Final[Language] = Language.EN

CATALOGUES: Final[Mapping[Language, Mapping[str, str]]] = MappingProxyType(
    {
        Language.UZ_LATN: MappingProxyType(dict(uz_latn.CATALOGUE)),
        Language.UZ_CYRL: MappingProxyType(dict(uz_cyrl.CATALOGUE)),
        Language.RU: MappingProxyType(dict(ru.CATALOGUE)),
        Language.EN: MappingProxyType(dict(en.CATALOGUE)),
    }
)
