"""Audio post-processing: ffmpeg behind ``hbd.contracts.AudioPostProcessor``.

Four things ship from here.

**The post-processor.** :class:`~hbd.audio.processor.FfmpegAudioPostProcessor` does the
two-pass loudnorm (-14 LUFS for the song, -16 for speech, both from config), the silence
trim, the fades, and the OGG/Opus voice-note encode that ``sendVoice`` requires. Nothing it
exposes raises: every method returns a ``Result``.

**The startup check.** :func:`~hbd.audio.startup.ensure_ffmpeg_available` must be called
during boot. Without it a worker missing ffmpeg — or running an ffmpeg built without
libopus — discovers the problem one paying customer at a time.

**The cover art.** :func:`~hbd.audio.cover.render_cover` draws the 320x320 watermark
thumbnail. It lives here rather than in the pipeline because this host's ffmpeg has no
``drawtext`` filter, so drawing the picture is Pillow's job and belongs beside the other
media work — and because the branding pass that muxes it into the mp3 is one file over.

**The lyric sheet.** :func:`~hbd.audio.lyric_sheet.write_lyric_sheet` typesets the one
deliverable whose orthography we own end to end, from ``LyricDraft.name_display`` and never
from the string that was submitted to the music vendor.
"""

from __future__ import annotations

from hbd.audio.constants import (
    LYRIC_SHEET_MIME,
    LYRIC_SHEET_SUFFIX,
    VOICE_NOTE_MIME,
    VOICE_NOTE_SUFFIX,
)
from hbd.audio.cover import COVER_MIME, COVER_SIZE, COVER_SUFFIX, render_cover
from hbd.audio.loudnorm import LoudnormMeasurement, parse_loudnorm_report
from hbd.audio.lyric_sheet import (
    canonicalize_uzbek_latin,
    render_lyric_sheet,
    write_lyric_sheet,
)
from hbd.audio.probe import parse_ffprobe_report
from hbd.audio.processor import FfmpegAudioPostProcessor
from hbd.audio.startup import ensure_ffmpeg_available

__all__ = [
    # post-processing
    "FfmpegAudioPostProcessor",
    # startup
    "ensure_ffmpeg_available",
    # cover art
    "render_cover",
    "COVER_MIME",
    "COVER_SIZE",
    "COVER_SUFFIX",
    # lyric sheet
    "render_lyric_sheet",
    "write_lyric_sheet",
    "canonicalize_uzbek_latin",
    # parsers, exported for the pipeline's own assertions
    "LoudnormMeasurement",
    "parse_loudnorm_report",
    "parse_ffprobe_report",
    # format facts the delivery layer needs when it uploads
    "VOICE_NOTE_MIME",
    "VOICE_NOTE_SUFFIX",
    "LYRIC_SHEET_MIME",
    "LYRIC_SHEET_SUFFIX",
]
