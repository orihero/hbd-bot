"""Fakes that exist only so the offline demo exercises the *real* control flow.

``bayram.providers.tts.fakes.FakeSttProvider`` hears back what the fake TTS rendered, which is
right for the greeting leg and useless for the song leg: ``FakeMusicProvider`` returns
genuine silence, so transcribing it yields an empty string, the name never verifies, and a
demo burns three re-rolls to arrive at a shrug.

:class:`KeytermSttProvider` stands in for a *good* STT instead. The name stage already
passes the intended name and every candidate orthography as keyterms, so echoing the first
keyterm is exactly what a perfect transcription of that chunk would return — no smuggled
knowledge, just the strongest honest answer available offline.

``mishear_first`` makes the interesting case demonstrable: the first N attempts come back
as something that will not match, so the acoustic loop actually re-rolls the name chunk
with the next candidate and *then* succeeds. That is the product's core mechanism, and a
demo where it never fires proves nothing about it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

from bayram.contracts import (
    HealthState,
    Language,
    ProviderHealth,
    Result,
    Transcript,
    Vendor,
    VendorOperation,
    err,
    ok,
)
from bayram.errors import BayramError, ValidationError
from bayram.logging import get_logger
from bayram.usage import LOGGING_USAGE_SINK, UsageSink, VendorUsage

__all__ = ["KeytermSttProvider", "KEYTERM_STT_NAME", "MISHEARD_TRANSCRIPT"]

_LOG = get_logger(__name__)

KEYTERM_STT_NAME: Final[str] = "fake_keyterm_stt"

#: Deliberately unlike any real name, so ``name_similarity`` scores it far below threshold.
MISHEARD_TRANSCRIPT: Final[str] = "zzz qqq vvv"

#: What the fake claims about its own certainty. Diagnostic only — the re-roll decision is
#: made on string similarity, never on this number.
_FAKE_CONFIDENCE: Final[float] = 0.92


class KeytermSttProvider:
    """An ``SttProvider`` that returns the first supplied keyterm. Never raises."""

    name: str = KEYTERM_STT_NAME

    def __init__(self, *, mishear_first: int = 0, usage: UsageSink = LOGGING_USAGE_SINK) -> None:
        if mishear_first < 0:
            raise ValueError(f"mishear_first must be >= 0, got {mishear_first}")
        self._mishear_first = mishear_first
        self._heard = 0
        self._usage = usage

    @property
    def call_count(self) -> int:
        return self._heard

    async def transcribe(
        self,
        audio: bytes,
        *,
        mime: str,
        language: Language,
        keyterms: Sequence[str] = (),
        timeout_s: float,
    ) -> Result[Transcript]:
        if not audio:
            rejected = ValidationError(
                "cannot transcribe an empty audio payload", context={"provider": self.name}
            )
            await self._record(
                operation=VendorOperation.TRANSCRIPTION,
                is_success=False,
                error=rejected,
                request_bytes=len(audio),
            )
            return err(rejected)
        self._heard += 1
        text = MISHEARD_TRANSCRIPT if self._heard <= self._mishear_first else _first(keyterms)
        _LOG.info(
            "fake transcription served",
            extra={"provider": self.name, "attempt": self._heard, "heard": text},
        )
        await self._record(
            operation=VendorOperation.TRANSCRIPTION,
            is_success=True,
            request_bytes=len(audio),
        )
        return ok(Transcript(text=text, language=language, confidence=_FAKE_CONFIDENCE))

    async def health(self) -> Result[ProviderHealth]:
        await self._record(operation=VendorOperation.HEALTH, is_success=True)
        return ok(
            ProviderHealth(
                name=self.name,
                state=HealthState.HEALTHY,
                as_of=datetime.now(tz=UTC),
                detail="fake provider; no vendor contacted",
            )
        )

    # -- internals ----------------------------------------------------------
    async def _record(
        self,
        *,
        operation: VendorOperation,
        is_success: bool,
        error: BayramError | None = None,
        request_bytes: int | None = None,
    ) -> None:
        """Record the call the way every other fake does: what happened, nothing more.

        No cost, no latency and no billed quantity: no vendor was contacted, so there is
        nothing genuine to put in those columns and a plausible-looking figure there would
        be exactly the fabricated number the usage table exists to keep out.
        """
        await self._usage.record(
            VendorUsage(
                vendor=Vendor.FAKE,
                operation=operation,
                provider=self.name,
                is_success=is_success,
                is_fake=True,
                error_code=error.error_code.value if error is not None else None,
                request_bytes=request_bytes,
            )
        )


def _first(keyterms: Sequence[str]) -> str:
    """The intended name, as the name stage supplies it. Empty when it supplied nothing."""
    for term in keyterms:
        cleaned = term.strip()
        if cleaned:
            return cleaned
    return ""
