"""The ``AudioPostProcessor`` implementation.

Split in two on purpose.

The first half needs no binary at all: it drives the processor at binaries that do not
exist and asserts on the failure contract — an ``Err`` rather than an exception, nothing
left in the destination directory, and a terminal error where a retry could not help.

The second half is marked ``integration`` and renders REAL audio with the REAL ffmpeg, then
reads the result back with ffprobe. Nothing about ffmpeg is mocked: the assertions that
matter here (that Telegram will see an Opus voice note, that the song lands on target
loudness) are only meaningful against the actual encoder.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hbd.audio.processor import FfmpegAudioPostProcessor
from hbd.audio.startup import ensure_ffmpeg_available
from hbd.config import Settings
from hbd.contracts import AudioPostProcessor, is_err, is_ok
from tests.test_audio.conftest import (
    ABSENT_BINARY,
    FFPROBE_BINARY,
    LEAD_SILENCE_S,
    SONG_LUFS,
    SPEECH_LUFS,
    TONE_S,
    make_processor,
    requires_ffmpeg,
    write_stub_binary,
)

#: Two-pass loudnorm is accurate but not exact; this is generous enough for a short clip.
LOUDNESS_TOLERANCE_LUFS = 2.0
VOICE_NOTE_SAMPLE_RATE_HZ = 48_000
UNTRIMMED_DURATION_S = LEAD_SILENCE_S * 2 + TONE_S


def stream_info(path: Path) -> dict[str, object]:
    """Read a file's real codec back with ffprobe, independently of our own parser."""
    assert FFPROBE_BINARY is not None
    completed = subprocess.run(
        [
            FFPROBE_BINARY,
            "-hide_banner",
            "-loglevel",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-select_streams",
            "a:0",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    payload = json.loads(completed.stdout)
    return {**payload["streams"][0], "format_name": payload["format"]["format_name"]}


def leftovers(directory: Path, *, expected: set[str]) -> set[str]:
    return {child.name for child in directory.iterdir()} - expected


# ===========================================================================
# Contract and configuration — no binary needed
# ===========================================================================
def test_the_processor_satisfies_the_frozen_protocol() -> None:
    assert isinstance(make_processor(), AudioPostProcessor)


def test_from_settings_takes_every_knob_from_config(settings: Settings) -> None:
    # Arrange / Act
    processor = FfmpegAudioPostProcessor.from_settings(settings)

    # Assert
    assert processor.ffmpeg_binary == settings.ffmpeg_binary
    assert processor.ffprobe_binary == settings.ffprobe_binary
    assert processor.true_peak_db == settings.loudnorm_true_peak_db
    assert processor.fade_in_ms == settings.fade_in_ms
    assert processor.fade_out_ms == settings.fade_out_ms
    assert processor.silence_trim_threshold_db == settings.silence_trim_threshold_db
    assert processor.opus_bitrate_bps == settings.opus_bitrate_bps
    assert processor.opus_sample_rate_hz == settings.opus_sample_rate_hz


def test_the_processor_is_immutable() -> None:
    processor = make_processor()

    with pytest.raises((AttributeError, TypeError)):
        processor.ffmpeg_binary = "something-else"  # type: ignore[misc]


# ===========================================================================
# Failure contract — no binary needed
# ===========================================================================
async def test_a_non_ogg_voice_note_destination_is_refused_before_any_work(
    tmp_path: Path,
) -> None:
    # Arrange: an .mp3 here would upload as a file attachment with a download button.
    processor = make_processor()
    destination = tmp_path / "greeting.mp3"

    # Act
    result = await processor.to_voice_note(tmp_path / "in.wav", destination=destination)

    # Assert
    assert is_err(result)
    assert ".ogg" in result.error.operator_message
    assert result.error.is_retryable is False


async def test_a_refused_voice_note_destination_writes_nothing(tmp_path: Path) -> None:
    await make_processor().to_voice_note(tmp_path / "in.wav", destination=tmp_path / "g.mp3")

    assert leftovers(tmp_path, expected=set()) == set()


async def test_probe_reports_an_error_when_ffprobe_is_not_installed(
    absent_binary_processor: FfmpegAudioPostProcessor, tmp_path: Path
) -> None:
    result = await absent_binary_processor.probe(tmp_path / "song.ogg")

    assert is_err(result)
    assert result.error.is_retryable is False


async def test_normalize_reports_an_error_when_ffmpeg_is_not_installed(
    absent_binary_processor: FfmpegAudioPostProcessor, tmp_path: Path
) -> None:
    result = await absent_binary_processor.normalize_loudness(
        tmp_path / "song.wav", destination=tmp_path / "out.wav", target_lufs=SONG_LUFS
    )

    assert is_err(result)


async def test_a_failed_normalize_leaves_no_scratch_directory_and_no_partial_file(
    absent_binary_processor: FfmpegAudioPostProcessor, tmp_path: Path
) -> None:
    # Arrange
    destination = tmp_path / "out.wav"

    # Act
    await absent_binary_processor.normalize_loudness(
        tmp_path / "song.wav", destination=destination, target_lufs=SONG_LUFS
    )

    # Assert: a failed render leaves NOTHING behind, temp or partial.
    assert not destination.exists()
    assert leftovers(tmp_path, expected=set()) == set()


async def test_a_failed_voice_note_leaves_no_scratch_directory_and_no_partial_file(
    absent_binary_processor: FfmpegAudioPostProcessor, tmp_path: Path
) -> None:
    destination = tmp_path / "greeting.ogg"

    await absent_binary_processor.to_voice_note(tmp_path / "in.wav", destination=destination)

    assert not destination.exists()
    assert leftovers(tmp_path, expected=set()) == set()


async def test_probe_with_loudness_fails_when_the_file_cannot_be_read(
    absent_binary_processor: FfmpegAudioPostProcessor, tmp_path: Path
) -> None:
    result = await absent_binary_processor.probe_with_loudness(
        tmp_path / "song.wav", target_lufs=SONG_LUFS
    )

    assert is_err(result)


# ===========================================================================
# Real ffmpeg from here down
# ===========================================================================
@pytest.mark.integration
@requires_ffmpeg
async def test_startup_check_passes_against_the_installed_ffmpeg() -> None:
    # Assert: the boot-time check passes against the ffmpeg that just rendered the audio.
    ensure_ffmpeg_available(ffmpeg_binary="ffmpeg", ffprobe_binary="ffprobe")


@pytest.mark.integration
@requires_ffmpeg
async def test_probe_reads_the_real_shape_of_a_real_file(
    processor: FfmpegAudioPostProcessor, tone_wav: Path
) -> None:
    # Act
    result = await processor.probe(tone_wav)

    # Assert
    assert is_ok(result)
    assert result.value.duration_s == pytest.approx(UNTRIMMED_DURATION_S, abs=0.2)
    assert result.value.sample_rate_hz == 44_100
    assert result.value.channels == 2


@pytest.mark.integration
@requires_ffmpeg
async def test_probing_a_file_that_is_not_audio_is_an_error(
    processor: FfmpegAudioPostProcessor, tmp_path: Path
) -> None:
    # Arrange
    corrupt = tmp_path / "not-audio.wav"
    corrupt.write_bytes(b"this is definitely not a RIFF header")

    result = await processor.probe(corrupt)

    assert is_err(result)


@pytest.mark.integration
@requires_ffmpeg
async def test_normalize_writes_the_destination_and_removes_its_scratch(
    processor: FfmpegAudioPostProcessor, tone_wav: Path, tmp_path: Path
) -> None:
    # Arrange
    destination = tmp_path / "song-normalized.wav"

    # Act
    result = await processor.normalize_loudness(
        tone_wav, destination=destination, target_lufs=SONG_LUFS
    )

    # Assert
    assert is_ok(result)
    assert result.value == destination
    assert destination.stat().st_size > 0
    assert leftovers(tmp_path, expected={tone_wav.name, destination.name}) == set()


@pytest.mark.integration
@requires_ffmpeg
async def test_normalize_trims_the_silence_off_both_ends(
    processor: FfmpegAudioPostProcessor, tone_wav: Path, tmp_path: Path
) -> None:
    # Arrange: the source is half a second of silence, a tone, half a second of silence.
    destination = tmp_path / "trimmed.wav"

    # Act
    await processor.normalize_loudness(tone_wav, destination=destination, target_lufs=SONG_LUFS)

    # Assert
    probed = await processor.probe(destination)
    assert is_ok(probed)
    assert probed.value.duration_s == pytest.approx(TONE_S, abs=0.4)
    assert probed.value.duration_s < UNTRIMMED_DURATION_S - 0.5


@pytest.mark.integration
@requires_ffmpeg
async def test_the_song_lands_on_the_configured_song_loudness(
    processor: FfmpegAudioPostProcessor, tone_wav: Path, tmp_path: Path
) -> None:
    # Arrange
    destination = tmp_path / "song.wav"

    # Act
    await processor.normalize_loudness(tone_wav, destination=destination, target_lufs=SONG_LUFS)

    # Assert
    measured = await processor.probe_with_loudness(destination, target_lufs=SONG_LUFS)
    assert is_ok(measured)
    assert measured.value.loudness_lufs is not None
    assert measured.value.loudness_lufs == pytest.approx(SONG_LUFS, abs=LOUDNESS_TOLERANCE_LUFS)


@pytest.mark.integration
@requires_ffmpeg
async def test_speech_lands_on_the_quieter_speech_target(
    processor: FfmpegAudioPostProcessor, tone_wav: Path, tmp_path: Path
) -> None:
    # Arrange: the same source, the other target — the value must come from the caller.
    destination = tmp_path / "greeting.wav"

    await processor.normalize_loudness(tone_wav, destination=destination, target_lufs=SPEECH_LUFS)

    measured = await processor.probe_with_loudness(destination, target_lufs=SPEECH_LUFS)
    assert is_ok(measured)
    assert measured.value.loudness_lufs is not None
    assert measured.value.loudness_lufs == pytest.approx(SPEECH_LUFS, abs=LOUDNESS_TOLERANCE_LUFS)


@pytest.mark.integration
@requires_ffmpeg
async def test_normalizing_a_corrupt_source_is_an_error_that_leaves_nothing_behind(
    processor: FfmpegAudioPostProcessor, tmp_path: Path
) -> None:
    # Arrange
    corrupt = tmp_path / "corrupt.wav"
    corrupt.write_bytes(b"\x00" * 512)
    destination = tmp_path / "out.wav"

    # Act
    result = await processor.normalize_loudness(
        corrupt, destination=destination, target_lufs=SONG_LUFS
    )

    # Assert
    assert is_err(result)
    assert not destination.exists()
    assert leftovers(tmp_path, expected={corrupt.name}) == set()


@pytest.mark.integration
@requires_ffmpeg
async def test_the_error_from_a_corrupt_source_carries_ffmpegs_own_stderr(
    processor: FfmpegAudioPostProcessor, tmp_path: Path
) -> None:
    corrupt = tmp_path / "corrupt.wav"
    corrupt.write_bytes(b"\x00" * 512)

    result = await processor.normalize_loudness(
        corrupt, destination=tmp_path / "out.wav", target_lufs=SONG_LUFS
    )

    assert is_err(result)
    assert result.error.context.get("stderr")


# ---------------------------------------------------------------------------
# The voice note — this is the one Telegram is picky about
# ---------------------------------------------------------------------------
@pytest.mark.integration
@requires_ffmpeg
async def test_a_voice_note_is_really_opus_in_ogg(
    processor: FfmpegAudioPostProcessor, tone_wav: Path, tmp_path: Path
) -> None:
    # Arrange
    destination = tmp_path / "greeting.ogg"

    # Act
    result = await processor.to_voice_note(tone_wav, destination=destination)

    # Assert: read back with ffprobe, not with our own parser.
    assert is_ok(result)
    info = stream_info(destination)
    assert info["codec_name"] == "opus"
    assert "ogg" in str(info["format_name"])


@pytest.mark.integration
@requires_ffmpeg
async def test_a_voice_note_is_mono_at_48_khz(
    processor: FfmpegAudioPostProcessor, tone_wav: Path, tmp_path: Path
) -> None:
    # Arrange: the source is 44.1 kHz stereo, so both values must actually be changed.
    destination = tmp_path / "greeting.ogg"

    await processor.to_voice_note(tone_wav, destination=destination)

    info = stream_info(destination)
    assert info["channels"] == 1
    assert int(str(info["sample_rate"])) == VOICE_NOTE_SAMPLE_RATE_HZ


@pytest.mark.integration
@requires_ffmpeg
async def test_a_voice_note_preserves_the_length_of_the_greeting(
    processor: FfmpegAudioPostProcessor, tone_wav: Path, tmp_path: Path
) -> None:
    destination = tmp_path / "greeting.ogg"

    await processor.to_voice_note(tone_wav, destination=destination)

    probed = await processor.probe(destination)
    assert is_ok(probed)
    assert probed.value.duration_s == pytest.approx(UNTRIMMED_DURATION_S, abs=0.3)


@pytest.mark.integration
@requires_ffmpeg
async def test_a_voice_note_at_32k_is_small_enough_to_send(
    processor: FfmpegAudioPostProcessor, tone_wav: Path, tmp_path: Path
) -> None:
    # Arrange: 3 seconds at 32 kbps is roughly 12 kB; assert generously on the order.
    destination = tmp_path / "greeting.ogg"

    await processor.to_voice_note(tone_wav, destination=destination)

    assert 0 < destination.stat().st_size < 60_000


@pytest.mark.integration
@requires_ffmpeg
async def test_the_full_pipeline_order_normalize_then_encode(
    processor: FfmpegAudioPostProcessor, tone_wav: Path, tmp_path: Path
) -> None:
    # Arrange: this is exactly what the delivery stage does for each greeting.
    normalized = tmp_path / "greeting-normalized.wav"
    voice_note = tmp_path / "greeting.ogg"

    # Act
    first = await processor.normalize_loudness(
        tone_wav, destination=normalized, target_lufs=SPEECH_LUFS
    )
    second = await processor.to_voice_note(normalized, destination=voice_note)

    # Assert
    assert is_ok(first)
    assert is_ok(second)
    assert stream_info(voice_note)["codec_name"] == "opus"
    assert leftovers(tmp_path, expected={tone_wav.name, normalized.name, voice_note.name}) == set()


@pytest.mark.integration
@requires_ffmpeg
async def test_a_re_render_overwrites_the_previous_take(
    processor: FfmpegAudioPostProcessor, tone_wav: Path, tmp_path: Path
) -> None:
    # Arrange: name verification re-rolls a chunk, so the same path is written twice.
    destination = tmp_path / "greeting.ogg"
    destination.write_bytes(b"a stale earlier take")

    result = await processor.to_voice_note(tone_wav, destination=destination)

    assert is_ok(result)
    assert destination.read_bytes()[:4] == b"OggS"


@pytest.mark.integration
@requires_ffmpeg
async def test_probe_with_loudness_measures_an_untouched_file(
    processor: FfmpegAudioPostProcessor, tone_wav: Path
) -> None:
    result = await processor.probe_with_loudness(tone_wav, target_lufs=SONG_LUFS)

    assert is_ok(result)
    assert result.value.loudness_lufs is not None
    assert result.value.duration_s > 0


# ---------------------------------------------------------------------------
# Degrading rather than failing
#
# Reached with a stand-in binary that succeeds in a specific broken way. The processor
# still forks and execs a real process and still parses real output; what is faked is the
# health of the toolchain, which is the only way to reach these branches deterministically.
# ---------------------------------------------------------------------------
@pytest.mark.integration
@requires_ffmpeg
async def test_an_unmeasurable_file_still_yields_a_probe_without_loudness(
    tone_wav: Path, tmp_path: Path
) -> None:
    # Arrange: an "ffmpeg" that exits cleanly and prints no loudness report at all.
    stub = write_stub_binary(tmp_path / "quiet-ffmpeg", script="exit 0")
    processor = make_processor(ffmpeg_binary=stub)

    # Act
    result = await processor.probe_with_loudness(tone_wav, target_lufs=SONG_LUFS)

    # Assert: the duration still comes back; only the loudness is unknown.
    assert is_ok(result)
    assert result.value.loudness_lufs is None
    assert result.value.duration_s > 0


@pytest.mark.integration
@requires_ffmpeg
async def test_a_missing_ffmpeg_does_not_stop_a_probe_from_reporting_duration(
    tone_wav: Path,
) -> None:
    # Arrange: ffprobe works, ffmpeg does not — the measurement pass cannot run.
    processor = make_processor(ffmpeg_binary=ABSENT_BINARY)

    result = await processor.probe_with_loudness(tone_wav, target_lufs=SONG_LUFS)

    assert is_ok(result)
    assert result.value.loudness_lufs is None


@pytest.mark.integration
@requires_ffmpeg
async def test_an_ffmpeg_that_writes_nothing_fails_cleanly_rather_than_crashing(
    tone_wav: Path, tmp_path: Path
) -> None:
    # Arrange: an "ffmpeg" that exits zero and writes no output file at all. This is a
    # broken binary, not a silent source — the two were conflated before, and a silent
    # source now has its own test below because it must NOT fail.
    stub = write_stub_binary(tmp_path / "empty-ffmpeg", script="exit 0")
    processor = make_processor(ffmpeg_binary=stub)

    # Act
    result = await processor.normalize_loudness(
        tone_wav, destination=tmp_path / "out.wav", target_lufs=SONG_LUFS
    )

    # Assert — a typed error, and no half-written deliverable left behind.
    assert is_err(result)
    assert not (tmp_path / "out.wav").exists()


@pytest.mark.integration
@requires_ffmpeg
async def test_a_wholly_silent_source_is_passed_through_not_failed(
    silent_wav: Path, tmp_path: Path
) -> None:
    # Arrange: real digital silence. The trim strips every sample and loudnorm reports a
    # non-finite measurement, so normalisation is undefined — but the audio is still a
    # valid deliverable and must survive. Losing a paid render to a cosmetic pass is the
    # failure mode this guards.
    processor = make_processor()
    destination = tmp_path / "out.wav"

    # Act
    result = await processor.normalize_loudness(
        silent_wav, destination=destination, target_lufs=SONG_LUFS
    )

    # Assert
    assert is_ok(result)
    assert destination.exists()
    assert destination.stat().st_size > 0


@pytest.mark.integration
@requires_ffmpeg
async def test_an_unwritable_voice_note_destination_is_an_error_not_a_crash(
    processor: FfmpegAudioPostProcessor, tone_wav: Path, tmp_path: Path
) -> None:
    # Arrange: a non-empty directory sitting where the file must go.
    destination = tmp_path / "greeting.ogg"
    destination.mkdir()
    (destination / "occupied").write_bytes(b"in the way")

    # Act
    result = await processor.to_voice_note(tone_wav, destination=destination)

    # Assert
    assert is_err(result)
    assert result.error.context["operation"] == "voice_note.encode"
    assert leftovers(tmp_path, expected={tone_wav.name, destination.name}) == set()


@pytest.mark.integration
@requires_ffmpeg
async def test_an_unwritable_normalize_destination_is_an_error_not_a_crash(
    processor: FfmpegAudioPostProcessor, tone_wav: Path, tmp_path: Path
) -> None:
    destination = tmp_path / "out.wav"
    destination.mkdir()
    (destination / "occupied").write_bytes(b"in the way")

    result = await processor.normalize_loudness(
        tone_wav, destination=destination, target_lufs=SONG_LUFS
    )

    assert is_err(result)
    assert str(destination) in str(result.error.context["destination"])
