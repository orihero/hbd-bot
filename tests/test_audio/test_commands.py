"""The exact argv of every ffmpeg run.

These assertions look pedantic and are not: ``sendVoice`` renders a non-Opus upload as a
file attachment and still returns 200, so a wrong flag here is a silent product defect that
no runtime check catches.
"""

from __future__ import annotations

from pathlib import Path

from hbd.audio.commands import (
    codec_args_for,
    loudnorm_apply_command,
    loudnorm_measure_command,
    silence_trim_command,
    voice_note_command,
)
from hbd.audio.constants import INTERMEDIATE_CODEC
from tests.test_audio.conftest import SONG_LUFS, TRUE_PEAK_DB, make_measurement

FFMPEG = "/usr/bin/ffmpeg"
SOURCE = Path("/tmp/in.mp3")
DESTINATION = Path("/tmp/out.ogg")


def flag_value(argv: tuple[str, ...], flag: str) -> str:
    """The argument immediately after ``flag``. Fails loudly if the flag is absent."""
    return argv[argv.index(flag) + 1]


# ---------------------------------------------------------------------------
# codec selection
# ---------------------------------------------------------------------------
def test_wav_intermediates_pin_the_sample_format() -> None:
    assert codec_args_for(Path("x.wav")) == ("-c:a", INTERMEDIATE_CODEC)


def test_non_wav_destinations_leave_the_codec_to_ffmpeg() -> None:
    assert codec_args_for(Path("x.ogg")) == ()


def test_codec_selection_ignores_suffix_case() -> None:
    assert codec_args_for(Path("X.WAV")) == ("-c:a", INTERMEDIATE_CODEC)


# ---------------------------------------------------------------------------
# trim
# ---------------------------------------------------------------------------
def test_trim_command_reads_the_source_and_writes_the_destination_last() -> None:
    argv = silence_trim_command(FFMPEG, SOURCE, Path("/tmp/t.wav"), threshold_db=-50.0)

    assert argv[0] == FFMPEG
    assert flag_value(argv, "-i") == str(SOURCE)
    assert argv[-1] == "/tmp/t.wav"


def test_trim_command_never_lets_ffmpeg_read_the_shared_stdin() -> None:
    # Arrange: without -nostdin a backgrounded ffmpeg can stop the whole worker.
    argv = silence_trim_command(FFMPEG, SOURCE, Path("/tmp/t.wav"), threshold_db=-50.0)

    assert "-nostdin" in argv


def test_trim_command_drops_embedded_cover_art() -> None:
    argv = silence_trim_command(FFMPEG, SOURCE, Path("/tmp/t.wav"), threshold_db=-50.0)

    assert "-vn" in argv


# ---------------------------------------------------------------------------
# measure
# ---------------------------------------------------------------------------
def test_measure_command_writes_no_file() -> None:
    argv = loudnorm_measure_command(
        FFMPEG, SOURCE, target_lufs=SONG_LUFS, true_peak_db=TRUE_PEAK_DB
    )

    assert flag_value(argv, "-f") == "null"
    assert argv[-1] == "-"


def test_measure_command_asks_for_the_json_report() -> None:
    argv = loudnorm_measure_command(
        FFMPEG, SOURCE, target_lufs=SONG_LUFS, true_peak_db=TRUE_PEAK_DB
    )

    assert "print_format=json" in flag_value(argv, "-af")


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------
def test_apply_command_normalises_before_it_fades() -> None:
    # Arrange: fading first would let the gain change re-level the fade shape.
    argv = loudnorm_apply_command(
        FFMPEG,
        SOURCE,
        Path("/tmp/n.wav"),
        target_lufs=SONG_LUFS,
        true_peak_db=TRUE_PEAK_DB,
        measurement=make_measurement(),
        duration_s=30.0,
        fade_in_ms=250,
        fade_out_ms=1_500,
    )

    chain = flag_value(argv, "-af")
    assert chain.index("loudnorm") < chain.index("afade")


def test_apply_command_omits_the_fade_when_the_clip_is_too_short() -> None:
    argv = loudnorm_apply_command(
        FFMPEG,
        SOURCE,
        Path("/tmp/n.wav"),
        target_lufs=SONG_LUFS,
        true_peak_db=TRUE_PEAK_DB,
        measurement=None,
        duration_s=0.5,
        fade_in_ms=250,
        fade_out_ms=1_500,
    )

    assert "afade" not in flag_value(argv, "-af")


# ---------------------------------------------------------------------------
# voice note — every flag below is load-bearing for sendVoice
# ---------------------------------------------------------------------------
def test_voice_note_command_encodes_opus_in_ogg() -> None:
    argv = voice_note_command(
        FFMPEG, SOURCE, DESTINATION, bitrate_bps=32_000, sample_rate_hz=48_000
    )

    assert flag_value(argv, "-c:a") == "libopus"
    assert flag_value(argv, "-f") == "ogg"


def test_voice_note_command_is_mono_at_the_configured_rate_and_bitrate() -> None:
    argv = voice_note_command(
        FFMPEG, SOURCE, DESTINATION, bitrate_bps=24_000, sample_rate_hz=48_000
    )

    assert flag_value(argv, "-ac") == "1"
    assert flag_value(argv, "-ar") == "48000"
    assert flag_value(argv, "-b:a") == "24000"


def test_voice_note_command_hints_the_encoder_that_the_signal_is_speech() -> None:
    argv = voice_note_command(
        FFMPEG, SOURCE, DESTINATION, bitrate_bps=32_000, sample_rate_hz=48_000
    )

    assert flag_value(argv, "-application") == "voip"
    assert flag_value(argv, "-vbr") == "on"


def test_voice_note_command_strips_vendor_metadata_from_a_customer_deliverable() -> None:
    argv = voice_note_command(
        FFMPEG, SOURCE, DESTINATION, bitrate_bps=32_000, sample_rate_hz=48_000
    )

    assert flag_value(argv, "-map_metadata") == "-1"


def test_voice_note_command_does_not_pin_a_pcm_codec_over_the_opus_one() -> None:
    # Arrange: the .ogg destination must not pick up the wav intermediate's codec args.
    argv = voice_note_command(
        FFMPEG, SOURCE, DESTINATION, bitrate_bps=32_000, sample_rate_hz=48_000
    )

    assert INTERMEDIATE_CODEC not in argv
