"""The front door: a typed name in, a fully-resolved ``RecipientName`` out.

This is the only function the rest of the system needs. It validates at the boundary,
canonicalises, decides the script and language, builds the ranked candidate list from the
CONFIGURED strategy order, and returns a ``Result`` — never an exception, because a bad name
is a user typo, not a bug.

``candidate_order`` has no default on purpose. The ranking is configuration
(``Settings.name_candidate_order``); making the caller pass it means no code path can
quietly bake in an order that a bake-off has since overturned.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from typing import Final

from hbd.contracts import (
    MAX_RECIPIENT_NAME_CHARS,
    Err,
    Language,
    NameStrategy,
    RecipientName,
    Result,
    err,
    ok,
)
from hbd.errors import ValidationError
from hbd.names.candidates import build_candidates
from hbd.names.forms import DisplayForm
from hbd.names.marks import APOSTROPHE_VARIANTS, normalize_input
from hbd.names.matching import sound_key
from hbd.names.script import detect_script, infer_name_language
from hbd.names.translit import unromanisable_letters

__all__ = ["resolve_name", "display_form", "MAX_NAME_WORDS"]

#: A celebration kit greets one person. More tokens than this is a sentence, not a name.
MAX_NAME_WORDS: Final[int] = 4

#: Punctuation a real name may legitimately contain.
_ALLOWED_PUNCTUATION: Final[frozenset[str]] = frozenset({" ", "-", "."})

#: Unicode letter categories. Uzbek's ʻ is ``Lm``, which is why it counts as a letter here.
_LETTER_CATEGORIES: Final[frozenset[str]] = frozenset({"Lu", "Ll", "Lt", "Lm", "Lo"})


def _invalid(message: str, *, raw: str, reason: str) -> Err:
    return err(
        ValidationError(
            message,
            context={"reason": reason, "raw_length": len(raw), "raw": raw},
        )
    )


def _has_letter(text: str) -> bool:
    return any(
        unicodedata.category(character) in _LETTER_CATEGORIES
        and character not in APOSTROPHE_VARIANTS
        for character in text
    )


def _first_offending_character(text: str) -> str | None:
    for character in text:
        if character in _ALLOWED_PUNCTUATION or character in APOSTROPHE_VARIANTS:
            continue
        if unicodedata.category(character) not in _LETTER_CATEGORIES:
            return character
    return None


def _capitalize_words(text: str) -> str:
    """Capitalise a word only when the user typed it entirely in lower case.

    ``gulomjon`` becomes ``Gulomjon``; ``McDonald`` and ``OʻKTAM`` are left exactly as typed,
    because a name's casing belongs to its owner, not to us.
    """
    words = text.split(" ")
    return " ".join(word if word != word.lower() else word.capitalize() for word in words)


def display_form(raw: str) -> DisplayForm:
    """Canonicalise ``raw`` into the human-facing spelling. Assumes ``raw`` is already valid.

    Prefer ``resolve_name`` at a system boundary; this is for the few places that only need
    the string a customer reads (a preview echo, a lyric-sheet heading).
    """
    return DisplayForm(text=_capitalize_words(normalize_input(raw)))


def _reject(raw: str, *, preserved: str, normalized: str) -> Err | None:
    """The validation gauntlet. Returns the first failure, or ``None`` when the name is usable.

    Ordered cheapest-first, and each failure carries a distinct ``reason`` so the bot layer
    can pick a specific message instead of a generic "that did not work".
    """
    if not normalized:
        return _invalid("recipient name is empty after normalisation", raw=raw, reason="empty")
    longest = max(len(normalized), len(preserved))
    if longest > MAX_RECIPIENT_NAME_CHARS:
        return _invalid(
            f"recipient name is {longest} characters, limit is {MAX_RECIPIENT_NAME_CHARS}",
            raw=raw,
            reason="too_long",
        )
    if not _has_letter(normalized):
        return _invalid("recipient name contains no letters", raw=raw, reason="no_letters")
    offending = _first_offending_character(normalized)
    if offending is not None:
        return _invalid(
            f"recipient name contains an unsupported character {offending!r}",
            raw=raw,
            reason="unsupported_character",
        )
    unromanisable = unromanisable_letters(normalized)
    if unromanisable:
        return _invalid(
            f"recipient name uses letters no romanisation covers: {''.join(unromanisable)}",
            raw=raw,
            reason="unsupported_script",
        )
    if len(normalized.split(" ")) > MAX_NAME_WORDS:
        return _invalid(
            f"recipient name has more than {MAX_NAME_WORDS} words",
            raw=raw,
            reason="too_many_words",
        )
    return None


def resolve_name(
    raw: str,
    *,
    candidate_order: Sequence[NameStrategy],
    ui_language: Language,
) -> Result[RecipientName]:
    """Validate and resolve a typed recipient name.

    ``ui_language`` is only a fallback for inferring the NAME's language when the script
    alone cannot settle it — the two are chosen independently and a Russian-speaking user
    names an Uzbek recipient every day.

    Returns ``Err(ValidationError)`` — never raises — when the input is empty, too long, has
    no letters, carries a digit or symbol, is written in a script we cannot romanise, or
    reads as a sentence rather than a name.
    """
    preserved = raw.strip()
    normalized = normalize_input(preserved)
    rejection = _reject(raw, preserved=preserved, normalized=normalized)
    if rejection is not None:
        return rejection

    display = DisplayForm(text=_capitalize_words(normalized))
    language = infer_name_language(display.text, fallback=ui_language)
    lookup_key = sound_key(display.text)
    if not lookup_key:
        # Belt and braces: the checks above should have caught this, and RecipientName
        # requires a non-empty key, so a miss here must still be a Result and not a raise.
        return _invalid("recipient name reduces to an empty lookup key", raw=raw, reason="no_key")

    return ok(
        RecipientName(
            raw=preserved,
            display=display.text,
            lookup_key=lookup_key,
            script=detect_script(display.text).script,
            language=language,
            candidates=build_candidates(display, order=candidate_order, language=language),
        )
    )
