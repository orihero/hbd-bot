#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the nine overlay cards for the Peshta promo (Variant D).

Plan: marketing/campaigns/peshta/04_generation_plan.md, sections 7.2 (fonts), 7.3 (safe zone,
glyph floor) and 7.4 (the nine cards).

WHY THIS EXISTS AT ALL
    This machine's ffmpeg 9.0.1 is the slim Homebrew formula: `drawtext`,
    `subtitles` and `ass` are all MISSING (plan 7.1). PIL therefore owns
    typography and ffmpeg only composites finished RGBA PNGs. That is strictly
    better, because a PIL renderer can assert the safe zone and the minimum
    glyph height *at render time* and refuse to write a bad card.

WHAT IT GUARANTEES
    G5a  every drawn pixel of c1-c8 lies inside X 40..940, Y 220..1500.
         `c9` is exempt by name: it is the full-frame white flash.
    G5b  rendered em size >= 76 px AND measured cap-height >= 53 px, on the
         narrative cards c1-c6 and c8. `c7` (48 pt handle pill) and `c9` are
         exempt by name, via SPEC["glyph_floor_exempt"].
    G14  writes cards/strings.txt, one line per card id + its rendered lines,
         tab separated, UTF-8. That file is the artefact G14 audits.

    The asserts run BEFORE the PNG is written, so a card that breaches either
    bound leaves no file behind.

USAGE
    .venv/bin/python marketing/campaigns/peshta/make_cards.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# Uzbek characters as EXPLICIT ESCAPES.
#
# Never as literals: an invisible literal U+00A0 in source is indistinguishable
# from a plain space on inspection, and a plain space is exactly the character
# that wraps -- a wrap between "15" and "000" turns a 15 000 so'm promo into a
# 15 so'm promo (plan 7.4 ruling 4, src/bayram/bot/pricing.py:35-41).
# --------------------------------------------------------------------------
TC = "\u02bb"  # MODIFIER LETTER TURNED COMMA -- the o' and g' mark
TA = "\u02bc"  # MODIFIER LETTER APOSTROPHE   -- the glottal-stop mark
NBSP = "\u00a0"  # NO-BREAK SPACE -- the price grouping separator, mandatory
ELL = "\u2026"  # HORIZONTAL ELLIPSIS

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "cards"

# --------------------------------------------------------------------------
# SPEC -- every number the renderer obeys lives here, nowhere else.
# --------------------------------------------------------------------------
SPEC = {
    "canvas": (1080, 1920),
    "font": os.path.expanduser("~/Library/Fonts/Montserrat-ExtraBold.ttf"),
    "font_fallback": "/Library/Fonts/Arial Unicode.ttf",
    # plan 7.3 -- 03 1.4 is authoritative; 01 7.4's looser bounds are superseded
    "safe": {"x_min": 40, "x_max": 940, "y_min": 220, "y_max": 1500},
    # The asymmetry trap: the safe box is NOT centred on the canvas centre 540.
    #   max half-width = min(540-40, 940-540) = 400  ->  800 px, not 900.
    "center_x": 540,
    "max_centered_w": 800,
    # A band/pill may fill the whole 800, but its text keeps at least this
    # inset from the band edge, so nothing reads as bursting out of its box.
    "min_text_inset": 12,
    # plan 7.3 / G5b -- the floor is TWO numbers, because cap-height is not
    # type size. Measured on the installed face, cap/size = 0.690..0.708.
    "glyph_floor": {"em_px": 76, "cap_px": 53},
    "glyph_floor_exempt": ("c7", "c9"),  # by name, plan 7.3 / 7.4 / G5b
    "safe_zone_exempt": ("c9",),  # the deliberate full-frame flash
    "alpha_threshold": 8,  # same threshold G5a's alphaextract scan uses
    "line_height": 1.15,  # x em size
    "strings_file": "strings.txt",
}

