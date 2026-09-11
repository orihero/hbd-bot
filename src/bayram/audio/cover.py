"""The generated cover art: the bot's mark over white text on black, 320x320, one JPEG per order.

**Why this file draws the picture instead of ffmpeg.** ffmpeg can composite text with the
``drawtext`` filter, and this host's ffmpeg cannot: the build has no libfreetype, so
``ffmpeg -filters | grep drawtext`` returns nothing at all. There is no Dockerfile pinning
the deployed build either, so "the encoder will draw it" is a bet on a capability nothing
checks at boot — and the failure mode is not an error, it is a filter-graph rejection at
render time on a paying customer's order. Pillow moves the question to install time, where
a missing dependency is a build failure rather than a lost song.

**Why contrast still sets the budget, and what the mark is allowed to spend of it.** The
picture exists to be legible as a forty-pixel square in a forwarded message on somebody
else's phone, seen for about a second, at whatever brightness that phone happens to be at.
Pure white on pure black is a 21:1 contrast ratio — the highest sRGB can express — and
three short lines are the most that survives that size. The mark is the one thing that
earns a place beside them: at forty pixels the text has already stopped being readable and
the magenta disc has not, so what a stranger recognises in a forwarded chat is a shape and
a colour, not a handle. That is the whole argument for it — recognition at the size where
the words fail — and it is why the mark is placed and sized in that order of priority: the
text keeps its own size and spacing, and the mark takes the room left over.

**Why it is the shipped avatar and not geometry re-drawn here.** ``brand/`` builds every
asset from one set of constants — bar width, the 3:5:4 rhythm, the flame ratio — so the
files stay consistent with each other by construction. A Pillow re-implementation of those
paths would be a fourth copy that no constant reaches, drifting from the bot's actual
profile picture one redraw at a time and showing a stranger two different logos for the
same bot. :data:`_LOGO_RESOURCE` is a byte-for-byte copy of ``brand/avatar-telegram.png``
instead, and ``test_cover.py`` asserts the two files are identical so a redraw that forgets
this copy fails a test rather than a customer.

**The three Telegram thumbnail constraints this is built to.** ``sendAudio``'s ``thumbnail``
is accepted only as a JPEG, only under 200 kB, and only with both sides at most 320 px; and
it is ignored entirely unless the file is uploaded multipart (an ``FSInputFile`` is, a
``file_id`` or URL is not). Telegram enforces none of this loudly — a thumbnail it dislikes
is dropped and the send still returns 200 — so :data:`COVER_MAX_BYTES` is checked here,
where a violation is an ``Err`` somebody can read, rather than discovered as an artwork-less
message in production.

Everything here is best-effort by construction: a watermark is worth less than the song, so
:func:`render_cover` returns ``Err`` and never raises, and its caller ships a kit with no
cover rather than failing an order over a picture. The mark is one degree softer still — a
cover with the text and no mark is worth much more than no cover at all, so a missing or
unreadable logo resource is logged and drawn around rather than failed on.
"""

from __future__ import annotations

import importlib.resources as resources
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from bayram.audio.tempfiles import publish, scratch_dir
from bayram.contracts import Result, err, ok
from bayram.errors import StorageError
from bayram.logging import get_logger
from bayram.watermark import COVER_LINES

__all__ = ["COVER_SIZE", "COVER_MIME", "COVER_SUFFIX", "COVER_MAX_BYTES", "render_cover"]

_LOG = get_logger(__name__)

#: Both sides, in pixels. Telegram's own ceiling for a thumbnail, so a larger image would be
#: re-scaled by the client at best and dropped at worst; a smaller one would waste the only
#: legibility we have.
COVER_SIZE: Final[int] = 320
#: The only format ``sendAudio``'s ``thumbnail`` accepts. Not negotiable and not inferred
#: from the filename anywhere in this codebase — it is passed as the asset's mime.
COVER_MIME: Final[str] = "image/jpeg"
#: Kept next to the mime because the two must agree: ffmpeg picks its muxer from the
#: destination suffix in the branding pass, and Telegram keys off the filename as well.
COVER_SUFFIX: Final[str] = ".jpg"
#: Telegram's thumbnail size limit. A 320x320 two-tone JPEG lands around 5 kB, so this is
#: never close — which is exactly why it is worth checking: the only way to approach it is a
#: caller passing a ``size`` this module was not designed for, and that caller deserves an
#: error rather than a silently artwork-less message.
COVER_MAX_BYTES: Final[int] = 200_000

