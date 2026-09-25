"""The margin rule (IMAGE_VIDEO_SPEC §4.3): a backend may cost at most a share of the price.

At boot and at every quote, the selected backend's estimated cash cost **per request** —
outputs × expected attempts × cost per output — converted at the configured UZS/USD rate, must
be ≤ ``media_max_cost_share`` of the SKU's price net of the Payme fee. Otherwise boot refuses
to offer that SKU on that backend, and a quote shows ``media.busy``.

**What cannot be proved is refused.** A backend with no known cost, a SKU with no price, or a
backend that costs money with no exchange rate configured is not a pass with a warning — the
one thing a sale must never be is a loss nobody computed (``RESEARCH-image-video-pipeline``
§6: at 5 000 UZS, Nano Banana Pro would be ~117% of net revenue).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from bayram.config import Settings
from bayram.db.enums import MediaBackend, MediaSku
from bayram.media.offering import sku_price_minor

__all__ = [
    "MarginVerdict",
    "STATIC_USD_PER_OUTPUT",
    "OUTPUTS_PER_REQUEST",
    "EXPECTED_ATTEMPTS_PER_OUTPUT",
    "PAYME_FEE_SHARE",
    "check_margin",
    "static_usd_per_output",
    "request_cost_ceiling_usd",
]

#: The static cost table (§4.3 "from ``/estimate`` or the static table"). ``None`` = unknown
#: until measured: published prices disagree 10–30× between sources (research §6). Higgsfield's
#: figure is the operator's measured ``/estimate``, read from settings by
#: :func:`static_usd_per_output`; fal has none until its adapter lands.
STATIC_USD_PER_OUTPUT: Final[Mapping[MediaBackend, float | None]] = MappingProxyType(
    {
        # Cash cost only; the GPU and its power are the owner's (research §6, D21).
        MediaBackend.LOCAL: 0.0,
        MediaBackend.FAKE: 0.0,
        MediaBackend.HIGGSFIELD: None,
        MediaBackend.FAL: None,
    }
)

#: One image request yields two images (O5); a video request one clip (§1.3).
OUTPUTS_PER_REQUEST: Final[Mapping[MediaSku, int]] = MappingProxyType(
    {MediaSku.IMAGE: 2, MediaSku.VIDEO_STANDARD: 1, MediaSku.VIDEO_FAST: 1}
)

#: Research §6's modelling assumption (identity holds ~50% per attempt). A model constant,
#: not a tunable: changing it changes what "the margin" means, which is a decision.
EXPECTED_ATTEMPTS_PER_OUTPUT: Final[float] = 1.5

#: The ~2% Payme fee the net revenue is taken after (research §6, unverified).
PAYME_FEE_SHARE: Final[float] = 0.02

#: Minor units per major for the catalogue currency (UZS tiyin, exponent 2).
_MINOR_PER_MAJOR: Final[int] = 100


@dataclass(frozen=True, slots=True)
class MarginVerdict:
    is_ok: bool
    #: Why not, for the operator. ``None`` when ``is_ok``.
    reason: str | None
    cost_usd: float | None
    ceiling_usd: float | None


def check_margin(
    settings: Settings,
    sku: MediaSku,
    backend: MediaBackend,
    *,
    usd_per_output: float | None = None,
) -> MarginVerdict:
    """Does ``sku`` on ``backend`` leave the configured margin? Pure; never raises.

    ``usd_per_output`` is a quote-time figure from the backend's ``/estimate``; without one
    the static table is used.
    """
    per_output = (
        static_usd_per_output(settings, sku, backend) if usd_per_output is None else usd_per_output
    )
    if per_output is None:
        return MarginVerdict(False, f"no known cost for {backend.value}", None, None)
    cost_usd = per_output * OUTPUTS_PER_REQUEST[sku] * EXPECTED_ATTEMPTS_PER_OUTPUT
    price_minor = sku_price_minor(settings, sku)
    if price_minor is None:
        return MarginVerdict(False, f"{sku.value} has no price", cost_usd, None)
    if cost_usd == 0.0:
        return MarginVerdict(True, None, cost_usd, None)
    rate = settings.media_uzs_per_usd
    if rate is None:
        return MarginVerdict(
            False,
            f"{backend.value} costs money and BAYRAM_MEDIA_UZS_PER_USD is unset",
            cost_usd,
            None,
        )
    net_usd = price_minor / _MINOR_PER_MAJOR * (1.0 - PAYME_FEE_SHARE) / rate
    ceiling_usd = settings.media_max_cost_share * net_usd
    if cost_usd > ceiling_usd:
        return MarginVerdict(
            False,
            f"{backend.value} costs ${cost_usd:.3f} per {sku.value} request, above the "
            f"${ceiling_usd:.3f} ceiling",
            cost_usd,
            ceiling_usd,
        )
    return MarginVerdict(True, None, cost_usd, ceiling_usd)


def static_usd_per_output(settings: Settings, sku: MediaSku, backend: MediaBackend) -> float | None:
    """The boot-time figure for one output of ``sku`` on ``backend``, or ``None`` (unknown).

    Boot does no IO, so Higgsfield's figure is the operator's recorded ``/estimate``
    (``BAYRAM_HIGGSFIELD_*_USD_PER_OUTPUT``); a quote passes the live one instead.
    """
    if backend is MediaBackend.HIGGSFIELD:
        if sku is MediaSku.IMAGE:
            return settings.higgsfield_image_usd_per_output
        return settings.higgsfield_video_usd_per_output
    return STATIC_USD_PER_OUTPUT[backend]


def request_cost_ceiling_usd(settings: Settings, sku: MediaSku) -> float:
    """The hard per-REQUEST cash ceiling (§4.3): every variant and every retry of one request
    together. The stage chain refuses to post an attempt whose estimate would cross it."""
    if sku is MediaSku.IMAGE:
        return settings.image_max_cost_usd
    return settings.video_fast_max_cost_usd
