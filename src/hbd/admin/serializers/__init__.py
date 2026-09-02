"""Response-boundary projections. The layer where §12.3 is enforced rather than described.

A serializer here is a pure function from a view model to a wire model. It holds no session,
reads no clock and asks no question of the database, which is what makes the masking rules
testable as data: the assertion "a VIEWER's order detail contains no substring of the
fixture's plaintext" is a call, not a fixture-and-a-client.
"""

from __future__ import annotations

from hbd.admin.serializers.redaction import (
    MASK,
    TELEGRAM_ID_VISIBLE_DIGITS,
    first_grapheme,
    mask_name,
    mask_telegram_user_id,
)

__all__ = [
    "MASK",
    "TELEGRAM_ID_VISIBLE_DIGITS",
    "first_grapheme",
    "mask_name",
    "mask_telegram_user_id",
]
