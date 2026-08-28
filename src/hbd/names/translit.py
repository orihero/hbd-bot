
# Latin ones are the SUBJECT of this module, not a typo in it.
"""Uzbek Latin <-> Cyrillic transliteration, both directions, digraphs included.

Two tables, one engine. The engine walks the string left to right taking the LONGEST key
that matches at each position, so ``sh``/``ch``/``oʻ``/``gʻ`` win over their first letters,
and restores the source casing onto the result (``Gʻ`` -> ``Ғ``, ``SH`` -> ``Ш``).

Two rules that are easy to get wrong and are therefore explicit here:

* Word-initial ``e`` is ``э`` in Uzbek Cyrillic (``Elyor`` -> ``Элёр``) and word-initial
  ``е`` is ``ye`` going the other way (``Елена`` -> ``Yelena``).
* Ў Қ Ғ Ҳ do not exist in the Russian alphabet. When the target language is Russian they
  are folded to о к г х, so we never hand a Russian model an Uzbek letter.

Russian romanisation uses its own table (``х`` -> ``kh``, ``ж`` -> ``zh``), because the
Uzbek convention (``х`` -> ``x``) turns ``Михаил`` into ``Mixail``.
"""

from __future__ import annotations

from typing import Final

from hbd.contracts import Language, Script
from hbd.names.marks import MODIFIER_APOSTROPHE, TURNED_COMMA, canonicalize_marks
from hbd.names.script import detect_script, is_russian_cyrillic

__all__ = [
    "latin_to_cyrillic",
    "cyrillic_to_latin",
    "transliterate",
    "unromanisable_letters",
]

_LATIN_TO_CYRILLIC: Final[dict[str, str]] = {
    # digraphs first — the engine matches longest-first, this order is documentation
    "oʻ": "ў",
    "gʻ": "ғ",
    "sh": "ш",
    "ch": "ч",
    "kh": "х",
    "ts": "ц",
    "yo": "ё",
    "yu": "ю",
    "ya": "я",
    "ye": "е",
    "a": "а",
    "b": "б",
    "c": "к",
    "d": "д",
    "e": "е",
    "f": "ф",
    "g": "г",
    "h": "ҳ",
    "i": "и",
    "j": "ж",
    "k": "к",
    "l": "л",
    "m": "м",
    "n": "н",
    "o": "о",
    "p": "п",
    "q": "қ",
    "r": "р",
    "s": "с",
    "t": "т",
    "u": "у",
    "v": "в",
    "w": "в",
    "x": "х",
    "y": "й",
    "z": "з",
    MODIFIER_APOSTROPHE: "ъ",
    TURNED_COMMA: "ъ",
}

#: Applied only at a word start, checked before the general table at the same key length.
_LATIN_TO_CYRILLIC_INITIAL: Final[dict[str, str]] = {"e": "э"}

_UZBEK_CYRILLIC_TO_LATIN: Final[dict[str, str]] = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "ғ": f"g{TURNED_COMMA}",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "j",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "қ": "q",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "ў": f"o{TURNED_COMMA}",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "x",
    "ҳ": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": MODIFIER_APOSTROPHE,
    "ы": "i",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
    # Karakalpak is written in Uzbekistan and its Cyrillic alphabet has letters neither
    # Uzbek nor Russian uses. Without these a Karakalpak name silently loses a letter.
    "ә": "a",
    "ң": "ng",
    "ө": "o",
    "ү": "u",
    "ұ": "u",
    "һ": "h",
    "і": "i",
}

#: Russian romanisation differs where it matters for pronunciation, not everywhere.
_RUSSIAN_CYRILLIC_TO_LATIN: Final[dict[str, str]] = {
    **_UZBEK_CYRILLIC_TO_LATIN,
    "х": "kh",
    "ж": "zh",
    "ы": "y",
    "ъ": "",
}

_CYRILLIC_TO_LATIN_INITIAL: Final[dict[str, str]] = {"е": "ye"}

#: Uzbek-only Cyrillic letters folded onto their nearest Russian counterparts. ``ў`` folds to
#: ``о``, not to the ``у`` of conventional Russian spelling (``Улугбек``): these strings are
#: fed to a speech model and never read by a human, and Uzbek ``ў`` is an o-vowel, so ``о``
#: is the spelling that gets it pronounced. The matching fold agrees, deliberately.
_UZBEK_TO_RUSSIAN_LETTERS: Final[dict[str, str]] = {
    "ў": "о",
    "қ": "к",
    "ғ": "г",
    "ҳ": "х",
    "Ў": "О",
    "Қ": "К",
    "Ғ": "Г",
    "Ҳ": "Х",
}

