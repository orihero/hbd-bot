"""Pure builders for the exact argv of every ffmpeg run this package makes.

Nothing here spawns anything. An ffmpeg command is a long, order-sensitive, easy-to-get-
subtly-wrong list of strings, and the cheapest place to assert on it is a unit test that
compares tuples — not a rendered file. So the argv lives here and the spawning lives in
:mod:`hbd.audio.runner`.

Normalisation deliberately runs as three separate ffmpeg passes rather than one clever
graph:

1. **trim** the silence and write an uncompressed intermediate,
2. **measure** the trimmed intermediate (loudnorm pass one),
3. **apply** the measured correction and the fades (loudnorm pass two).

The split exists because the fade-out has to start at ``duration - fade_out`` and the
duration is only known AFTER the trim. Computing it from the untrimmed source would place
the fade past the end of the audio, which silently produces no fade at all.
"""

from __future__ import annotations

from pathlib import Path

from hbd.audio.constants import (
    FFMPEG_COMMON_ARGS,
    INTERMEDIATE_CODEC,
    INTERMEDIATE_SUFFIX,
    NULL_MUXER,
    NULL_SINK,
    OPUS_APPLICATION,
    OUTPUT_HYGIENE_ARGS,
    VOICE_NOTE_CHANNELS,
    VOICE_NOTE_CODEC,
    VOICE_NOTE_CONTAINER,
    VOICE_NOTE_VBR,
)
from hbd.audio.filters import (
    fade_filter,
    join_filters,
    loudnorm_apply_filter,
    loudnorm_measure_filter,
    silence_trim_filter,
)
from hbd.audio.loudnorm import LoudnormMeasurement

__all__ = [
    "silence_trim_command",
    "loudnorm_measure_command",
    "loudnorm_apply_command",
    "voice_note_command",
    "codec_args_for",
]


def codec_args_for(destination: Path) -> tuple[str, ...]:
    """Pin the codec for our own uncompressed intermediates; let ffmpeg infer otherwise.

    A ``.wav`` destination is always an intermediate in this package, and pinning the
    sample format keeps a chain of passes bit-identical across ffmpeg builds.
    """
    if destination.suffix.lower() == INTERMEDIATE_SUFFIX:
        return ("-c:a", INTERMEDIATE_CODEC)
    return ()


def silence_trim_command(
    binary: str, source: Path, destination: Path, *, threshold_db: float
) -> tuple[str, ...]:
    """Pass one of three: strip the silence off both ends."""
    return (
        binary,
        *FFMPEG_COMMON_ARGS,
        "-i",
        str(source),
        "-af",
        silence_trim_filter(threshold_db=threshold_db),
        *OUTPUT_HYGIENE_ARGS,
        *codec_args_for(destination),
        str(destination),
    )


def loudnorm_measure_command(
    binary: str, source: Path, *, target_lufs: float, true_peak_db: float
) -> tuple[str, ...]:
    """Pass two of three: measure only, write nothing, print the report to stderr."""
    return (
        binary,
        *FFMPEG_COMMON_ARGS,
        "-i",
        str(source),
        "-af",
        loudnorm_measure_filter(target_lufs=target_lufs, true_peak_db=true_peak_db),
        "-vn",
        "-f",
        NULL_MUXER,
        NULL_SINK,
    )


def loudnorm_apply_command(
    binary: str,
    source: Path,
    destination: Path,
    *,
    target_lufs: float,
    true_peak_db: float,
    measurement: LoudnormMeasurement | None,
    duration_s: float,
    fade_in_ms: int,
    fade_out_ms: int,
) -> tuple[str, ...]:
    """Pass three of three: apply the correction, then fade.

    ``measurement`` may be ``None``; :func:`loudnorm_apply_filter` then degrades to a
    single dynamic pass rather than failing the render.
    """
    chain = join_filters(
        loudnorm_apply_filter(
            target_lufs=target_lufs, true_peak_db=true_peak_db, measurement=measurement
        ),
        fade_filter(fade_in_ms=fade_in_ms, fade_out_ms=fade_out_ms, duration_s=duration_s),
    )
    return (
        binary,
        *FFMPEG_COMMON_ARGS,
        "-i",
        str(source),
        "-af",
        chain,
        *OUTPUT_HYGIENE_ARGS,
        *codec_args_for(destination),
        str(destination),
    )


def voice_note_command(
    binary: str, source: Path, destination: Path, *, bitrate_bps: int, sample_rate_hz: int
) -> tuple[str, ...]:
    """Transcode to what ``sendVoice`` accepts.

    Every one of ``libopus``, ``ogg``, mono and 48 kHz is load-bearing. Telegram renders
    anything else as a file attachment with a download button instead of a waveform, and
    it does so silently — the API call still returns 200.
    """
    return (
        binary,
        *FFMPEG_COMMON_ARGS,
        "-i",
        str(source),
        *OUTPUT_HYGIENE_ARGS,
        "-ac",
        str(VOICE_NOTE_CHANNELS),
        "-ar",
        str(sample_rate_hz),
        "-c:a",
        VOICE_NOTE_CODEC,
        "-b:a",
        str(bitrate_bps),
        "-vbr",
        VOICE_NOTE_VBR,
        "-application",
        OPUS_APPLICATION,
        "-f",
        VOICE_NOTE_CONTAINER,
        str(destination),
    )
