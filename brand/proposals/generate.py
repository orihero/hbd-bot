"""Bayram — six logo proposals.

Same discipline as brand/: no fonts, geometry generated from constants.
Bar width 9, flame = 0.8 x bar width and 1.944x as tall as wide, rhythm 3:5:4.
Change a constant here and every file below stays consistent.
"""
from __future__ import annotations
import math, pathlib

INK, FLAME, WHITE = "#1C1620", "#BD32AF", "#FFFFFF"
OUT = pathlib.Path(__file__).parent


def n(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return s if s != "-0" else "0"


def flame(c: float, tip: float, r: float) -> str:
    """The canonical flame: width 2r, height 3.889r, tip at (c, tip)."""
    return (
        f'<path d="M{n(c)} {n(tip)}'
        f'C{n(c+0.76*r)} {n(tip+1.502*r)} {n(c+r)} {n(tip+2.469*r)} {n(c+r)} {n(tip+2.889*r)}'
        f'a{n(r)} {n(r)} 0 0 1 {n(-2*r)} 0'
        f'C{n(c-r)} {n(tip+2.469*r)} {n(c-0.76*r)} {n(tip+1.502*r)} {n(c)} {n(tip)}Z" fill="{{flame}}"/>'
    )


def bar(cx: float, top: float, h: float, w: float = 9.0) -> str:
    return (f'<rect x="{n(cx-w/2)}" y="{n(top)}" width="{n(w)}" height="{n(h)}" '
            f'rx="{n(w/2)}" fill="{{ink}}"/>')


# ---------------------------------------------------------------- 01 monogram
def monogram() -> list[str]:
    """B built from the level meter's own bar width, one flame on the stem."""
    return [
        '<g transform="translate(3.9 0)">',
        f'<g stroke="{{ink}}" stroke-width="9" stroke-linecap="round" fill="none">',
        '<path d="M18.5 24V53"/>',
        '<path d="M18.5 24H29A7.25 7.25 0 0 1 29 38.5H18.5"/>',
        '<path d="M18.5 38.5H30.5A7.25 7.25 0 0 1 30.5 53H18.5"/>',
        "</g>",
        flame(18.5, 4.3, 3.6),
        "</g>",
    ]


# ----------------------------------------------------------------- 02 suzani
def suzani() -> list[str]:
    """Eight-fold rosette. Petal lengths run 5:3:4:3 — the meter, made radial."""
    lengths = [16, 11, 13.5, 11, 16, 11, 13.5, 11]
    r0, w = 9.0, 7.0
    out = ['<g transform="translate(32 32)">']
    for k, ln in enumerate(lengths):
        out.append(
            f'<rect x="{n(-w/2)}" y="{n(-(r0+ln))}" width="{n(w)}" height="{n(ln)}" '
            f'rx="{n(w/2)}" fill="{{ink}}" transform="rotate({k*45})"/>'
        )
    out += ['<circle cx="0" cy="0" r="6.5" fill="{flame}"/>', "</g>"]
    return out


# ------------------------------------------------------------------ 03 doira
def doira() -> list[str]:
    """The frame drum. Twelve rim beads = twelve segments of the usul cycle."""
    circ = 2 * math.pi * 24
    dash = circ / 12
    out = [
        f'<circle cx="32" cy="32" r="24" fill="none" stroke="{{ink}}" stroke-width="5.5" '
        f'stroke-linecap="butt" stroke-dasharray="{n(dash*0.8)} {n(dash*0.2)}"/>'
    ]
    for cx, h in ((22, 12), (32, 20), (42, 16)):
        out.append(bar(cx, 47 - h, h, w=7))
        out.append(flame(cx, 47 - h - 1.2 - 3.889 * 2.8, 2.8))
    return out


# --------------------------------------------------------------- 05 envelope
def bubble() -> list[str]:
    """A Telegram message with the song still burning inside it."""
    out = [
        f'<path d="M20 40L12 56L32 46Z" fill="{{ink}}" stroke="{{ink}}" stroke-width="4" '
        'stroke-linejoin="round"/>',
        '<rect x="5" y="5" width="54" height="44" rx="14" fill="{ink}"/>',
    ]
    for cx, h in ((22, 9), (32, 15), (42, 12)):
        out.append(
            f'<rect x="{n(cx-3.5)}" y="{n(40-h)}" width="7" height="{n(h)}" rx="3.5" fill="{{paper}}"/>'
        )
        out.append(flame(cx, 40 - h - 1.2 - 3.889 * 2.8, 2.8))
    return out


# ------------------------------------------------------------------- 06 ikat
def ikat() -> list[str]:
    """The flame rebuilt out of the meter's bars — abr ikat's stepped edge."""
    halves = [2.8, 5.2, 7.6, 9.9, 11.8, 12.8, 11.6, 7.8]
    out = []
    for i, hw in enumerate(halves):
        y = 8 + i * 6.2
        out.append(
            f'<rect x="{n(32-hw)}" y="{n(y)}" width="{n(2*hw)}" height="5.6" rx="2.8" fill="{{flame}}"/>'
        )
    return out


# --------------------------------------------------------------- 04 wordmark
def wordmark() -> list[str]:
    return [
        f'<g stroke="{{ink}}" stroke-width="12" stroke-linecap="round" stroke-linejoin="round" fill="none">',
        '<path d="M6 28V88"/><path d="M6 28H21A15 15 0 0 1 21 58H6"/><path d="M6 58H23A15 15 0 0 1 23 88H6"/>',
        '<path d="M58 88L75 28L92 88"/><path d="M65 64H85"/>',
        '<path d="M100 28L117 58L134 28"/><path d="M117 58V88"/>',
        '<path d="M150 28V88"/><path d="M150 28H165A15 15 0 0 1 165 58H150"/><path d="M164 58L180 88"/>',
        '<path d="M200 88L217 28L234 88"/><path d="M207 64H227"/>',
        '<path d="M250 88V28L269 62L288 28V88"/>',
        "</g>",
        flame(6, 2.133, 4.8),
    ]


REVERSED = {  # ink, flame, paper -- for white-out-of-magenta
    "05-bubble": (WHITE, FLAME, FLAME),
}
DEFAULT_REVERSED = (WHITE, WHITE, WHITE)

CONCEPTS = {
    "01-monogram": ("Bayram monogram", monogram()),
    "02-suzani": ("Suzani rosette", suzani()),
    "03-doira": ("Doira", doira()),
    "05-bubble": ("Message bubble", bubble()),
    "06-ikat": ("Ikat flame", ikat()),
}

HEAD = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vb}" width="{w}" height="{h}" fill="none" role="img" aria-label="{label}">'


