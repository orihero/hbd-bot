"""Typesetting the lyric sheet.

This is the one deliverable whose orthography we control end to end, so it is the one
place the name MUST be perfect. The sheet is typeset from ``LyricDraft.name_display`` —
the display form — never from the candidate string that was submitted to the music vendor.
Those are two different values and conflating them is the failure this product exists to
avoid.

Two passes do the work:

* For Uzbek Latin, every apostrophe-like mark a keyboard or a model might emit is resolved
  to the RIGHT letter: U+02BB MODIFIER LETTER TURNED COMMA after o/g (oʻ, gʻ), and U+02BC
  MODIFIER LETTER APOSTROPHE everywhere else, where the mark is a glottal stop (maʼno).
  Blanket-replacing every apostrophe with U+02BB is a common and wrong shortcut.
* In every language, an occurrence of the name spelled with the wrong mark is rewritten to
  the display form exactly. This runs for Russian and English too — where the o/g rule
  must NOT run, because it would turn "don't" into "donʼt".
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from hbd.audio.constants import (
    APOSTROPHE_LIKE,
    LYRIC_SHEET_MIME,
    MODIFIER_APOSTROPHE,
    MODIFIER_TURNED_COMMA,
    TURNED_COMMA_HOSTS,
)
from hbd.audio.tempfiles import publish, scratch_dir
from hbd.contracts import Language, LyricDraft, Result, err, ok
from hbd.errors import AudioProcessingError
from hbd.logging import get_logger

__all__ = [
    "canonicalize_uzbek_latin",
    "enforce_display_name",
    "render_lyric_sheet",
    "write_lyric_sheet",
    "LYRIC_SHEET_MIME",
]

_LOG = get_logger(__name__)

_TITLE_RULE = "—"
_SECTION_OPEN, _SECTION_CLOSE = "[", "]"
_APOSTROPHE_CLASS = f"[{re.escape(''.join(sorted(APOSTROPHE_LIKE)))}]"
_STAGED_NAME = "lyrics"


def canonicalize_uzbek_latin(text: str) -> str:
    """Resolve every apostrophe-like mark to the correct Uzbek Latin modifier letter."""
    resolved: list[str] = []
    for char in text:
        if char not in APOSTROPHE_LIKE:
            resolved.append(char)
            continue
        previous = resolved[-1] if resolved else ""
        resolved.append(
            MODIFIER_TURNED_COMMA if previous in TURNED_COMMA_HOSTS else MODIFIER_APOSTROPHE
        )
    return "".join(resolved)


def enforce_display_name(text: str, name_display: str) -> str:
    """Rewrite any apostrophe-variant spelling of the name to the display form exactly.

    A no-op when the name carries no modifier letter — there is then nothing that could
    have been mis-typed, and we must not rewrite ordinary words.
    """
    if not any(char in APOSTROPHE_LIKE for char in name_display):
        return text
    pattern = "".join(
        _APOSTROPHE_CLASS if char in APOSTROPHE_LIKE else re.escape(char) for char in name_display
    )
    return re.sub(pattern, name_display.replace("\\", "\\\\"), text, flags=re.IGNORECASE)


def _clean(text: str, *, language: Language, name_display: str) -> str:
    """NFC, correct modifier letters, exact display name, no trailing whitespace."""
    composed = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    if language is Language.UZ_LATN:
        composed = canonicalize_uzbek_latin(composed)
    return enforce_display_name(composed, name_display).rstrip()


def render_lyric_sheet(lyrics: LyricDraft) -> str:
    """Render the sheet as clean UTF-8 text. Pure: no I/O, no clock."""
    name_display = unicodedata.normalize("NFC", lyrics.name_display)

    def clean(value: str) -> str:
        return _clean(value, language=lyrics.language, name_display=name_display)

    title = clean(lyrics.title)
    blocks: list[str] = [f"{title}\n{_TITLE_RULE * len(title)}"]
    for section in lyrics.sections:
        label = f"{_SECTION_OPEN}{clean(section.label)}{_SECTION_CLOSE}"
        body = "\n".join(clean(line) for line in section.lines)
        blocks.append(f"{label}\n{body}")
    return "\n\n".join(blocks) + "\n"


def write_lyric_sheet(lyrics: LyricDraft, *, destination: Path) -> Result[Path]:
    """Write the sheet to ``destination`` as UTF-8. Never raises; never leaves a partial file."""
    try:
        text = render_lyric_sheet(lyrics)
        with scratch_dir(destination) as scratch:
            staged = scratch / _STAGED_NAME
            staged.write_text(text, encoding="utf-8", newline="\n")
            publish(staged, destination)
    except (OSError, UnicodeError) as exc:
        _LOG.warning(
            "audio.lyric_sheet.write_failed",
            extra={"destination": str(destination), "reason": str(exc)},
        )
        return err(
            AudioProcessingError(
                f"could not write the lyric sheet to {destination}: {exc}",
                context={"destination": str(destination)},
                cause=exc,
            )
        )
    return ok(destination)
