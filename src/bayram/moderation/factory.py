"""Build the media moderator from ``Settings`` (IMAGE_VIDEO_SPEC §6.2).

``media_moderator="fake"`` (or ``use_fake_providers``, which always wins, as it does for the
generation backends) builds :class:`~bayram.moderation.fake.FakeModerator`. ``"gateway"`` is
the guard stack on the owner's 5090, whose client is M3.1; until it exists that name builds
:class:`UnbuiltGuardModerator`, which answers every call ``Err(unavailable)`` — the stage
chain's fail-closed path (§6.4, O10): before payment a request is answered ``media.busy`` and
nothing is sold; after it the output screen retries and finally holds.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

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

__all__ = ["build_media_moderator", "UnbuiltGuardModerator"]


class UnbuiltGuardModerator:
    """The ``gateway`` moderator before M3.1: nothing is judged, so nothing is allowed."""

    name = "gateway_guard_unbuilt"

    def _unavailable(self) -> ModerationUnavailableError:
        return ModerationUnavailableError(
            "the gateway guard client is not built yet (IMAGE_VIDEO_SPEC M3.1)",
            context={"moderator": self.name},
        )

    async def screen_text(self, items: Sequence[TextItem], *, policy: str) -> Result[MediaVerdict]:
        return err(self._unavailable())

    async def screen_images(
        self, items: Sequence[ImageItem], *, policy: str
    ) -> Result[MediaVerdict]:
        return err(self._unavailable())

    async def transcribe(self, audio: Path, *, language_hint: str) -> Result[VoiceTranscript]:
        return err(self._unavailable())


def build_media_moderator(settings: Settings) -> MediaModerator:
    if settings.use_fake_providers or settings.media_moderator == "fake":
        return FakeModerator()
    return UnbuiltGuardModerator()
