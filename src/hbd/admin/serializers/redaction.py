"""Masking, done to text rather than to pixels.

§12.3's rule is that an unmasked value must never be *in* a JSON payload the operator did
not explicitly request. Not blurred by CSS, not hidden behind a client toggle, not present
in a field the SPA declines to render — absent from the bytes. Everything in this module
exists to make the masked form the only form a read endpoint can produce, so revealing a
name stays a decision somebody makes at ``POST /reveal``, with a reason code, a step-up and
an audit row, rather than a decision a stylesheet makes.

**Names are cut at a grapheme cluster, never at a code point and never at a byte.** The
market is Uzbek, Russian and Uzbek-Cyrillic, and the plan names the case that breaks naive
slicing: ``Gʻulom`` must mask to ``G•••``. The ``ʻ`` is U+02BB MODIFIER LETTER TURNED COMMA
— three bytes in UTF-8, its own code point, and a character that a Python ``[:1]`` over
*bytes* would split into a replacement character and a NUL of a name. It must also never be
normalised to U+0027 or U+2019: NFC and NFKC both leave it alone, and this module does not
call either, but the temptation to "clean up the name first" is exactly how the wrong
apostrophe reaches the vendor and the song mispronounces somebody's grandmother.

A cut at the first *code point* would be right for ``Gʻulom`` and wrong for a name written
with a combining mark — ``é`` as ``e`` + U+0301 masks to a bare ``e`` under that rule, which
is a different letter in several of the languages this ships to, and for an emoji-bearing
display name it produces half a character the browser renders as a replacement box. So the
cut is at a grapheme cluster boundary.

:func:`first_grapheme` is a deliberately small approximation of UAX #29 rather than a
dependency. The full algorithm needs the Grapheme_Cluster_Break property table, which
``unicodedata`` does not expose and the ``regex`` package would bring in for one call site;
what this implements is the subset that decides real names — a base character plus its
combining marks, variation selectors, emoji modifiers, ZWJ sequences and regional-indicator
pairs. It is allowed to keep *more* than one cluster in an exotic case and must never keep
*fewer*: over-keeping shows the operator one extra mark, under-keeping emits mojibake, so
the failure the approximation can produce is the harmless one.

**Telegram ids keep their last digits, not their first.** ``•••••123`` is what §12.3
specifies, and the tail is the half that matters: an operator matching a support ticket
against a list needs a discriminator, and the leading digits of a Telegram id are close to
constant within a cohort of accounts created around the same time, so masking the tail would
leave a value that is both unusable and less private than it looks.
"""

from __future__ import annotations

import unicodedata
from typing import Final

__all__ = [
    "MASK",
    "TELEGRAM_ID_VISIBLE_DIGITS",
    "first_grapheme",
    "mask_name",
    "mask_telegram_user_id",
]

#: The elision. Three U+2022 BULLETs rather than ``***`` or ``...``: an asterisk reads as a
#: footnote and a full stop reads as a truncation the operator could scroll, and both have
#: been mistaken for part of a name in exactly the languages this ships to.
MASK: Final[str] = "•••"

#: How many trailing digits of a Telegram id survive masking (§12.3's ``•••••123``).
TELEGRAM_ID_VISIBLE_DIGITS: Final[int] = 3

#: Fixed-width prefix for a masked id. Constant rather than proportional to the id's length,
#: because a mask whose width tracks the value leaks the value's magnitude — and a Telegram
#: id's digit count is a coarse account-age signal.
_ID_MASK: Final[str] = "•" * 5

