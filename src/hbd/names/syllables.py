"""Syllabification, hyphenated respelling, and where the stress falls.

Uzbek syllables are V, CV, VC, CVC or CVCC and every syllable has exactly one vowel, so
splitting reduces to: count the consonants between two vowels and decide how many belong to
the syllable on the left.

* 0 consonants -> the boundary sits between the vowels (``Sa-ida``)
* 1 consonant  -> it opens the next syllable (``Gu-lo-…``, never ``Gul-o-…``)
* 2 or more    -> the last one opens the next syllable, the rest close the previous one
  (``Gu-lom-jon``, ``Shoh-ruh``)

``oʻ`` is one vowel and ``sh``, ``ch``, ``gʻ`` are one consonant each, so the string is
tokenised into units before any counting happens. ``ng`` is deliberately NOT a unit: Uzbek
splits ``yan-gi``, not ``ya-ngi``.

Uzbek stress is on the FINAL syllable. Russian stress is lexical and we do not guess it, so
``stress_index`` returns ``None`` for anything that is not Uzbek.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Final

from hbd.contracts import Language
from hbd.names.marks import MODIFIER_APOSTROPHE, TURNED_COMMA, canonicalize_marks

__all__ = [
    "syllabify",
    "hyphenate",
    "stress_index",
    "SYLLABLE_SEPARATOR",
]

SYLLABLE_SEPARATOR: Final[str] = "-"

#: Multi-character units. Longest first; the tokeniser takes the first that matches.
_LATIN_UNITS: Final[tuple[str, ...]] = (f"o{TURNED_COMMA}", f"g{TURNED_COMMA}", "sh", "ch")

_LATIN_VOWELS: Final[frozenset[str]] = frozenset({"a", "e", "i", "o", "u", f"o{TURNED_COMMA}"})

_CYRILLIC_VOWELS: Final[frozenset[str]] = frozenset("аеёиоуўэюяы")

_WORD_SEPARATORS: Final[frozenset[str]] = frozenset({" ", "-"})

#: A syllable never STARTS with one of these: the soft/hard signs and the tutuq belgisi
#: modify the consonant before them, so they close a syllable rather than open one
#: (``Санъат`` -> ``Санъ-ат``, never ``Сан-ъат``).
_NEVER_INITIAL: Final[frozenset[str]] = frozenset({"ъ", "ь", MODIFIER_APOSTROPHE})


def _is_vowel(unit: str) -> bool:
    lowered = unit.lower()
    return lowered in _LATIN_VOWELS or lowered in _CYRILLIC_VOWELS


def _tokenize(word: str) -> tuple[str, ...]:
    """Split a word into pronunciation units, treating Uzbek digraphs as single letters."""
    units: list[str] = []
    index = 0
    lowered = word.lower()
    while index < len(word):
        for unit in _LATIN_UNITS:
            if lowered.startswith(unit, index):
                units.append(word[index : index + len(unit)])
                index += len(unit)
                break
        else:
            units.append(word[index])
            index += 1
    return tuple(units)


def _vowel_positions(units: tuple[str, ...]) -> tuple[int, ...]:
    return tuple(index for index, unit in enumerate(units) if _is_vowel(unit))


def _boundaries(units: tuple[str, ...], vowels: tuple[int, ...]) -> tuple[int, ...]:
    """Indices at which a new syllable starts, derived from the consonant runs."""
    starts: list[int] = []
    for previous, current in pairwise(vowels):
        consonants = current - previous - 1
        # No consonant: the break sits on the vowel. Otherwise exactly one consonant — the
        # last of the run — opens the next syllable and the rest close the previous one.
        start = current if consonants == 0 else current - 1
        while start < current and units[start].lower() in _NEVER_INITIAL:
            start += 1
        starts.append(start)
    return tuple(starts)


def _syllabify_word(word: str) -> tuple[str, ...]:
    units = _tokenize(word)
    if not units:
        return ()
    vowels = _vowel_positions(units)
    if len(vowels) <= 1:
        return (word,)
    starts = _boundaries(units, vowels)
    pieces: list[str] = []
    cursor = 0
    for start in starts:
        pieces.append("".join(units[cursor:start]))
        cursor = start
    pieces.append("".join(units[cursor:]))
    return tuple(piece for piece in pieces if piece)


def syllabify(text: str) -> tuple[str, ...]:
    """Split ``text`` into syllables. Separators between words are preserved as their own units.

    ``syllabify("Gʻulomjon")`` -> ``("Gʻu", "lom", "jon")``.
    ``syllabify("Ali Vali")``  -> ``("A", "li", " ", "Va", "li")``.
    """
    canonical = canonicalize_marks(text)
    syllables: list[str] = []
    buffer: list[str] = []
    for character in canonical:
        if character in _WORD_SEPARATORS:
            syllables.extend(_syllabify_word("".join(buffer)))
            syllables.append(character)
            buffer = []
            continue
        buffer.append(character)
    syllables.extend(_syllabify_word("".join(buffer)))
    return tuple(syllables)


def hyphenate(text: str, *, separator: str = SYLLABLE_SEPARATOR) -> str:
    """Join the syllables of ``text`` with ``separator``: ``Gulomjon`` -> ``Gu-lom-jon``.

    A separator already present in the source (a space, an existing hyphen) is kept as-is and
    is not doubled up.
    """
    pieces: list[str] = []
    for syllable in syllabify(text):
        if syllable in _WORD_SEPARATORS:
            pieces.append(syllable)
            continue
        if pieces and pieces[-1] not in _WORD_SEPARATORS:
            pieces.append(separator)
        pieces.append(syllable)
    return "".join(pieces)


def stress_index(syllables: tuple[str, ...], *, language: Language) -> int | None:
    """Index of the stressed syllable, or ``None`` when the language's stress is lexical.

    Uzbek stress is on the final syllable of the word. Russian and English stress cannot be
    derived from spelling, and guessing it would be worse than admitting we do not know.
    """
    if language not in (Language.UZ_LATN, Language.UZ_CYRL):
        return None
    spoken = [index for index, unit in enumerate(syllables) if unit not in _WORD_SEPARATORS]
    return spoken[-1] if spoken else None