# --------------------------------------------------------------------------
# CARDS -- the nine cards of plan 7.4.
#
# size/colour/Y come from the plan. Where a size differs from the printed
# figure the plan's own 7.2 note authorises it: every width in 7.3/7.4 was
# measured on Arial Unicode and "Montserrat ExtraBold is materially wider" --
# re-derive c1/c3's sizes from the installed face. See DISCREPANCIES below.
# --------------------------------------------------------------------------
CARDS = {
    "c1": {
        "window": "0-126 / 0.000-2.540 s",
        "lines": ["SOAT 23:55.", f"SOVG{TC}A ESA YO{TC}Q!"],
        # plan says 84 pt; on Montserrat ExtraBold line 2 measures 817 px,
        # over the 800 px centred bound before any pill padding. 79 pt is the
        # largest size that fits and still clears the 76 px em floor.
        "size": 79,
        "fill": "#FFE600",
        "band": {"color": "#121212", "alpha": 0.90, "pad_x": 40, "pad_y": 26, "radius": 28},
        "y": 380,
    },
    "c2": {
        "window": "80-126 / 1.600-2.540 s (3-frame alpha pulse)",
        "lines": [f"TO{TC}XTA{ELL}"],
        "size": 84,
        "fill": "#FFE600",
        "band": None,  # bare text over video -> carries its own black stroke
        "stroke": {"width": 5, "color": "#121212"},
        "y": 560,
    },
    "c3": {
        "window": "127-217 / 2.540-4.360 s",
        "lines": ["BAYRAM-BOTDA!"],
        # plan says 88 pt; measures 816 px on the installed face. 83 pt fits.
        "size": 83,
        "fill": "#121212",
        "band": {"color": "#FFE600", "alpha": 1.0, "pad_x": 40, "pad_y": 26, "radius": 28},
        "y": 420,
        "deco": {"kind": "flame", "place": "above", "w": 78, "h": 92, "gap": 18},
    },
    "c4": {
        "window": "218-399 / 4.360-8.000 s",
        # plan 7.4 ruling 5 specifies a TWO-line break, measured on Arial
        # Unicode: "ATALGAN QO'SHIQ!" = 755 px. On Montserrat ExtraBold it is
        # 834 px at 80 pt and 792 px at the 76 pt floor -- both breach the
        # 800 px centred bound once the black stroke is counted. Broken into
        # three lines at the specified 80 pt instead of dropping under the
        # floor. The break still keeps the modifier with its head noun.
        "lines": ["UNING ISMIGA", "ATALGAN", f"QO{TC}SHIQ!"],
        "size": 80,
        "fill": "#FFD700",  # karaoke gold
        "band": None,
        "stroke": {"width": 6, "color": "#000000"},
        "y": 1200,
    },
    "c5": {
        "window": "400-524 / 8.000-10.500 s",
        "lines": [f"SO{TC}ZLARINI O{TC}QISH", "BEPUL!"],
        "size": 76,  # already at the G5b floor -- cannot shrink
        "fill": "#FFFFFF",
        # line 1 measures 770 px, so the badge is a full 800 px band and the
        # pad_x below gets clamped to 15. Reported at render time, not hidden.
        "band": {"color": "#00C853", "alpha": 1.0, "pad_x": 40, "pad_y": 26, "radius": 28},
        "y": 880,
    },
    "c6": {
        "window": "575-749 / 11.500-15.000 s",
        "lines": ["HOZIROQ KIRING:", "@bayram_uzbot"],
        "size": 80,
        "fill": "#FFE600",
        "line_fill": {1: "#FFFFFF"},  # the handle is white, the call is yellow
        "band": None,
        "stroke": {"width": 5, "color": "#121212"},
        "y": 1050,  # moved up from 1350: at 1350 the block breached Y 1500
        "deco": {"kind": "chevron", "place": "inline", "line": 1, "w": 52, "h": 56, "gap": 18},
    },
    "c7": {
        "window": "145-749 / 2.900-15.000 s",
        "lines": ["@bayram_uzbot"],
        "size": 48,  # deliberately small: a persistent corner pill
        "fill": "#FFFFFF",
        "band": {"color": "#0088CC", "alpha": 1.0, "pad_x": 30, "pad_y": 12, "radius": 40},
        "align": "right",  # right edge of the pill sits on X 940
        "right_x": 940,
        "y": 290,  # pill spans Y 250-330
        "deco": {"kind": "plane", "place": "inline", "line": 0, "w": 44, "h": 44, "gap": 16},
    },
    "c8": {
        "window": "420-749 / 8.400-15.000 s",
        # The NBSP is the whole point of this line -- see plan 7.4 ruling 4.
        "lines": ["ATIGI 15" + NBSP + "000 SO" + TC + "M", "Bitta kofe narxi"],
        "size": 76,
        "fill": "#FFFFFF",
        "band": {"color": "#00C853", "alpha": 1.0, "pad_x": 40, "pad_y": 26, "radius": 28},
        "y": 1300,
    },
    "c9": {
        "window": "4.335-4.375, 6.155-6.195, 13.215-13.255 s (2 frames each)",
        "lines": [],
        "size": 0,
        "fill": "#FFFFFF",
        "band": None,
        "y": 0,
        "full_frame": True,  # the alpha IS the whole canvas, on purpose
    },
}

