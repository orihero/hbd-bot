"""ffmpeg for a video: normalise the clip, prepare a voice, mux, and pick frames to screen.

IMAGE_VIDEO_SPEC §5.3, §5.4, §5.6, §6.4 L4. Every call is a host subprocess
(``asyncio.create_subprocess_exec`` through ``bayram.audio.runner``; ffmpeg is already a host
dependency, ``runtime/startup.py verify_host``), writes to a ``.part`` file and renames it into
place, and answers ``Result`` — nothing here raises.

* :meth:`FfmpegVideoTools.normalise` — the fetched clip, **verified by ffprobe** (a video
  stream, positive geometry and duration) and made fit for Telegram: H.264 ``yuv420p`` is
  re-wrapped with ``+faststart`` and no audio track; anything else is re-encoded to it. Given
  a ``target`` size, a clip ffprobe measures at any other geometry is scaled to cover it and
  centre-cropped to exactly it (§4.3: Kling has no ``resolution`` and was measured at
  716×1284 for a 720×1280 ask). What it returns is what the row records as ``video_raw``.
* :meth:`FfmpegVideoTools.prepare_voice` — an own voice note (§5.4): decode, ``loudnorm``
  I=−16 LUFS, mono 48 kHz. **No cloning, no voice conversion**: the customer's voice as sent.
* :meth:`FfmpegVideoTools.mux` — the narration or the note onto the silent clip (§5.6),
  audio AAC 128k, video stream-copied, cut at the clip's own duration so **the output is as
  long as the video**. A line that runs long (§5.3): up to 15 % over is sped up with
  ``atempo`` (never an own voice note, which is muxed as-is); past that, or any over-long own
  note, is **trimmed at the clip length with a 250 ms fade-out** — never a failed paid job.
* :meth:`FfmpegVideoTools.rewrap` — a silent video (``voice_mode='none'``) re-wrapped with
  ``+faststart`` (§5.6).
* :meth:`FfmpegVideoTools.frames` — L4's frames of a video: 1 fps from the start plus the
  last frame, at most eight (§6.4).

:class:`VideoTools` is the seam: a fake in the unit suite (no ffmpeg there); the argv and the
filter chains are pure and tested without a binary, and the real binary is exercised by
``integration`` tests that skip when it is absent.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable

from bayram.audio.probe import ffprobe_args, parse_ffprobe_report
from bayram.audio.runner import run_command
from bayram.contracts import Err, Result, err, is_err, ok
from bayram.errors import ValidationError

__all__ = [
    "MAX_TEMPO",
    "FADE_OUT_S",
    "MAX_SCREEN_FRAMES",
    "AudioFit",
    "VideoProbe",
    "MuxOutcome",
    "VideoTools",
    "FfmpegVideoTools",
    "audio_fit",
    "narration_filter",
    "mux_args",
    "rewrap_args",
    "normalise_args",
    "geometry_filter",
    "voice_args",
    "frame_args",
    "last_frame_args",
    "video_probe_args",
    "parse_video_probe",
    "is_streamable",
]

#: §5.3: a line up to 15 % longer than the clip is sped up, never more.
MAX_TEMPO: Final[float] = 1.15
#: §5.3 / §5.4: a line or note that still runs long is cut at the clip with this fade.
FADE_OUT_S: Final[float] = 0.25
#: §6.4 L4: first, last and 1 fps frames, at most eight.
MAX_SCREEN_FRAMES: Final[int] = 8
#: §5.6: the narration track.
_AUDIO_BITRATE: Final[str] = "128k"
_AUDIO_RATE_HZ: Final[int] = 48_000
#: §5.4: an own note is normalised to this integrated loudness.
_VOICE_LUFS: Final[int] = -16
#: A re-encode keeps the look of the render; the clip is five seconds, so speed is cheap.
_REENCODE_CRF: Final[int] = 20
_JPEG_QSCALE: Final[int] = 3
_STREAMABLE_CODEC: Final[str] = "h264"
_STREAMABLE_PIX_FMT: Final[str] = "yuv420p"
#: The last frame is read this far before the end (a frame at the very end may not decode).
_LAST_FRAME_OFFSET_S: Final[float] = 0.1


class AudioFit(StrEnum):
    """How a voice track was fitted to the clip (§5.3). Logged per language (Q11 note)."""

    PAD = "pad"
    TEMPO = "tempo"
    TRIM = "trim"


@dataclass(frozen=True, slots=True)
class VideoProbe:
    """What ffprobe says a video file is."""

    width: int
    height: int
    duration_s: float
    codec: str
    pix_fmt: str | None
    has_audio: bool


@dataclass(frozen=True, slots=True)
class MuxOutcome:
    """The muxed file's shape and how its audio was fitted."""

    probe: VideoProbe
    audio_s: float
    fit: AudioFit