#: Pure black ground and pure white ink: 21:1, the highest contrast ratio sRGB can express.
#: Written as tuples rather than ``"black"``/``"white"`` because the mode is RGB and a named
#: colour is one more thing that has to be looked up to know what was meant.
_GROUND: Final[tuple[int, int, int]] = (0, 0, 0)
_INK: Final[tuple[int, int, int]] = (255, 255, 255)
#: Glyph height as a fraction of the image side. A ninth gives a 35 px glyph at 320 px, which
#: sets ``@bayram_uzbot`` — the longest of :data:`~bayram.watermark.COVER_LINES` at thirteen
#: characters — 260 px wide, so it clears each edge by 30 px. Tuning it is a layout change,
#: not a preference, and the hazard is *below* this number: the divisor divides, so a
#: SMALLER one means a larger glyph, and at 8 the handle is 292 px and all but touching the
#: edges. Pillow will happily draw the overflow off the canvas without complaining.
#:
#: The margin used to be 66 px, when the handle was ``@hbduzbot`` at nine characters. The
#: 2026-09-10 rename spent more than half of that slack, so a longer handle than this one
#: needs the divisor revisited rather than assumed.
_FONT_DIVISOR: Final[int] = 9

#: The bot's profile picture, as package data. A byte-for-byte copy of
#: ``brand/avatar-telegram.png`` — see the module docstring for why it is copied rather than
#: re-drawn, and ``test_cover.py`` for the test that keeps the two in step.
_LOGO_PACKAGE: Final[str] = "bayram.audio.assets"
_LOGO_RESOURCE: Final[str] = "logo.png"
#: The mark's side as a fraction of the image side. At 0.34 the 320 px cover carries a
#: 108 px disc, which is 13 px at Telegram's forty-pixel thumbnail — still a recognisable
#: disc, and still small enough to leave the three text lines their own size. Raising it
#: does not make the mark clearer at thumbnail size, it only takes width from the text.
_LOGO_FRACTION: Final[float] = 0.34
#: Gap between the mark's bottom edge and the top of the text block, as a fraction of the
#: image side. Smaller and the disc crowds the first line; larger and the two read as two
#: unrelated objects rather than one stacked block.
_LOGO_GAP_FRACTION: Final[float] = 0.055
#: Baseline-to-baseline spacing as a multiple of the glyph height. 1.4 leaves the block
#: airy enough to read at thumbnail size without pushing three lines past the canvas.
_LINE_SPACING: Final[float] = 1.4
#: JPEG knobs. Quality 90 is far above what two-tone text needs and costs nothing at this
#: size; ``optimize`` re-runs the Huffman tables, which is deterministic and shaves bytes.
_JPEG_QUALITY: Final[int] = 90

_OPERATION: Final[str] = "cover.render"
_STAGED_STEM: Final[str] = "cover"


def render_cover(
    destination: Path,
    *,
    lines: Sequence[str] = COVER_LINES,
    size: int = COVER_SIZE,
) -> Result[Path]:
    """Draw the cover at ``destination``. Returns ``Err`` on any failure and NEVER raises.

    Staged through :func:`bayram.audio.tempfiles.scratch_dir` and published with an atomic
    move, exactly as ``processor.normalize_loudness`` does, for the same reason: the
    workspace is read by the archival step and by the admin panel, and a half-written JPEG
    under the final name is indistinguishable from a finished one until something tries to
    decode it. A crash mid-``save`` must leave no file at that path at all.

    The output is byte-for-byte deterministic for the same arguments. That is load-bearing
    rather than tidy: the caller hashes this file into ``GeneratedAsset.sha256``, and a
    re-run of the same order has to produce the same digest or idempotency stops meaning
    anything.

    Every exception is caught, including Pillow's own — it raises ``OSError`` subclasses for
    a refused write but plain ``ValueError`` for an unencodable mode, and the set is not
    something this module should have to track. A cover is worth less than a song, so the
    contract callers rely on is "this returns, whatever happens".
    """
    try:
        with scratch_dir(destination) as scratch:
            staged = scratch / f"{_STAGED_STEM}{destination.suffix or COVER_SUFFIX}"
            _draw(staged, lines=tuple(lines), size=size)
            written = staged.stat().st_size
            if written > COVER_MAX_BYTES:
                return err(_oversized(destination, written=written, size=size))
            publish(staged, destination)
    # Broad on purpose; see the docstring. Pillow raises OSError for a refused write and a
    # bare ValueError for an unencodable mode, and enumerating that set here would mean
    # this module tracking another library's exception taxonomy in order to keep a promise
    # ("never raises") that a broad catch keeps unconditionally.
    except Exception as exc:
        _LOG.warning(
            "audio.cover.render_failed",
            extra={"destination": str(destination), "reason": str(exc)},
        )
        return err(
            StorageError(
                f"{_OPERATION}: the cover could not be drawn at {destination}: {exc}",
                context={"operation": _OPERATION, "destination": str(destination)},
                cause=exc,
            )
        )
    return ok(destination)