ORDER = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8", "c9"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
class CardError(AssertionError):
    """A card that must not be written to disk."""


def hex_rgba(h: str, alpha: float = 1.0):
    h = h.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r, g, b, int(round(255 * alpha)))


def load_font(size: int) -> ImageFont.FreeTypeFont:
    path = SPEC["font"]
    if not os.path.exists(path):
        path = SPEC["font_fallback"]
        print(f"  ! Montserrat ExtraBold missing, falling back to {path}")
    return ImageFont.truetype(path, size)


def text_w(font: ImageFont.FreeTypeFont, s: str) -> int:
    b = font.getbbox(s)
    return b[2] - b[0]


def cap_height(font: ImageFont.FreeTypeFont) -> int:
    b = font.getbbox("A")
    return b[3] - b[1]


def _mask_bytes(font: ImageFont.FreeTypeFont, ch: str) -> tuple:
    """(size, pixels) of a single glyph's rendered mask."""
    m = font.getmask(ch, mode="L")
    return m.size, Image.frombytes("L", m.size, bytes(m)).tobytes()


def check_coverage(font: ImageFont.FreeTypeFont, text: str, cid: str) -> None:
    """Refuse a card whose face lacks a glyph -- tofu passes a safe-zone assert
    happily, which is exactly how both earlier drafts nearly shipped emoji
    rectangles (plan 7.2)."""
    notdef = _mask_bytes(font, "\ue04f")  # private use, certainly absent
    for ch in text:
        if ch in (" ", NBSP):
            continue
        if _mask_bytes(font, ch) == notdef:
            raise CardError(
                f"{cid}: font has no glyph for U+{ord(ch):04X} ({ch!r}) -- would render as tofu"
            )


def alpha_extent(img: Image.Image):
    """min/max x and y of pixels with alpha > threshold -- the same measurement
    G5a makes with ffmpeg alphaextract + a raw row/column scan."""
    thr = SPEC["alpha_threshold"]
    mask = img.getchannel("A").point(lambda v: 255 if v > thr else 0)
    box = mask.getbbox()
    if box is None:
        return None
    x0, y0, x1, y1 = box
    return x0, y0, x1 - 1, y1 - 1  # inclusive, as the G5a scan reports


# --------------------------------------------------------------------------
# vector marks -- the emoji replacement (plan 7.2: the only installed faces
# render U+1F525 and U+1F449 as identical tofu rectangles)
# --------------------------------------------------------------------------
def _poly(d: ImageDraw.ImageDraw, pts, box, fill):
    x, y, w, h = box
    d.polygon([(x + px * w, y + py * h) for px, py in pts], fill=fill)


def draw_flame(d, box):
    _poly(d, [(0.50, 0.00), (0.72, 0.27), (0.65, 0.36), (0.87, 0.57), (0.84, 0.78),
              (0.62, 0.98), (0.37, 0.99), (0.14, 0.80), (0.13, 0.55), (0.31, 0.29),
              (0.35, 0.47), (0.41, 0.19)], box, hex_rgba("#FF6B00"))
    _poly(d, [(0.50, 0.43), (0.66, 0.63), (0.63, 0.84), (0.50, 0.94), (0.36, 0.85),
              (0.34, 0.64)], box, hex_rgba("#FFE600"))