@runtime_checkable
class VideoTools(Protocol):
    """The ffmpeg calls the video stages make. Nothing raises."""

    async def probe(self, path: Path) -> Result[VideoProbe]: ...

    async def normalise(
        self, src: Path, dest: Path, *, target: tuple[int, int] | None = None
    ) -> Result[VideoProbe]: ...

    async def prepare_voice(self, src: Path, dest: Path) -> Result[float]: ...

    async def audio_seconds(self, path: Path) -> Result[float]: ...

    async def mux(
        self, video: Path, audio: Path, dest: Path, *, may_speed_up: bool
    ) -> Result[MuxOutcome]: ...

    async def rewrap(self, src: Path, dest: Path) -> Result[VideoProbe]: ...

    async def frames(self, video: Path, outdir: Path) -> Result[tuple[Path, ...]]: ...


# ---------------------------------------------------------------------------
# Pure: the fit, the filters, the argv
# ---------------------------------------------------------------------------
def audio_fit(audio_s: float, video_s: float, *, may_speed_up: bool) -> AudioFit:
    """§5.3: pad what fits; speed up what is at most 15 % over (not an own note); trim the rest."""
    if audio_s <= video_s:
        return AudioFit.PAD
    if may_speed_up and audio_s <= video_s * MAX_TEMPO:
        return AudioFit.TEMPO
    return AudioFit.TRIM


def narration_filter(audio_s: float, video_s: float, *, may_speed_up: bool) -> str:
    """The ``-af`` chain for the voice track. Always ends in ``apad`` so ``-t`` sets the
    length: the audio is padded with silence to the clip, never shorter than it."""
    fit = audio_fit(audio_s, video_s, may_speed_up=may_speed_up)
    steps = [f"aresample={_AUDIO_RATE_HZ}"]
    if fit is AudioFit.TEMPO:
        steps.append(f"atempo={audio_s / video_s:.4f}")
    elif fit is AudioFit.TRIM:
        start = max(0.0, video_s - FADE_OUT_S)
        steps.append(f"afade=t=out:st={start:.3f}:d={FADE_OUT_S}")
    steps.append("apad")
    return ",".join(steps)


def _seconds(value: float) -> str:
    return f"{value:.3f}"


def mux_args(
    binary: str, video: Path, audio: Path, dest: Path, *, video_s: float, audio_filter: str
) -> tuple[str, ...]:
    """§5.6, verbatim but for the fitted filter: video copied, AAC 128k, cut at the clip."""
    return (
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-af",
        audio_filter,
        "-c:a",
        "aac",
        "-b:a",
        _AUDIO_BITRATE,
        "-ar",
        str(_AUDIO_RATE_HZ),
        "-t",
        _seconds(video_s),
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(dest),
    )


def rewrap_args(binary: str, src: Path, dest: Path) -> tuple[str, ...]:
    """A silent clip re-wrapped for streaming (§5.6): the video stream only, copied."""
    return (
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-c:v",
        "copy",
        "-an",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(dest),
    )


def geometry_filter(target: tuple[int, int] | None) -> str:
    """The ``-vf`` chain: even dimensions, or — with a target — exactly the target, scaled to
    cover it and centre-cropped, square pixels (§4.3). Never letterboxed: a bar would be
    muxed, screened and delivered as part of the picture."""
    if target is None:
        return "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    width, height = target
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1"
    )