_ZERO_WIDTH_JOINER: Final[str] = "‍"
#: Variation selectors 1–16 and the supplement, which choose a glyph and are never a cluster
#: of their own.
_VARIATION_SELECTORS: Final[range] = range(0xFE00, 0xFE10)
_VARIATION_SELECTORS_SUPPLEMENT: Final[range] = range(0xE0100, 0xE01F0)
#: Emoji skin-tone modifiers, which attach to the preceding base.
_EMOJI_MODIFIERS: Final[range] = range(0x1F3FB, 0x1F400)
#: Regional indicator symbols. Exactly two of them form one flag.
_REGIONAL_INDICATORS: Final[range] = range(0x1F1E6, 0x1F200)
#: The three combining-mark categories of the Unicode general-category table.
_COMBINING_CATEGORIES: Final[frozenset[str]] = frozenset({"Mn", "Mc", "Me"})


def _is_regional_indicator(char: str) -> bool:
    return ord(char) in _REGIONAL_INDICATORS


def _extends_cluster(char: str) -> bool:
    """Whether ``char`` attaches to whatever precedes it instead of starting a cluster.

    Combining marks, variation selectors and emoji modifiers all have this property, and it
    is the property — not the character's identity — that the loop below tests. U+02BB is
    deliberately **not** in this set: it is category ``Lm``, a letter, and a cluster of its
    own, which is why ``Gʻulom`` masks to ``G`` rather than to ``Gʻ``.
    """
    code = ord(char)
    return (
        unicodedata.category(char) in _COMBINING_CATEGORIES
        or code in _VARIATION_SELECTORS
        or code in _VARIATION_SELECTORS_SUPPLEMENT
        or code in _EMOJI_MODIFIERS
    )


def first_grapheme(text: str) -> str:
    """The first user-perceived character of ``text``, or ``""`` for an empty string.

    Never normalises, never decomposes, never re-encodes: the slice returned is a substring
    of the input, so a name that survives this function unchanged is byte-identical to the
    one the customer typed.
    """
    if not text:
        return ""
    end = 1
    # A flag is exactly two regional indicators. Consuming a run of them would swallow a
    # sequence of flags into one "character", so the pair is taken and the loop below then
    # picks up anything attached to it.
    if _is_regional_indicator(text[0]) and len(text) > 1 and _is_regional_indicator(text[1]):
        end = 2
    while end < len(text):
        char = text[end]
        if _extends_cluster(char):
            end += 1
            continue
        # ZWJ binds the cluster to the next base — the emoji-sequence case. Both the joiner
        # and what it joins are consumed, and the loop continues so a multi-joiner sequence
        # stays whole.
        if char == _ZERO_WIDTH_JOINER and end + 1 < len(text):
            end += 2
            continue
        break
    return text[:end]


def mask_name(name: str | None) -> str | None:
    """``Gʻulom`` → ``G•••``. ``None`` stays ``None``, because a purge is not a mask.

    The distinction is load-bearing and §12.3 states it directly: ``identity_purged_at`` is
    always displayed, because "no name" and "name erased on schedule" are different facts
    about a record and only one of them is defensible. Returning ``"•••"`` for a purged
    identity would tell the operator there is something to reveal, and the reveal would then
    find nothing — so the absence is passed through untouched and the wire model carries the
    purge timestamp beside it.

    A name that is empty or whitespace-only masks to the bare :data:`MASK`. It cannot be
    reached through the wizard (the brief's name field is length-bounded and stripped), but
    a hand-written row or a future writer could produce one, and returning ``""`` here would
    render as "no name" — the purged case, from a record that was never purged.
    """
    if name is None:
        return None
    head = first_grapheme(name.strip())
    return f"{head}{MASK}" if head else MASK


def mask_telegram_user_id(telegram_user_id: int) -> str:
    """``123456789`` → ``•••••789`` (§12.3).

    A negative id — Telegram uses them for channels and supergroups, and nothing stops one
    reaching the ``users`` table through a future writer — masks by its digits, not by its
    text, so the sign never survives into the visible tail.
    """
    digits = str(abs(telegram_user_id))
    if len(digits) <= TELEGRAM_ID_VISIBLE_DIGITS:
        return _ID_MASK
    return f"{_ID_MASK}{digits[-TELEGRAM_ID_VISIBLE_DIGITS:]}"
