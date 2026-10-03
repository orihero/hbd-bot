"""Marketing channel and attribution models, protocols, and parameter parsing.

Supports parsing Telegram deep-link start parameters such as:
- ``utm_source=kanallanidodasi``
- ``utm_source_kanallanidodasi``
- ``c_kanallanidodasi`` / ``c=kanallanidodasi``
- ``src_kanallanidodasi`` / ``src=kanallanidodasi``
- ``ref_kanallanidodasi`` / ``ref=kanallanidodasi``
- ``kanallanidodasi`` (plain channel identifier)

Telegram deep-link restrictions:
- Max 64 characters from ``[A-Za-z0-9_-]``.
- Although some users might enter ``=``, Telegram clients can drop or truncate strings
  containing ``=``. This parser handles both ``=`` and ``_`` gracefully.
"""

from __future__ import annotations

import re
from typing import Final, Protocol

__all__ = [
    "parse_channel_param",
    "ChannelAttributionStore",
    "MAX_CHANNEL_LENGTH",
]

MAX_CHANNEL_LENGTH: Final[int] = 64

# Known prefixes for traffic sources
_PREFIX_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:utm_source|utm_campaign|utm_medium|source|src|ref|c)[=_]",
    re.IGNORECASE,
)

# Allowed characters in sanitized channel names
_CLEAN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^a-zA-Z0-9_-]")


def parse_channel_param(raw: str | None) -> str | None:
    """Extract a clean, sanitized channel label from a Telegram /start payload.

    Returns ``None`` if:
    - ``raw`` is empty or whitespace
    - ``raw`` equals ``"paid"`` (reserved for Payme return deep link)
    - sanitized result is empty

    Examples:
        >>> parse_channel_param("utm_source=kanallanidodasi")
        'kanallanidodasi'
        >>> parse_channel_param("utm_source_kanallanidodasi")
        'kanallanidodasi'
        >>> parse_channel_param("c_tashkent_news")
        'tashkent_news'
        >>> parse_channel_param("instagram")
        'instagram'
        >>> parse_channel_param("paid")
        None
    """
    if raw is None:
        return None
    val = raw.strip()
    if not val or val.lower() == "paid":
        return None

    # If compound like utm_source=foo&utm_medium=bar or foo;bar or foo__bar, take primary
    for sep in ("&", ";"):
        if sep in val:
            parts = val.split(sep)
            for part in parts:
                cleaned_part = parse_channel_param(part)
                if cleaned_part:
                    return cleaned_part

    # Strip recognized prefix (e.g. utm_source=, utm_source_, c_, src_, ref_)
    stripped = _PREFIX_PATTERN.sub("", val)
    if not stripped:
        return None

    # Sanitize characters and limit to MAX_CHANNEL_LENGTH
    cleaned = _CLEAN_PATTERN.sub("", stripped).strip("_").strip("-")
    if not cleaned or cleaned.lower() == "paid":
        return None

    return cleaned[:MAX_CHANNEL_LENGTH].lower()


class ChannelAttributionStore(Protocol):
    """Asynchronous port for recording traffic attribution."""

    async def record_attribution(
        self,
        telegram_user_id: int,
        *,
        raw_param: str,
        channel: str,
    ) -> bool:
        """Record an inbound start parameter attribution.

        Returns True if this was a first-touch attribution for the user.
        """
        ...
