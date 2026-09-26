"""Parsing ffprobe.

The pipeline asserts on what it produced — a greeting that came out 4 seconds long, or a
song ffmpeg quietly wrote as stereo. That only works if a missing field is a failure rather
than a zero, so most of these tests are about ffprobe NOT answering the question.
"""

from __future__ import annotations

import json
from pathlib import Path

from bayram.audio.probe import ffprobe_args, parse_ffprobe_report, with_loudness
from bayram.contracts import AudioProbe, is_err, is_ok

SOURCE = Path("/tmp/song.ogg")


def report(**overrides: object) -> str:
    stream: dict[str, object] = {
        "codec_type": "audio",
        "sample_rate": 48_000,
        "channels": 1,
        "duration": 123.456,
    }
    stream.update(overrides)
    return json.dumps({"streams": [stream], "format": {"duration": 123.456}})


# ---------------------------------------------------------------------------
# argv
# ---------------------------------------------------------------------------
def test_ffprobe_is_asked_for_json_and_only_the_first_audio_stream() -> None:
    argv = ffprobe_args("/usr/bin/ffprobe", SOURCE)

    assert argv[0] == "/usr/bin/ffprobe"
    assert "json" in argv
    assert "a:0" in argv
    assert argv[-1] == str(SOURCE)


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------
def test_reads_duration_sample_rate_and_channels() -> None:
    # Arrange / Act
    result = parse_ffprobe_report(report(), source=SOURCE)

    # Assert
    assert is_ok(result)
    assert result.value.duration_s == 123.456
    assert result.value.sample_rate_hz == 48_000
    assert result.value.channels == 1


def test_ffprobe_string_numbers_are_coerced() -> None:
    # Arrange: ffprobe emits sample_rate as a STRING, not a number.
    result = parse_ffprobe_report(report(sample_rate="44100"), source=SOURCE)

    assert is_ok(result)
    assert result.value.sample_rate_hz == 44_100


def test_falls_back_to_the_container_duration_when_the_stream_has_none() -> None:
    # Arrange: some containers only carry duration at format level.
    payload = json.dumps(
        {
            "streams": [{"codec_type": "audio", "sample_rate": 48_000, "channels": 2}],
            "format": {"duration": 61.5},
        }
    )

    result = parse_ffprobe_report(payload, source=SOURCE)

    assert is_ok(result)
    assert result.value.duration_s == 61.5


def test_unknown_ffprobe_fields_are_ignored() -> None:
    result = parse_ffprobe_report(report(bit_rate="128000", profile="LC"), source=SOURCE)

    assert is_ok(result)


# ---------------------------------------------------------------------------
# malformed
# ---------------------------------------------------------------------------
def test_returns_an_error_when_ffprobe_printed_nothing() -> None:
    result = parse_ffprobe_report("", source=SOURCE)

    assert is_err(result)
    assert "not a JSON object" in result.error.operator_message


def test_returns_an_error_when_there_is_no_audio_stream() -> None:
    payload = json.dumps({"streams": [], "format": {"duration": 10.0}})

    result = parse_ffprobe_report(payload, source=SOURCE)

    assert is_err(result)
    assert "no audio stream" in result.error.operator_message


def test_returns_an_error_rather_than_defaulting_a_missing_duration_to_zero() -> None:
    payload = json.dumps(
        {"streams": [{"codec_type": "audio", "sample_rate": 48_000, "channels": 1}]}
    )

    result = parse_ffprobe_report(payload, source=SOURCE)

    assert is_err(result)
    assert "duration" in result.error.operator_message


def test_returns_an_error_when_the_duration_is_zero_everywhere() -> None:
    # Arrange: this is what a silence-trimmed, wholly silent file looks like.
    payload = json.dumps(
        {
            "streams": [
                {"codec_type": "audio", "sample_rate": 48_000, "channels": 1, "duration": 0.0}
            ],
            "format": {"duration": 0.0},
        }
    )

    assert is_err(parse_ffprobe_report(payload, source=SOURCE))


def test_a_zero_stream_duration_falls_back_to_the_container_duration() -> None:
    # Arrange: an ogg stream often reports 0 while the container knows the real length.
    result = parse_ffprobe_report(report(duration=0.0), source=SOURCE)

    assert is_ok(result)
    assert result.value.duration_s == 123.456


def test_returns_an_error_when_the_channel_count_is_absent() -> None:
    payload = json.dumps(
        {"streams": [{"codec_type": "audio", "sample_rate": 48_000, "duration": 3.0}]}
    )

    assert is_err(parse_ffprobe_report(payload, source=SOURCE))


def test_returns_an_error_when_a_value_is_out_of_range() -> None:
    # Arrange: AudioProbe requires channels > 0; ffprobe should never say 0, but might.
    assert is_err(parse_ffprobe_report(report(channels=0), source=SOURCE))


def test_the_failure_carries_the_payload_for_the_log() -> None:
    result = parse_ffprobe_report("garbage from ffprobe", source=SOURCE)

    assert is_err(result)
    assert "garbage from ffprobe" in str(result.error.context["payload"])


def test_never_raises_on_hostile_payloads() -> None:
    for hostile in ("", "[]", "null", "{", '{"streams": "not-a-list"}'):
        assert is_err(parse_ffprobe_report(hostile, source=SOURCE))


# ---------------------------------------------------------------------------
# with_loudness
# ---------------------------------------------------------------------------
def test_with_loudness_returns_a_new_probe_and_never_mutates_the_original() -> None:
    # Arrange
    original = AudioProbe(duration_s=10.0, sample_rate_hz=48_000, channels=1)

    # Act
    enriched = with_loudness(original, -14.2)

    # Assert
    assert enriched.loudness_lufs == -14.2
    assert original.loudness_lufs is None
    assert enriched is not original


def test_with_loudness_accepts_an_unmeasured_none() -> None:
    original = AudioProbe(duration_s=10.0, sample_rate_hz=48_000, channels=1)

    assert with_loudness(original, None).loudness_lufs is None