def _logo(side: int) -> Image.Image | None:
    """The mark at ``side``x``side`` pixels, or ``None`` if it cannot be read.

    ``None`` rather than an exception because a cover carrying the text and no mark is
    worth far more than no cover at all: the caller draws the text block centred in the
    whole canvas instead, which is exactly the picture this module shipped before the mark
    existed. The only ways to get here are a broken wheel or a corrupt resource, and both
    deserve a log line rather than a customer's missing artwork.

    ``LANCZOS`` is named rather than left to default because the result is hashed into
    ``GeneratedAsset.sha256``: the filter has to be a decision this file records, not
    whatever Pillow's default happens to be in the installed version.
    """
    try:
        source = resources.files(_LOGO_PACKAGE).joinpath(_LOGO_RESOURCE)
        with resources.as_file(source) as path, Image.open(path) as opened:
            # Converted and resized INSIDE the context: `Image.open` is lazy and the file
            # object is closed on exit, so deferring either would read a closed handle.
            # Annotated because Pillow's `resize` is typed as returning `Any`, and an
            # unchecked `Any` flowing out of here is how a None-check silently stops
            # meaning anything at the call site.
            resized: Image.Image = opened.convert("RGBA").resize(
                (side, side), Image.Resampling.LANCZOS
            )
            return resized
    except Exception as exc:
        _LOG.warning(
            "audio.cover.logo_unavailable",
            extra={"resource": f"{_LOGO_PACKAGE}/{_LOGO_RESOURCE}", "reason": str(exc)},
        )
        return None


def _draw(staged: Path, *, lines: tuple[str, ...], size: int) -> None:
    """Render the mark and the text block into ``staged``. Raises; the caller owns the catch.

    The mark and the lines are laid out as ONE stacked block, centred as a whole rather
    than each part being placed independently. Three lines centred one at a time drift
    apart as the glyph heights differ, and a mark centred separately from the text it
    belongs to reads as two objects that happen to share a canvas.

    The text keeps the size and spacing it had before the mark existed, and the mark takes
    the room left over. That order is the module docstring's contrast argument expressed as
    code: the words are what the picture has to say, and the disc is what makes it
    recognisable once the words are too small to read.
    """
    image = Image.new("RGB", (size, size), _GROUND)
    canvas = ImageDraw.Draw(image)
    glyph = size / _FONT_DIVISOR
    font = ImageFont.load_default(size=int(glyph))
    step = glyph * _LINE_SPACING
    # The text block's height is the gaps BETWEEN the lines plus one line, not one step per
    # line: counting a trailing gap pushes the whole block up by half a line spacing, which
    # at 320 pixels is a visible, and entirely avoidable, lopsided margin.
    text_height = step * (len(lines) - 1) + glyph

    side = int(size * _LOGO_FRACTION)
    gap = size * _LOGO_GAP_FRACTION
    mark = _logo(side) if side > 0 else None
    # Everything below measures from one total height, so the no-mark case is not a special
    # layout — it is this same arithmetic with a zero-height mark and no gap, which is why
    # losing the resource degrades to the old picture exactly rather than approximately.
    stack = text_height if mark is None else side + gap + text_height
    top = (size - stack) / 2

    if mark is not None:
        # `mark` is the mask as well as the source: the disc has transparent corners, and
        # pasting without it would stamp a black square's worth of JPEG ringing around it.
        image.paste(mark, (int((size - side) / 2), int(top)), mark)
        top += side + gap

    for index, line in enumerate(lines):
        # ``mt`` anchors the middle of the top edge of the text, which is what makes the
        # horizontal centring exact rather than an estimate from a measured bounding box.
        canvas.text((size / 2, top + step * index), line, font=font, fill=_INK, anchor="mt")
    image.save(staged, format="JPEG", quality=_JPEG_QUALITY, optimize=True)


def _oversized(destination: Path, *, written: int, size: int) -> StorageError:
    """Refuse a cover Telegram would drop, rather than shipping an invisible thumbnail."""
    _LOG.warning(
        "audio.cover.too_large",
        extra={"destination": str(destination), "bytes": written, "side_px": size},
    )
    return StorageError(
        f"{_OPERATION}: the cover is {written} bytes, over Telegram's {COVER_MAX_BYTES}-byte "
        "thumbnail limit, and would be dropped silently",
        context={"operation": _OPERATION, "bytes": written, "side_px": size},
    )
