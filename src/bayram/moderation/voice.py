"""Whether whisper's transcript of an own voice note can be trusted (IMAGE_VIDEO_SPEC §5.4).

L1 screens a voice note through its transcript, so a transcript that is not a transcription
— whisper hallucinates on Uzbek (rejected #13), and fills music, moaning or noise with filler
text — would let an unscreened sound through with a harmless-looking text. So the note is
**refused before payment, as ``review``,** when any of these holds:

* the transcript is empty, or ``no_speech_prob`` is high while silencedetect finds speech;
* the mean ``avg_logprob`` is below −1.0, or any segment's ``compression_ratio`` exceeds 2.4;
* the detected language is not uz, ru or en;
* there are fewer than about one word per 1.5 s of voiced audio.

Pure: the numbers come from :class:`~bayram.moderation.contracts.VoiceTranscript` (G3) and
:class:`~bayram.media.voice_probe.VoiceMeasure` (ffmpeg). Residual (§11 R11): tone and
non-verbal sound are unscreened.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from bayram.moderation.contracts import VoiceTranscript

__all__ = [
    "MIN_AVG_LOGPROB",
    "MAX_COMPRESSION_RATIO",
    "HIGH_NO_SPEECH_PROB",
    "SECONDS_PER_WORD",
    "MIN_VOICED_FOR_SPEECH_S",
    "ACCEPTED_LANGUAGES",
    "UntrustedTranscript",
    "untrusted_transcript",
]

MIN_AVG_LOGPROB: Final[float] = -1.0
MAX_COMPRESSION_RATIO: Final[float] = 2.4
#: Whisper's own ``no_speech_threshold``.
HIGH_NO_SPEECH_PROB: Final[float] = 0.6
#: "Fewer than ~1 word per 1.5 s of voiced audio" (§5.4).
SECONDS_PER_WORD: Final[float] = 1.5
#: Voiced audio below this is "no speech found" for the ``no_speech_prob`` rule.
MIN_VOICED_FOR_SPEECH_S: Final[float] = 0.5
ACCEPTED_LANGUAGES: Final[frozenset[str]] = frozenset({"uz", "ru", "en"})

#: Whisper's detected language may come back as a name rather than a code.
_LANGUAGE_NAMES: Final[dict[str, str]] = {"uzbek": "uz", "russian": "ru", "english": "en"}


class UntrustedTranscript(StrEnum):
    """Why a transcript was not trusted. Logged, never shown (SEC-3)."""

    EMPTY = "empty"
    NO_SPEECH = "no_speech"
    LOW_LOGPROB = "low_logprob"
    COMPRESSION = "compression"
    LANGUAGE = "language"
    WORD_RATE = "word_rate"


def _language_code(language: str) -> str:
    lowered = language.strip().lower()
    return _LANGUAGE_NAMES.get(lowered, lowered)


def untrusted_transcript(
    transcript: VoiceTranscript, *, voiced_s: float
) -> UntrustedTranscript | None:
    """The first §5.4 rule the transcript fails, or ``None`` when it reads as real speech."""
    words = len(transcript.text.split())
    if words == 0:
        return UntrustedTranscript.EMPTY
    if (
        transcript.no_speech_prob is not None
        and transcript.no_speech_prob >= HIGH_NO_SPEECH_PROB
        and voiced_s >= MIN_VOICED_FOR_SPEECH_S
    ):
        return UntrustedTranscript.NO_SPEECH
    if transcript.avg_logprob is not None and transcript.avg_logprob < MIN_AVG_LOGPROB:
        return UntrustedTranscript.LOW_LOGPROB
    if (
        transcript.max_compression_ratio is not None
        and transcript.max_compression_ratio > MAX_COMPRESSION_RATIO
    ):
        return UntrustedTranscript.COMPRESSION
    if _language_code(transcript.language) not in ACCEPTED_LANGUAGES:
        return UntrustedTranscript.LANGUAGE
    if words < int(voiced_s / SECONDS_PER_WORD):
        return UntrustedTranscript.WORD_RATE
    return None