def draw_chevron(d, box):
    for off in (0.0, 0.45):
        _poly(d, [(0.05 + off, 0.02), (0.50 + off, 0.50), (0.05 + off, 0.98),
                  (0.00 + off, 0.80), (0.28 + off, 0.50), (0.00 + off, 0.20)],
              box, hex_rgba("#FFE600"))


def draw_plane(d, box):
    _poly(d, [(0.00, 0.44), (1.00, 0.00), (0.63, 1.00), (0.45, 0.66)], box, hex_rgba("#FFFFFF"))
    _poly(d, [(0.45, 0.66), (1.00, 0.00), (0.30, 0.56)], box, hex_rgba("#CFE9F7"))


MARKS = {"flame": draw_flame, "chevron": draw_chevron, "plane": draw_plane}


# --------------------------------------------------------------------------
# the renderer
# --------------------------------------------------------------------------
def render(cid: str, spec: dict) -> tuple[Image.Image, list[str]]:
    W, H = SPEC["canvas"]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if spec.get("full_frame"):
        d.rectangle([0, 0, W - 1, H - 1], fill=hex_rgba(spec["fill"]))
        return img, []

    size = spec["size"]
    font = load_font(size)
    lines = spec["lines"]
    for ln in lines:
        check_coverage(font, ln, cid)

    deco = spec.get("deco")
    stroke = spec.get("stroke") or {}
    sw = stroke.get("width", 0)

    # line widths, including an inline mark and its gap where one is specified
    widths = []
    for i, ln in enumerate(lines):
        w = text_w(font, ln) + 2 * sw
        if deco and deco["place"] == "inline" and deco["line"] == i:
            w += deco["w"] + deco["gap"]
        widths.append(w)
    max_w = max(widths)

    band = spec.get("band")
    pad_x = band["pad_x"] if band else 0
    block_w = max_w + 2 * pad_x

    # The 800 px centred bound is hard. Rather than silently overflow it (or
    # silently shrink the type), squeeze the band padding and say so.
    if block_w > SPEC["max_centered_w"]:
        if not band:
            raise CardError(
                f"{cid}: widest line is {max_w} px, over the {SPEC['max_centered_w']} px "
                f"centred bound at {size} pt, and there is no band padding to give back"
            )
        new_pad = (SPEC["max_centered_w"] - max_w) // 2
        if new_pad < SPEC["min_text_inset"]:
            raise CardError(
                f"{cid}: widest line is {max_w} px; a {SPEC['max_centered_w']} px band leaves "
                f"{new_pad} px inset, under the {SPEC['min_text_inset']} px minimum"
            )
        print(f"  ~ {cid}: band padding clamped {pad_x} -> {new_pad} px (line is {max_w} px)")
        pad_x = new_pad
        block_w = max_w + 2 * pad_x

    lh = int(round(size * SPEC["line_height"]))
    pad_y = band["pad_y"] if band else 0
    block_h = lh * len(lines) + 2 * pad_y

    # horizontal placement
    if spec.get("align") == "right":
        x1 = spec["right_x"]
        x0 = x1 - block_w
    else:
        x0 = SPEC["center_x"] - block_w // 2
        x1 = x0 + block_w
    cx = (x0 + x1) // 2

    y0 = spec["y"] - block_h // 2
    y1 = y0 + block_h

    # a mark placed above the block needs its room reserved before drawing
    if deco and deco["place"] == "above":
        dy1 = y0 - deco["gap"]
        d_box = (cx - deco["w"] / 2, dy1 - deco["h"], deco["w"], deco["h"])
    else:
        d_box = None

    if band:
        d.rounded_rectangle([x0, y0, x1, y1], radius=band["radius"],
                            fill=hex_rgba(band["color"], band["alpha"]))

    for i, ln in enumerate(lines):
        fill = hex_rgba((spec.get("line_fill") or {}).get(i, spec["fill"]))
        ty = y0 + pad_y + lh * i + lh // 2
        if deco and deco["place"] == "inline" and deco["line"] == i:
            tw = text_w(font, ln)
            total = deco["w"] + deco["gap"] + tw
            mx = cx - total / 2
            MARKS[deco["kind"]](d, (mx, ty - deco["h"] / 2, deco["w"], deco["h"]))
            tx = mx + deco["w"] + deco["gap"]
            anchor = "lm"
        else:
            tx, anchor = cx, "mm"
        d.text((tx, ty), ln, font=font, fill=fill, anchor=anchor,
               stroke_width=sw, stroke_fill=hex_rgba(stroke["color"]) if sw else None)

    if d_box:
        MARKS[deco["kind"]](d, d_box)

    return img, lines


