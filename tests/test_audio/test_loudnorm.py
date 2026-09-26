"""Parsing loudnorm's pass-one report.

ffmpeg's stderr is external data we did not construct, so the tests below are mostly about
what happens when it is NOT the clean JSON the docs promise: a truncated object, a warning
printed after it, prose instead of a report, or the ``-inf`` a silent input produces.
"""

from __future__ import annotations

from bayram.audio.loudnorm import (
    LoudnormMeasurement,
    extract_last_json_object,
    parse_loudnorm_report,
)
from bayram.contracts import is_err, is_ok
from bayram.errors import ErrorCode

REPORT = """
[Parsed_loudnorm_0 @ 0x7f8]
{
\t"input_i" : "-22.53",
\t"input_tp" : "-3.25",
\t"input_lra" : "7.10",
\t"input_thresh" : "-33.04",
\t"output_i" : "-14.02",
\t"target_offset" : "0.40"
}
"""

SILENT_REPORT = REPORT.replace('"-22.53"', '"-inf"').replace('"-3.25"', '"-inf"')


def stderr_with(report: str) -> str:
    """A realistic stream: ffmpeg's normal chatter, then the report."""
    return (
        "ffmpeg version 7.1 Copyright (c) 2000-2024\n"
        "  Stream #0:0: Audio: pcm_s16le, 44100 Hz, stereo\n"
        f"{report}\n"
        "[out#0/null @ 0x1] video:0kB audio:5168kB\n"
    )


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------
def test_parses_the_five_values_pass_two_needs() -> None:
    # Arrange
    stderr = stderr_with(REPORT)

    # Act
    result = parse_loudnorm_report(stderr)

    # Assert
    assert is_ok(result)
    assert result.value.input_i == -22.53
    assert result.value.input_tp == -3.25
    assert result.value.input_lra == 7.10
    assert result.value.input_thresh == -33.04
    assert result.value.target_offset == 0.40


def test_ffmpeg_quoted_strings_are_coerced_to_floats() -> None:
    # Arrange: every value in the real report is a QUOTED string, never a JSON number.
    result = parse_loudnorm_report(stderr_with(REPORT))

    assert is_ok(result)
    assert isinstance(result.value.input_i, float)


def test_unknown_keys_from_a_newer_ffmpeg_do_not_break_a_render() -> None:
    report = REPORT.replace('"output_i"', '"some_future_field" : "1.0",\n\t"output_i"')

    result = parse_loudnorm_report(stderr_with(report))

    assert is_ok(result)


def test_a_report_is_found_even_when_ffmpeg_keeps_talking_afterwards() -> None:
    stderr = stderr_with(REPORT) + "\n[warning] something happened later\n"

    assert is_ok(parse_loudnorm_report(stderr))


# ---------------------------------------------------------------------------
# silence
# ---------------------------------------------------------------------------
def test_a_silent_input_parses_but_is_marked_unusable() -> None:
    # Arrange: silence measures -inf, which ffmpeg's own pass two would reject.
    result = parse_loudnorm_report(stderr_with(SILENT_REPORT))

    # Assert: it is an Ok, so the caller decides — and is_usable tells it to degrade.
    assert is_ok(result)
    assert result.value.is_usable is False


def test_a_finite_measurement_is_usable() -> None:
    result = parse_loudnorm_report(stderr_with(REPORT))

    assert is_ok(result)
    assert result.value.is_usable is True


def test_a_nan_measurement_is_unusable() -> None:
    measurement = LoudnormMeasurement(
        input_i=float("nan"), input_tp=-3.0, input_lra=7.0, input_thresh=-33.0, target_offset=0.0
    )

    assert measurement.is_usable is False


# ---------------------------------------------------------------------------
# malformed input
# ---------------------------------------------------------------------------
def test_returns_an_error_when_ffmpeg_printed_no_report_at_all() -> None:
    result = parse_loudnorm_report("ffmpeg version 7.1\nno json here\n")

    assert is_err(result)
    assert result.error.error_code is ErrorCode.AUDIO_FAILED


def test_returns_an_error_when_the_report_is_truncated() -> None:
    stderr = stderr_with('{"input_i" : "-22.53", "input_tp"')

    assert is_err(parse_loudnorm_report(stderr))


def test_returns_an_error_when_a_required_field_is_missing() -> None:
    # Arrange: syntactically valid JSON, wrong SHAPE. Validation must catch it.
    stderr = stderr_with('{"input_i" : "-22.53"}')

    result = parse_loudnorm_report(stderr)

    assert is_err(result)
    assert "shape validation" in result.error.operator_message


def test_returns_an_error_when_a_value_is_not_a_number() -> None:
    stderr = stderr_with(REPORT.replace('"-22.53"', '"not-a-number"'))

    assert is_err(parse_loudnorm_report(stderr))


def test_the_failure_carries_the_stderr_so_it_is_diagnosable_from_the_log() -> None:
    result = parse_loudnorm_report("nothing useful whatsoever")

    assert is_err(result)
    assert "nothing useful whatsoever" in str(result.error.context["stderr"])


def test_an_error_never_escapes_as_an_exception() -> None:
    # Arrange: the worst input there is.
    for hostile in ("", "{", "}", "{}", "null", "[1,2,3]", "{\x00}"):
        assert is_err(parse_loudnorm_report(hostile))


# ---------------------------------------------------------------------------
# the extractor
# ---------------------------------------------------------------------------
def test_extractor_returns_the_last_object_when_there_are_several() -> None:
    assert extract_last_json_object('{"a":1} noise {"b":2}') == '{"b":2}'


def test_extractor_returns_none_without_braces() -> None:
    assert extract_last_json_object("no braces here") is None


def test_extractor_returns_none_for_a_closing_brace_alone() -> None:
    assert extract_last_json_object("dangling }") is None
