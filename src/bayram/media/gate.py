"""The capability block at Done/quote (IMAGE_VIDEO_SPEC §7.2 step 1, §4.5, O11).

One question — "may this user be quoted this SKU right now?" — answered from settings, the
operator's Redis switches and the margin rule. The answer is a reason or ``None``; the bot
turns every reason but ``NOT_OFFERED`` into ``media.busy``. The backend's health and the
ETA ≤ deadline check are made beside this by ``media_screen`` (``bayram.runtime.media_jobs``),
where the provider and the GPU queue are in hand.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from bayram.config import Settings
from bayram.db.enums import MediaBackend, MediaSku
from bayram.media.margin import check_margin
from bayram.media.offering import effective_backend, media_offered
from bayram.media.overrides import MediaOverrides

__all__ = ["QuoteBlock", "quote_block"]


class QuoteBlock(StrEnum):
    NOT_OFFERED = "not_offered"
    PAUSED = "paused"
    GPU_RESERVED = "gpu_reserved"
    MARGIN = "margin"
    #: The backend's ``health()`` is not healthy (§7.2 step 1). Set by ``media_screen``, which
    #: holds the provider; this pure function never makes a call.
    UNHEALTHY = "unhealthy"
    #: The backend cannot take the job's photos as screened (§4.3 "caps drive routing"),
    #: e.g. a text-only image model. Set by ``media_screen``, which holds the capabilities.
    CANNOT_CARRY = "cannot_carry"


def quote_block(
    settings: Settings,
    sku: MediaSku,
    telegram_user_id: int,
    overrides: MediaOverrides,
    *,
    now: datetime,
    usd_per_output: float | None = None,
) -> QuoteBlock | None:
    """Why ``sku`` cannot be quoted now, or ``None``. Pure; the caller reads the switches."""
    # Entitlement first: a user outside the beta learns nothing about a pause.
    if not media_offered(settings, sku, telegram_user_id, is_paused=False):
        return QuoteBlock.NOT_OFFERED
    if overrides.is_paused:
        return QuoteBlock.PAUSED
    backend = effective_backend(settings, sku, overrides.backend)
    # O11: during the owner's reserved window the LOCAL tier takes no new orders. Paid jobs
    # already queued are not this function's business — they continue (§4.5).
    if backend is MediaBackend.LOCAL and overrides.is_gpu_reserved(now):
        return QuoteBlock.GPU_RESERVED
    if not check_margin(settings, sku, backend, usd_per_output=usd_per_output).is_ok:
        return QuoteBlock.MARGIN
    return None
