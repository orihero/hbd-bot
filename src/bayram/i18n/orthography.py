"""Interface-copy orthography guard for Uzbek Latin.

The product exists to get one character right. In *display* copy — which is everything
in this package — the tutuq belgisi and the oʻ/gʻ diacritic have exactly one correct
spelling each:

* ``ʻ`` U+02BB MODIFIER LETTER TURNED COMMA — the oʻ / gʻ diacritic.
* ``ʼ`` U+02BC MODIFIER LETTER APOSTROPHE — the tutuq belgisi (maʼlumot, sanʼat).

Everything a phone keyboard actually produces instead — U+0027 APOSTROPHE, U+0060 GRAVE
ACCENT, U+00B4 ACUTE ACCENT, U+2018 and U+2019 — is wrong here and is rejected when the
catalogue loads, so a typo cannot reach a customer.

This is deliberately NOT the same rule as the name subsystem's input canonicaliser:
that one *accepts* the wrong characters and repairs them, because it is fed by users.
This one *refuses* them, because it is fed by us.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "UZ_LATN_TURNED_COMMA",
    "UZ_LATN_MODIFIER_APOSTROPHE",
    "FORBIDDEN_UZ_LATN_CHARS",
    "find_forbidden_chars",
    "describe_chars",
]

#: The two characters that are correct in Uzbek Latin display copy.
UZ_LATN_TURNED_COMMA: Final[str] = "ʻ"
UZ_LATN_MODIFIER_APOSTROPHE: Final[str] = "ʼ"

#: Look-alikes that must never appear in an ``uz_latn`` string.
FORBIDDEN_UZ_LATN_CHARS: Final[tuple[str, ...]] = (
    "'",  # APOSTROPHE
    "`",  # GRAVE ACCENT
    "\u00b4",  # ACUTE ACCENT (escaped: the literal is itself a confusable)
    "‘",  # LEFT SINGLE QUOTATION MARK
    "’",  # RIGHT SINGLE QUOTATION MARK
)


def find_forbidden_chars(text: str) -> tuple[str, ...]:
    """Return the forbidden look-alikes present in ``text``, in catalogue order.

    Empty tuple means the string is clean. Never raises.
    """
    return tuple(char for char in FORBIDDEN_UZ_LATN_CHARS if char in text)


def describe_chars(chars: tuple[str, ...]) -> str:
    """Render code points as ``U+XXXX`` for an operator-facing message."""
    return ", ".join(f"U+{ord(char):04X}" for char in chars)
