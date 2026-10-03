"""Render lyrics as an elegant branded image card.

Draws the song title, recipient name, lyrics sections, and watermark onto a styled
portrait canvas using Pillow with system font resolution and fallback.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from bayram.audio.tempfiles import publish, scratch_dir
from bayram.contracts import Language, LyricDraft, Result, err, ok
from bayram.errors import StorageError
from bayram.logging import get_logger
from bayram.watermark import WATERMARK_HANDLE

__all__ = [
    "render_lyrics_image",
    "is_google_music_provider",
    "localize_section_label",
    "LYRICS_IMAGE_FILENAME",
    "LYRICS_IMAGE_MIME",
    "IMAGE_WIDTH",
]

_LOG = get_logger(__name__)

LYRICS_IMAGE_FILENAME: Final[str] = "lyrics.png"
LYRICS_IMAGE_MIME: Final[str] = "image/png"
IMAGE_WIDTH: Final[int] = 1080
_WIDTH: Final[int] = IMAGE_WIDTH
_MIN_HEIGHT: Final[int] = 1080
_PADDING_X: Final[int] = 90
_PADDING_Y: Final[int] = 80
_MAX_TEXT_WIDTH: Final[int] = _WIDTH - (2 * _PADDING_X)

# Palette — Midnight Navy (Default / ElevenLabs)
_BG_TOP: Final[tuple[int, int, int]] = (18, 20, 32)
_BG_BOTTOM: Final[tuple[int, int, int]] = (28, 24, 48)
_COLOR_TITLE: Final[tuple[int, int, int]] = (255, 255, 255)
_COLOR_SUBTITLE: Final[tuple[int, int, int]] = (245, 195, 75)
_COLOR_SECTION_LABEL: Final[tuple[int, int, int]] = (235, 185, 70)
_COLOR_TEXT: Final[tuple[int, int, int]] = (245, 246, 250)
_COLOR_MUTED: Final[tuple[int, int, int]] = (155, 165, 190)
_COLOR_DIVIDER: Final[tuple[int, int, int]] = (65, 70, 95)

# Palette — Vibrant Amber Orange (Google Flow / Gemini Lyria)
_BG_ORANGE_TOP: Final[tuple[int, int, int]] = (220, 90, 20)
_BG_ORANGE_BOTTOM: Final[tuple[int, int, int]] = (135, 45, 12)
_COLOR_ORANGE_SUBTITLE: Final[tuple[int, int, int]] = (255, 235, 180)
_COLOR_ORANGE_SECTION_LABEL: Final[tuple[int, int, int]] = (255, 225, 160)
_COLOR_ORANGE_DIVIDER: Final[tuple[int, int, int]] = (245, 135, 65)
_COLOR_ORANGE_MUTED: Final[tuple[int, int, int]] = (245, 195, 165)


def is_google_music_provider(provider: str | None) -> bool:
    """Return True if the provider indicates Google Lyria / Gemini music generation."""
    if not provider:
        return False
    normalized = provider.strip().lower()
    return "gemini" in normalized or "google" in normalized or "lyria" in normalized


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


def localize_section_label(label: str, language: Language) -> str:
    """Translate and normalize a lyrics section label for the card image.

    Maps English section keys (e.g. verse-1, chorus, intro, outro, bridge) to native
    musical terminology in Uzbek (Latin and Cyrillic), Russian, and English.
    """
    trimmed = label.strip()
    if not trimmed:
        return ""

    raw = trimmed.lower()

    # Extract any number in the label (e.g. verse-1, verse 2, куплет 1 -> 1, 2)
    num_match = re.search(r"\d+", raw)
    num = num_match.group(0) if num_match else None

    # Pre-chorus
    if re.search(r"pre[-_\s]*chorus|предприпев|naqarot[-_\s]*oldi|нақарот[-_\s]*олди", raw):
        if language is Language.EN:
            return "PRE-CHORUS"
        if language is Language.RU:
            return "ПРЕДПРИПЕВ"
        if language is Language.UZ_CYRL:
            return "НАҚАРОТ ОЛДИ"
        return "NAQAROT OLDI"

    # Chorus / Refrain / Hook
    if re.search(r"chorus|припев|naqarot|нақарот|refrain|hook|хук", raw):
        if num:
            if language is Language.EN:
                return f"CHORUS {num}"
            if language is Language.RU:
                return f"ПРИПЕВ {num}"
            if language is Language.UZ_CYRL:
                return f"{num}-НАҚАРОТ"
            return f"{num}-NAQAROT"
        if language is Language.EN:
            return "HOOK" if ("hook" in raw or "хук" in raw) else "CHORUS"
        if language is Language.RU:
            return "ПРИПЕВ"
        if language is Language.UZ_CYRL:
            return "НАҚАРОТ"
        return "NAQAROT"

    # Verse
    if re.search(r"verse|куплет|band|банд", raw):
        if num:
            if language is Language.EN:
                return f"VERSE {num}"
            if language is Language.RU:
                return f"КУПЛЕТ {num}"
            if language is Language.UZ_CYRL:
                return f"{num}-БАНД"
            return f"{num}-BAND"
        if language is Language.EN:
            return "VERSE"
        if language is Language.RU:
            return "КУПЛЕТ"
        if language is Language.UZ_CYRL:
            return "БАНД"
        return "BAND"

    # Intro
    if re.search(r"intro|кириш|kirish|вступление|интро", raw):
        if language is Language.EN:
            return "INTRO"
        if language is Language.RU:
            return "ВСТУПЛЕНИЕ"
        if language is Language.UZ_CYRL:
            return "КИРИШ"
        return "KIRISH"

    # Outro
    if re.search(r"outro|хотима|xotima|концовк|аутро|финал", raw):
        if language is Language.EN:
            return "OUTRO"
        if language is Language.RU:
            return "ФИНАЛ"
        if language is Language.UZ_CYRL:
            return "ХОТИМА"
        return "XOTIMA"

    # Bridge
    if re.search(r"bridge|бридж|ўтиш|oʻtish|o'tish|otish|кўприк|koʻprik|ko'prik|koprik", raw):
        if language is Language.EN:
            return "BRIDGE"
        if language is Language.RU:
            return "БРИДЖ"
        if language is Language.UZ_CYRL:
            return "ЎТИШ"
        return "OʻTISH"

    return trimmed.upper()


def render_lyrics_image(
    lyrics: LyricDraft,
    destination: Path,
    *,
    language: Language = Language.RU,
    handle: str = WATERMARK_HANDLE,
    provider: str | None = None,
    theme: str | None = None,
) -> Result[Path]:
    """Render the lyrics into a PNG image card at ``destination``. Never raises.

    If ``provider`` indicates Google Lyria / Gemini flow (or ``theme == "orange"``),
    the card is rendered with an orange gradient background to provide clear visual feedback
    on whether Google flow generated the music. For ElevenLabs and default runs, the classic
    dark navy background is used.
    """
    try:
        effective_lang = (
            language if language is not None else getattr(lyrics, "language", Language.RU)
        )
        font_title = _resolve_font(40)
        font_sub = _resolve_font(26)
        font_sec = _resolve_font(22)
        font_body = _resolve_font(28)
        font_foot = _resolve_font(22)

        line_h = 42
        sec_gap = 36

        is_orange = (
            theme == "orange"
            or is_google_music_provider(provider)
            or (theme is not None and is_google_music_provider(theme))
        )
        bg_top = _BG_ORANGE_TOP if is_orange else _BG_TOP
        bg_bottom = _BG_ORANGE_BOTTOM if is_orange else _BG_BOTTOM
        color_subtitle = _COLOR_ORANGE_SUBTITLE if is_orange else _COLOR_SUBTITLE
        color_sec_label = _COLOR_ORANGE_SECTION_LABEL if is_orange else _COLOR_SECTION_LABEL
        color_divider = _COLOR_ORANGE_DIVIDER if is_orange else _COLOR_DIVIDER
        color_muted = _COLOR_ORANGE_MUTED if is_orange else _COLOR_MUTED

        # Subtitle
        subtitle = ""
        if lyrics.name_display:
            if effective_lang is Language.EN:
                subtitle = f"For {lyrics.name_display}"
            elif effective_lang in (Language.UZ_LATN, Language.UZ_CYRL):
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
            label = localize_section_label(sec.label, effective_lang) if sec.label else ""
            sec_h = (36 if label else 0) + (len(sec_lines) * line_h) + sec_gap
            body_h += sec_h
            prepared_sections.append((label, sec_lines))

        footer_h = 70 + _PADDING_Y
        total_h = max(_MIN_HEIGHT, header_h + body_h + footer_h)

        image = Image.new("RGB", (_WIDTH, total_h), bg_top)
        draw = ImageDraw.Draw(image)

        # Gradient background
        for y in range(total_h):
            ratio = y / total_h
            r = int(bg_top[0] + (bg_bottom[0] - bg_top[0]) * ratio)
            g = int(bg_top[1] + (bg_bottom[1] - bg_top[1]) * ratio)
            b = int(bg_top[2] + (bg_bottom[2] - bg_top[2]) * ratio)
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
            draw.text(
                (_WIDTH // 2, cur_y), subtitle, font=font_sub, fill=color_subtitle, anchor="mt"
            )
            cur_y += 38

        # Divider
        cur_y += 15
        draw.line([(_PADDING_X, cur_y), (_WIDTH - _PADDING_X, cur_y)], fill=color_divider, width=2)
        cur_y += 35

        # Sections
        for label, lines in prepared_sections:
            if label:
                draw.text((_PADDING_X, cur_y), label, font=font_sec, fill=color_sec_label)
                cur_y += 34
            for line in lines:
                draw.text((_PADDING_X + 8, cur_y), line, font=font_body, fill=_COLOR_TEXT)
                cur_y += line_h
            cur_y += sec_gap

        # Footer divider and watermark
        cur_y = max(cur_y, total_h - footer_h)
        draw.line([(_PADDING_X, cur_y), (_WIDTH - _PADDING_X, cur_y)], fill=color_divider, width=2)
        cur_y += 30
        watermark_text = f"BAYRAM STUDIO • {handle}"
        draw.text(
            (_WIDTH // 2, cur_y), watermark_text, font=font_foot, fill=color_muted, anchor="mt"
        )

        with scratch_dir(destination) as scratch:
            staged = scratch / "lyrics.png"
            image.save(staged, format="PNG", optimize=True)
            publish(staged, destination)

        return ok(destination)
    except Exception as exc:
        _LOG.warning("lyrics_image.render_failed", extra={"reason": str(exc)})
        return err(StorageError("could not render lyrics image", cause=exc))
