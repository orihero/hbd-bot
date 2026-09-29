"""Render lyrics as an elegant branded image card.

Draws the song title, recipient name, lyrics sections, and watermark onto a styled
portrait canvas using Pillow with system font resolution and fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from bayram.audio.tempfiles import publish, scratch_dir
from bayram.contracts import Language, LyricDraft, Result, err, ok
from bayram.errors import StorageError
from bayram.logging import get_logger
from bayram.watermark import WATERMARK_HANDLE

__all__ = ["render_lyrics_image", "LYRICS_IMAGE_FILENAME", "LYRICS_IMAGE_MIME", "IMAGE_WIDTH"]

_LOG = get_logger(__name__)

LYRICS_IMAGE_FILENAME: Final[str] = "lyrics.png"
LYRICS_IMAGE_MIME: Final[str] = "image/png"
IMAGE_WIDTH: Final[int] = 1080
_WIDTH: Final[int] = IMAGE_WIDTH
_MIN_HEIGHT: Final[int] = 1080
_PADDING_X: Final[int] = 90
_PADDING_Y: Final[int] = 80
_MAX_TEXT_WIDTH: Final[int] = _WIDTH - (2 * _PADDING_X)

# Palette
_BG_TOP: Final[tuple[int, int, int]] = (18, 20, 32)
_BG_BOTTOM: Final[tuple[int, int, int]] = (28, 24, 48)
_COLOR_TITLE: Final[tuple[int, int, int]] = (255, 255, 255)
_COLOR_SUBTITLE: Final[tuple[int, int, int]] = (245, 195, 75)
_COLOR_SECTION_LABEL: Final[tuple[int, int, int]] = (235, 185, 70)
_COLOR_TEXT: Final[tuple[int, int, int]] = (245, 246, 250)
_COLOR_MUTED: Final[tuple[int, int, int]] = (155, 165, 190)
_COLOR_DIVIDER: Final[tuple[int, int, int]] = (65, 70, 95)

_FONT_CANDIDATES: tuple[str, ...] = (
    # macOS
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Geneva.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    # Linux (Debian / Ubuntu / Alpine)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
)


def _resolve_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    return ImageFont.load_default(size=size)


def _wrap_text(
    text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, max_width: int
) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        bbox = font.getbbox(trial)
        if (bbox[2] - bbox[0]) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def render_lyrics_image(
    lyrics: LyricDraft,
    destination: Path,
    *,
    language: Language = Language.RU,
    handle: str = WATERMARK_HANDLE,
) -> Result[Path]:
    """Render the lyrics into a PNG image card at ``destination``. Never raises."""
    try:
        font_title = _resolve_font(40)
        font_sub = _resolve_font(26)
        font_sec = _resolve_font(22)
        font_body = _resolve_font(28)
        font_foot = _resolve_font(22)

        line_h = 42
        sec_gap = 36

        # Subtitle
        subtitle = ""
        if lyrics.name_display:
            if language is Language.EN:
                subtitle = f"For {lyrics.name_display}"
            elif language in (Language.UZ_LATN, Language.UZ_CYRL):
                subtitle = f"{lyrics.name_display} uchun"
            else:
                subtitle = f"Для {lyrics.name_display}"

        # Precompute wrapped lines and content height
        header_h = _PADDING_Y + 55 + (42 if subtitle else 0) + 40
        body_h = 0
        prepared_sections: list[tuple[str, list[str]]] = []
        for sec in lyrics.sections:
            sec_lines: list[str] = []
            for line in sec.lines:
                sec_lines.extend(_wrap_text(line, font_body, _MAX_TEXT_WIDTH))
            label = sec.label.strip().upper() if sec.label else ""
            sec_h = (36 if label else 0) + (len(sec_lines) * line_h) + sec_gap
            body_h += sec_h
            prepared_sections.append((label, sec_lines))

        footer_h = 70 + _PADDING_Y
        total_h = max(_MIN_HEIGHT, header_h + body_h + footer_h)

        image = Image.new("RGB", (_WIDTH, total_h), _BG_TOP)
        draw = ImageDraw.Draw(image)

        # Gradient background
        for y in range(total_h):
            ratio = y / total_h
            r = int(_BG_TOP[0] + (_BG_BOTTOM[0] - _BG_TOP[0]) * ratio)
            g = int(_BG_TOP[1] + (_BG_BOTTOM[1] - _BG_TOP[1]) * ratio)
            b = int(_BG_TOP[2] + (_BG_BOTTOM[2] - _BG_TOP[2]) * ratio)
            draw.line([(0, y), (_WIDTH, y)], fill=(r, g, b))

        # Title
        cur_y = _PADDING_Y
        title_lines = _wrap_text(lyrics.title, font_title, _MAX_TEXT_WIDTH)
        for t_line in title_lines:
            draw.text((_WIDTH // 2, cur_y), t_line, font=font_title, fill=_COLOR_TITLE, anchor="mt")
            cur_y += 50

        # Subtitle
        if subtitle:
            cur_y += 8
            draw.text((_WIDTH // 2, cur_y), subtitle, font=font_sub, fill=_COLOR_SUBTITLE, anchor="mt")
            cur_y += 38

        # Divider
        cur_y += 15
        draw.line([(_PADDING_X, cur_y), (_WIDTH - _PADDING_X, cur_y)], fill=_COLOR_DIVIDER, width=2)
        cur_y += 35

        # Sections
        for label, lines in prepared_sections:
            if label:
                draw.text((_PADDING_X, cur_y), label, font=font_sec, fill=_COLOR_SECTION_LABEL)
                cur_y += 34
            for line in lines:
                draw.text((_PADDING_X + 8, cur_y), line, font=font_body, fill=_COLOR_TEXT)
                cur_y += line_h
            cur_y += sec_gap

        # Footer divider and watermark
        cur_y = max(cur_y, total_h - footer_h)
        draw.line([(_PADDING_X, cur_y), (_WIDTH - _PADDING_X, cur_y)], fill=_COLOR_DIVIDER, width=2)
        cur_y += 30
        watermark_text = f"BAYRAM STUDIO • {handle}"
        draw.text(
            (_WIDTH // 2, cur_y), watermark_text, font=font_foot, fill=_COLOR_MUTED, anchor="mt"
        )

        with scratch_dir(destination) as scratch:
            staged = scratch / "lyrics.png"
            image.save(staged, format="PNG", optimize=True)
            publish(staged, destination)

        return ok(destination)
    except Exception as exc:
        _LOG.warning("lyrics_image.render_failed", extra={"reason": str(exc)})
        return err(StorageError("could not render lyrics image", cause=exc))
