"""The routing rules, pure (IMAGE_VIDEO_SPEC §3.3, §4.1, §4.4; §10 M6.2).

What may be fallen back on, where to, and how many references a backend is sent. The stage
chain that applies them is ``tests/test_runtime/test_media_routing.py``.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

import pytest

from bayram.config import Settings
from bayram.db.enums import MediaBackend, MediaSku
from bayram.errors import (
    BayramError,
    ErrorCode,
    ProviderAmbiguousError,
    ProviderError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
    ValidationError,
)
from bayram.media.contracts import (
    AMBIGUOUS,
    PRE_SUBMIT,
    SUBMIT_PHASE_KEY,
    MediaCapabilities,
    max_references,
)
from bayram.media.routing import (
    can_carry,
    collage_needed_on,
    fallback_backend,
    is_fallback_error,
    refs_sent,
    route_backends,
)

_PRE: dict[str, Any] = {SUBMIT_PHASE_KEY: PRE_SUBMIT}


def _caps(max_refs: int, **limits: int) -> MediaCapabilities:
    return MediaCapabilities(
        kinds=frozenset({"image", "video"}),
        max_reference_images=max_refs,
        native_audio=False,
        durations_s=(5.0,),
        aspects=frozenset({"9:16"}),
        cancel="none",
        estimate="table",
        webhook=False,
        idempotent_submit=False,
        provider_moderation=False,
        output_retention_s=None,
        reference_limits=MappingProxyType(limits),  # type: ignore[arg-type]
    )


def _live(settings: Settings, **update: Any) -> Settings:
    return settings.model_copy(update={"use_fake_providers": False, **update})


# ---------------------------------------------------------------------------
# What may be fallen back on (§3.3: "only on a pre-submit error")
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "error",
    [
        ProviderUnavailableError("down", provider="p", context=_PRE),
        ProviderQuotaExhaustedError("no balance", provider="p", context=_PRE),
        ProviderRateLimitedError("busy", provider="p", context=_PRE),
        ProviderError(
            "502, no job id",
            provider="local",
            code=ErrorCode.INVALID_INPUT,
            is_retryable=False,
            context={**_PRE, "http_status": 502},
        ),
    ],
)
def test_a_pre_submit_refusal_by_the_backend_may_fall_back(error: BayramError) -> None:
    assert is_fallback_error(error)


@pytest.mark.parametrize(
    ("error", "why"),
    [
        (
            ProviderAmbiguousError("maybe", provider="p", context={SUBMIT_PHASE_KEY: AMBIGUOUS}),
            "ambiguous",
        ),
        (ProviderUnavailableError("down", provider="p"), "phase unknown"),
        (ValidationError("composite first", context=_PRE), "our refusal of the request"),
        (
            ProviderError(
                "over the ceiling",
                provider="p",
                code=ErrorCode.INVALID_INPUT,
                is_retryable=False,
                context=_PRE,
            ),
            "cost ceiling",
        ),
    ],
)
def test_nothing_else_falls_back(error: BayramError, why: str) -> None:
    assert not is_fallback_error(error), why


# ---------------------------------------------------------------------------
# Where to
# ---------------------------------------------------------------------------
def test_no_fallback_is_configured_by_default(settings: Settings) -> None:
    live = _live(settings)

    assert fallback_backend(live, MediaSku.IMAGE, MediaBackend.LOCAL) is None
    assert route_backends(live, MediaSku.VIDEO_FAST, None) == (MediaBackend.HIGGSFIELD,)


def test_the_route_is_the_effective_backend_then_the_fallback(settings: Settings) -> None:
    live = _live(settings, video_fast_fallback_backend="local")

    assert route_backends(live, MediaSku.VIDEO_FAST, None) == (
        MediaBackend.HIGGSFIELD,
        MediaBackend.LOCAL,
    )
    # An operator override that already points at the fallback leaves nothing to fall to.
    assert route_backends(live, MediaSku.VIDEO_FAST, MediaBackend.LOCAL) == (MediaBackend.LOCAL,)


def test_a_fake_fallback_is_ignored_outside_a_fake_deployment(settings: Settings) -> None:
    live = _live(settings, image_fallback_backend="fake")

    assert fallback_backend(live, MediaSku.IMAGE, MediaBackend.LOCAL) is None


def test_under_fake_providers_the_fallback_is_the_fake(settings: Settings) -> None:
    fakes = settings.model_copy(
        update={"use_fake_providers": True, "image_fallback_backend": "higgsfield"}
    )

    assert fallback_backend(fakes, MediaSku.IMAGE, MediaBackend.HIGGSFIELD) is MediaBackend.FAKE
    assert fallback_backend(fakes, MediaSku.IMAGE, MediaBackend.FAKE) is None


# ---------------------------------------------------------------------------
# How many references (§4.4, O6)
# ---------------------------------------------------------------------------
def test_photos_go_natively_when_the_backend_takes_that_many() -> None:
    multi, single = _caps(4), _caps(1)

    assert refs_sent(multi, "video", photos=3, has_collage=True) == 3
    assert refs_sent(single, "video", photos=3, has_collage=True) == 1
    assert refs_sent(single, "video", photos=3, has_collage=False) is None
    assert refs_sent(single, "image", photos=1, has_collage=False) == 1


def test_the_limit_is_per_kind_where_the_backend_says_so() -> None:
    caps = _caps(9, image=0, video=9)

    assert max_references(caps, "image") == 0
    assert max_references(caps, "video") == 9
    # A text-only image model carries a request with no photo, and none with one.
    assert can_carry(caps, "image", photos=0, has_collage=False)
    assert not can_carry(caps, "image", photos=1, has_collage=False)
    assert can_carry(caps, "video", photos=4, has_collage=False)


def test_a_one_ref_fallback_needs_the_screened_collage() -> None:
    assert can_carry(_caps(1), "image", photos=3, has_collage=True)
    assert not can_carry(_caps(1), "image", photos=3, has_collage=False)


def test_a_collage_is_built_when_any_backend_on_the_route_needs_one() -> None:
    assert not collage_needed_on([_caps(4)], "image", photos=3)
    assert collage_needed_on([_caps(4), _caps(1)], "image", photos=3)
    assert not collage_needed_on([_caps(1)], "image", photos=1)
