"""An own voice note's real length and speech: ffprobe and silencedetect (IMAGE_VIDEO_SPEC §5.4).

Telegram's ``voice.duration`` is client-reported and whole seconds, so a 5.9 s note passes the
bot's pre-row check as "5". ``media_screen`` downloads the note and asks ffprobe — the
authoritative length, refused before payment above the clip plus 0.25 s — and ffmpeg's
``silencedetect`` for how much of it is speech, which the whisper checks read (a transcript
with far fewer words than the voiced seconds could hold is whisper filling music or noise with
filler text).

:class:`VoiceProbe` is the seam: :class:`FfmpegVoiceProbe` in the worker, a fake in tests (no
ffmpeg in the unit suite). Both calls answer ``Result``; neither raises.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from bayram.audio.probe import ffprobe_args, parse_ffprobe_report
from bayram.audio.runner import run_command
from bayram.contracts import Result, is_err, ok

__all__ = [
    "SILENCE_NOISE_DB",
    "SILENCE_MIN_S",
    "VoiceProbe",
    "VoiceMeasure",
    "FfmpegVoiceProbe",
    "silencedetect_args",
    "silent_seconds",
]

#: Below this level counts as silence; a phone voice note's room noise sits well under it.
SILENCE_NOISE_DB: Final[int] = -35
#: A pause shorter than this is part of speech, not silence.
SILENCE_MIN_S: Final[float] = 0.3

_SILENCE_START = re.compile(r"silence_start:\s*(-?[0-9.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[0-9.]+)")


@dataclass(frozen=True, slots=True)
class VoiceMeasure:
    """The note's real length and how much of it is not silence, in seconds."""

    duration_s: float
    voiced_s: float


@runtime_checkable
class VoiceProbe(Protocol):
    async def measure(self, path: Path) -> Result[VoiceMeasure]: ...


def silencedetect_args(binary: str, source: Path) -> tuple[str, ...]:
    return (
        binary,
        "-hide_banner",
        "-nostats",
        "-i",
        str(source),
        "-af",
        f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_S}",
        "-f",
        "null",
        "-",
    )


def silent_seconds(stderr: str, duration_s: float) -> float:
    """Total silence in ffmpeg's ``silencedetect`` log, each span clipped to the note. A span
    still open at the end (no ``silence_end``) runs to the end of the note."""
    total = 0.0
    start: float | None = None
    for line in stderr.splitlines():
        started = _SILENCE_START.search(line)
        if started is not None:
            start = max(0.0, float(started.group(1)))
            continue
        ended = _SILENCE_END.search(line)
        if ended is not None and start is not None:
            total += max(0.0, min(float(ended.group(1)), duration_s) - start)
            start = None
    if start is not None:
        total += max(0.0, duration_s - start)
    return min(total, duration_s)


@dataclass(frozen=True, slots=True)
class FfmpegVoiceProbe:
    """ffprobe for the length, ffmpeg ``silencedetect`` for the speech. Host binaries."""

    ffprobe_binary: str = "ffprobe"
    ffmpeg_binary: str = "ffmpeg"
    timeout_s: float = 30.0

    async def measure(self, path: Path) -> Result[VoiceMeasure]:
        probed = await run_command(
            ffprobe_args(self.ffprobe_binary, path),
            operation="voice_note.probe",
            timeout_s=self.timeout_s,
        )
        if is_err(probed):
            return probed
        report = parse_ffprobe_report(probed.value.stdout, source=path)
        if is_err(report):
            return report
        duration = report.value.duration_s
        detected = await run_command(
            silencedetect_args(self.ffmpeg_binary, path),
            operation="voice_note.silencedetect",
            timeout_s=self.timeout_s,
        )
        if is_err(detected):
            return detected
        voiced = max(0.0, duration - silent_seconds(detected.value.stderr, duration))
        return ok(VoiceMeasure(duration_s=duration, voiced_s=voiced))
