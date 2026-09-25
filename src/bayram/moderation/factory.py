"""Build the media moderator from ``Settings`` (IMAGE_VIDEO_SPEC §6.2).

``media_moderator="fake"`` (or ``use_fake_providers``, which always wins, as it does for the
generation backends) builds :class:`~bayram.moderation.fake.FakeModerator`. ``"gateway"``
builds :class:`~bayram.moderation.gateway.GatewayGuardModerator` against
``media_moderator_base_url`` — or ``genai_base_url`` when that is empty, the guards living on
the same 5090 (§6.2) — with the gateway's key and Access token only on the gateway's own
host, and the ``media_moderator_*`` credentials anywhere else (:func:`guard_credentials`).
With neither set there is nothing to call, and the name builds
:class:`UnbuiltGuardModerator`, which answers every call ``Err(unavailable)`` — the stage
chain's fail-closed path (§6.4, O10): before payment a request is answered ``media.busy`` and
nothing is sold; after it the output screen retries and finally holds. Boot refuses an
offered SKU in that state (``bayram.media.boot``), so this is a development answer only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from bayram.config import Settings
from bayram.contracts import Result, err
from bayram.errors import ModerationUnavailableError
from bayram.moderation.contracts import (
    ImageItem,
    MediaModerator,
    MediaVerdict,
    TextItem,
    VoiceTranscript,
)
from bayram.moderation.fake import FakeModerator
from bayram.moderation.gateway import GatewayGuardModerator

__all__ = [
    "build_media_moderator",
    "moderator_base_url",
    "guard_credentials",
    "is_gateway_host",
    "GuardCredentials",
    "UnbuiltGuardModerator",
]


@dataclass(frozen=True, slots=True)
class GuardCredentials:
    """What the guard calls send: the key header and the Access service-token pair."""

    api_key: str
    access_client_id: str
    access_client_secret: str


class UnbuiltGuardModerator:
    """The ``gateway`` moderator with no address to call: nothing is judged, nothing allowed."""

    name = "gateway_guard_unconfigured"

    def _unavailable(self) -> ModerationUnavailableError:
        return ModerationUnavailableError(
            "no guard endpoint is configured (BAYRAM_MEDIA_MODERATOR_BASE_URL / "
            "BAYRAM_GENAI_BASE_URL, IMAGE_VIDEO_SPEC §6.2)",
            context={"moderator": self.name},
        )

    async def screen_text(
        self, items: Sequence[TextItem], *, policy: str, lang_hint: str | None = None
    ) -> Result[MediaVerdict]:
        return err(self._unavailable())

    async def screen_images(
        self, items: Sequence[ImageItem], *, policy: str, lang_hint: str | None = None
    ) -> Result[MediaVerdict]:
        return err(self._unavailable())

    async def transcribe(self, audio: Path, *, language_hint: str) -> Result[VoiceTranscript]:
        return err(self._unavailable())


def moderator_base_url(settings: Settings) -> str:
    """Where the guards answer: their own URL, else the generation gateway's (§6.2)."""
    return (settings.media_moderator_base_url or settings.genai_base_url).strip()


def _host(url: str) -> tuple[str, int | None] | None:
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    if not parts.hostname:
        return None
    return parts.hostname.lower(), port


def is_gateway_host(settings: Settings) -> bool:
    """Whether the guards answer on the generation gateway's own host (and port).

    True when ``media_moderator_base_url`` is empty (the guards ARE the gateway's, §6.2) or
    names the same host as ``genai_base_url``. Anything unparsable is another host.
    """
    own = settings.media_moderator_base_url.strip()
    if not own:
        return True
    guard, gateway = _host(own), _host(settings.genai_base_url)
    return guard is not None and guard == gateway


def guard_credentials(settings: Settings) -> GuardCredentials:
    """The credentials for the guard host — never the gateway's on a host that is not it.

    The 5090's key and its Cloudflare Access token open the generation gateway; pointing
    ``media_moderator_base_url`` at a hosted guard endpoint (the D24 fallback) must not hand
    them to that third party with every request. Another host gets its own
    ``media_moderator_*`` credentials, and boot refuses it without a key
    (``bayram.media.boot``).
    """
    if is_gateway_host(settings):
        return GuardCredentials(
            api_key=settings.genai_api_key,
            access_client_id=settings.genai_access_client_id,
            access_client_secret=settings.genai_access_client_secret,
        )
    return GuardCredentials(
        api_key=settings.media_moderator_api_key,
        access_client_id=settings.media_moderator_access_client_id,
        access_client_secret=settings.media_moderator_access_client_secret,
    )


def build_media_moderator(settings: Settings) -> MediaModerator:
    if settings.use_fake_providers or settings.media_moderator == "fake":
        return FakeModerator()
    base_url = moderator_base_url(settings)
    if not base_url:
        return UnbuiltGuardModerator()
    credentials = guard_credentials(settings)
    return GatewayGuardModerator(
        base_url=base_url,
        api_key=credentials.api_key,
        access_client_id=credentials.access_client_id,
        access_client_secret=credentials.access_client_secret,
        text_route=settings.media_guard_text_route,
        timeout_s=settings.media_guard_timeout_s,
        sexual_block_p=settings.media_sexual_image_block_p,
    )