def normalise_args(
    binary: str, src: Path, dest: Path, *, target: tuple[int, int] | None = None
) -> tuple[str, ...]:
    """A clip that is not H.264 ``yuv420p`` or not the target size, re-encoded (no audio)."""
    return (
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-vf",
        geometry_filter(target),
        "-c:v",
        "libx264",
        "-pix_fmt",
        _STREAMABLE_PIX_FMT,
        "-crf",
        str(_REENCODE_CRF),
        "-preset",
        "veryfast",
        "-an",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(dest),
    )


def voice_args(binary: str, src: Path, dest: Path) -> tuple[str, ...]:
    """§5.4: an own note, loudness-normalised, mono 48 kHz, as 16-bit WAV for the mux."""
    return (
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-map",
        "0:a:0",
        "-af",
        f"loudnorm=I={_VOICE_LUFS}:TP=-1.5:LRA=11,aresample={_AUDIO_RATE_HZ}",
        "-ac",
        "1",
        "-ar",
        str(_AUDIO_RATE_HZ),
        "-c:a",
        "pcm_s16le",
        "-f",
        "wav",
        str(dest),
    )


def frame_args(binary: str, video: Path, pattern: Path, *, count: int) -> tuple[str, ...]:
    """One frame a second from the start (the first frame included), at most ``count``."""
    return (
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video),
        "-vf",
        "fps=1",
        "-frames:v",
        str(count),
        "-q:v",
        str(_JPEG_QSCALE),
        str(pattern),
    )


def last_frame_args(binary: str, video: Path, dest: Path) -> tuple[str, ...]:
    return (
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-sseof",
        f"-{_LAST_FRAME_OFFSET_S}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-q:v",
        str(_JPEG_QSCALE),
        str(dest),
    )


