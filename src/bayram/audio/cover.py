"""The generated cover art: the bot's artwork, 320x320, one JPEG per order.

**Why this file makes the picture instead of ffmpeg.** ffmpeg can composite images and text,
and this host's ffmpeg is not trusted to: the build has no libfreetype, so
``ffmpeg -filters | grep drawtext`` returns nothing at all, and there is no Dockerfile
pinning the deployed build. "The encoder will draw it" is a bet on a capability nothing
checks at boot, whose failure mode is not an error but a filter-graph rejection at render
time on a paying customer's order. Pillow moves the question to install time, where a
missing dependency is a build failure rather than a lost song.

**The cover is one image, shipped whole, and it is deliberately not composed here.** It
already carries the handle, the product's name and its own typography, set by whoever draws
``brand/Logo-Bot.png``. Drawing text over it in Pillow would put two typefaces on one
picture and re-state a handle the artwork states better — and it would make the brand's own
file a background rather than the deliverable. So this module resizes and encodes; it does
not lay anything out. Changing the cover means replacing the PNG, with no code change and
no release note about fonts.

**What was here before, and why it went.** Until 2026-09-11 this drew three white lines on
black — ``GENERATE`` / ``YOURS AT`` / the handle — chosen for a 21:1 contrast ratio because
a cover is read as a forty-pixel square in a forwarded chat. That reasoning still holds and
the artwork answers it differently: at forty pixels the text was never legible either, and
what survives the size is a shape and a colour, which is what the artwork is. The handle is
still carried three other ways — the ID3 tags, the caption and the archived lyric sheet —
so dropping it from the picture costs the watermark nothing (:mod:`bayram.watermark`).

**Why it is a copy of the brand file rather than a reference to it.** The application ships
as a wheel and ``brand/`` is not packaged, so the bytes have to live under
:data:`_COVER_PACKAGE`. It is a byte-for-byte copy of ``brand/Logo-Bot.png``, and
``test_cover.py`` asserts the two are identical — a redraw that forgets to re-copy fails a
test rather than shipping a stranger last month's artwork. The full 1254x1254 source is
shipped rather than a pre-scaled cut so that byte-identity is the test, instead of a
resampling result that would differ between Pillow versions.

**The three Telegram thumbnail constraints this is built to.** ``sendAudio``'s ``thumbnail``
is accepted only as a JPEG, only under 200 kB, and only with both sides at most 320 px; and
it is ignored entirely unless the file is uploaded multipart (an ``FSInputFile`` is, a
``file_id`` or URL is not). Telegram enforces none of this loudly — a thumbnail it dislikes
is dropped and the send still returns 200 — so :data:`COVER_MAX_BYTES` is checked here,
where a violation is an ``Err`` somebody can read, rather than discovered as an artwork-less
message in production.

Everything here is best-effort by construction: a cover is worth less than the song, so
:func:`render_cover` returns ``Err`` and never raises, and its caller ships a kit with no
cover rather than failing an order over a picture. There is no degraded picture any more —
the artwork is the whole cover, so an unreadable resource means no cover, not a plainer one.
"""

from __future__ import annotations

import importlib.resources as resources
from pathlib import Path
from typing import Final

from PIL import Image

from bayram.audio.tempfiles import publish, scratch_dir
from bayram.contracts import Result, err, ok
from bayram.errors import StorageError
from bayram.logging import get_logger

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

#: The cover artwork, as package data: a byte-for-byte copy of ``brand/Logo-Bot.png``. See
#: the module docstring for why it is copied rather than referenced, and ``test_cover.py``
#: for the test that keeps the two in step.
_COVER_PACKAGE: Final[str] = "bayram.audio.assets"
_COVER_RESOURCE: Final[str] = "cover.png"
#: JPEG knobs. The artwork is a photographic gradient rather than flat colour, so quality is
#: doing real work here in a way it was not when this drew two-tone text: below about 85 the
#: blue ground bands visibly at 320 px. ``optimize`` re-runs the Huffman tables, which is
#: deterministic and shaves bytes.
_JPEG_QUALITY: Final[int] = 90

_OPERATION: Final[str] = "cover.render"
_STAGED_STEM: Final[str] = "cover"


def render_cover(destination: Path, *, size: int = COVER_SIZE) -> Result[Path]:
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
            _draw(staged, size=size)
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


def _draw(staged: Path, *, size: int) -> None:
    """Write the artwork to ``staged`` at ``size``x``size``. Raises; the caller owns the catch.

    Three deliberate choices, all of which the digest depends on.

    ``LANCZOS`` is named rather than left to Pillow's default, because the result is hashed
    into ``GeneratedAsset.sha256``: the resampling filter has to be a decision this file
    records, not whatever the installed version happens to prefer.

    The centre crop is not currently doing anything — ``brand/Logo-Bot.png`` is square, so
    the crop box is the whole image — and it is here for the day somebody replaces that file
    with a rectangle. Without it a non-square source would be *stretched* to fit, which
    distorts a face and a wordmark and would ship looking like a bug rather than a swap.

    ``convert("RGB")`` is unconditional because JPEG has no alpha channel: Pillow raises
    ``OSError`` saving an RGBA image as JPEG, and the brand file gaining transparency one
    day is exactly the sort of change nobody would think to mention.
    """
    source = resources.files(_COVER_PACKAGE).joinpath(_COVER_RESOURCE)
    with resources.as_file(source) as path, Image.open(path) as opened:
        # Everything happens inside the context: `Image.open` is lazy and the file object is
        # closed on exit, so deferring any of it would read from a closed handle.
        side = min(opened.width, opened.height)
        left = (opened.width - side) // 2
        top = (opened.height - side) // 2
        square = opened.crop((left, top, left + side, top + side))
        cover = square.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
        cover.save(staged, format="JPEG", quality=_JPEG_QUALITY, optimize=True)


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
