"""Which alphabet is this name written in, and which language does that imply?

Three questions, three answers:

* **Latin or Cyrillic?** Decided by counting letters, not by guessing from the language the
  user picked — a Russian-speaking user routinely types a Latin name and vice versa.
* **Mixed?** ``Alisher Навоий`` happens (autocorrect, a paste, two keyboards). We report it
  so the caller can pick the dominant script deliberately instead of silently.
* **Uzbek Cyrillic or Russian Cyrillic?** Ў Қ Ғ Ҳ exist only in the Uzbek alphabet; ы and щ
  are effectively Russian-only. That distinction changes the transliteration table.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Final

from hbd.contracts import Language, Script

__all__ = [
    "ScriptProfile",
    "UZBEK_CYRILLIC_MARKERS",
    "RUSSIAN_CYRILLIC_MARKERS",
    "detect_script",
    "is_uzbek_cyrillic",
    "is_russian_cyrillic",
    "infer_name_language",
]

#: Letters that exist in the Uzbek Cyrillic alphabet and not in the Russian one.
UZBEK_CYRILLIC_MARKERS: Final[frozenset[str]] = frozenset("ўқғҳЎҚҒҲ")

#: Letters that are, in practice, Russian-only. Uzbek Cyrillic keeps ъ, ь, э, ё and ц for
#: loanwords, so those are not evidence; ы and щ are.
RUSSIAN_CYRILLIC_MARKERS: Final[frozenset[str]] = frozenset("ыщЫЩ")

_CYRILLIC_BLOCK_NAME: Final[str] = "CYRILLIC"
_LATIN_BLOCK_NAME: Final[str] = "LATIN"


def _letter_script(character: str) -> str | None:
    """``"LATIN"``, ``"CYRILLIC"``, ``"OTHER"`` or ``None`` for a non-letter."""
    if not character.isalpha():
        return None
    # An unnamed code point yields "", which falls through to OTHER rather than raising.
    first_word = unicodedata.name(character, "").split(" ", 1)[0]
    if first_word == _LATIN_BLOCK_NAME:
        return _LATIN_BLOCK_NAME
    if first_word == _CYRILLIC_BLOCK_NAME:
        return _CYRILLIC_BLOCK_NAME
    if first_word == "MODIFIER":
        return None  # the Uzbek marks are letters but carry no script signal
    return "OTHER"


@dataclass(frozen=True, slots=True)
class ScriptProfile:
    """Letter census of one string. ``script`` is the dominant script, ties go to Latin."""

    script: Script
    latin_letters: int
    cyrillic_letters: int
    other_letters: int

    @property
    def has_letters(self) -> bool:
        return bool(self.latin_letters or self.cyrillic_letters or self.other_letters)

    @property
    def is_mixed(self) -> bool:
        """True when both alphabets appear — a paste artefact, not a normal name."""
        return bool(self.latin_letters and self.cyrillic_letters)


def detect_script(text: str) -> ScriptProfile:
    """Census the letters in ``text``. Never raises; an empty string reports Latin, 0, 0, 0."""
    latin = cyrillic = other = 0
    for character in text:
        match _letter_script(character):
            case "LATIN":
                latin += 1
            case "CYRILLIC":
                cyrillic += 1
            case "OTHER":
                other += 1
            case _:
                continue
    dominant = Script.CYRILLIC if cyrillic > latin else Script.LATIN
    return ScriptProfile(
        script=dominant, latin_letters=latin, cyrillic_letters=cyrillic, other_letters=other
    )


def is_uzbek_cyrillic(text: str) -> bool:
    """True when a letter unique to the Uzbek Cyrillic alphabet appears."""
    return any(character in UZBEK_CYRILLIC_MARKERS for character in text)


def is_russian_cyrillic(text: str) -> bool:
    """True when a letter that is effectively Russian-only appears and no Uzbek marker does."""
    if is_uzbek_cyrillic(text):
        return False
    return any(character in RUSSIAN_CYRILLIC_MARKERS for character in text)


def infer_name_language(text: str, *, fallback: Language) -> Language:
    """Best-effort language of the NAME itself, independent of the interface language.

    Only the script and its marker letters are evidence. When Cyrillic text carries no
    marker either way the fallback wins if it is already Cyrillic, otherwise Russian is the
    safer default for an unmarked Cyrillic string.
    """
    profile = detect_script(text)
    if profile.script is Script.LATIN:
        return fallback if fallback.script is Script.LATIN else Language.UZ_LATN
    if is_uzbek_cyrillic(text):
        return Language.UZ_CYRL
    if is_russian_cyrillic(text):
        return Language.RU
    return fallback if fallback.script is Script.CYRILLIC else Language.RU
