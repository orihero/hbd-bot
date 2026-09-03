#!/usr/bin/env python3
"""
Rebuild the four vendored `.woff2` faces in ``admin-ui/src/assets/fonts/``.

Nothing in the build or the test run needs this script: the fonts are committed binaries and
that is deliberate — the panel must build on a machine with no network, and a font that is
fetched at build time is a font nobody has inspected. This exists so the binaries are
*reproducible* rather than mysterious, and so the next person to touch the palette can see
exactly which codepoints were kept and why.

    python3 -m venv .fontenv && .fontenv/bin/pip install fonttools brotli
    .fontenv/bin/python admin-ui/tools/build-fonts.py

Sources are the upstream variable fonts in ``google/fonts``. All six are SIL OFL 1.1 and
**none of them reserves its name** — the phrase "Reserved Font Name" appears only in the
licence body's definitions, never in a copyright line — so the three text faces keep their
own family names and only the merged symbol face, which is no longer any one of them, is
renamed.

WHY THESE FOUR FACES

* Mulish and Urbanist are the reskin's body and heading faces.
* Noto Sans Mono replaces JetBrains Mono. §12.1 T7 says self-hosting JetBrains Mono
  "guarantees U+02BB/U+02BC and Cyrillic coverage". It does not: JetBrains Mono has no
  U+02BB at all, and no Ғ/Қ/Ҳ (U+0492/U+049A/U+04B2) — three of the letters an Uzbek name
  is spelled with in Cyrillic. Noto Sans Mono has every one.
* HBD Status Symbols carries §11.3's status glyphs. Neither Mulish nor Urbanist contains a
  single one of them, and no one OFL face covers all twelve, so three are merged.

WHY THIS SUBSET

Latin, Latin Extended-A/B/Additional, the *whole* Cyrillic block and Cyrillic Supplement.
The Cyrillic choice is the load-bearing one. Google's own "cyrillic" subset is U+0400-045F
plus a handful of strays, which leaves out Ғ U+0492, Қ U+049A and Ҳ U+04B2 — they live in
"cyrillic-ext". Shipping Google's split would render Ғулом with the Ғ in a different
typeface. U+02B0-02FF is kept whole for the same reason: U+02BB and U+02BC are the two
codepoints this product exists to get right.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "assets" / "fonts"
WORK = Path(os.environ.get("HBD_FONT_WORK", "/tmp/hbd-fonts"))
RAW = "https://raw.githubusercontent.com/google/fonts/main/ofl"

#: Every codepoint the console may have to draw in a text face.
TEXT_UNICODES = [
    "U+0000-00FF",   # Basic Latin + Latin-1 Supplement
    "U+0100-024F",   # Latin Extended-A and -B
    "U+0259",        # ə
    "U+02B0-02FF",   # Spacing Modifier Letters — U+02BB and U+02BC LIVE HERE
    "U+0300-036F",   # Combining Diacritical Marks
    "U+0400-04FF",   # Cyrillic, whole block: Ў U+040E, Ғ U+0492, Қ U+049A, Ҳ U+04B2
    "U+0500-052F",   # Cyrillic Supplement
    "U+1E00-1EFF",   # Latin Extended Additional
    "U+2000-206F",   # General Punctuation
    "U+20A0-20BF",   # Currency Symbols
    "U+2113", "U+2116", "U+2122",           # ℓ  №  ™
    "U+2190-2199", "U+21BA-21BB",           # arrows, ↺ ↻
    "U+2212", "U+2215", "U+2248", "U+2260",
    "U+FEFF", "U+FFFD",
]

SUBSET_FLAGS = [
    "--flavor=woff2",
    "--no-hinting",
    "--desubroutinize",
    "--drop-tables+=DSIG,MATH,SVG,COLR,CPAL,BASE,JSTF,VORG",
    "--layout-features=kern,liga,calt,ccmp,mark,mkmk,locl,tnum,zero,onum,lnum,frac,ss01,ss02",
    "--name-IDs=*",
]

#: (upstream directory, upstream filename, axis pins, output name, family name)
TEXT_FACES = [
    # Mulish's variable default is wght=200 (ExtraLight). Re-defaulting to 400 means the raw
    # binary is Regular anywhere it is opened without a weight — including a canvas probe.
    (
        "mulish",
        "Mulish[wght].ttf",
        ["wght=200:400:1000"],
        "mulish-latin-cyrillic-var.woff2",
        "Mulish",
    ),
    ("urbanist", "Urbanist[wght].ttf", [], "urbanist-latin-var.woff2", "Urbanist"),
    # wdth is pinned and wght clipped to 400-700: the console sets mono at 400 and 500 and
    # nothing else, and the full two-axis face is 141 kB against this one's 81 kB.
    (
        "notosansmono",
        "NotoSansMono[wdth,wght].ttf",
        ["wdth=100", "wght=400:700"],
        "noto-sans-mono-latin-cyrillic-var.woff2",
        "Noto Sans Mono",
    ),
]

#: (upstream directory, upstream filename, codepoints it is the source of)
SYMBOL_SOURCES = [
    (
        "notosanssymbols2",
        "NotoSansSymbols2-Regular.ttf",
        [
            0x25CB,  # ○ draft
            0x25D4,  # ◔ brief_ready
            0x25D1,  # ◑ lyrics_ready
            0x25C6,  # ◆ authorized
            0x25C9,  # ◉ generating
            0x2713,  # ✓ delivered
            0x2717,  # ✗ failed
            0x25A0,  # ■ terminal
            0x1F512,  # 🔒 purged
            0x25CF,
            0x25D0,
            0x25D5,  # ● ◐ ◕ — the rest of the pie ramp
            0x25B2,
            0x25BC,  # ▲ ▼ — the delta chips
            0x26A0,  # ⚠
        ],
    ),
    ("notosansmath", "NotoSansMath-Regular.ttf", [0x2298, 0x21BB]),  # ⊘ cancelled, ↻ retryable
    ("notosanssymbols", "NotoSansSymbols[wght].ttf", [0x2691]),  # ⚑ held
]

SYMBOL_FAMILY = "HBD Status Symbols"


def fetch(directory: str, filename: str) -> Path:
    """Download one upstream face and its licence into the work directory."""
    WORK.mkdir(parents=True, exist_ok=True)
    target = WORK / filename
    if not target.exists():
        quoted = filename.replace("[", "%5B").replace("]", "%5D")
        subprocess.run(["curl", "-sSfL", "-o", str(target), f"{RAW}/{directory}/{quoted}"], check=True)
    licence = OUT / "licences" / f"OFL-{directory}.txt"
    if not licence.exists():
        licence.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["curl", "-sSfL", "-o", str(licence), f"{RAW}/{directory}/OFL.txt"], check=True)
    return target


def subset(source: Path, unicodes: list[str], destination: Path, extra: list[str] = []) -> int:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "fontTools.subset",
            str(source),
            "--unicodes=" + ",".join(unicodes),
            f"--output-file={destination}",
            *SUBSET_FLAGS,
            *extra,
        ],
        check=True,
    )
    return destination.stat().st_size


def add_notdef_box(font_path: Path) -> None:
    """Give the face a VISIBLE `.notdef`, because every one of these ships an empty one.

    This is not cosmetics. `.notdef` is what a browser draws for a codepoint that no font in
    the chain covers, and the shape it draws is the *first* font's — which, now that the
    first font is one of ours, means ours. Mulish, Urbanist, Noto Sans Mono and all three
    Noto symbol faces upstream give `.notdef` an advance width and **zero contours**: a
    blank of half an em.

    So before this, an uncoverable character in a name was drawn as a hollow box by whatever
    system font led the stack, and after self-hosting it would have been drawn as *nothing
    at all* — a name quietly one character shorter, with no error, no log line and no way for
    an operator to know a character had been eaten. For a console whose entire job is
    getting a name right, silently dropping a character is strictly worse than showing a box.

    It is also what keeps `e2e/font-coverage.spec.ts` able to detect a missing glyph: its
    whole method is "does this character's bitmap equal the bitmap of a codepoint nothing
    covers", and a blank `.notdef` makes that bitmap empty. The first run after self-hosting
    failed on exactly that, with "the guaranteed-missing U+50000 painted nothing" — the
    negative control doing its job, on its very first outing against a real change.

    The box is drawn static: `.notdef` gets no `gvar` entry, so it does not follow the weight
    axis, and it should not — it is a diagnostic, not a letter.
    """
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont

    with TTFont(font_path) as font:
        upm = font["head"].unitsPerEm
        advance, left_side_bearing = font["hmtx"][".notdef"]
        # Proportions of the em, so the 2000-upm face (Urbanist) gets the same shape as the
        # 1000-upm ones rather than a box a quarter of the size.
        stroke = round(upm * 0.045)
        x0, x1 = round(advance * 0.10), advance - round(advance * 0.10)
        y0, y1 = round(upm * 0.02), round(upm * 0.68)

        pen = TTGlyphPen(None)
        # Outer rectangle, then the counter drawn the other way round: TrueType fills by
        # non-zero winding, so an inner contour that runs the same direction as the outer
        # one produces a solid block instead of a hollow box.
        for x_left, x_right, y_bottom, y_top, clockwise in (
            (x0, x1, y0, y1, True),
            (x0 + stroke, x1 - stroke, y0 + stroke, y1 - stroke, False),
        ):
            corners = [
                (x_left, y_bottom),
                (x_left, y_top),
                (x_right, y_top),
                (x_right, y_bottom),
            ]
            if not clockwise:
                corners.reverse()
            pen.moveTo(corners[0])
            for corner in corners[1:]:
                pen.lineTo(corner)
            pen.closePath()

        font["glyf"][".notdef"] = pen.glyph()
        font["hmtx"][".notdef"] = (advance, left_side_bearing)
        font.save(font_path)


def name_as(font_path: Path, family: str) -> None:
    """Make the binary call itself what the `@font-face` rule calls it.

    Cosmetic in the browser — the family a page matches on comes from the `@font-face` rule,
    not from the file — but a Mulish whose name table still says "Mulish ExtraLight" (its
    upstream variable default before the re-default to 400) is the kind of detail that costs
    somebody an afternoon in a font inspector.
    """
    from fontTools.ttLib import TTFont

    with TTFont(font_path) as font:
        table = font["name"]
        for name_id, text in (
            (1, family),
            (2, "Regular"),
            (4, f"{family} Regular"),
            (6, f"{family.replace(' ', '')}-Regular"),
            (16, family),
            (17, "Regular"),
        ):
            for record in list(table.names):
                if record.nameID == name_id:
                    table.removeNames(nameID=name_id)
                    break
            table.setName(text, name_id, 3, 1, 0x409)
        font.save(font_path)


def build_text_faces() -> None:
    for directory, filename, pins, out_name, family in TEXT_FACES:
        source = fetch(directory, filename)
        if pins:
            pinned = WORK / f"{filename[:-4]}-pinned.ttf"
            subprocess.run(
                [sys.executable, "-m", "fontTools.varLib.instancer", str(source), *pins,
                 "-o", str(pinned)],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            source = pinned
        subset(source, TEXT_UNICODES, OUT / out_name)
        add_notdef_box(OUT / out_name)
        name_as(OUT / out_name, family)
        size = (OUT / out_name).stat().st_size
        print(f"{out_name:<44} {size:>7,} bytes")


def build_symbol_face() -> None:
    from fontTools.merge import Merger
    from fontTools.ttLib import TTFont

    parts: list[str] = []
    for directory, filename, codepoints in SYMBOL_SOURCES:
        source = fetch(directory, filename)
        with TTFont(source, lazy=True) as probe:
            variable = "fvar" in probe
        if variable:
            static = WORK / f"{filename[:-4]}-static.ttf"
            subprocess.run(
                [sys.executable, "-m", "fontTools.varLib.instancer", str(source), "wght=400",
                 "-o", str(static)],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            source = static
        part = WORK / f"{filename[:-4]}-part.ttf"
        subprocess.run(
            [sys.executable, "-m", "fontTools.subset", str(source),
             "--unicodes=" + ",".join(f"U+{cp:04X}" for cp in codepoints),
             f"--output-file={part}", "--no-hinting",
             "--drop-tables+=DSIG,MATH,SVG,COLR,CPAL,BASE,JSTF,vmtx,vhea,VORG",
             "--layout-features=", "--name-IDs=*"],
            check=True,
        )
        parts.append(str(part))

    merged = Merger().merge(parts)

    # One consistent line box. Noto Sans Math declares a 3105/2550 win box for its extenders,
    # which would inflate every line one of these glyphs lands in; Symbols 2's box is the one
    # the shapes were actually drawn against.
    hhea, os2 = merged["hhea"], merged["OS/2"]
    hhea.ascent, hhea.descent, hhea.lineGap = 1069, -630, 0
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = 1069, -630, 0
    os2.usWinAscent, os2.usWinDescent = 1069, 630
    os2.fsSelection |= 1 << 7  # USE_TYPO_METRICS
    os2.sxHeight, os2.sCapHeight = 536, 945
    assert merged["head"].unitsPerEm == 1000, "the three sources must share one em"

    merged["name"].names = []
    for name_id, text in (
        (0, "Subset and merge of Noto Sans Symbols 2, Noto Sans Math and Noto Sans Symbols. "
            "Copyright 2022 The Noto Project Authors (https://github.com/notofonts). "
            "Licensed under the SIL Open Font License 1.1. Renamed because it is a merge; "
            "none of the three sources reserves its name."),
        (1, SYMBOL_FAMILY),
        (2, "Regular"),
        (3, f"{SYMBOL_FAMILY}:2026"),
        (4, f"{SYMBOL_FAMILY} Regular"),
        (5, "Version 1.000"),
        (6, "HBDStatusSymbols-Regular"),
        (13, "This Font Software is licensed under the SIL Open Font License, Version 1.1."),
        (14, "https://openfontlicense.org"),
    ):
        merged["name"].setName(text, name_id, 3, 1, 0x409)

    staged = WORK / "hbd-status-symbols.ttf"
    merged.save(staged)
    size = subset(staged, ["*"], OUT / "hbd-status-symbols.woff2")
    add_notdef_box(OUT / "hbd-status-symbols.woff2")
    size = (OUT / "hbd-status-symbols.woff2").stat().st_size
    print(f"{'hbd-status-symbols.woff2':<44} {size:>7,} bytes")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    build_text_faces()
    build_symbol_face()