#: The two languages whose Cyrillic alphabet has Ў Қ Ғ Ҳ in it.
_UZBEK_LANGUAGES: Final[frozenset[Language]] = frozenset({Language.UZ_LATN, Language.UZ_CYRL})

_MAX_LATIN_KEY: Final[int] = max(len(key) for key in _LATIN_TO_CYRILLIC)
_MAX_CYRILLIC_KEY: Final[int] = max(len(key) for key in _UZBEK_CYRILLIC_TO_LATIN)


def _is_word_start(text: str, index: int) -> bool:
    if index == 0:
        return True
    return not text[index - 1].isalpha()


def _restore_case(source: str, target: str) -> str:
    """Carry the source segment's casing onto the transliterated segment."""
    if not target:
        return ""
    cased = [character for character in source if character.isupper() or character.islower()]
    if not any(character.isupper() for character in cased):
        return target
    if len(cased) > 1 and all(character.isupper() for character in cased):
        return target.upper()
    return target[0].upper() + target[1:]


def _match_at(
    lowered: str,
    index: int,
    table: dict[str, str],
    initial: dict[str, str] | None,
    max_key_length: int,
) -> tuple[str, str] | None:
    for length in range(max_key_length, 0, -1):
        key = lowered[index : index + length]
        if len(key) != length:
            continue
        if initial is not None and key in initial:
            return key, initial[key]
        if key in table:
            return key, table[key]
    return None


def _apply(text: str, table: dict[str, str], initial: dict[str, str], max_key: int) -> str:
    lowered = text.lower()
    pieces: list[str] = []
    index = 0
    while index < len(text):
        at_word_start = _is_word_start(text, index)
        matched = _match_at(lowered, index, table, initial if at_word_start else None, max_key)
        if matched is None:
            pieces.append(text[index])
            index += 1
            continue
        key, value = matched
        pieces.append(_restore_case(text[index : index + len(key)], value))
        index += len(key)
    return "".join(pieces)


def latin_to_cyrillic(text: str, *, language: Language = Language.UZ_CYRL) -> str:
    """Transliterate Latin text into Cyrillic. Non-Latin characters pass through unchanged.

    ``language`` selects the target alphabet: either Uzbek language keeps Ў Қ Ғ Ҳ, Russian
    and English fold them onto Russian letters.
    """
    converted = _apply(
        canonicalize_marks(text), _LATIN_TO_CYRILLIC, _LATIN_TO_CYRILLIC_INITIAL, _MAX_LATIN_KEY
    )
    if language in _UZBEK_LANGUAGES:
        return converted
    return "".join(_UZBEK_TO_RUSSIAN_LETTERS.get(character, character) for character in converted)


def cyrillic_to_latin(text: str, *, language: Language | None = None) -> str:
    """Transliterate Cyrillic text into Latin. Non-Cyrillic characters pass through unchanged.

    ``language`` picks the romanisation table. When omitted it is inferred: text carrying a
    Russian-only letter romanises the Russian way, everything else the Uzbek way.
    """
    resolved = language if language is not None else _infer_cyrillic_language(text)
    table = _RUSSIAN_CYRILLIC_TO_LATIN if resolved is Language.RU else _UZBEK_CYRILLIC_TO_LATIN
    return _apply(text, table, _CYRILLIC_TO_LATIN_INITIAL, _MAX_CYRILLIC_KEY)


def _infer_cyrillic_language(text: str) -> Language:
    return Language.RU if is_russian_cyrillic(text) else Language.UZ_CYRL


def unromanisable_letters(text: str) -> tuple[str, ...]:
    """Letters that survive romanisation unconverted, in first-seen order.

    A non-empty result means the text is in a script no table here covers — Arabic, Han,
    Greek, or a Cyrillic letter from an alphabet we do not serve. Such a letter would be
    silently dropped from the sound key, quietly turning one name into a different one, so
    callers reject the input instead.
    """
    romanised = cyrillic_to_latin(canonicalize_marks(text))
    unconverted = (
        character
        for character in romanised
        if character.isalpha()
        and not character.isascii()
        and character not in (TURNED_COMMA, MODIFIER_APOSTROPHE)
    )
    return tuple(dict.fromkeys(unconverted))


def transliterate(text: str, *, target: Script, language: Language | None = None) -> str:
    """Convert ``text`` into ``target`` script, leaving it alone if it is already there."""
    profile = detect_script(text)
    if target is Script.CYRILLIC:
        if profile.cyrillic_letters and not profile.latin_letters:
            return text
        return latin_to_cyrillic(text, language=language or Language.UZ_CYRL)
    if profile.latin_letters and not profile.cyrillic_letters:
        return text
    return cyrillic_to_latin(text, language=language)
