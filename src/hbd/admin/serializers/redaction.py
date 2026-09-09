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

**A phone number keeps its last two digits and no head at all**, which is a narrower rule
than the Telegram id's and is not an inconsistency. The two values are asked different
questions: an id is SEARCHED on, so its mask must discriminate one row from a page, while
nothing in this API filters, sorts or routes on a number — the phone mask exists only to let
an operator confirm a value they already have in front of them. The temptation to keep a
readable ``+998`` head, on the grounds that a single-market product's dialling prefix is
common knowledge, is refused in :func:`mask_phone` for the reason stated there: the column
admits every E.164 number, so a fixed-width head hides the country code of a foreign number
while publishing the first digits of its subscriber part — leaking exactly what it claims to
protect, in the one case the operator cannot spot.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

__all__ = [
    "MASK",
    "PHONE_VISIBLE_DIGITS",
    "TELEGRAM_ID_VISIBLE_DIGITS",
    "first_grapheme",
    "mask_name",
    "mask_phone",
    "mask_telegram_user_id",
    "mask_username",
]

#: The elision. Three U+2022 BULLETs rather than ``***`` or ``...``: an asterisk reads as a
#: footnote and a full stop reads as a truncation the operator could scroll, and both have
#: been mistaken for part of a name in exactly the languages this ships to.
MASK: Final[str] = "•••"

#: How many trailing digits of a Telegram id survive masking (§12.3's ``•••••123``).
TELEGRAM_ID_VISIBLE_DIGITS: Final[int] = 3

#: How many trailing digits of a phone number survive masking. TWO, and the asymmetry with
#: :data:`TELEGRAM_ID_VISIBLE_DIGITS` is deliberate rather than an oversight. A Telegram id
#: is SEARCHED on — ``UserFilters`` has an exact filter for it and every ``/users/**`` route
#: keys on it — so its mask has to carry enough of a discriminator to pick one row out of a
#: page, and three trailing digits is that. Nothing in this API filters, sorts or routes on
#: a phone number (``db/admin/users.py`` explains why it must not), so this mask's only job
#: is to let an operator CONFIRM a number they already have in front of them from a support
#: ticket. Two digits does that at one-in-a-hundred ambiguity; a third buys no capability
#: and narrows a subscriber space by a further factor of ten.
PHONE_VISIBLE_DIGITS: Final[int] = 2

#: Fixed-width prefix for a masked id or number. Constant rather than proportional to the
#: value's length, because a mask whose width tracks the value leaks the value's magnitude —
#: a Telegram id's digit count is a coarse account-age signal, and a phone number's digit
#: count is a country. Shared by :func:`mask_telegram_user_id` and :func:`mask_phone` so the
#: two never drift into two elision widths on one row of the same table.
_ID_MASK: Final[str] = "•" * 5

#: An E.164 number and nothing else: a leading ``+``, a non-zero country digit, then 7 to 14
#: more. The same shape ``hbd.user_profiles.normalise_phone`` admits, restated here because
#: this module imports nothing from the bot's side of the house and a value that reaches a
#: masker is untrusted on read like any other stored string.
_E164_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\+[1-9]\d{7,14}$")

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


def mask_username(username: str | None) -> str | None:
    """``Gʻulom`` → ``@G•••``. A stored handle carries no ``@``; the display form does.

    Routed through :func:`mask_name` rather than sliced here, because a second slicing
    implementation in this module is exactly how ``Gʻulom`` eventually masks to ``G`` in one
    of them and to ``Gʻ`` in the other. It also inherits the property that makes a masked
    value a legitimate monogram source: :func:`first_grapheme` never normalises, and NFKC
    folds U+02BB — correct Uzbek Latin orthography — into a plain apostrophe, so a handle
    round-tripped through ``.normalize()`` anywhere on this path would hand the panel a
    different letter than the customer has.

    A leading ``@`` is stripped before masking and re-prefixed after, so a handle stored with
    one and a handle stored without one mask identically — the panel must not show two shapes
    for one fact because two writers disagreed about a sigil. Telegram handles are ASCII
    today; the grapheme walk costs nothing and survives the day that stops being true.

    ``None`` stays ``None`` for :func:`mask_name`'s reason: Telegram does not require a
    handle, so its absence is a fact about the account rather than something withheld, and
    ``@•••`` would send an operator to ``POST /reveal`` for a value nobody ever held.
    """
    if username is None:
        return None
    masked = mask_name(username.lstrip("@"))
    return None if masked is None else f"@{masked}"


def mask_phone(phone: str | None) -> str | None:
    """``+998901234542`` → ``•••••42``. ``None`` stays ``None``.

    **No country prefix survives, and that is the whole design.** The obvious alternative —
    keep a fixed ``+998`` in the clear, on the grounds that a single-market product's dialling
    prefix is a constant everybody shares — is wrong in the direction that matters, because
    the column is not single-market. ``phone_e164`` is ``String(16)`` and the normaliser
    admits ``^\\+[1-9]\\d{7,14}$``, so a Russian or Kazakh number is entirely expressible in
    this market: ``mask_phone("+79161234567")`` under a fixed four-character head renders
    ``+791•••••67``, which hides the country code (``+7``) and publishes the first two digits
    of the subscriber number. A mask that leaks what it protects and protects what it does
    not is worse than no mask, because the operator believes it.

    The elision is the fixed-width :data:`_ID_MASK` rather than one bullet per hidden digit:
    a mask whose width tracks the value leaks the value's length, and a phone number's digit
    count is a country.

    Anything that is not E.164 masks to the bare :data:`MASK` and is **never echoed**. A
    value this function cannot parse is one it must not describe: the input is a stored
    string, and a hand-written row or a future writer could put anything there.

    ``None`` stays ``None`` because there is nothing to mask — the customer never shared a
    number, or ``/forget`` deleted the row that held it. PD-3 puts no purge stamp on that
    table, so the wire distinguishes the two through ``isProfilePresent`` and not here.
    """
    if phone is None:
        return None
    if _E164_PATTERN.fullmatch(phone) is None:
        return MASK
    return f"{_ID_MASK}{phone[-PHONE_VISIBLE_DIGITS:]}"


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
