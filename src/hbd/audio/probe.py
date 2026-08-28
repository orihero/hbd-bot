"""Reading a file's real shape back out of ffprobe.

The pipeline asserts on what it produced — a greeting that came out 4 seconds long, or a
song ffmpeg silently wrote as stereo, is a bug we want to catch before Telegram does. So
ffprobe's JSON is parsed defensively: shape-validated with pydantic, unknown keys ignored,
and a missing duration treated as a failure rather than defaulted to zero.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, ValidationError

from hbd.audio.runner import tail
from hbd.contracts import AudioProbe, Result, err, ok
from hbd.errors import AudioProcessingError
from hbd.logging import get_logger

__all__ = ["parse_ffprobe_report", "ffprobe_args", "with_loudness"]

_LOG = get_logger(__name__)

_AUDIO_CODEC_TYPE: Final[str] = "audio"


class _FfprobeStream(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    codec_type: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    duration: float | None = None


class _FfprobeFormat(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    duration: float | None = None


class _FfprobeReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    streams: tuple[_FfprobeStream, ...] = ()
    format: _FfprobeFormat | None = None


def ffprobe_args(binary: str, source: Path) -> tuple[str, ...]:
    """The exact ffprobe invocation. Kept next to the parser that consumes its output."""
    return (
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-select_streams",
        "a:0",
        str(source),
    )


def _load_object(payload: str) -> dict[str, Any] | None:
    try:
        loaded = json.loads(payload)
    except (ValueError, TypeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _first_audio_stream(report: _FfprobeReport) -> _FfprobeStream | None:
    for stream in report.streams:
        if stream.codec_type is None or stream.codec_type == _AUDIO_CODEC_TYPE:
            return stream
    return None


def _duration_of(stream: _FfprobeStream, report: _FfprobeReport) -> float | None:
    """Prefer the stream's own duration; some containers only carry it at format level."""
    if stream.duration is not None and stream.duration > 0:
        return stream.duration
    if report.format is not None and report.format.duration is not None:
        return report.format.duration if report.format.duration > 0 else None
    return None


def parse_ffprobe_report(payload: str, *, source: Path) -> Result[AudioProbe]:
    """Turn ffprobe's stdout into an ``AudioProbe``. Never raises."""
    loaded = _load_object(payload)
    if loaded is None:
        return err(_failure("ffprobe output was not a JSON object", payload, source))

    try:
        report = _FfprobeReport.model_validate(loaded)
    except ValidationError as exc:
        return err(_failure("ffprobe output failed shape validation", payload, source, cause=exc))

    stream = _first_audio_stream(report)
    if stream is None:
        return err(_failure("ffprobe found no audio stream", payload, source))

    duration_s = _duration_of(stream, report)
    if duration_s is None:
        return err(_failure("ffprobe reported no usable duration", payload, source))
    if stream.sample_rate is None or stream.channels is None:
        return err(_failure("ffprobe reported no sample rate or channel count", payload, source))

    try:
        return ok(
            AudioProbe(
                duration_s=duration_s,
                sample_rate_hz=stream.sample_rate,
                channels=stream.channels,
            )
        )
    except ValidationError as exc:
        return err(_failure("ffprobe values are out of range", payload, source, cause=exc))


def with_loudness(probe: AudioProbe, loudness_lufs: float | None) -> AudioProbe:
    """Return a NEW probe carrying a measured loudness. Never mutates."""
    return AudioProbe(
        duration_s=probe.duration_s,
        loudness_lufs=loudness_lufs,
        sample_rate_hz=probe.sample_rate_hz,
        channels=probe.channels,
    )


def _failure(
    message: str, payload: str, source: Path, *, cause: Exception | None = None
) -> AudioProcessingError:
    _LOG.warning("audio.probe.unreadable", extra={"source": str(source), "reason": message})
    return AudioProcessingError(
        f"{message} for {source.name}",
        context={"source": str(source), "payload": tail(payload)},
        cause=cause,
    )
