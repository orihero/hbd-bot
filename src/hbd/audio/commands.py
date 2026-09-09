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

:func:`brand_command` is a FOURTH pass and deliberately not folded into pass three.
``loudnorm_apply_command`` also builds every greeting intermediate, and its
``OUTPUT_HYGIENE_ARGS`` carries a ``-vn`` that would drop an attached cover picture without
saying so; its failure mode today is "ship the un-normalised raw render", which is a price
worth paying for loudness and not for a tag. A separate copy-only pass can therefore fail
on its own, cost the customer nothing but the watermark, and carry its own hygiene tuple.
"""

from __future__ import annotations

from pathlib import Path

from hbd.audio.constants import (
    BRAND_HYGIENE_ARGS,
    FFMPEG_COMMON_ARGS,
    ID3V2_VERSION,
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
    "brand_command",
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


def brand_command(
    binary: str,
    source: Path,
    *,
    destination: Path,
    cover: Path | None,
    tags: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    """The watermark pass: attach the cover picture and write the ID3 tags. Copy only.

    Three things about this argv are load-bearing, and each of them was chosen against a
    specific way of getting it wrong.

    ``-c:a copy``. This pass runs AFTER two-pass loudnorm, so re-encoding here would undo
    the only mastering the customer gets and would do it invisibly — the file plays, it is
    just quieter and lossier than the one we measured. There is nothing to re-encode for
    either: a tag and a picture are container-level, not sample-level.

    ``-c:v copy`` rather than ``-c:v mjpeg``. The cover arrives from
    :func:`hbd.audio.cover.render_cover` as a JPEG already, so a re-encode would cost
    quality for nothing — and, more usefully, copying means this pass needs no video
    ENCODER at all. That is what keeps ``startup.REQUIRED_ENCODERS`` at ``("libopus",)``:
    an ffmpeg that can serve every order today can still serve every order with artwork,
    so the boot check does not have to grow a new way to refuse to start.

    ``-map_metadata -1`` BEFORE the ``-metadata`` flags. ffmpeg applies output options in
    order, so the wipe placed after them wipes exactly the tags this function exists to
    write, exits zero, and produces an untagged file. Placing it first is why
    :data:`~hbd.audio.constants.BRAND_HYGIENE_ARGS` is spliced in above the tag pairs and
    not appended with them.

    The cover is optional and its absence removes the whole second input rather than
    passing an empty one: an ``-i`` with no file is an ffmpeg error, and a ``-map 1:v``
    against an input that does not exist is a different one.
    """
    picture: tuple[str, ...] = ()
    mapping: tuple[str, ...] = ()
    if cover is not None:
        picture = ("-i", str(cover))
        # ``attached_pic`` is what turns a mapped video stream into cover art rather than a
        # one-frame video track; without it players show a file with a stray video stream.
        mapping = (
            "-map",
            "0:a",
            "-map",
            "1:v",
            "-c:v",
            "copy",
            "-disposition:v:0",
            "attached_pic",
        )
    metadata = tuple(element for key, value in tags for element in ("-metadata", f"{key}={value}"))
    return (
        binary,
        *FFMPEG_COMMON_ARGS,
        "-i",
        str(source),
        *picture,
        *mapping,
        "-c:a",
        "copy",
        "-id3v2_version",
        ID3V2_VERSION,
        *BRAND_HYGIENE_ARGS,
        *metadata,
        str(destination),
    )
