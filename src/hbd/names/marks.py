
# Latin ones are the SUBJECT of this module, not a typo in it.
"""Unicode canonicalisation of the one character this product lives or dies by.

Uzbek Latin uses two distinct modifier letters that a phone keyboard does not have:

* ``ʻ`` U+02BB MODIFIER LETTER TURNED COMMA — the second half of the digraphs ``oʻ`` and
  ``gʻ`` (``Gʻulomjon``, ``Oʻktam``). It is a LETTER, not punctuation.
* ``ʼ`` U+02BC MODIFIER LETTER APOSTROPHE — the *tutuq belgisi*, which separates syllables
  after any other letter (``Maʼruf``, ``Raʼno``, ``Sanʼat``).

Real input never contains either. It contains U+2018, U+2019 (iOS smart quotes), U+0027
(ASCII), U+0060 (grave), U+00B4 (acute) and a long tail of near-misses. Every one of them
means the same thing to the person typing, so every one of them is canonicalised here —
to U+02BB after ``o``/``g``, to U+02BC everywhere else.

Nothing in this module mutates its input; every function returns a new string.
"""

from __future__ import annotations

import unicodedata
from typing import Final

__all__ = [
    "TURNED_COMMA",
    "MODIFIER_APOSTROPHE",
    "APOSTROPHE_VARIANTS",
    "DIGRAPH_BASE_LETTERS",
    "canonicalize_marks",
    "strip_marks",
    "to_ascii_marks",
    "normalize_input",
    "has_mark",
]

#: U+02BB — the digraph mark in ``oʻ`` / ``gʻ``.
TURNED_COMMA: Final[str] = "ʻ"
#: U+02BC — the tutuq belgisi.
MODIFIER_APOSTROPHE: Final[str] = "ʼ"
#: What an ASCII-only channel gets.
ASCII_APOSTROPHE: Final[str] = "'"

#: Every character a human, a keyboard or an autocorrect might produce for either mark.
#: U+02BB and U+02BC are included so canonicalisation is idempotent and so a mark typed
#: correctly but in the WRONG role (``Maʻruf``) is still re-assigned by role below.
APOSTROPHE_VARIANTS: Final[frozenset[str]] = frozenset(
    {
        "'",  # ' APOSTROPHE
        "`",  # ` GRAVE ACCENT
        "´",  # ´ ACUTE ACCENT
        "ʹ",  # ʹ MODIFIER LETTER PRIME
        "ʺ",  # ʺ MODIFIER LETTER DOUBLE PRIME
        "ʻ",  # ʻ MODIFIER LETTER TURNED COMMA (canonical digraph mark)
        "ʼ",  # ʼ MODIFIER LETTER APOSTROPHE (canonical tutuq belgisi)
        "ʽ",  # ʽ MODIFIER LETTER REVERSED COMMA
        "ˈ",  # ˈ MODIFIER LETTER VERTICAL LINE (stress mark)
        "՚",  # ՚ ARMENIAN APOSTROPHE
        "‘",  # ‘ LEFT SINGLE QUOTATION MARK
        "’",  # ’ RIGHT SINGLE QUOTATION MARK
        "‚",  # ‚ SINGLE LOW-9 QUOTATION MARK
        "‛",  # ‛ SINGLE HIGH-REVERSED-9 QUOTATION MARK
        "′",  # ′ PRIME
        "‵",  # ‵ REVERSED PRIME
        "＇",  # ＇ FULLWIDTH APOSTROPHE
    }
)

#: A mark directly after one of these is the digraph mark, not the tutuq belgisi.
DIGRAPH_BASE_LETTERS: Final[frozenset[str]] = frozenset("oOgG")

#: Invisible characters that survive a copy-paste and break every later comparison.
_ZERO_WIDTH: Final[frozenset[str]] = frozenset("​‌‍‎‏⁠﻿")

_SPACE_LIKE: Final[frozenset[str]] = frozenset("      \t")

#: Dashes a user may type inside a double-barrelled name.
_DASH_LIKE: Final[frozenset[str]] = frozenset("‐‑‒–—−")

#: Control, format, surrogate, private-use and unassigned categories, plus any combining
#: mark that NFC could not compose onto its base (a hand-typed stress accent, for example).
#: Legitimate diacritics survive because NFC precomposes them into single letters first.
_DROPPED: Final[frozenset[str]] = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Mn", "Me"})


def has_mark(text: str) -> bool:
    """True when ``text`` carries any apostrophe-class character, canonical or not."""
    return any(character in APOSTROPHE_VARIANTS for character in text)


def canonicalize_marks(text: str) -> str:
    """Rewrite every apostrophe variant to the correct modifier letter for its role.

    After ``o`` or ``g`` the mark forms a digraph and becomes U+02BB; anywhere else it is
    the tutuq belgisi and becomes U+02BC. A leading mark has no base letter, so it is
    dropped rather than guessed at.
    """
    characters: list[str] = []
    for character in text:
        if character not in APOSTROPHE_VARIANTS:
            characters.append(character)
            continue
        previous = characters[-1] if characters else ""
        if previous == "":
            continue
        characters.append(TURNED_COMMA if previous in DIGRAPH_BASE_LETTERS else MODIFIER_APOSTROPHE)
    return "".join(characters)


def strip_marks(text: str) -> str:
    """Remove every apostrophe-class character: ``Gʻulomjon`` -> ``Gulomjon``."""
    return "".join(character for character in text if character not in APOSTROPHE_VARIANTS)


def to_ascii_marks(text: str) -> str:
    """Replace every apostrophe-class character with U+0027: ``Gʻulomjon`` -> ``G'ulomjon``."""
    return "".join(
        ASCII_APOSTROPHE if character in APOSTROPHE_VARIANTS else character for character in text
    )


def normalize_input(text: str) -> str:
    """The single entry point for raw user text.

    NFC-composes, deletes invisibles and control characters, folds exotic spaces and dashes
    to ASCII, collapses runs of whitespace, trims, then canonicalises the marks. Idempotent.
    """
    composed = unicodedata.normalize("NFC", text)
    cleaned: list[str] = []
    for character in composed:
        if character in _ZERO_WIDTH:
            continue
        if character in _SPACE_LIKE:
            cleaned.append(" ")
            continue
        if character in _DASH_LIKE:
            cleaned.append("-")
            continue
        if character not in APOSTROPHE_VARIANTS and unicodedata.category(character) in _DROPPED:
            continue
        cleaned.append(character)
    collapsed = " ".join("".join(cleaned).split())
    return canonicalize_marks(collapsed)
