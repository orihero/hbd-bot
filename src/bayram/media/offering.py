"""Who may see, quote and pay for a media SKU (IMAGE_VIDEO_SPEC §2.5, §7.2, §7.4).

``media_offered(kind, tier, user)`` =
``is_<sku>_offered`` **and** not ``media:paused:<sku>`` **and** (rail is live-paid **or**
(``media_beta_enabled`` **and** ``user ∈ media_beta_allowlist``)).

**Live-paid** is ``checkout_provider == "payme"`` and ``credits_enforced`` and **not**
``payme_is_sandbox`` (O9): sandbox money is not money, so the Payme sandbox keeps media on the
allowlist. Everything here is a pure function of ``Settings`` (plus the pause bit, read by the
caller from :mod:`bayram.media.overrides`), so the 🎁/🎟/💳 handlers and ``media_start`` can
re-evaluate it at press/run time — a rendered button is never proof of entitlement (§2.5).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType
from typing import Final, assert_never

from bayram.config import MediaBackendName, Settings
from bayram.contracts import Result, err
from bayram.db.enums import MediaBackend, MediaKind, MediaSku
from bayram.errors import CheckoutError
from bayram.logging import get_logger

__all__ = [
    "SKU_PRICE_FIELDS",
    "SKU_OFFERED_FIELDS",
    "SKU_BACKEND_FIELDS",
    "MEDIA_STUB_CHARGE_KEY",
    "is_live_paid",
    "is_beta_member",
    "is_sku_offered",
    "offered_skus",
    "sku_price_minor",
    "daily_cap",
    "env_backend",
    "effective_backend",
    "media_offered",
    "media_charge_refusal",
    "guarded_media_charge",
]

_LOG = get_logger(__name__)

#: The ``Settings`` field behind each SKU, spelled once so a fourth SKU is one edit here.
SKU_OFFERED_FIELDS: Final[Mapping[MediaSku, str]] = MappingProxyType(
    {
        MediaSku.IMAGE: "is_image_offered",
        MediaSku.VIDEO_STANDARD: "is_video_standard_offered",
        MediaSku.VIDEO_FAST: "is_video_fast_offered",
    }
)
SKU_PRICE_FIELDS: Final[Mapping[MediaSku, str]] = MappingProxyType(
    {
        MediaSku.IMAGE: "image_price_minor",
        MediaSku.VIDEO_STANDARD: "video_standard_price_minor",
        MediaSku.VIDEO_FAST: "video_fast_price_minor",
    }
)
SKU_BACKEND_FIELDS: Final[Mapping[MediaSku, str]] = MappingProxyType(
    {
        MediaSku.IMAGE: "image_backend",
        MediaSku.VIDEO_STANDARD: "video_standard_backend",
        MediaSku.VIDEO_FAST: "video_fast_backend",
    }
)

#: The locale key a refused media 💳 answers with.
MEDIA_STUB_CHARGE_KEY: Final[str] = "checkout.failed"


def is_live_paid(settings: Settings) -> bool:
    """Real money moves: Payme, an enforced meter, and not the sandbox (§2.5, O9)."""
    return (
        settings.checkout_provider == "payme"
        and settings.credits_enforced
        and not settings.payme_is_sandbox
    )


def is_beta_member(settings: Settings, telegram_user_id: int) -> bool:
    return settings.media_beta_enabled and telegram_user_id in settings.media_beta_allowlist


def is_sku_offered(settings: Settings, sku: MediaSku) -> bool:
    """The env flag alone. See :func:`media_offered` for the whole rule."""
    value = getattr(settings, SKU_OFFERED_FIELDS[sku])
    return bool(value)


def offered_skus(settings: Settings) -> tuple[MediaSku, ...]:
    return tuple(sku for sku in MediaSku if is_sku_offered(settings, sku))


def sku_price_minor(settings: Settings, sku: MediaSku) -> int | None:
    value = getattr(settings, SKU_PRICE_FIELDS[sku])
    return value if isinstance(value, int) else None


def daily_cap(settings: Settings, kind: MediaKind) -> int:
    """Paid requests of ``kind`` one account may start per UTC day (§7.6).

    Per KIND, not per SKU: both video tiers share one cap, as they share the one-open-request
    index. An exhaustive ``match`` so a third kind cannot ship without a cap.
    """
    match kind:
        case MediaKind.IMAGE:
            return settings.media_daily_cap_image
        case MediaKind.VIDEO:
            return settings.media_daily_cap_video
        case _:
            assert_never(kind)


def env_backend(settings: Settings, sku: MediaSku) -> MediaBackend:
    name: MediaBackendName = getattr(settings, SKU_BACKEND_FIELDS[sku])
    return MediaBackend(name)


def effective_backend(
    settings: Settings, sku: MediaSku, override: MediaBackend | None
) -> MediaBackend:
    """The Redis override when there is one, else the env backend (§4.5).

    Under ``use_fake_providers`` everything renders on the fake, whatever either says: that
    flag is "no vendor is contacted", and a Redis key must not be able to un-say it.

    The converse holds too: **an override of ``fake`` is ignored everywhere else** (§4.5 "an
    offered SKU whose effective backend is fake" is refused). Boot only sees the env backend,
    so a Redis key naming the fake would otherwise sell placeholder PNGs as the product.
    """
    if settings.use_fake_providers:
        return MediaBackend.FAKE
    if override is MediaBackend.FAKE:
        # §4.5 "unknown → ignored + alert": ERROR, because somebody meant to reroute paid
        # traffic and it is not happening.
        _LOG.error(
            "a media backend override names the fake outside a fake deployment; ignored",
            extra={"sku": sku.value},
        )
        return env_backend(settings, sku)
    return override if override is not None else env_backend(settings, sku)


def media_offered(
    settings: Settings, sku: MediaSku, telegram_user_id: int, *, is_paused: bool
) -> bool:
    """IMAGE_VIDEO_SPEC §2.5, verbatim. ``is_paused`` comes from ``overrides.read_paused``."""
    if not is_sku_offered(settings, sku) or is_paused:
        return False
    return is_live_paid(settings) or is_beta_member(settings, telegram_user_id)


def media_charge_refusal(settings: Settings, sku: MediaSku) -> CheckoutError | None:
    """Why a media 💳 must not reach ``CheckoutProvider.charge`` now, or ``None``.

    💳 is offered only on a live-paid rail (§2.5). The case that matters most is the stub:
    ``StubCheckoutProvider.charge`` reports every purchase PAID with no money moved
    (§7.2 step 2), so a media SKU on the stub would be a free render recorded as a sale.
    The sandbox is refused too: its money is not money, and beta covers that rail.
    """
    if is_live_paid(settings):
        return None
    return CheckoutError(
        "a media SKU is never charged on a rail that is not live-paid",
        user_message_key=MEDIA_STUB_CHARGE_KEY,
        context={
            "sku": sku.value,
            "checkout_provider": settings.checkout_provider,
            "payme_is_sandbox": settings.payme_is_sandbox,
        },
    )


async def guarded_media_charge[T](
    settings: Settings, sku: MediaSku, charge: Callable[[], Awaitable[Result[T]]]
) -> Result[T]:
    """Run ``charge`` only when :func:`media_charge_refusal` allows it.

    The one entry point the media pay handler (M5.1) calls: on the stub rail nothing is
    charged, so no receipt is written and no job is started (§10 M2.2).
    """
    refusal = media_charge_refusal(settings, sku)
    if refusal is not None:
        return err(refusal)
    return await charge()
