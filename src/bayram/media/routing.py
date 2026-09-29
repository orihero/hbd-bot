"""Which backend a media job renders on, and when it may move (IMAGE_VIDEO_SPEC §3.3, §4).

Three rules, each in one place:

* **The route** of a SKU is its effective backend (the env backend with the operator's Redis
  override on top, :func:`bayram.media.offering.effective_backend`) and then, optionally, its
  configured fallback (``*_fallback_backend``). Nothing else is ever tried.
* **Fallback only on a pre-submit error** (§3.3): the backend refused before anything was
  created there — unavailable, out of quota, rate-limited, or the gateway's 502 with no job
  id. Never after an ambiguous submit (R7), never for our own refusal of the request (a
  reference the model cannot take, a cost over the ceiling), and never for a vendor's content
  refusal. The stage chain adds the job-level half: a job moves only while nothing of it was
  ever posted, so one job renders on one backend and its polls ask the backend it is on.
* **Capabilities drive the references** (§4.3 "caps drive routing", §4.4): photos go natively
  when the backend takes that many for the kind (a multi-ref model, O6), else the collage.
  :func:`can_carry` is what a fallback is held to before a job is moved onto it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final

from bayram.config import MediaBackendName, Settings
from bayram.db.enums import MediaBackend, MediaSku
from bayram.errors import (
    BayramError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
)
from bayram.logging import get_logger
from bayram.media.composite import needs_collage
from bayram.media.contracts import MediaCapabilities, MediaKindName, is_pre_submit, max_references
from bayram.media.offering import effective_backend

__all__ = [
    "SKU_FALLBACK_FIELDS",
    "configured_fallback",
    "fallback_backend",
    "route_backends",
    "is_fallback_error",
    "refs_sent",
    "can_carry",
    "collage_needed_on",
]

_LOG = get_logger(__name__)

#: The ``Settings`` field naming each SKU's fallback, spelled once (§4.5's per-SKU pattern).
SKU_FALLBACK_FIELDS: Final[Mapping[MediaSku, str]] = MappingProxyType(
    {
        MediaSku.IMAGE: "image_fallback_backend",
        MediaSku.VIDEO_STANDARD: "video_standard_fallback_backend",
        MediaSku.VIDEO_FAST: "video_fast_fallback_backend",
    }
)

#: The pre-submit error classes a job may fall back on (§4.1: "``ProviderUnavailableError``
#: (pre-submit, fall-back-able)"; §3.3 adds quota and rate-limited).
_FALLBACK_CLASSES: Final[tuple[type[BayramError], ...]] = (
    ProviderUnavailableError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitedError,
)
#: The local gateway's validation failure: a 502 with no job id queued nothing (§4.2).
_GATEWAY_VALIDATION_STATUS: Final[int] = 502


def configured_fallback(settings: Settings, sku: MediaSku) -> MediaBackend | None:
    """The env fallback for ``sku`` as written, or ``None``. Boot reads this one."""
    name: MediaBackendName | None = getattr(settings, SKU_FALLBACK_FIELDS[sku])
    return MediaBackend(name) if name is not None else None


def fallback_backend(
    settings: Settings, sku: MediaSku, current: MediaBackend
) -> MediaBackend | None:
    """Where a job of ``sku`` on ``current`` may move, or ``None``.

    Under ``use_fake_providers`` a configured fallback is the fake, as every backend is
    (``effective_backend``). Outside it a fallback of ``fake`` is ignored (boot refuses it
    for an offered SKU; a job must never be moved onto placeholder renders). A fallback equal
    to the backend the job is already on is no fallback.
    """
    configured = configured_fallback(settings, sku)
    if configured is None:
        return None
    if settings.use_fake_providers:
        target = MediaBackend.FAKE
    elif configured is MediaBackend.FAKE:
        _LOG.error(
            "a media fallback backend names the fake outside a fake deployment; ignored",
            extra={"sku": sku.value},
        )
        return None
    else:
        target = configured
    return None if target is current else target


def route_backends(
    settings: Settings, sku: MediaSku, override: MediaBackend | None
) -> tuple[MediaBackend, ...]:
    """The backends a new job of ``sku`` may render on, in order: primary, then fallback."""
    primary = effective_backend(settings, sku, override)
    fallback = fallback_backend(settings, sku, primary)
    return (primary,) if fallback is None else (primary, fallback)


def is_fallback_error(error: BayramError) -> bool:
    """A submit failure another backend may be tried after (§3.3). Pure.

    Pre-submit AND one of the classes the spec names. A pre-submit ``ValidationError`` or a
    cost-ceiling refusal is about the request, not the backend, and moves nothing.
    """
    if not is_pre_submit(error):
        return False
    if isinstance(error, _FALLBACK_CLASSES):
        return True
    return error.context.get("http_status") == _GATEWAY_VALIDATION_STATUS


def refs_sent(
    caps: MediaCapabilities, kind: MediaKindName, *, photos: int, has_collage: bool
) -> int | None:
    """How many references a request of ``kind`` carries on a backend with ``caps``.

    ``photos`` when they fit natively (§4.4: "the originals go natively and no collage is
    made"), else one collage — or ``None`` when the photos do not fit and no collage was
    screened for them, which that backend therefore cannot be given.
    """
    if not needs_collage(photos, max_references(caps, kind)):
        return photos
    return 1 if has_collage else None


def can_carry(
    caps: MediaCapabilities, kind: MediaKindName, *, photos: int, has_collage: bool
) -> bool:
    """Whether a backend with ``caps`` can render this job as screened (a fallback's test)."""
    if kind not in caps.kinds:
        return False
    sent = refs_sent(caps, kind, photos=photos, has_collage=has_collage)
    # A text-only model (0 references) carries a request with no photo and nothing else.
    return sent is not None and sent <= max_references(caps, kind)


def collage_needed_on(
    capabilities: Sequence[MediaCapabilities], kind: MediaKindName, *, photos: int
) -> bool:
    """Whether any backend on the route needs a collage for ``photos`` (§4.4).

    Built and screened at the quote whenever one of them does, so a fallback onto a one-ref
    backend has screened bytes to send; a multi-ref backend still gets the originals.
    """
    return any(needs_collage(photos, max_references(caps, kind)) for caps in capabilities)
