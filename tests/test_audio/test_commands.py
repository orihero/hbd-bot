"""The exact argv of every ffmpeg run.

These assertions look pedantic and are not: ``sendVoice`` renders a non-Opus upload as a
file attachment and still returns 200, so a wrong flag here is a silent product defect that
no runtime check catches.
"""

from __future__ import annotations

from pathlib import Path

from bayram.audio.commands import (
    brand_command,
    codec_args_for,
    loudnorm_apply_command,
    loudnorm_measure_command,
    silence_trim_command,
    voice_note_command,
)
from bayram.audio.constants import ID3V2_VERSION, INTERMEDIATE_CODEC
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


# ---------------------------------------------------------------------------
# branding — the watermark pass. Every flag here is a way to lose the watermark
# silently: ffmpeg exits zero for all of them.
# ---------------------------------------------------------------------------
COVER = Path("/tmp/cover.jpg")
TAGS: tuple[tuple[str, str], ...] = (
    ("title", "Tugʻilgan kun"),
    ("artist", "@bayram_uzbot"),
    ("album", "Generate yours at @bayram_uzbot"),
    ("comment", "This song has been generated by @bayram_uzbot"),
)


def indices_of(argv: tuple[str, ...], flag: str) -> list[int]:
    """Every position ``flag`` appears at. Order is the whole point of this pass."""
    return [index for index, element in enumerate(argv) if element == flag]


def test_brand_command_wipes_vendor_metadata_before_it_writes_ours() -> None:
    # Arrange: ffmpeg applies output options in order, so -map_metadata -1 placed AFTER the
    # -metadata flags wipes exactly the tags this pass exists to write — and exits zero.
    argv = brand_command(FFMPEG, SOURCE, destination=Path("/tmp/out.mp3"), cover=COVER, tags=TAGS)

    # Act
    wipe = argv.index("-map_metadata")
    first_tag = argv.index("-metadata")

    # Assert
    assert wipe < first_tag


def test_brand_command_never_drops_the_video_stream_the_cover_arrives_on() -> None:
    # Arrange: an attached picture IS a video stream, so the -vn that every other output in
    # this module carries would discard the artwork with no error anywhere.
    argv = brand_command(FFMPEG, SOURCE, destination=Path("/tmp/out.mp3"), cover=COVER, tags=TAGS)

    # Assert
    assert "-vn" not in argv


def test_brand_command_never_re_encodes_the_normalised_audio() -> None:
    # Arrange: this pass runs after two-pass loudnorm; re-encoding would undo it invisibly.
    argv = brand_command(FFMPEG, SOURCE, destination=Path("/tmp/out.mp3"), cover=COVER, tags=TAGS)

    # Assert
    assert flag_value(argv, "-c:a") == "copy"


def test_brand_command_attaches_the_cover_as_a_second_input() -> None:
    # Arrange
    argv = brand_command(FFMPEG, SOURCE, destination=Path("/tmp/out.mp3"), cover=COVER, tags=TAGS)

    # Act
    inputs = [argv[index + 1] for index in indices_of(argv, "-i")]
    maps = [argv[index + 1] for index in indices_of(argv, "-map")]

    # Assert
    assert inputs == [str(SOURCE), str(COVER)]
    assert maps == ["0:a", "1:v"]
    assert flag_value(argv, "-c:v") == "copy"
    assert flag_value(argv, "-disposition:v:0") == "attached_pic"


def test_brand_command_without_a_cover_maps_nothing_and_reads_one_input() -> None:
    # Arrange: an -i with no file is an ffmpeg error, and -map 1:v against an input that
    # does not exist is a different one, so the whole second input has to disappear.
    argv = brand_command(FFMPEG, SOURCE, destination=Path("/tmp/out.mp3"), cover=None, tags=TAGS)

    # Assert
    assert indices_of(argv, "-i") == [argv.index("-i")]
    assert "-map" not in argv
    assert "-c:v" not in argv
    assert "-disposition:v:0" not in argv


def test_brand_command_still_writes_the_tags_when_there_is_no_cover() -> None:
    # Arrange: a missing picture is not a missing watermark — three of the four tags are it.
    argv = brand_command(FFMPEG, SOURCE, destination=Path("/tmp/out.mp3"), cover=None, tags=TAGS)

    # Assert
    assert len(indices_of(argv, "-metadata")) == len(TAGS)


def test_brand_command_passes_a_tag_value_with_spaces_as_one_argv_element() -> None:
    # Arrange: run_command spawns without a shell, so quoting a value would put literal
    # quotation marks inside the ID3 frame.
    argv = brand_command(FFMPEG, SOURCE, destination=Path("/tmp/out.mp3"), cover=None, tags=TAGS)

    # Assert
    assert "comment=This song has been generated by @bayram_uzbot" in argv


def test_brand_command_pins_id3v2_point_three() -> None:
    # Arrange: ffmpeg defaults to 2.4, which Telegram and many Android players read badly.
    argv = brand_command(FFMPEG, SOURCE, destination=Path("/tmp/out.mp3"), cover=COVER, tags=TAGS)

    # Assert
    assert flag_value(argv, "-id3v2_version") == ID3V2_VERSION


def test_brand_command_writes_the_destination_last() -> None:
    argv = brand_command(FFMPEG, SOURCE, destination=Path("/tmp/out.mp3"), cover=COVER, tags=TAGS)

    assert argv[-1] == "/tmp/out.mp3"


# ---------------------------------------------------------------------------
# the pass that must NOT have changed
# ---------------------------------------------------------------------------
def test_the_loudnorm_apply_argv_is_byte_identical_to_what_it_produced_before() -> None:
    """Pinned literally, because the branding pass was deliberately NOT folded into it.

    ``loudnorm_apply_command`` also builds every greeting intermediate and its hygiene
    tuple carries the ``-vn``. A future edit that "unifies" the two passes would drop the
    cover from every song and change every greeting at the same time; this is the tripwire.
    """
    argv = loudnorm_apply_command(
        FFMPEG,
        SOURCE,
        Path("/tmp/n.wav"),
        target_lufs=-14.0,
        true_peak_db=-1.0,
        measurement=None,
        duration_s=30.0,
        fade_in_ms=250,
        fade_out_ms=1_500,
    )

    assert argv == (
        FFMPEG,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(SOURCE),
        "-af",
        "loudnorm=I=-14.000:TP=-1.000:LRA=11.000,"
        "afade=t=in:st=0:d=0.250,afade=t=out:st=28.500:d=1.500",
        "-vn",
        "-map_metadata",
        "-1",
        "-c:a",
        "pcm_s16le",
        "/tmp/n.wav",
    )
