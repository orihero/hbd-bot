"""Dependency-free text -> PNG rendering for the A/B harness.

Why this file exists at all
--------------------------
The ffmpeg on this machine is built WITHOUT libfreetype and WITHOUT libass:

    $ ffmpeg -filters | grep drawtext   ->  (nothing)
    $ ffmpeg -h filter=drawtext         ->  Unknown filter 'drawtext'.

So `drawtext` and `subtitles` are both unavailable, and every burned-in label
in the comparison (half labels, running timecode, contact-sheet captions) has
to arrive as an image that ffmpeg `overlay`s.  numpy / Pillow / opencv are also
absent from every interpreter on this box and the brief forbids pip-installing
them, so the PNGs are written here with nothing but `zlib` and `struct` from
the standard library, using a hand-rolled 5x7 bitmap font.

The font is deliberately tiny and blocky: at scale >= 4 it is crisp at 1080p
and it survives h264 encoding better than an anti-aliased face would.
"""

from __future__ import annotations

import struct
import zlib

# --------------------------------------------------------------------------
# 5x7 bitmap font.  Each glyph is 7 rows of 5 columns; '#' = ink.
# --------------------------------------------------------------------------
_GLYPHS = {
    "0": (" ### ", "#   #", "#  ##", "# # #", "##  #", "#   #", " ### "),
    "1": ("  #  ", " ##  ", "  #  ", "  #  ", "  #  ", "  #  ", " ### "),
    "2": (" ### ", "#   #", "    #", "   # ", "  #  ", " #   ", "#####"),
    "3": ("#####", "   # ", "  ## ", "    #", "    #", "#   #", " ### "),
    "4": ("   # ", "  ## ", " # # ", "#  # ", "#####", "   # ", "   # "),
    "5": ("#####", "#    ", "#### ", "    #", "    #", "#   #", " ### "),
    "6": ("  ## ", " #   ", "#    ", "#### ", "#   #", "#   #", " ### "),
    "7": ("#####", "    #", "   # ", "  #  ", " #   ", " #   ", " #   "),
    "8": (" ### ", "#   #", "#   #", " ### ", "#   #", "#   #", " ### "),
    "9": (" ### ", "#   #", "#   #", " ####", "    #", "   # ", " ##  "),
    "A": (" ### ", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"),
    "B": ("#### ", "#   #", "#   #", "#### ", "#   #", "#   #", "#### "),
    "C": (" ### ", "#   #", "#    ", "#    ", "#    ", "#   #", " ### "),
    "D": ("#### ", "#   #", "#   #", "#   #", "#   #", "#   #", "#### "),
    "E": ("#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#####"),
    "F": ("#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#    "),
    "G": (" ### ", "#   #", "#    ", "#  ##", "#   #", "#   #", " ####"),
    "H": ("#   #", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"),
    "I": (" ### ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", " ### "),
    "J": ("    #", "    #", "    #", "    #", "    #", "#   #", " ### "),
    "K": ("#   #", "#  # ", "# #  ", "##   ", "# #  ", "#  # ", "#   #"),
    "L": ("#    ", "#    ", "#    ", "#    ", "#    ", "#    ", "#####"),
    "M": ("#   #", "## ##", "# # #", "#   #", "#   #", "#   #", "#   #"),
    "N": ("#   #", "##  #", "# # #", "#  ##", "#   #", "#   #", "#   #"),
    "O": (" ### ", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "),
    "P": ("#### ", "#   #", "#   #", "#### ", "#    ", "#    ", "#    "),
    "Q": (" ### ", "#   #", "#   #", "#   #", "# # #", "#  # ", " ## #"),
    "R": ("#### ", "#   #", "#   #", "#### ", "# #  ", "#  # ", "#   #"),
    "S": (" ####", "#    ", "#    ", " ### ", "    #", "    #", "#### "),
    "T": ("#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  "),
    "U": ("#   #", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "),
    "V": ("#   #", "#   #", "#   #", "#   #", "#   #", " # # ", "  #  "),
    "W": ("#   #", "#   #", "#   #", "# # #", "# # #", "## ##", "#   #"),
    "X": ("#   #", "#   #", " # # ", "  #  ", " # # ", "#   #", "#   #"),
    "Y": ("#   #", "#   #", " # # ", "  #  ", "  #  ", "  #  ", "  #  "),
    "Z": ("#####", "    #", "   # ", "  #  ", " #   ", "#    ", "#####"),
    " ": ("     ", "     ", "     ", "     ", "     ", "     ", "     "),
    ":": ("     ", "  #  ", "  #  ", "     ", "  #  ", "  #  ", "     "),
    ".": ("     ", "     ", "     ", "     ", "     ", "  ## ", "  ## "),
    ",": ("     ", "     ", "     ", "     ", "  ## ", "  ## ", "  #  "),
    "-": ("     ", "     ", "     ", "#####", "     ", "     ", "     "),
    "_": ("     ", "     ", "     ", "     ", "     ", "     ", "#####"),
    "+": ("     ", "  #  ", "  #  ", "#####", "  #  ", "  #  ", "     "),
    "=": ("     ", "     ", "#####", "     ", "#####", "     ", "     "),
    "/": ("    #", "    #", "   # ", "  #  ", " #   ", "#    ", "#    "),
    "(": ("   # ", "  #  ", " #   ", " #   ", " #   ", "  #  ", "   # "),
    ")": (" #   ", "  #  ", "   # ", "   # ", "   # ", "  #  ", " #   "),
    "[": ("  ###", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "  ###"),
    "]": ("###  ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "###  "),
    "#": (" # # ", "#####", " # # ", " # # ", "#####", " # # ", "     "),
    "|": ("  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  "),
    "%": ("#   #", "#  # ", "  #  ", "  #  ", "  #  ", " #  #", "#   #"),
    "!": ("  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "     ", "  #  "),
    "?": (" ### ", "#   #", "    #", "   # ", "  #  ", "     ", "  #  "),
    "<": ("    #", "   # ", "  #  ", " #   ", "  #  ", "   # ", "    #"),
    ">": ("#    ", " #   ", "  #  ", "   # ", "  #  ", " #   ", "#    "),
}
_MISSING = ("#####", "#   #", "#   #", "#   #", "#   #", "#   #", "#####")

GLYPH_W, GLYPH_H = 5, 7
ADVANCE = GLYPH_W + 1  # one blank column of tracking between glyphs


def text_width(text: str, scale: int) -> int:
    """Pixel width of `text` at `scale` (trailing tracking column trimmed)."""
    if not text:
        return 0
    return (len(text) * ADVANCE - 1) * scale


def text_height(scale: int) -> int:
    return GLYPH_H * scale


class Canvas:
    """A tiny RGBA raster.  Rows are bytearrays of length w*4."""

    def __init__(self, w: int, h: int, fill=(0, 0, 0, 0)):
        self.w, self.h = w, h
        row = bytes(fill) * w
        self.rows = [bytearray(row) for _ in range(h)]

    def rect(self, x: int, y: int, w: int, h: int, color) -> None:
        r, g, b, a = color
        px = bytes((r, g, b, a))
        for yy in range(max(0, y), min(self.h, y + h)):
            x0, x1 = max(0, x), min(self.w, x + w)
            if x1 > x0:
                self.rows[yy][x0 * 4 : x1 * 4] = px * (x1 - x0)

    def text(self, x: int, y: int, s: str, scale: int, color) -> int:
        """Draw `s` with its top-left at (x, y).  Returns the x after the text."""
        r, g, b, a = color
        px = bytes((r, g, b, a))
        for ch in s.upper():
            glyph = _GLYPHS.get(ch, _MISSING)
            for gy, line in enumerate(glyph):
                for gx, cell in enumerate(line):
                    if cell != "#":
                        continue
                    bx, by = x + gx * scale, y + gy * scale
                    for yy in range(by, by + scale):
                        if 0 <= yy < self.h:
                            x0, x1 = max(0, bx), min(self.w, bx + scale)
                            if x1 > x0:
                                self.rows[yy][x0 * 4 : x1 * 4] = px * (x1 - x0)
            x += ADVANCE * scale
        return x

    def save(self, path: str) -> str:
        raw = b"".join(b"\x00" + bytes(r) for r in self.rows)
        comp = zlib.compress(raw, 9)

        def chunk(tag: bytes, data: bytes) -> bytes:
            body = tag + data
            return (
                struct.pack(">I", len(data))
                + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
            )

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0)
        png = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", comp)
            + chunk(b"IEND", b"")
        )
        with open(path, "wb") as fh:
            fh.write(png)
        return path


def label_strip(
    path: str,
    width: int,
    text: str,
    scale: int = 6,
    fg=(255, 255, 255, 255),
    accent=(255, 230, 0, 255),
    bg=(0, 0, 0, 170),
    pad: int = 14,
) -> str:
    """A full-width translucent banner with `text` left-aligned and an accent bar."""
    h = text_height(scale) + pad * 2
    c = Canvas(width, h, (0, 0, 0, 0))
    c.rect(0, 0, width, h, bg)
    c.rect(0, 0, 10, h, accent)  # colour-codes which half you are looking at
    c.text(10 + pad, pad, text, scale, fg)
    return c.save(path)


def badge(
    path: str,
    text: str,
    scale: int = 5,
    fg=(255, 255, 255, 255),
    bg=(0, 0, 0, 190),
    pad: int = 10,
) -> str:
    """A shrink-to-fit translucent badge, used for timecode and sheet captions."""
    w = text_width(text, scale) + pad * 2
    h = text_height(scale) + pad * 2
    c = Canvas(w, h, (0, 0, 0, 0))
    c.rect(0, 0, w, h, bg)
    c.text(pad, pad, text, scale, fg)
    return c.save(path)
