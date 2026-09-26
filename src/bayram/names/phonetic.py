"""Phonetic respelling: the name rewritten the way an English-trained model reads it.

No music model on earth accepts IPA, SSML ``<phoneme>`` or a lexicon entry. The only lever
we have is the spelling we hand it, and those models are overwhelmingly trained on English
orthography. So the respelling targets English grapheme habits, not linguistic accuracy:

    Gʻulomjon -> Ghoolomjon      (gʻ = gh, u = oo)
    Xurshid   -> Khoorsheed      (x = kh, i = ee)

Cyrillic input is transliterated to Latin first, so one rule table serves all four
languages. This produces the ``PHONETIC`` candidate and nothing else — it is never shown to
a human, and it is never the display form.
"""

from __future__ import annotations

from typing import Final

from bayram.contracts import Language, Script
from bayram.names.marks import MODIFIER_APOSTROPHE, TURNED_COMMA, canonicalize_marks
from bayram.names.script import detect_script
from bayram.names.translit import cyrillic_to_latin

__all__ = ["respell_phonetically"]

_RESPELLING: Final[dict[str, str]] = {
    # digraphs and the Uzbek letter-marks, matched before any single letter
    f"g{TURNED_COMMA}": "gh",
    f"o{TURNED_COMMA}": "o",
    "sh": "sh",
    "ch": "ch",
    "kh": "kh",
    "zh": "zh",
    "ng": "ng",
    "yo": "yo",
    "yu": "yoo",
    "ya": "ya",
    "ye": "ye",
    "a": "a",
    "b": "b",
    "c": "k",
    "d": "d",
    "e": "e",
    "f": "f",
    "g": "g",
    "h": "h",
    "i": "ee",
    "j": "j",
    "k": "k",
    "l": "l",
    "m": "m",
    "n": "n",
    "o": "o",
    "p": "p",
    "q": "k",
    "r": "r",
    "s": "s",
    "t": "t",
    "u": "oo",
    "v": "v",
    "w": "w",
    "x": "kh",
    "y": "y",
    "z": "z",
    MODIFIER_APOSTROPHE: "",
    TURNED_COMMA: "",
}

_MAX_KEY_LENGTH: Final[int] = max(len(key) for key in _RESPELLING)


def _respell(text: str) -> str:
    """Rewrite every unit, capitalising the first unit of each word from its source casing."""
    lowered = text.lower()
    pieces: list[str] = []
    index = 0
    at_word_start = True
    while index < len(text):
        matched = _match_at(lowered, index)
        if matched is None:
            pieces.append(text[index])
            at_word_start = not text[index].isalpha()
            index += 1
            continue
        key, value = matched
        if at_word_start and text[index].isupper() and value:
            value = value[0].upper() + value[1:]
        pieces.append(value)
        at_word_start = False
        index += len(key)
    return "".join(pieces)


def _match_at(lowered: str, index: int) -> tuple[str, str] | None:
    for length in range(_MAX_KEY_LENGTH, 0, -1):
        key = lowered[index : index + length]
        if len(key) == length and key in _RESPELLING:
            return key, _RESPELLING[key]
    return None


def respell_phonetically(text: str, *, language: Language | None = None) -> str:
    """Return an English-orthography respelling of ``text``.

    Cyrillic input is romanised first; ``language`` is passed to that step so a Russian name
    romanises the Russian way. Word separators are preserved.
    """
    canonical = canonicalize_marks(text)
    if detect_script(canonical).script is Script.CYRILLIC:
        canonical = cyrillic_to_latin(canonical, language=language)
    return _respell(canonical)
