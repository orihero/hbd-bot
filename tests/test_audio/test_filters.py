"""The ``-af`` chains. Pure string assertions — no binary, no filesystem."""

from __future__ import annotations

from bayram.audio.constants import LOUDNORM_OFFSET_LIMIT, NO_OP_FILTER
from bayram.audio.filters import (
    fade_filter,
    join_filters,
    loudnorm_apply_filter,
    loudnorm_measure_filter,
    silence_trim_filter,
)
from tests.test_audio.conftest import SONG_LUFS, SPEECH_LUFS, TRUE_PEAK_DB, make_measurement


# ---------------------------------------------------------------------------
# silence trim
# ---------------------------------------------------------------------------
def test_silence_trim_runs_the_reverse_idiom_so_both_ends_are_trimmed() -> None:
    # Arrange / Act
    chain = silence_trim_filter(threshold_db=-50.0)

    # Assert: silenceremove only trims the head, so it must appear twice around areverse.
    assert chain.count("silenceremove") == 2
    assert chain.count("areverse") == 2
    assert chain.endswith("areverse")


def test_silence_trim_carries_the_configured_threshold_in_db() -> None:
    chain = silence_trim_filter(threshold_db=-42.5)

    assert "start_threshold=-42.500dB" in chain


# ---------------------------------------------------------------------------
# fades
# ---------------------------------------------------------------------------
def test_fade_places_the_fade_out_at_the_end_of_the_clip() -> None:
    # Arrange: 10s clip, 1.5s fade-out -> the fade must start at 8.5s.
    chain = fade_filter(fade_in_ms=250, fade_out_ms=1_500, duration_s=10.0)

    assert chain is not None
    assert "afade=t=in:st=0:d=0.250" in chain
    assert "afade=t=out:st=8.500:d=1.500" in chain


def test_fade_returns_none_when_the_clip_is_too_short_to_hold_both_fades() -> None:
    # Arrange: 1s of audio cannot carry 0.25s in and 1.5s out without gating the middle.
    assert fade_filter(fade_in_ms=250, fade_out_ms=1_500, duration_s=1.0) is None


def test_fade_returns_none_for_a_zero_length_clip() -> None:
    assert fade_filter(fade_in_ms=10, fade_out_ms=10, duration_s=0.0) is None


def test_fade_omits_the_stage_that_is_configured_off() -> None:
    chain = fade_filter(fade_in_ms=0, fade_out_ms=1_000, duration_s=10.0)

    assert chain is not None
    assert "t=in" not in chain
    assert "t=out" in chain


def test_fade_returns_none_when_both_fades_are_configured_off() -> None:
    assert fade_filter(fade_in_ms=0, fade_out_ms=0, duration_s=10.0) is None


# ---------------------------------------------------------------------------
# loudnorm
# ---------------------------------------------------------------------------
def test_measure_filter_requests_json_so_the_report_can_be_parsed() -> None:
    chain = loudnorm_measure_filter(target_lufs=SONG_LUFS, true_peak_db=TRUE_PEAK_DB)

    assert "print_format=json" in chain
    assert "I=-14.000" in chain
    assert "TP=-1.000" in chain


def test_measure_filter_uses_the_speech_target_when_given_one() -> None:
    chain = loudnorm_measure_filter(target_lufs=SPEECH_LUFS, true_peak_db=TRUE_PEAK_DB)

    assert "I=-16.000" in chain


def test_apply_filter_is_linear_and_carries_every_measured_value() -> None:
    measurement = make_measurement()

    chain = loudnorm_apply_filter(
        target_lufs=SONG_LUFS, true_peak_db=TRUE_PEAK_DB, measurement=measurement
    )

    assert "linear=true" in chain
    assert "measured_I=-22.500" in chain
    assert "measured_TP=-3.250" in chain
    assert "measured_LRA=7.100" in chain
    assert "measured_thresh=-33.000" in chain
    assert "offset=0.400" in chain


def test_apply_filter_degrades_to_a_single_dynamic_pass_without_a_measurement() -> None:
    chain = loudnorm_apply_filter(
        target_lufs=SONG_LUFS, true_peak_db=TRUE_PEAK_DB, measurement=None
    )

    assert "linear=true" not in chain
    assert "measured_I" not in chain
    assert chain.startswith("loudnorm=I=-14.000")


def test_apply_filter_ignores_a_measurement_taken_from_silence() -> None:
    # Arrange: a silent input measures -inf; feeding that back would fail pass two.
    measurement = make_measurement(input_i=float("-inf"))

    chain = loudnorm_apply_filter(
        target_lufs=SONG_LUFS, true_peak_db=TRUE_PEAK_DB, measurement=measurement
    )

    assert "measured_I" not in chain
    assert "inf" not in chain


def test_apply_filter_clamps_an_offset_ffmpeg_would_reject() -> None:
    measurement = make_measurement(target_offset=5_000.0)

    chain = loudnorm_apply_filter(
        target_lufs=SONG_LUFS, true_peak_db=TRUE_PEAK_DB, measurement=measurement
    )

    assert f"offset={LOUDNORM_OFFSET_LIMIT:.3f}" in chain


def test_apply_filter_clamps_a_large_negative_offset_too() -> None:
    measurement = make_measurement(target_offset=-5_000.0)

    chain = loudnorm_apply_filter(
        target_lufs=SONG_LUFS, true_peak_db=TRUE_PEAK_DB, measurement=measurement
    )

    assert f"offset={-LOUDNORM_OFFSET_LIMIT:.3f}" in chain


# ---------------------------------------------------------------------------
# joining
# ---------------------------------------------------------------------------
def test_join_drops_the_stages_that_are_absent() -> None:
    assert join_filters("a", None, "b", "") == "a,b"


def test_join_returns_a_pass_through_rather_than_an_empty_argument() -> None:
    # Arrange: ffmpeg errors on an empty -af, so an all-empty chain must still be valid.
    assert join_filters(None, "") == NO_OP_FILTER
