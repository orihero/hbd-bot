"""ffmpeg for a video (IMAGE_VIDEO_SPEC §5.3, §5.4, §5.6, §6.4 L4).

The fit, the filter chains, the argv and the ffprobe parser are pure and run everywhere. The
second half renders with the REAL ffmpeg against the vendored 5.06 s clip the fake backend
serves, is marked ``integration``, and skips when the binary is absent — the §10 M4.3 line
"mux output duration = video duration" is asserted on what ffmpeg actually wrote, never on a
mock of it (the ``tests/test_audio`` rule).
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from bayram.contracts import is_err
from bayram.media.mux import (
    FADE_OUT_S,
    MAX_SCREEN_FRAMES,
    AudioFit,
    FfmpegVideoTools,
    VideoProbe,
    audio_fit,
    is_streamable,
    mux_args,
    narration_filter,
    parse_video_probe,
)
from bayram.providers.media.fake import fake_clip_bytes
from bayram.providers.tts.fakes import silent_wav

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
requires_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None,
    reason="needs a real ffmpeg and ffprobe on PATH: these tests mux actual video",
)
#: The vendored clip: 81 frames at 16 fps.
_CLIP_S = 81 / 16
#: An AAC frame or two either side; the stage's own check allows 0.15 s.
_SLACK_S = 0.1


# ---------------------------------------------------------------------------
# Pure
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("audio_s", "may_speed_up", "fit"),
    [
        (3.0, True, AudioFit.PAD),
        (5.0, False, AudioFit.PAD),
        (5.5, True, AudioFit.TEMPO),
        (5.5, False, AudioFit.TRIM),  # an own note is never sped up (§5.4)
        (6.0, True, AudioFit.TRIM),  # past 15 % (§5.3)
    ],
)
def test_the_fit_follows_5_3(audio_s: float, may_speed_up: bool, fit: AudioFit) -> None:
    assert audio_fit(audio_s, 5.0, may_speed_up=may_speed_up) is fit


def test_the_filters_pad_speed_up_or_fade_and_always_pad_to_the_clip() -> None:
    assert narration_filter(3.0, 5.0, may_speed_up=True) == "aresample=48000,apad"
    assert "atempo=1.1000" in narration_filter(5.5, 5.0, may_speed_up=True)
    trim = narration_filter(6.5, 5.0, may_speed_up=True)
    assert f"afade=t=out:st={5.0 - FADE_OUT_S:.3f}:d={FADE_OUT_S}" in trim
    assert "atempo" not in trim
    for chain in (trim, narration_filter(5.5, 5.0, may_speed_up=True)):
        assert chain.endswith(",apad")


def test_the_mux_copies_the_video_encodes_aac_and_cuts_at_the_clip() -> None:
    args = mux_args(
        "ffmpeg",
        Path("raw.mp4"),
        Path("voice.wav"),
        Path("out.mp4.part"),
        video_s=5.0625,
        audio_filter="aresample=48000,apad",
    )

    joined = " ".join(args)
    assert "-map 0:v:0 -map 1:a:0" in joined
    assert "-c:v copy" in joined and "-c:a aac -b:a 128k" in joined
    assert "-t 5.062" in joined or "-t 5.063" in joined
    assert "-movflags +faststart" in joined
    assert args[-1] == "out.mp4.part"


def _report(**video: object) -> str:
    stream = {"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p", **video}
    return json.dumps({"streams": [stream], "format": {"duration": "5.0625"}})


def test_ffprobe_is_read_for_geometry_and_duration_and_refuses_what_is_not_a_clip() -> None:
    probe = parse_video_probe(_report(width=720, height=1280), source=Path("v.mp4"))
    assert not is_err(probe)
    assert (probe.value.width, probe.value.height) == (720, 1280)
    assert probe.value.duration_s == pytest.approx(5.0625)
    assert is_streamable(probe.value)

    audio_only = json.dumps({"streams": [{"codec_type": "audio"}], "format": {"duration": "5"}})
    assert is_err(parse_video_probe(audio_only, source=Path("a.mp4")))
    assert is_err(parse_video_probe(_report(width=0, height=10), source=Path("v.mp4")))
    no_length = json.dumps({"streams": [{"codec_type": "video", "width": 2, "height": 2}]})
    assert is_err(parse_video_probe(no_length, source=Path("v.mp4")))
    assert is_err(parse_video_probe("not json", source=Path("v.mp4")))


def test_only_even_h264_yuv420p_is_streamable_as_is() -> None:
    base = VideoProbe(
        width=720, height=1280, duration_s=5.0, codec="h264", pix_fmt="yuv420p", has_audio=False
    )
    assert is_streamable(base)
    assert not is_streamable(dataclasses.replace(base, codec="hevc"))
    assert not is_streamable(dataclasses.replace(base, pix_fmt="yuv444p"))
    assert not is_streamable(dataclasses.replace(base, width=721))


# ---------------------------------------------------------------------------
# The real ffmpeg
# ---------------------------------------------------------------------------
@pytest.fixture
def tools() -> FfmpegVideoTools:
    assert FFMPEG is not None and FFPROBE is not None
    return FfmpegVideoTools(ffmpeg_binary=FFMPEG, ffprobe_binary=FFPROBE, timeout_s=60.0)


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    path = tmp_path / "raw.mp4"
    path.write_bytes(fake_clip_bytes())
    return path


def _wav(tmp_path: Path, seconds: float) -> Path:
    path = tmp_path / f"voice-{seconds}.wav"
    path.write_bytes(silent_wav(seconds))
    return path


@pytest.mark.integration
@requires_ffmpeg
async def test_normalise_reads_the_clip_and_keeps_its_shape(
    tools: FfmpegVideoTools, clip: Path, tmp_path: Path
) -> None:
    made = await tools.normalise(clip, tmp_path / "video-raw.mp4")

    assert not is_err(made), made
    assert (made.value.width, made.value.height) == (144, 256)
    assert made.value.duration_s == pytest.approx(_CLIP_S, abs=_SLACK_S)
    assert is_streamable(made.value) and not made.value.has_audio


@pytest.mark.integration
@requires_ffmpeg
@pytest.mark.parametrize(
    ("voice_s", "may_speed_up", "fit"),
    [
        (3.0, True, AudioFit.PAD),
        (5.5, True, AudioFit.TEMPO),
        (7.0, True, AudioFit.TRIM),
        (5.25, False, AudioFit.TRIM),
    ],
)
async def test_the_muxed_clip_is_exactly_as_long_as_the_video(
    tools: FfmpegVideoTools,
    clip: Path,
    tmp_path: Path,
    voice_s: float,
    may_speed_up: bool,
    fit: AudioFit,
) -> None:
    muxed = await tools.mux(
        clip, _wav(tmp_path, voice_s), tmp_path / "video.mp4", may_speed_up=may_speed_up
    )

    assert not is_err(muxed), muxed
    assert muxed.value.fit is fit
    assert muxed.value.probe.has_audio
    assert (muxed.value.probe.width, muxed.value.probe.height) == (144, 256)
    assert muxed.value.probe.duration_s == pytest.approx(_CLIP_S, abs=_SLACK_S)
    assert not (tmp_path / "video.mp4.part").exists()


@pytest.mark.integration
@requires_ffmpeg
async def test_a_silent_clip_is_rewrapped_without_audio(
    tools: FfmpegVideoTools, clip: Path, tmp_path: Path
) -> None:
    made = await tools.rewrap(clip, tmp_path / "video.mp4")

    assert not is_err(made), made
    assert not made.value.has_audio
    assert made.value.duration_s == pytest.approx(_CLIP_S, abs=_SLACK_S)


@pytest.mark.integration
@requires_ffmpeg
async def test_frames_are_the_first_one_a_second_and_the_last(
    tools: FfmpegVideoTools, clip: Path, tmp_path: Path
) -> None:
    frames = await tools.frames(clip, tmp_path / "frames")

    assert not is_err(frames), frames
    assert 3 <= len(frames.value) <= MAX_SCREEN_FRAMES
    assert frames.value[-1].name == "frame-last.jpg"
    assert all(path.stat().st_size > 0 for path in frames.value)


@pytest.fixture
def opus_note(tmp_path: Path) -> Path:
    """Three seconds of tone as a Telegram-shaped OGG/Opus voice note."""
    note = tmp_path / "voice-0.ogg"
    assert FFMPEG is not None
    made = subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=220:duration=3",
            "-c:a",
            "libopus",
            str(note),
        ],
        capture_output=True,
        check=False,
    )
    if made.returncode != 0:
        pytest.skip("this ffmpeg cannot encode Opus to build the test note")
    return note


@pytest.mark.integration
@requires_ffmpeg
async def test_an_own_note_is_loudness_normalised_to_mono_48k(
    tools: FfmpegVideoTools, opus_note: Path, tmp_path: Path
) -> None:
    seconds = await tools.prepare_voice(opus_note, tmp_path / "narration.wav")

    assert not is_err(seconds), seconds
    assert seconds.value == pytest.approx(3.0, abs=0.1)
