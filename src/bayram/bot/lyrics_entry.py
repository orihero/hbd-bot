"""The paste-your-own path: typed text in, a well-formed :class:`LyricDraft` out.

Some customers arrive with the words already written — a poem an aunt wrote, a verse from a
family song — and telling them to accept a machine's attempt instead would be the wrong
product. So the preview step accepts a pasted lyric as a plain message.

What it must NOT accept is a lyric shaped differently from a generated one. The pipeline
downstream assumes exactly one name-hook section, non-empty lines and a bounded title; a
pasted draft that quietly broke any of those would fail hours later, in the worker, after
the customer had paid. That is why the actual construction happens in
``bayram.pipeline.lyric_shape.build_lyric_draft`` — the one place that decides what a
well-formed lyric looks like — and this module only does the part that is genuinely about
typed text: bounds, blank-line splitting, and turning a rejection into the sentence this
user should read.

Nothing here raises. Text we cannot use comes back as an ``Err`` carrying the locale key
the user should be shown, so the handler has no branching of its own to get wrong.

This module is also the ONE place where the watermark can re-enter the product. Everything
in ``bayram.watermark`` is added to rendered output — the preview screen's invite line, the
lyric-sheet message, the archived ``lyrics.txt`` rules — and all of that output is sitting
in the customer's own chat, directly above a screen that says "send me your own as a
message". Selecting the whole message and pasting it back is the ordinary way to edit words
you were just shown. Before :func:`_without_watermark_lines` existed, that paste became
``LyricSection`` lines, then ``Brief.approved_lyrics``, then a vendor chunk whose text was
exactly ``"✨ Generate yours at @bayram_uzbot"`` — a voice singing the advertisement in the
middle of the birthday song, which is precisely the invariant ``bayram.watermark`` is shaped
to protect. The filter lives HERE and not downstream because this is the only boundary
where untrusted text becomes a draft; every other producer of a ``LyricDraft`` is our own
code, which never had the watermark to begin with.
"""

from __future__ import annotations

import re
from typing import Final

from bayram.contracts import Language, LyricDraft, Result, err, ok
from bayram.errors import ValidationError
from bayram.logging import get_logger
from bayram.pipeline.lyric_shape import (
    MAX_LYRIC_SECTIONS,
    build_lyric_draft,
    clean_label,
    clean_lines,
)
from bayram.watermark import contains_watermark

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
    name_display: str | None = None,
    title: str,
) -> Result[LyricDraft]:
    """Validate and shape what the user pasted. Never raises.

    ``title`` is supplied by the caller — the previous draft's title, or the recipient's
    display name for a first-ever paste. This module does not invent one: a title guessed
    from the first line of a pasted poem is a guess the customer never asked for. An empty
    string is allowed and resolves to ``build_lyric_draft``'s own default.

    ``name_display`` is the canonical spelling; ``build_lyric_draft`` is what guarantees it
    survives into a name-hook section, so a pasted lyric gets the same hook guarantee as a
    generated one.

    ``name_display=None`` builds a NAMELESS lyric, with no hook and nobody named. That is
    the bring-your-own-lyrics path, where the wizard never asks who the song is for: the
    customer already put whatever name they wanted into their own words, and weaving another
    one in on top would sing a word they did not write.

    Watermark lines are dropped before anything else happens, INCLUDING before the length
    bounds. Two reasons, in this order. The bounds exist to describe the customer's own
    words, and a paste is not "too long" because the bot's own advertisement pushed it over
    3000 — measuring the text we would actually sing is the only measurement that means
    anything. And a paste that is nothing but watermark then arrives at the ``too short``
    branch on its own, with no fourth rejection message to write or translate.
    """
    pasted, watermark_lines = _without_watermark_lines(text)
    length = len(pasted)
    if length < MIN_LYRIC_CHARS:
        # Two operator messages, one user message. The customer is shown the same "that is
        # too short to be a song" sentence either way — there is no useful thing to tell
        # someone who pasted our own advertisement back at us — but an operator reading the
        # logs needs to be able to tell "sent ok instead of pressing approve" apart from
        # "the whole paste was watermark", because only the second one means a screen of
        # ours is inviting a paste it should not be.
        emptied_by_filter = watermark_lines > 0 and length == 0
        reason = "pasted lyric is too short"
        if emptied_by_filter:
            reason = "pasted lyric was nothing but watermark"
        return _rejected(reason, key=LYRICS_TOO_SHORT_KEY, length=length)
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
        extra={
            "sections": len(draft.sections),
            "length": length,
            "watermark_lines": watermark_lines,
        },
    )
    return ok(draft)


def _without_watermark_lines(text: str) -> tuple[str, int]:
    """Strip every line carrying the watermark; return the survivors and how many went.

    THE DEFECT THIS FIXES: nothing filtered here, so the "✨ Generate yours at @bayram_uzbot"
    line the preview screen prints under the customer's own lyric — and the rules wrapping
    the delivered lyric sheet — came straight back in when the customer selected the whole
    message and pasted it, cleared the 20-character floor on their own, and were handed to
    the vendor as chunk text to be sung.

    Line-level, and stripped rather than rejected. A customer who pastes back the words we
    just showed them has done nothing wrong and must not be told their lyric is invalid;
    they would have no idea which of the words on their screen we objected to. Dropping the
    lines and shaping the rest is the behaviour that needs no explanation.

    The predicate is :func:`bayram.watermark.contains_watermark` rather than a set of literals
    assembled here, and that is the whole point of using it. ``watermark.invite`` and
    ``watermark.song`` are LOCALISED — a Russian customer pastes back
    "✨ Сделайте свою в @bayram_uzbot", an Uzbek one "✨ Oʻzingiznikini @bayram_uzbot da yarating" —
    so a filter matching the English sentence would leak in three locales out of four. Every
    rendering the bot can produce interpolates ``WATERMARK_HANDLE``, which is one of the
    needles that predicate looks for, so all four are caught by construction and a fifth
    locale is caught the day it is added. Re-deriving the strings here would be a second
    copy of the vocabulary that goes stale silently.

    The predicate is deliberately generous, so a line of the CUSTOMER'S OWN in which they
    happen to name the bot — "thank you @bayram_uzbot for this song" — is dropped too. That is
    intended: there is no way to tell that line from a pasted one, and the invariant is
    about what gets sung, not about who typed it. A voice singing "at bayram_uzbot" ruins the
    song no matter whose sentence it came from, and the cost of the false positive is one
    line of a multi-line paste.

    Blank lines are preserved exactly — ``contains_watermark("")`` is False — because they
    are the section separator :data:`_BLANK_LINE` splits on, and dropping them would fuse a
    customer's verses into one block. Rejoining with ``"\\n"`` also normalises the CRLF a
    desktop client can paste, which :data:`_BLANK_LINE` could not see through before: its
    ``\\n[ \\t]*\\n`` never matched ``"\\r\\n\\r\\n"``, so a CRLF paste arrived as a single
    section. That is a fix, not a side effect, and it is stated here so nobody "simplifies"
    the join back into a slice of the original string.
    """
    lines = text.splitlines()
    kept = [line for line in lines if not contains_watermark(line)]
    return "\n".join(kept).strip(), len(lines) - len(kept)


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
