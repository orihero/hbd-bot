"""Turning a vendor-neutral :class:`SpeechRequest` into vendor text.

The product's whole promise lives in one substitution. ``SpeechRequest.text`` carries the
**display** name — perfect U+02BB, what a human reads. ``SpeechRequest.name_submitted``
carries the orthography we actually want the engine to *say*, which is usually a different
string and which nobody ever sees. This module swaps one for the other without the caller
ever formatting vendor markup.

Two ways to locate the name in the text, in order:

1. An explicit ``{name}`` placeholder. Unambiguous; preferred for generated scripts.
2. Token matching under a light normalisation — casefold and drop the apostrophe family,
   so ``Gʻulomjon`` in the copy matches a submitted ``Gulomjon``. This is deliberately
   *not* the full name-normalisation subsystem; it only has to recognise the same name
   spelled with a different mark.

Capitalising for stress is NOT implemented anywhere here: in a generative model all-caps
reads as louder, not stressed.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Final

__all__ = [
    "ELEVENLABS_AUDIO_TAGS",
    "NAME_PLACEHOLDER",
    "NameApplication",
    "apply_mood_tag",
    "apply_name",
    "normalize_for_match",
    "render_name",
    "strip_markup",
]

#: Explicit slot a generated script may use instead of relying on token matching.
NAME_PLACEHOLDER: Final[str] = "{name}"

#: Every mark that real input uses where Uzbek Latin wants U+02BB, plus the ASCII quote.
#: Dropped entirely when comparing, so all spellings of one name compare equal. Written as
#: escapes because several of these are visually identical and a reviewer cannot tell them
#: apart in a literal:
#: U+02BB turned comma, U+02BC apostrophe, U+02B9 prime, U+2018/U+2019 curly quotes,
#: U+2032 prime, U+0027 apostrophe, U+0060 grave, U+00B4 acute.
_APOSTROPHE_CHARS: Final[str] = (
    "\u02bb\u02bc\u02b9"  # turned comma, modifier apostrophe, modifier prime
    "\u2018\u2019\u2032"  # left/right single quote, prime
    "\u0027\u0060\u00b4"  # ASCII apostrophe, grave accent, acute accent
)
_APOSTROPHE_SET: Final[frozenset[str]] = frozenset(_APOSTROPHE_CHARS)

#: A word, allowing an internal apostrophe-family mark: ``G‘ulomjon`` is ONE token.
_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(rf"\w+(?:[{re.escape(_APOSTROPHE_CHARS)}]\w+)*")

#: Bracketed performance directions understood by ElevenLabs v3.
ELEVENLABS_AUDIO_TAGS: Final[frozenset[str]] = frozenset(
    {
        "excited",
        "happy",
        "cheerfully",
        "warmly",
        "gently",
        "sad",
        "curious",
        "whispers",
        "laughs",
        "sighs",
        "shouts",
        "sarcastic",
        "dramatic",
    }
)

_AUDIO_TAG_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[[^\[\]]{1,40}\]")
_XML_TAG_PATTERN: Final[re.Pattern[str]] = re.compile(r"<[^<>]{1,200}>")
_WHITESPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s{2,}")


@dataclass(frozen=True, slots=True)
class NameApplication:
    """Result of substituting the submitted orthography into a script."""

    text: str
    is_applied: bool
    replacement_count: int


def normalize_for_match(text: str) -> str:
    """Casefold and drop marks so two spellings of one name compare equal."""
    return "".join(
        char.casefold() for char in text if char.isalnum() and char not in _APOSTROPHE_SET
    )


def render_name(
    name_submitted: str, *, name_ipa: str | None = None, is_phoneme_supported: bool = False
) -> str:
    """The exact string that replaces the name in the script.

    With IPA and a phoneme-capable engine this is a ``<phoneme>`` element; otherwise it is
    the submitted orthography verbatim, which is the whole point of ranked candidates.
    """
    if not name_ipa or not is_phoneme_supported:
        return name_submitted
    return (
        f'<phoneme alphabet="ipa" ph="{html.escape(name_ipa, quote=True)}">'
        f"{html.escape(name_submitted, quote=False)}</phoneme>"
    )


def apply_name(
    text: str,
    *,
    name_submitted: str,
    name_ipa: str | None = None,
    is_phoneme_supported: bool = False,
) -> NameApplication:
    """Replace the display name in ``text`` with the submitted orthography.

    Returns the original text with ``is_applied=False`` when the name cannot be located;
    the caller logs that and still synthesises, because a greeting saying the name
    slightly wrong beats no greeting at all.
    """
    rendered = render_name(
        name_submitted, name_ipa=name_ipa, is_phoneme_supported=is_phoneme_supported
    )
    if NAME_PLACEHOLDER in text:
        return NameApplication(
            text=text.replace(NAME_PLACEHOLDER, rendered),
            is_applied=True,
            replacement_count=text.count(NAME_PLACEHOLDER),
        )

    target = normalize_for_match(name_submitted)
    if not target:
        return NameApplication(text=text, is_applied=False, replacement_count=0)

    pieces: list[str] = []
    cursor = 0
    count = 0
    for match in _TOKEN_PATTERN.finditer(text):
        if normalize_for_match(match.group()) != target:
            continue
        pieces.append(text[cursor : match.start()])
        pieces.append(rendered)
        cursor = match.end()
        count += 1
    if count == 0:
        return NameApplication(text=text, is_applied=False, replacement_count=0)
    pieces.append(text[cursor:])
    return NameApplication(text="".join(pieces), is_applied=True, replacement_count=count)


def apply_mood_tag(text: str, mood: str) -> tuple[str, bool]:
    """Prefix an ElevenLabs v3 audio tag. Unknown moods are ignored, never injected."""
    normalized = mood.strip().strip("[]").casefold()
    if normalized not in ELEVENLABS_AUDIO_TAGS:
        return (text, False)
    return (f"[{normalized}] {text}", True)


def strip_markup(text: str) -> str:
    """Remove audio tags and phoneme elements — what will actually be *spoken*."""
    without_tags = _XML_TAG_PATTERN.sub("", _AUDIO_TAG_PATTERN.sub("", text))
    return _WHITESPACE_PATTERN.sub(" ", without_tags).strip()
