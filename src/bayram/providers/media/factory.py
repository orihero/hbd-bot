"""Build the media provider for a backend from ``Settings`` (IMAGE_VIDEO_SPEC §4.3, O18).

The caller resolves WHICH backend — ``bayram.media.offering.effective_backend``, the env
backend with the operator's Redis override on top — and stamps it on the job row; this module
only turns the name into an adapter. ``use_fake_providers`` wins over everything: under it no
vendor is ever contacted, whatever a backend setting or a Redis key says.

Higgsfield is built (M6.1). fal is not yet: its name builds :class:`UnbuiltMediaProvider`, which
answers every call with a PRE-submit ``ProviderUnavailableError`` — so an operator override
pointed at it fails the submit cleanly (and falls back, §3.3) instead of crashing a stage.
Boot refuses to OFFER a SKU on it (``bayram.media.boot``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx

from bayram.config import Settings
from bayram.contracts import HealthState, ProviderHealth, Result, err, ok
from bayram.db.enums import MediaBackend, MediaSku
from bayram.errors import ProviderUnavailableError
from bayram.media.contracts import (
    PRE_SUBMIT,
    SUBMIT_PHASE_KEY,
    CostEstimate,
    GeneratedMedia,
    JobHandle,
    JobStatus,
    MediaCapabilities,
    MediaGenProvider,
    MediaKindName,
    MediaRequest,
)
from bayram.media.margin import OUTPUTS_PER_REQUEST, request_cost_ceiling_usd
from bayram.providers.media.fake import FakeMediaProvider
from bayram.providers.media.higgsfield import HiggsfieldProvider
from bayram.providers.media.local_gateway import LocalGatewayProvider

__all__ = ["build_media_provider", "higgsfield_submit_ceilings", "UnbuiltMediaProvider"]


class UnbuiltMediaProvider:
    """A backend named in configuration whose adapter does not exist yet (M6)."""

    def __init__(self, backend: MediaBackend) -> None:
        self.name = f"{backend.value}_unbuilt"
        self._backend = backend

    def _unavailable(self) -> ProviderUnavailableError:
        return ProviderUnavailableError(
            f"the {self._backend.value} media backend is not built yet (IMAGE_VIDEO_SPEC M6)",
            provider=self.name,
            is_retryable=False,
            context={SUBMIT_PHASE_KEY: PRE_SUBMIT},
        )

    def capabilities(self) -> MediaCapabilities:
        return MediaCapabilities(
            kinds=frozenset(),
            max_reference_images=0,
            native_audio=False,
            durations_s=(),
            aspects=frozenset(),
            cancel="none",
            estimate="none",
            webhook=False,
            idempotent_submit=False,
            provider_moderation=False,
            output_retention_s=None,
        )

    async def estimate_cost(self, req: MediaRequest) -> Result[CostEstimate]:
        return ok(CostEstimate(usd=None, basis="none"))

    async def submit(
        self,
        req: MediaRequest,
        *,
        correlation_key: str,
        webhook_url: str | None,
        timeout_s: float,
    ) -> Result[JobHandle]:
        return err(self._unavailable())

    async def poll(self, handle: JobHandle, *, timeout_s: float) -> Result[JobStatus]:
        return err(self._unavailable())

    async def fetch(
        self,
        handle: JobHandle,
        index: int,
        dest: Path,
        *,
        max_bytes: int,
        timeout_s: float,
    ) -> Result[GeneratedMedia]:
        return err(self._unavailable())

    async def cancel(self, handle: JobHandle) -> Result[bool]:
        return ok(False)

    async def health(self) -> Result[ProviderHealth]:
        return ok(
            ProviderHealth(
                name=self.name,
                state=HealthState.UNAVAILABLE,
                as_of=datetime.now(tz=UTC),
                detail="not built",
            )
        )


def build_media_provider(
    settings: Settings,
    backend: MediaBackend,
    *,
    client: httpx.AsyncClient | None = None,
) -> MediaGenProvider:
    """The adapter for ``backend``. Pass ``client`` to share a pooled connection."""
    if settings.use_fake_providers or backend is MediaBackend.FAKE:
        return FakeMediaProvider()
    if backend is MediaBackend.LOCAL:
        return LocalGatewayProvider(
            base_url=settings.genai_base_url,
            api_key=settings.genai_api_key,
            access_client_id=settings.genai_access_client_id,
            access_client_secret=settings.genai_access_client_secret,
            client=client,
        )
    if backend is MediaBackend.HIGGSFIELD:
        return HiggsfieldProvider(
            key_id=settings.higgsfield_api_key_id,
            secret=settings.higgsfield_api_secret,
            base_url=settings.higgsfield_base_url,
            usd_per_credit=settings.higgsfield_usd_per_credit,
            max_submit_cost_usd=higgsfield_submit_ceilings(settings),
            health_model=settings.higgsfield_video_model,
            client=client,
        )
    return UnbuiltMediaProvider(backend)


def higgsfield_submit_ceilings(settings: Settings) -> dict[MediaKindName, float]:
    """The adapter's last-gate cap on ONE submit: the request's ceiling shared by its outputs
    (§4.3). The stage chain enforces the request's whole ceiling across retries on top."""
    return {
        "image": request_cost_ceiling_usd(settings, MediaSku.IMAGE)
        / OUTPUTS_PER_REQUEST[MediaSku.IMAGE],
        "video": request_cost_ceiling_usd(settings, MediaSku.VIDEO_FAST),
    }