def write(path: str, body: str) -> None:
    (OUT / path).write_text(body + "\n")
    print("wrote", path)


for slug, (label, body) in CONCEPTS.items():
    els = "\n  ".join(body)
    write(f"mark-{slug}.svg",
          HEAD.format(vb="64 64", w=64, h=64, label=f"Bayram — {label}")
          + "\n  " + els.format(ink=INK, flame=FLAME, paper="#FFFFFF") + "\n</svg>")
    # Telegram avatar: white out of a flame-coloured disc, same 9-unit clear space
    r_ink, r_flame, r_paper = REVERSED.get(slug, DEFAULT_REVERSED)
    inner = "\n    ".join(body).format(ink=r_ink, flame=r_flame, paper=r_paper)
    write(f"avatar-{slug}.svg",
          HEAD.format(vb="512 512", w=512, h=512, label=f"Bayram — {label}")
          + f'\n  <rect width="512" height="512" rx="256" fill="{FLAME}"/>'
          + '\n  <g transform="translate(96 96) scale(5)">\n    ' + inner + "\n  </g>\n</svg>")

wm = "\n  ".join(wordmark()).format(ink=INK, flame=FLAME, paper="#FFFFFF")
write("04-wordmark-bayram.svg",
      HEAD.format(vb="294 94", w=294, h=94, label="BAYRAM") + "\n  " + wm + "\n</svg>")
