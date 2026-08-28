"""Named constants for the audio module.

Anything a human would want to tune lives in ``hbd.config``. What lives here is either a
vendor/format fact (Telegram needs OGG/Opus, ffmpeg's loudnorm defaults to LRA=11) or an
internal bound that no operator would ever set. No literal below is repeated in code.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "MS_PER_SECOND",
    "LOUDNORM_TARGET_LRA",
    "LOUDNORM_OFFSET_LIMIT",
    "SILENCE_KEEP_S",
    "MAX_CAPTURED_STDERR_CHARS",
    "DEFAULT_FFMPEG_TIMEOUT_S",
    "STARTUP_PROBE_TIMEOUT_S",
    "PROCESS_KILL_GRACE_S",
    "SCRATCH_DIR_PREFIX",
    "INTERMEDIATE_CODEC",
    "INTERMEDIATE_SUFFIX",
    "FFMPEG_COMMON_ARGS",
    "OUTPUT_HYGIENE_ARGS",
    "NULL_MUXER",
    "NULL_SINK",
    "VOICE_NOTE_SUFFIX",
    "VOICE_NOTE_MIME",
    "VOICE_NOTE_CONTAINER",
    "VOICE_NOTE_CODEC",
    "VOICE_NOTE_CHANNELS",
    "VOICE_NOTE_VBR",
    "OPUS_APPLICATION",
    "REQUIRED_ENCODERS",
    "LYRIC_SHEET_SUFFIX",
    "LYRIC_SHEET_MIME",
    "MODIFIER_TURNED_COMMA",
    "MODIFIER_APOSTROPHE",
    "APOSTROPHE_LIKE",
    "TURNED_COMMA_HOSTS",
    "NO_OP_FILTER",
]

MS_PER_SECOND: Final[float] = 1_000.0

# -- loudnorm ---------------------------------------------------------------
#: ffmpeg's own default loudness range target. Not an operator knob: changing it changes
#: how much dynamics get squashed, which is a mastering decision, not a deployment one.
LOUDNORM_TARGET_LRA: Final[float] = 11.0
#: ffmpeg rejects an ``offset`` outside this range with an unhelpful error.
LOUDNORM_OFFSET_LIMIT: Final[float] = 99.0

# -- silence trim -----------------------------------------------------------
#: Seconds of the detected silence to keep, so a trim never clips the attack transient.
SILENCE_KEEP_S: Final[float] = 0.05

# -- subprocess -------------------------------------------------------------
#: ffmpeg's stderr can be megabytes. We keep the tail — the failure is always at the end.
MAX_CAPTURED_STDERR_CHARS: Final[int] = 4_000
#: Generous enough for a two-pass render of a ten-minute track on a loaded worker.
DEFAULT_FFMPEG_TIMEOUT_S: Final[float] = 180.0
#: The startup capability probe only prints a table; it must never hang a boot.
STARTUP_PROBE_TIMEOUT_S: Final[float] = 15.0
#: How long a killed ffmpeg gets to actually die before we stop waiting for it.
PROCESS_KILL_GRACE_S: Final[float] = 5.0

# -- filesystem -------------------------------------------------------------
#: Scratch dirs are created NEXT TO the destination so the final move is atomic and
#: same-device. The dot prefix keeps them out of casual directory listings.
SCRATCH_DIR_PREFIX: Final[str] = ".hbd-audio-"
#: Intermediates stay uncompressed so a multi-stage chain never stacks lossy generations.
INTERMEDIATE_CODEC: Final[str] = "pcm_s16le"
INTERMEDIATE_SUFFIX: Final[str] = ".wav"

# -- ffmpeg invocation -------------------------------------------------------
#: On every run. ``-nostdin`` matters most: without it a backgrounded ffmpeg that reads
#: the shared stdin can stop the whole worker. ``-y`` is safe because we only ever write
#: into a private scratch directory.
FFMPEG_COMMON_ARGS: Final[tuple[str, ...]] = ("-hide_banner", "-nostdin", "-y")
#: On every output. ``-vn`` drops embedded cover art (an mp3 from a vendor often carries
#: one, and it breaks a wav mux); ``-map_metadata -1`` keeps vendor tags out of a customer
#: deliverable.
OUTPUT_HYGIENE_ARGS: Final[tuple[str, ...]] = ("-vn", "-map_metadata", "-1")
#: The analysis pass produces no file: it decodes to nothing and prints its report.
NULL_MUXER: Final[str] = "null"
NULL_SINK: Final[str] = "-"

# -- Telegram voice notes ---------------------------------------------------
#: sendVoice renders anything that is not OGG/Opus as a file attachment. All four of
#: these are load-bearing; none of them is a preference.
VOICE_NOTE_SUFFIX: Final[str] = ".ogg"
VOICE_NOTE_MIME: Final[str] = "audio/ogg"
VOICE_NOTE_CONTAINER: Final[str] = "ogg"
VOICE_NOTE_CODEC: Final[str] = "libopus"
VOICE_NOTE_CHANNELS: Final[int] = 1
#: Variable bitrate: the configured rate becomes an average, so a quiet passage spends its
#: bits on the loud one instead of padding.
VOICE_NOTE_VBR: Final[str] = "on"
#: Opus signal hint. Every voice note we produce is speech.
OPUS_APPLICATION: Final[str] = "voip"
#: Checked once at startup. A distro ffmpeg built without libopus fails every order.
REQUIRED_ENCODERS: Final[tuple[str, ...]] = (VOICE_NOTE_CODEC,)

# -- lyric sheet ------------------------------------------------------------
LYRIC_SHEET_SUFFIX: Final[str] = ".txt"
LYRIC_SHEET_MIME: Final[str] = "text/plain; charset=utf-8"

# -- Uzbek Latin orthography ------------------------------------------------
#: U+02BB MODIFIER LETTER TURNED COMMA — the correct mark in oʻ and gʻ.
MODIFIER_TURNED_COMMA: Final[str] = "ʻ"
#: U+02BC MODIFIER LETTER APOSTROPHE — the glottal stop, as in maʼno. A different letter.
MODIFIER_APOSTROPHE: Final[str] = "ʼ"
#: Everything a phone keyboard, a word processor or a model actually emits for either.
#: Written as escapes on purpose: several of these are visually indistinguishable from one
#: another in an editor, and the whole point of the set is that they are DIFFERENT.
APOSTROPHE_LIKE: Final[frozenset[str]] = frozenset(
    "\u0027"  # APOSTROPHE
    "\u0060"  # GRAVE ACCENT
    "\u00B4"  # ACUTE ACCENT
    "\u2018"  # LEFT SINGLE QUOTATION MARK   <- what a phone keyboard actually types
    "\u2019"  # RIGHT SINGLE QUOTATION MARK  <- what a word processor autocorrects to
    "\u201B"  # SINGLE HIGH-REVERSED-9 QUOTATION MARK
    "\u02B9"  # MODIFIER LETTER PRIME
    "\u02BB"  # MODIFIER LETTER TURNED COMMA <- the correct one, in o-/g-
    "\u02BC"  # MODIFIER LETTER APOSTROPHE   <- the correct one, for the glottal stop
    "\u2032"  # PRIME
)
#: Only these four letters take the turned comma. After anything else the mark is a
#: glottal stop, so blanket-replacing every apostrophe with U+02BB is WRONG.
TURNED_COMMA_HOSTS: Final[frozenset[str]] = frozenset("oOgG")

# -- ffmpeg ------------------------------------------------------------------
#: A filter chain must never be empty; ffmpeg's explicit pass-through.
NO_OP_FILTER: Final[str] = "anull"