def assert_card(cid: str, img: Image.Image, spec: dict) -> str:
    """G5a + G5b. Raises before anything is written."""
    notes = []

    # ---- G5b: legibility floor -------------------------------------------
    if cid in SPEC["glyph_floor_exempt"]:
        notes.append("glyph floor EXEMPT")
    else:
        em = spec["size"]
        cap = cap_height(load_font(em))
        fl = SPEC["glyph_floor"]
        if em < fl["em_px"]:
            raise CardError(f"{cid}: G5b rendered em size {em} px < {fl['em_px']} px floor")
        if cap < fl["cap_px"]:
            raise CardError(
                f"{cid}: G5b measured cap-height {cap} px < {fl['cap_px']} px floor "
                f"(em {em} px, cap/em {cap / em:.3f})"
            )
        notes.append(f"em {em} px, cap {cap} px")

    # ---- G5a: safe zone ---------------------------------------------------
    if cid in SPEC["safe_zone_exempt"]:
        notes.append("safe zone EXEMPT (full-frame flash)")
        return "  ".join(notes)

    ext = alpha_extent(img)
    if ext is None:
        raise CardError(f"{cid}: rendered nothing -- alpha is empty everywhere")
    xa, ya, xb, yb = ext
    s = SPEC["safe"]
    if xa < s["x_min"] or xb > s["x_max"]:
        raise CardError(
            f"{cid}: G5a X {xa}..{xb} outside safe zone {s['x_min']}..{s['x_max']}"
        )
    if ya < s["y_min"] or yb > s["y_max"]:
        raise CardError(
            f"{cid}: G5a Y {ya}..{yb} outside safe zone {s['y_min']}..{s['y_max']}"
        )
    notes.append(f"X {xa}..{xb}  Y {ya}..{yb}")
    return "  ".join(notes)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"font: {SPEC['font']}")
    print(f"out : {OUT_DIR}\n")

    written, strings = [], []
    failed = 0
    for cid in ORDER:
        spec = CARDS[cid]
        png = OUT_DIR / f"{cid}.png"
        if png.exists():
            png.unlink()  # never let a stale card from a previous run survive
        try:
            img, lines = render(cid, spec)
            notes = assert_card(cid, img, spec)
        except CardError as exc:
            print(f"  FAIL {cid}: {exc}")
            failed += 1
            continue
        img.save(png)
        written.append(cid)
        strings.append("\t".join([cid] + lines))
        print(f"  ok   {cid}  {notes}   {spec['window']}")

    # strings.txt: one line per card id + its exact rendered lines, tab
    # separated, UTF-8. This is the artefact gate G14 audits; G14 dies on
    # FileNotFoundError without it, and a skip is a fail.
    sf = OUT_DIR / SPEC["strings_file"]
    sf.write_text("\n".join(strings) + "\n", encoding="utf-8")

    body = sf.read_text(encoding="utf-8")
    print(f"\nwrote {sf}")
    print(f"  G14 self-check: ASCII apostrophes = {body.count(chr(39))} (must be 0)"
          f" | U+00A0 count = {body.count(NBSP)} (must be >= 1)")
    print(f"\n{len(written)}/{len(ORDER)} cards written"
          + (f", {failed} REFUSED" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
