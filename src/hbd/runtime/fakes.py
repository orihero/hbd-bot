"""Fakes that exist only so the offline demo exercises the *real* control flow.

``hbd.providers.tts.fakes.FakeSttProvider`` hears back what the fake TTS rendered, which is
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

from hbd.contracts import (
    HealthState,
    Language,
    ProviderHealth,
    Result,
    Transcript,
    err,
    ok,
)
from hbd.errors import ValidationError
from hbd.logging import get_logger

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

    def __init__(self, *, mishear_first: int = 0) -> None:
        if mishear_first < 0:
            raise ValueError(f"mishear_first must be >= 0, got {mishear_first}")
        self._mishear_first = mishear_first
        self._heard = 0

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
            return err(
                ValidationError(
                    "cannot transcribe an empty audio payload", context={"provider": self.name}
                )
            )
        self._heard += 1
        text = MISHEARD_TRANSCRIPT if self._heard <= self._mishear_first else _first(keyterms)
        _LOG.info(
            "fake transcription served",
            extra={"provider": self.name, "attempt": self._heard, "heard": text},
        )
        return ok(Transcript(text=text, language=language, confidence=_FAKE_CONFIDENCE))

    async def health(self) -> Result[ProviderHealth]:
        return ok(
            ProviderHealth(
                name=self.name,
                state=HealthState.HEALTHY,
                as_of=datetime.now(tz=UTC),
                detail="fake provider; no vendor contacted",
            )
        )


def _first(keyterms: Sequence[str]) -> str:
    """The intended name, as the name stage supplies it. Empty when it supplied nothing."""
    for term in keyterms:
        cleaned = term.strip()
        if cleaned:
            return cleaned
    return ""
