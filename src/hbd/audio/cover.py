"""The generated cover art: white text on black, 320x320, one JPEG per order.

**Why this file draws the picture instead of ffmpeg.** ffmpeg can composite text with the
``drawtext`` filter, and this host's ffmpeg cannot: the build has no libfreetype, so
``ffmpeg -filters | grep drawtext`` returns nothing at all. There is no Dockerfile pinning
the deployed build either, so "the encoder will draw it" is a bet on a capability nothing
checks at boot — and the failure mode is not an error, it is a filter-graph rejection at
render time on a paying customer's order. Pillow moves the question to install time, where
a missing dependency is a build failure rather than a lost song.

**Why the design is maximal contrast rather than branded.** The picture exists to be
legible as a forty-pixel square in a forwarded message on somebody else's phone, seen for
about a second, at whatever brightness that phone happens to be at. Pure white on pure
black is a 21:1 contrast ratio — the highest sRGB can express — and three short lines are
the most that survives that size. Anything prettier is a picture nobody can read.

**The three Telegram thumbnail constraints this is built to.** ``sendAudio``'s ``thumbnail``
is accepted only as a JPEG, only under 200 kB, and only with both sides at most 320 px; and
it is ignored entirely unless the file is uploaded multipart (an ``FSInputFile`` is, a
``file_id`` or URL is not). Telegram enforces none of this loudly — a thumbnail it dislikes
is dropped and the send still returns 200 — so :data:`COVER_MAX_BYTES` is checked here,
where a violation is an ``Err`` somebody can read, rather than discovered as an artwork-less
message in production.

Everything here is best-effort by construction: a watermark is worth less than the song, so
:func:`render_cover` returns ``Err`` and never raises, and its caller ships a kit with no
cover rather than failing an order over a picture.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from hbd.audio.tempfiles import publish, scratch_dir
from hbd.contracts import Result, err, ok
from hbd.errors import StorageError
from hbd.logging import get_logger
from hbd.watermark import COVER_LINES

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
#: Glyph height as a fraction of the image side. A ninth is what makes ``@hbduzbot`` — the
#: longest of :data:`~hbd.watermark.COVER_LINES` at nine characters — fill the width without
#: touching the edges. Tuning it is a layout change, not a preference: a larger divisor
#: makes the longest line overflow, and Pillow will happily draw it off the canvas.
_FONT_DIVISOR: Final[int] = 9
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

    Staged through :func:`hbd.audio.tempfiles.scratch_dir` and published with an atomic
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


def _draw(staged: Path, *, lines: tuple[str, ...], size: int) -> None:
    """Render the text block into ``staged``. Raises; :func:`render_cover` owns the catch.

    The block is centred as a whole rather than each line being placed independently,
    because three lines centred one at a time drift apart as the glyph heights differ and
    the result reads as a mistake at thumbnail size.
    """
    image = Image.new("RGB", (size, size), _GROUND)
    canvas = ImageDraw.Draw(image)
    glyph = size / _FONT_DIVISOR
    font = ImageFont.load_default(size=int(glyph))
    step = glyph * _LINE_SPACING
    # The block's height is the gaps BETWEEN the lines plus one line, not one step per
    # line: counting a trailing gap pushes the whole block up by half a line spacing, which
    # at 320 pixels is a visible, and entirely avoidable, lopsided margin.
    top = (size - (step * (len(lines) - 1) + glyph)) / 2
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
