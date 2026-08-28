"""The paste-your-own path: typed text in, a well-formed :class:`LyricDraft` out.

Some customers arrive with the words already written — a poem an aunt wrote, a verse from a
family song — and telling them to accept a machine's attempt instead would be the wrong
product. So the preview step accepts a pasted lyric as a plain message.

What it must NOT accept is a lyric shaped differently from a generated one. The pipeline
downstream assumes exactly one name-hook section, non-empty lines and a bounded title; a
pasted draft that quietly broke any of those would fail hours later, in the worker, after
the customer had paid. That is why the actual construction happens in
``hbd.pipeline.lyric_shape.build_lyric_draft`` — the one place that decides what a
well-formed lyric looks like — and this module only does the part that is genuinely about
typed text: bounds, blank-line splitting, and turning a rejection into the sentence this
user should read.

Nothing here raises. Text we cannot use comes back as an ``Err`` carrying the locale key
the user should be shown, so the handler has no branching of its own to get wrong.
"""

from __future__ import annotations

import re
from typing import Final

from hbd.contracts import Language, LyricDraft, Result, err, ok
from hbd.errors import ValidationError
from hbd.logging import get_logger
from hbd.pipeline.lyric_shape import (
    MAX_LYRIC_SECTIONS,
    build_lyric_draft,
    clean_label,
    clean_lines,
)

__all__ = [
    "parse_typed_lyrics",
    "MIN_LYRIC_CHARS",
    "MAX_LYRIC_CHARS",
    "LYRICS_TOO_SHORT_KEY",
    "LYRICS_TOO_LONG_KEY",
]

_LOG = get_logger(__name__)

#: Below this a message is a comment about the lyric, not a lyric. Cheap, and it catches
#: the "ok" and "yes" a user sends when they meant to press the approve button.
MIN_LYRIC_CHARS: Final[int] = 20

#: Above this we are not looking at a song. That is all this bound does: it says what may
#: be a lyric, and it does NOT keep the preview inside Telegram's per-message ceiling,
#: because ``translate`` escapes the body on the way back out and 3000 pasted ampersands
#: render as 15000 characters. ``screens.MAX_PREVIEW_LYRIC_CHARS`` owns the wire limit and
#: measures the escaped string; the two numbers happen to match and are not the same rule.
MAX_LYRIC_CHARS: Final[int] = 3_000

LYRICS_TOO_SHORT_KEY: Final[str] = "wizard.lyrics.too_short"
LYRICS_TOO_LONG_KEY: Final[str] = "wizard.lyrics.too_long"

#: A blank line — possibly carrying stray spaces, and possibly one of several — is how
#: people already separate verses, so that is what a section break is here.
_BLANK_LINE: Final[re.Pattern[str]] = re.compile(r"\n[ \t]*\n")


def parse_typed_lyrics(
    text: str,
    *,
    language: Language,
    name_display: str,
    title: str,
) -> Result[LyricDraft]:
    """Validate and shape what the user pasted. Never raises.

    ``title`` is supplied by the caller — the previous draft's title, or the recipient's
    display name for a first-ever paste. This module does not invent one: a title guessed
    from the first line of a pasted poem is a guess the customer never asked for.

    ``name_display`` is the canonical spelling; ``build_lyric_draft`` is what guarantees it
    survives into a name-hook section, so a pasted lyric gets the same hook guarantee as a
    generated one.
    """
    pasted = text.strip()
    length = len(pasted)
    if length < MIN_LYRIC_CHARS:
        return _rejected("pasted lyric is too short", key=LYRICS_TOO_SHORT_KEY, length=length)
    if length > MAX_LYRIC_CHARS:
        return _rejected("pasted lyric is too long", key=LYRICS_TOO_LONG_KEY, length=length)

    sections = _sections_from(pasted)
    if not sections:  # pragma: no cover - defensive; see below for why it cannot happen
        # Belt and braces, not a reachable input. ``pasted`` is stripped and has cleared
        # MIN_LYRIC_CHARS, so its first character is non-whitespace; every separator
        # ``str.splitlines`` breaks on is whitespace, so that character always lands in a
        # line that survives ``clean_lines``. The guard stays because the alternative to it
        # is a ``pydantic.ValidationError`` out of ``build_lyric_draft`` — this module
        # promises never to raise, and that promise should not rest on the cleaning rules
        # in another module never changing.
        return _rejected(
            "pasted lyric held no usable line", key=LYRICS_TOO_SHORT_KEY, length=length
        )

    draft = build_lyric_draft(sections, title=title, language=language, name_display=name_display)
    _LOG.info(
        "customer supplied their own lyric",
        extra={"sections": len(draft.sections), "length": length},
    )
    return ok(draft)


def _sections_from(pasted: str) -> tuple[tuple[str, tuple[str, ...], bool], ...]:
    """Split on blank lines into at most ``MAX_LYRIC_SECTIONS`` cleaned blocks.

    A blank line is how people already separate verses, so no markup is asked of the user.
    Blocks are labelled positionally because a pasted lyric carries no structure we can
    trust, and nothing downstream reads a label for meaning.

    ``is_name_hook`` is left False on every block: which one carries the name is
    ``build_lyric_draft``'s decision, made the same way for both paths.
    """
    blocks: list[tuple[str, tuple[str, ...], bool]] = []
    for index, block in enumerate(_BLANK_LINE.split(pasted)):
        if len(blocks) >= MAX_LYRIC_SECTIONS:
            break
        lines = clean_lines(tuple(block.splitlines()))
        if lines:
            blocks.append((clean_label("", index=index), lines, False))
    return tuple(blocks)


def _rejected(operator_message: str, *, key: str, length: int) -> Result[LyricDraft]:
    """One rejection shape, so every branch above reads the same.

    The context scalars become template parameters in ``error_text``, which is how
    ``{limit}`` reaches the message without the handler knowing which limit applies.
    """
    limit = MIN_LYRIC_CHARS if key == LYRICS_TOO_SHORT_KEY else MAX_LYRIC_CHARS
    _LOG.info(operator_message, extra={"length": length, "limit": limit})
    return err(
        ValidationError(
            operator_message,
            user_message_key=key,
            context={"length": length, "limit": limit},
        )
    )
