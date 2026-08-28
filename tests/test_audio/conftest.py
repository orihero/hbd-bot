"""Shared fixtures for the audio tests.

Two rules hold across this directory:

* **ffmpeg is never mocked.** Anything that needs it uses the real binary, is marked
  ``integration`` so ``make test`` skips it, and skips with a readable reason when the
  binary is absent. A test that mocked ffmpeg would assert on our idea of ffmpeg, which is
  exactly the thing most likely to be wrong.
* **Everything else needs no binary at all.** The filter chains, the argv, both parsers,
  the lyric sheet and the scratch-file invariants are pure, and they carry the coverage.
"""

from __future__ import annotations

import shutil
import stat
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from hbd.audio.loudnorm import LoudnormMeasurement
from hbd.audio.processor import FfmpegAudioPostProcessor

FFMPEG_BINARY = shutil.which("ffmpeg")
FFPROBE_BINARY = shutil.which("ffprobe")

#: A name no package manager will ever install, used to exercise the missing-binary path.
ABSENT_BINARY = "hbd-definitely-not-installed-ffmpeg"

_SKIP_REASON = (
    "needs a real ffmpeg and ffprobe on PATH: these tests render actual audio rather than "
    "asserting on a mock of the encoder. Install ffmpeg (with libopus) to run them."
)

requires_ffmpeg = pytest.mark.skipif(
    FFMPEG_BINARY is None or FFPROBE_BINARY is None, reason=_SKIP_REASON
)

#: Half a second of digital silence at each end, so a trim has something to remove.
LEAD_SILENCE_S = 0.5
TONE_S = 2.0
SOURCE_SAMPLE_RATE_HZ = 44_100
SOURCE_CHANNELS = 2


def make_processor(**overrides: object) -> FfmpegAudioPostProcessor:
    """A processor pointed at the real binaries, with test-sized defaults."""
    defaults: dict[str, object] = {
        "ffmpeg_binary": FFMPEG_BINARY or ABSENT_BINARY,
        "ffprobe_binary": FFPROBE_BINARY or ABSENT_BINARY,
        "true_peak_db": -1.0,
        "fade_in_ms": 100,
        "fade_out_ms": 200,
        "silence_trim_threshold_db": -50.0,
        "opus_bitrate_bps": 32_000,
        "opus_sample_rate_hz": 48_000,
        "timeout_s": 60.0,
    }
    return FfmpegAudioPostProcessor(**{**defaults, **overrides})  # type: ignore[arg-type]


@pytest.fixture
def processor() -> FfmpegAudioPostProcessor:
    return make_processor()


@pytest.fixture
def absent_binary_processor() -> FfmpegAudioPostProcessor:
    """Points at binaries that do not exist. Needs no ffmpeg to run."""
    return make_processor(ffmpeg_binary=ABSENT_BINARY, ffprobe_binary=ABSENT_BINARY)


@pytest.fixture
def tone_wav(tmp_path: Path) -> Iterator[Path]:
    """A real, tiny wav: silence, a 440 Hz tone, silence.

    Built with ffmpeg itself rather than hand-rolled PCM, because the point of the
    integration tests is that OUR command lines work on a file ffmpeg is happy with.
    """
    if FFMPEG_BINARY is None:
        pytest.skip(_SKIP_REASON)

    destination = tmp_path / "tone.wav"
    delay_ms = int(LEAD_SILENCE_S * 1_000)
    completed = subprocess.run(
        [
            FFMPEG_BINARY,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={TONE_S}",
            "-af",
            f"adelay={delay_ms}|{delay_ms},apad=pad_dur={LEAD_SILENCE_S}",
            "-ar",
            str(SOURCE_SAMPLE_RATE_HZ),
            "-ac",
            str(SOURCE_CHANNELS),
            str(destination),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"ffmpeg could not build the test tone: {completed.stderr[-400:]}")
    yield destination


@pytest.fixture
def silent_wav(tmp_path: Path) -> Iterator[Path]:
    """A real wav carrying nothing but digital silence.

    Degenerate on purpose: the trim strips every sample and loudnorm reports a non-finite
    measurement, so this is the input that proves normalisation degrades to a pass-through
    instead of throwing away an otherwise valid render.
    """
    if FFMPEG_BINARY is None:
        pytest.skip(_SKIP_REASON)

    destination = tmp_path / "silent.wav"
    completed = subprocess.run(
        [
            FFMPEG_BINARY,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={SOURCE_SAMPLE_RATE_HZ}:cl=mono",
            "-t",
            "1.0",
            str(destination),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"ffmpeg could not build the silent test file: {completed.stderr[-400:]}")
    yield destination


# ---------------------------------------------------------------------------
# Loudness targets and a measurement factory, shared by the pure tests
# ---------------------------------------------------------------------------
SONG_LUFS = -14.0
SPEECH_LUFS = -16.0
TRUE_PEAK_DB = -1.0


def make_measurement(**overrides: float) -> LoudnormMeasurement:
    """A plausible loudnorm pass-one report. Keyword-overridable, like the root factories."""
    defaults: dict[str, float] = {
        "input_i": -22.5,
        "input_tp": -3.25,
        "input_lra": 7.1,
        "input_thresh": -33.0,
        "target_offset": 0.4,
    }
    return LoudnormMeasurement(**{**defaults, **overrides})


# ---------------------------------------------------------------------------
# Stand-in binaries
# ---------------------------------------------------------------------------
def write_stub_binary(path: Path, *, script: str) -> str:
    """A real executable that behaves in one specific broken way.

    Used to reach the degradation paths a healthy ffmpeg never takes: exiting zero without
    writing an output file, or printing no loudness report. Returns its absolute path, so
    the caller passes it as ``ffmpeg_binary`` and no PATH manipulation is needed.
    """
    path.write_text(f"#!/bin/sh\n{script}\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)
