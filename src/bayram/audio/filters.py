"""Pure builders for ffmpeg ``-af`` filter chains.

Every function here is a string function: no I/O, no subprocess, no clock. That is
deliberate — the filter graph is the part most likely to be wrong, and this way it is
asserted on directly in unit tests that need no binary.

Chain order is fixed and matters: **trim, then normalise, then fade.** Trimming first
means the loudness measurement is not dragged down by leading silence; fading last means
the fade shape survives the gain change instead of being re-levelled by it.
"""

from __future__ import annotations

from bayram.audio.constants import (
    LOUDNORM_OFFSET_LIMIT,
    LOUDNORM_TARGET_LRA,
    MS_PER_SECOND,
    NO_OP_FILTER,
    SILENCE_KEEP_S,
)
from bayram.audio.loudnorm import LoudnormMeasurement

__all__ = [
    "silence_trim_filter",
    "fade_filter",
    "loudnorm_measure_filter",
    "loudnorm_apply_filter",
    "join_filters",
]

#: ffmpeg parses filter arguments itself; fixed precision keeps a command reproducible
#: and keeps float repr noise (``-14.000000000000002``) out of the log.
_DECIMALS = 3


def _number(value: float) -> str:
    return f"{value:.{_DECIMALS}f}"


def _clamp(value: float, *, limit: float) -> float:
    return max(-limit, min(limit, value))


def silence_trim_filter(*, threshold_db: float) -> str:
    """Trim silence from BOTH ends.

    ffmpeg's ``silenceremove`` only trims the head, so the idiom is to run it, reverse,
    run it again and reverse back. A sliver of the silence is kept at each end so the
    first transient is not clipped.
    """
    single = (
        "silenceremove="
        f"start_periods=1:start_threshold={_number(threshold_db)}dB:"
        f"start_silence={_number(SILENCE_KEEP_S)}"
    )
    return f"{single},areverse,{single},areverse"


def fade_filter(*, fade_in_ms: int, fade_out_ms: int, duration_s: float) -> str | None:
    """Fade in from the head and out to the tail of a clip of known duration.

    Returns ``None`` when the clip is too short to carry both fades — overlapping fades
    would gate the middle of the audio, which is worse than no fade at all.
    """
    fade_in_s = fade_in_ms / MS_PER_SECOND
    fade_out_s = fade_out_ms / MS_PER_SECOND
    if duration_s <= 0 or fade_in_s + fade_out_s >= duration_s:
        return None

    parts: list[str] = []
    if fade_in_ms > 0:
        parts.append(f"afade=t=in:st=0:d={_number(fade_in_s)}")
    if fade_out_ms > 0:
        start = duration_s - fade_out_s
        parts.append(f"afade=t=out:st={_number(start)}:d={_number(fade_out_s)}")
    return ",".join(parts) if parts else None


def _loudnorm_targets(*, target_lufs: float, true_peak_db: float) -> str:
    return (
        f"loudnorm=I={_number(target_lufs)}"
        f":TP={_number(true_peak_db)}"
        f":LRA={_number(LOUDNORM_TARGET_LRA)}"
    )


def loudnorm_measure_filter(*, target_lufs: float, true_peak_db: float) -> str:
    """Pass one: measure only. The ``-f null`` sink discards the audio it produces."""
    targets = _loudnorm_targets(target_lufs=target_lufs, true_peak_db=true_peak_db)
    return f"{targets}:print_format=json"


def loudnorm_apply_filter(
    *,
    target_lufs: float,
    true_peak_db: float,
    measurement: LoudnormMeasurement | None,
) -> str:
    """Pass two: apply the measured correction linearly.

    With a usable measurement this is a single precise gain change (``linear=true``).
    Without one — silent input, or a measurement that would not parse — it degrades to
    single-pass dynamic normalisation, which is worse but never wrong.
    """
    targets = _loudnorm_targets(target_lufs=target_lufs, true_peak_db=true_peak_db)
    if measurement is None or not measurement.is_usable:
        return targets
    offset = _clamp(measurement.target_offset, limit=LOUDNORM_OFFSET_LIMIT)
    return (
        f"{targets}"
        f":measured_I={_number(measurement.input_i)}"
        f":measured_TP={_number(measurement.input_tp)}"
        f":measured_LRA={_number(measurement.input_lra)}"
        f":measured_thresh={_number(measurement.input_thresh)}"
        f":offset={_number(offset)}"
        ":linear=true:print_format=summary"
    )


def join_filters(*parts: str | None) -> str:
    """Join the non-empty stages into one ``-af`` argument, never an empty string."""
    present = [part for part in parts if part]
    return ",".join(present) if present else NO_OP_FILTER