def video_probe_args(binary: str, source: Path) -> tuple[str, ...]:
    return (
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(source),
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def parse_video_probe(payload: str, *, source: Path) -> Result[VideoProbe]:
    """ffprobe's JSON → :class:`VideoProbe`. A file with no video stream, no geometry or no
    positive duration is refused: that is not a clip we can deliver (§5.6)."""
    try:
        loaded = json.loads(payload)
    except (ValueError, TypeError):
        loaded = None
    if not isinstance(loaded, dict):
        return err(_refused("ffprobe output was not a JSON object", source))
    streams = loaded.get("streams")
    listed = [s for s in streams if isinstance(s, dict)] if isinstance(streams, list) else []
    video = next((s for s in listed if s.get("codec_type") == "video"), None)
    if video is None:
        return err(_refused("the file has no video stream", source))
    width, height = _number(video.get("width")), _number(video.get("height"))
    fmt = loaded.get("format")
    duration = _number(video.get("duration"))
    if duration is None and isinstance(fmt, dict):
        duration = _number(fmt.get("duration"))
    if not width or not height or width <= 0 or height <= 0:
        return err(_refused("the video has no geometry", source))
    if duration is None or duration <= 0:
        return err(_refused("the video has no duration", source))
    codec = video.get("codec_name")
    pix_fmt = video.get("pix_fmt")
    return ok(
        VideoProbe(
            width=int(width),
            height=int(height),
            duration_s=duration,
            codec=codec if isinstance(codec, str) else "",
            pix_fmt=pix_fmt if isinstance(pix_fmt, str) else None,
            has_audio=any(s.get("codec_type") == "audio" for s in listed),
        )
    )


def is_streamable(probe: VideoProbe) -> bool:
    """H.264 ``yuv420p`` with even dimensions plays inline everywhere Telegram runs."""
    return (
        probe.codec == _STREAMABLE_CODEC
        and probe.pix_fmt == _STREAMABLE_PIX_FMT
        and probe.width % 2 == 0
        and probe.height % 2 == 0
    )


def _refused(message: str, source: Path) -> ValidationError:
    return ValidationError(message, context={"file": source.name})


def _part(dest: Path) -> Path:
    return dest.with_name(f"{dest.name}.part")


# ---------------------------------------------------------------------------
# The host binaries
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class FfmpegVideoTools:
    """:class:`VideoTools` over the host's ``ffmpeg`` and ``ffprobe``."""

    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    timeout_s: float = 180.0

    async def _run(self, args: tuple[str, ...], operation: str) -> Result[str]:
        ran = await run_command(args, operation=operation, timeout_s=self.timeout_s)
        if is_err(ran):
            return ran
        return ok(ran.value.stdout)

    async def _write(self, args: tuple[str, ...], operation: str, dest: Path) -> Result[Path]:
        """Run an ffmpeg that writes ``dest``'s ``.part`` (the last argv), then rename."""
        part = Path(args[-1])
        part.parent.mkdir(parents=True, exist_ok=True)
        ran = await self._run(args, operation)
        if is_err(ran):
            part.unlink(missing_ok=True)
            return ran
        part.replace(dest)
        return ok(dest)

    async def probe(self, path: Path) -> Result[VideoProbe]:
        ran = await self._run(video_probe_args(self.ffprobe_binary, path), "video.probe")
        if is_err(ran):
            return ran
        return parse_video_probe(ran.value, source=path)

    async def audio_seconds(self, path: Path) -> Result[float]:
        ran = await self._run(ffprobe_args(self.ffprobe_binary, path), "narration.probe")
        if is_err(ran):
            return ran
        report = parse_ffprobe_report(ran.value, source=path)
        if is_err(report):
            return report
        return ok(report.value.duration_s)

    async def normalise(
        self, src: Path, dest: Path, *, target: tuple[int, int] | None = None
    ) -> Result[VideoProbe]:
        probed = await self.probe(src)
        if is_err(probed):
            return probed
        clip = probed.value
        is_on_target = target is None or (clip.width, clip.height) == target
        args = (
            rewrap_args(self.ffmpeg_binary, src, _part(dest))
            if is_streamable(clip) and is_on_target
            else normalise_args(self.ffmpeg_binary, src, _part(dest), target=target)
        )
        written = await self._write(args, "video.normalise", dest)
        if is_err(written):
            return written
        return await self.probe(dest)

    async def prepare_voice(self, src: Path, dest: Path) -> Result[float]:
        written = await self._write(
            voice_args(self.ffmpeg_binary, src, _part(dest)), "voice_note.prepare", dest
        )
        if is_err(written):
            return written
        return await self.audio_seconds(dest)

    async def mux(
        self, video: Path, audio: Path, dest: Path, *, may_speed_up: bool
    ) -> Result[MuxOutcome]:
        clip = await self.probe(video)
        if is_err(clip):
            return clip
        voice = await self.audio_seconds(audio)
        if is_err(voice):
            return voice
        video_s, audio_s = clip.value.duration_s, voice.value
        args = mux_args(
            self.ffmpeg_binary,
            video,
            audio,
            _part(dest),
            video_s=video_s,
            audio_filter=narration_filter(audio_s, video_s, may_speed_up=may_speed_up),
        )
        written = await self._write(args, "video.mux", dest)
        if is_err(written):
            return written
        muxed = await self.probe(dest)
        if is_err(muxed):
            return muxed
        return ok(
            MuxOutcome(
                probe=muxed.value,
                audio_s=audio_s,
                fit=audio_fit(audio_s, video_s, may_speed_up=may_speed_up),
            )
        )

    async def rewrap(self, src: Path, dest: Path) -> Result[VideoProbe]:
        written = await self._write(
            rewrap_args(self.ffmpeg_binary, src, _part(dest)), "video.rewrap", dest
        )
        if is_err(written):
            return written
        return await self.probe(dest)

    async def frames(self, video: Path, outdir: Path) -> Result[tuple[Path, ...]]:
        outdir.mkdir(parents=True, exist_ok=True)
        for stale in outdir.glob("frame-*.jpg"):
            stale.unlink(missing_ok=True)
        ran = await self._run(
            frame_args(
                self.ffmpeg_binary,
                video,
                outdir / "frame-%02d.jpg",
                count=MAX_SCREEN_FRAMES - 1,
            ),
            "video.frames",
        )
        if is_err(ran):
            return ran
        last = outdir / "frame-last.jpg"
        ended = await self._run(
            last_frame_args(self.ffmpeg_binary, video, last), "video.last_frame"
        )
        if isinstance(ended, Err):
            return ended
        found = tuple(sorted(p for p in outdir.glob("frame-*.jpg") if p != last))
        if last.exists():
            found = (*found, last)
        if not found:
            return err(_refused("no frame could be read from the video", video))
        return ok(found[:MAX_SCREEN_FRAMES])
