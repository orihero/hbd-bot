"""Style tags per genre, plus the tags that protect the name chunk.

Two rules this module exists to hold:

1. **Style tags are a closed set we control.** Nothing a customer types ever reaches a
   ``positive_styles`` / ``negative_styles`` list. Eleven Music rejects prompts that name a
   real artist (``ErrorCode.ARTIST_NAME_IN_STYLE``), and the only way to guarantee we never
   trip it is to never interpolate user text into a style field.
2. **The name chunk gets its own styles.** The whole product is the name being audible and
   correct, so that one chunk asks for clear diction and a dry, front-of-mix lead, and
   explicitly pushes away the treatments that smear a syllable.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from bayram.contracts import ContextAdherence, Genre

__all__ = [
    "positive_styles_for",
    "negative_styles_for",
    "GENRE_POSITIVE_STYLES",
    "FALLBACK_POSITIVE_STYLES",
    "UNIVERSAL_NEGATIVE_STYLES",
    "NAME_CHUNK_POSITIVE_STYLES",
    "NAME_CHUNK_NEGATIVE_STYLES",
    "INTRO_POSITIVE_STYLES",
    "NAME_CHUNK_CONTEXT_ADHERENCE",
    "BODY_CHUNK_CONTEXT_ADHERENCE",
]

#: How literally the model should follow the chunk text. The name chunk is pinned high:
#: we want the given graphemes sung, not a tasteful reinterpretation of them. The body sits
#: one notch below so the melody still breathes.
#:
#: The vendor's scale is the three-value enum, not a 0..1 float — sending a float rejects
#: every chunk in the plan with a 422.
NAME_CHUNK_CONTEXT_ADHERENCE: Final[ContextAdherence] = ContextAdherence.HIGH
BODY_CHUNK_CONTEXT_ADHERENCE: Final[ContextAdherence] = ContextAdherence.MEDIUM

GENRE_POSITIVE_STYLES: Final[Mapping[Genre, tuple[str, ...]]] = MappingProxyType(
    {
        Genre.POP: ("modern pop", "bright synths", "four-on-the-floor", "radio production"),
        Genre.RETRO_ESTRADA: (
            "soviet estrada",
            "1970s pop orchestra",
            "warm tape",
            "string section",
        ),
        Genre.HIP_HOP: ("hip hop", "boom bap drums", "sub bass", "rhythmic delivery"),
        Genre.ROCK: ("rock band", "electric guitars", "live drums", "anthemic chorus"),
        Genre.ACOUSTIC_BALLAD: (
            "acoustic ballad",
            "fingerpicked guitar",
            "intimate",
            "soft dynamics",
        ),
        Genre.DANCE_ELECTRONIC: (
            "dance",
            "electronic production",
            "sidechained pads",
            "club energy",
        ),
        Genre.UZBEK_POP: ("uzbek pop", "central asian pop", "doira percussion", "festive"),
        Genre.UZBEK_FOLK: ("uzbek folk", "dutar", "doira", "traditional melody"),
        Genre.SHASHMAQOM: ("shashmaqom", "classical central asian", "tanbur", "melismatic"),
        Genre.JAZZ_LOUNGE: ("jazz lounge", "brushed drums", "upright bass", "rhodes piano"),
    }
)

#: Used when a genre somehow has no entry. Never raise over a missing style tag — a
#: neutral song beats no song.
FALLBACK_POSITIVE_STYLES: Final[tuple[str, ...]] = ("warm celebratory pop", "upbeat")

#: Applied to every chunk of every song. A celebration kit is never explicit.
UNIVERSAL_NEGATIVE_STYLES: Final[tuple[str, ...]] = (
    "explicit lyrics",
    "aggressive",
    "melancholic",
    "distorted vocals",
)

NAME_CHUNK_POSITIVE_STYLES: Final[tuple[str, ...]] = (
    "clear diction",
    "solo lead vocal",
    "front of mix vocal",
    "unhurried phrasing",
)

#: Everything that turns a name into mush.
NAME_CHUNK_NEGATIVE_STYLES: Final[tuple[str, ...]] = (
    "mumbled vocals",
    "heavy reverb on vocal",
    "vocal chops",
    "layered backing choir",
    "vocoder",
    "loud instrumentation over vocal",
)

INTRO_POSITIVE_STYLES: Final[tuple[str, ...]] = ("instrumental intro", "building energy")


def positive_styles_for(
    genre: Genre, *, is_name_chunk: bool = False, is_intro: bool = False
) -> tuple[str, ...]:
    """Return the positive style tags for one chunk. Never raises, never mutates."""
    base = GENRE_POSITIVE_STYLES.get(genre, FALLBACK_POSITIVE_STYLES)
    if is_name_chunk:
        return (*base, *NAME_CHUNK_POSITIVE_STYLES)
    if is_intro:
        return (*base, *INTRO_POSITIVE_STYLES)
    return base


def negative_styles_for(*, is_name_chunk: bool = False) -> tuple[str, ...]:
    """Return the negative style tags for one chunk. Never raises, never mutates."""
    if is_name_chunk:
        return (*UNIVERSAL_NEGATIVE_STYLES, *NAME_CHUNK_NEGATIVE_STYLES)
    return UNIVERSAL_NEGATIVE_STYLES
