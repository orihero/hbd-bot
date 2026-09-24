"""The collage: several reference photos, one input at the target size (IMAGE_VIDEO_SPEC §4.4).

The local gateway takes one ``image`` string (§4.2), so when a customer sends more photos
than the backend takes references (O6, D21) they are laid out on one canvas and that canvas
is the input — the img2img source for an image, the i2v start frame for a video (§1.3). When
``capabilities().max_reference_images >= len(refs)`` the originals go natively and this module
is not called: :func:`needs_collage` is that decision, in one place.

What the builder promises, each a line of §4.4:

* **every photo is EXIF-transposed and then stripped.** A phone photo is stored sideways with
  an Orientation tag; honouring the tag is what makes it upright, and the tag — with the GPS,
  camera and timestamp tags beside it — never reaches the canvas, because the canvas is a new
  image that inherits no metadata from its sources and is saved with none;
* **the canvas is exactly the target size** (§1.3's per-aspect sizes; the gateway ignores
  input size and every size is sent explicitly, so a collage at any other size would be
  rescaled by a model we do not control);
* **layout by count** — 1 fit; 2 side-by-side on a landscape or square canvas, stacked on a
  portrait one; 3 one large plus two small; 4 a 2×2 grid — with 2 px neutral gutters, each
  photo fitted whole (never cropped: cropping would cut a face out of a reference) and
  letterboxed on a blurred copy of the first photo;
* **JPEG q90**, stored as a ``collage`` input and screened like an upload (L2, §6).

A multi-frame image (animated WebP, APNG, a GIF sent as a document) is refused rather than
flattened to its first frame: §3.3 ``media_screen`` rejects those before a collage is ever
built, and this module refuses them again so the collage never becomes the one place an
unscreened frame could hide.

**Nothing here raises.** :func:`build_collage` returns ``Err`` — a :class:`ValidationError`
for a photo we will not use (the customer's fault, terminal), a :class:`StorageError` for a
write that failed (ours) — and writes through a scratch directory with an atomic move, so a
crash leaves no half-written JPEG under the final name. The output is deterministic for the
same inputs, which is what lets the stage record its ``sha256`` and a re-run agree with it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from PIL import Image, ImageFilter, ImageOps

from bayram.audio.tempfiles import publish, scratch_dir
from bayram.contracts import Result, err, ok
from bayram.db.enums import MediaAspect
from bayram.errors import StorageError, ValidationError
from bayram.logging import get_logger
from bayram.media.contracts import MediaKindName

__all__ = [
    "COLLAGE_MIME",
    "COLLAGE_SUFFIX",
    "COLLAGE_JPEG_QUALITY",
    "MAX_COLLAGE_PHOTOS",
    "GUTTER_PX",
    "IMAGE_SIZES",
    "VIDEO_SIZES",
    "Collage",
    "Cell",
    "target_size",
    "needs_collage",
    "layout_cells",
    "build_collage",
]

_LOG = get_logger(__name__)

COLLAGE_MIME: Final[str] = "image/jpeg"
COLLAGE_SUFFIX: Final[str] = ".jpg"
#: §4.4. Named rather than left to Pillow's default because the output is hashed.
COLLAGE_JPEG_QUALITY: Final[int] = 90
#: The layouts §4.4 defines stop at four, and so does ``media_max_reference_images``.
MAX_COLLAGE_PHOTOS: Final[int] = 4
#: §4.4: "2 px neutral gutters".
GUTTER_PX: Final[int] = 2
#: Mid grey: neutral against any photo, and the matte a transparent PNG is flattened onto.
_NEUTRAL: Final[tuple[int, int, int]] = (128, 128, 128)

#: The generation sizes per aspect (§1.3), all multiples of 16. Image: flux2 presets; video:
#: Wan at 720p. The collage for a job is built at its job's size, so the start frame of a
#: video and the img2img source of an image are never rescaled by the gateway.
IMAGE_SIZES: Final[Mapping[MediaAspect, tuple[int, int]]] = MappingProxyType(
    {
        MediaAspect.PORTRAIT: (768, 1344),
        MediaAspect.SQUARE: (1024, 1024),
        MediaAspect.LANDSCAPE: (1344, 768),
    }
)
VIDEO_SIZES: Final[Mapping[MediaAspect, tuple[int, int]]] = MappingProxyType(
    {
        MediaAspect.PORTRAIT: (720, 1280),
        MediaAspect.SQUARE: (960, 960),
        MediaAspect.LANDSCAPE: (1280, 720),
    }
)

#: A Telegram photo is at most 2560 px on its long side; a document can be anything. Well
#: under Pillow's own bomb threshold (~179 Mpx raises), so a crafted header is refused from
#: its declared size before a single pixel is decoded — the host has ~831 MiB free (§0.1).
_MAX_SOURCE_PIXELS: Final[int] = 40_000_000
#: The blur on the letterbox ground, as a share of the canvas's long side: enough that the
#: first photo reads as colour, not as a second copy of the subject.
_BLUR_SHARE: Final[float] = 1 / 40
#: The ground is dimmed toward black so the fitted photos stand forward of it.
_GROUND_DIM: Final[float] = 0.7

_OPERATION: Final[str] = "media.collage"
_STAGED_STEM: Final[str] = "collage"
_HASH_CHUNK: Final[int] = 1 << 16


@dataclass(frozen=True, slots=True)
class Cell:
    """One photo's box on the canvas, in pixels: ``(left, top)`` and its size."""

    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class Collage:
    """A finished collage on disk: what the stage records as the ``collage`` input (§3.2.2)."""

    path: Path
    mime: str
    width: int
    height: int
    size_bytes: int
    sha256: str
    photo_count: int


def target_size(kind: MediaKindName, aspect: MediaAspect) -> tuple[int, int]:
    """The ``(width, height)`` a job of ``kind`` generates at for ``aspect`` (§1.3)."""
    sizes = IMAGE_SIZES if kind == "image" else VIDEO_SIZES
    return sizes[aspect]


def needs_collage(photo_count: int, max_reference_images: int) -> bool:
    """True when the photos must be composited: more of them than the backend takes (§4.4).

    One photo on a 1-ref backend goes natively; no photos is a text-only request.
    """
    return photo_count > max(max_reference_images, 1)


def _split(length: int, parts: int) -> list[tuple[int, int]]:
    """Cut ``length`` into ``parts`` spans with a gutter between each: ``(start, size)``."""
    usable = length - GUTTER_PX * (parts - 1)
    base, extra = divmod(usable, parts)
    spans: list[tuple[int, int]] = []
    start = 0
    for index in range(parts):
        size = base + (1 if index < extra else 0)
        spans.append((start, size))
        start += size + GUTTER_PX
    return spans


def layout_cells(count: int, width: int, height: int) -> tuple[Cell, ...]:
    """The boxes ``count`` photos occupy on a ``width``×``height`` canvas (§4.4).

    The long axis decides the orientation: a portrait canvas stacks what a landscape or
    square one sets side by side, so every cell keeps a usable shape at 9:16 and at 16:9.
    """
    if not 1 <= count <= MAX_COLLAGE_PHOTOS:
        raise ValueError(f"a collage lays out 1..{MAX_COLLAGE_PHOTOS} photos, not {count}")
    portrait = height > width
    if count == 1:
        return (Cell(0, 0, width, height),)
    if count == 2:
        if portrait:
            return tuple(Cell(0, top, width, size) for top, size in _split(height, 2))
        return tuple(Cell(left, 0, size, height) for left, size in _split(width, 2))
    if count == 3:
        # The first photo is the large one: it is also the ground, so it is the one the
        # customer sent first and most likely meant as the subject.
        if portrait:
            (top_start, top_size), (bottom_start, bottom_size) = _split(height, 2)
            large = Cell(0, top_start, width, top_size)
            smalls = tuple(
                Cell(left, bottom_start, size, bottom_size) for left, size in _split(width, 2)
            )
        else:
            (left_start, left_size), (right_start, right_size) = _split(width, 2)
            large = Cell(left_start, 0, left_size, height)
            smalls = tuple(
                Cell(right_start, top, right_size, size) for top, size in _split(height, 2)
            )
        return (large, *smalls)
    rows = _split(height, 2)
    columns = _split(width, 2)
    return tuple(Cell(left, top, cw, ch) for top, ch in rows for left, cw in columns)


def build_collage(
    photos: Sequence[Path], destination: Path, *, width: int, height: int
) -> Result[Collage]:
    """Composite ``photos`` into one ``width``×``height`` JPEG at ``destination``. Never raises.

    ``photos`` are the screened storage copies (§3.3 "screened bytes only"), in the order the
    customer sent them. Returns ``Err(ValidationError)`` for a photo we will not use and
    ``Err(StorageError)`` when the canvas could not be written.
    """
    count = len(photos)
    if not 1 <= count <= MAX_COLLAGE_PHOTOS:
        return err(
            ValidationError(
                f"{_OPERATION}: {count} photos; a collage takes 1..{MAX_COLLAGE_PHOTOS}",
                context={"operation": _OPERATION, "photo_count": count},
            )
        )
    if width <= 0 or height <= 0:
        return err(
            ValidationError(
                f"{_OPERATION}: target size {width}x{height} is not a canvas",
                context={"operation": _OPERATION, "width": width, "height": height},
            )
        )

    decoded: list[Image.Image] = []
    for index, photo in enumerate(photos):
        loaded = _load_photo(photo, index=index, long_side=max(width, height))
        if isinstance(loaded, ValidationError):
            return err(loaded)
        decoded.append(loaded)

    try:
        canvas = _compose(decoded, width=width, height=height)
        with scratch_dir(destination) as scratch:
            staged = scratch / f"{_STAGED_STEM}{COLLAGE_SUFFIX}"
            # A fresh canvas carries no ``info`` from its sources, and nothing is passed for
            # ``exif``/``icc_profile``: the file has no metadata segment to strip.
            canvas.save(staged, format="JPEG", quality=COLLAGE_JPEG_QUALITY, optimize=True)
            size_bytes = staged.stat().st_size
            digest = _sha256(staged)
            publish(staged, destination)
    # Broad for the same reason as ``audio.cover``: Pillow raises OSError for a refused write
    # and ValueError for an unencodable mode, and the promise here is "returns, always".
    except Exception as exc:
        _LOG.warning(
            "media.collage.write_failed",
            extra={"destination": str(destination), "reason": type(exc).__name__},
        )
        return err(
            StorageError(
                f"{_OPERATION}: the collage could not be written at {destination}: {exc}",
                context={"operation": _OPERATION, "destination": str(destination)},
                cause=exc,
            )
        )
    finally:
        for image in decoded:
            image.close()

    return ok(
        Collage(
            path=destination,
            mime=COLLAGE_MIME,
            width=width,
            height=height,
            size_bytes=size_bytes,
            sha256=digest,
            photo_count=count,
        )
    )


def _refused(index: int, reason: str, *, cause: BaseException | None = None) -> ValidationError:
    # The photo's path is operator context only; the reason never quotes the bytes.
    return ValidationError(
        f"{_OPERATION}: photo {index} refused: {reason}",
        context={"operation": _OPERATION, "photo_index": index, "reason": reason},
        cause=cause,
    )


def _load_photo(path: Path, *, index: int, long_side: int) -> Image.Image | ValidationError:
    """Decode one photo upright, as plain RGB with no metadata, or say why not."""
    try:
        with Image.open(path) as opened:
            if getattr(opened, "n_frames", 1) > 1:
                return _refused(index, "multi_frame")
            if opened.width * opened.height > _MAX_SOURCE_PIXELS:
                return _refused(index, "too_large")
            # JPEG can decode at 1/2, 1/4, 1/8 scale straight from the DCT: a 12 Mpx phone
            # photo never has to exist at full size to fill a 1344 px canvas. A square request
            # because the orientation is not applied yet.
            opened.draft("RGB", (long_side, long_side))
            upright = ImageOps.exif_transpose(opened)
            return _flatten(upright)
    except Exception as exc:
        # Unreadable, truncated, not an image, or Pillow's own DecompressionBombError.
        return _refused(index, "undecodable", cause=exc)


def _flatten(image: Image.Image) -> Image.Image:
    """RGB with any transparency matted onto neutral grey; a new image with empty ``info``."""
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        matte = Image.new("RGBA", rgba.size, (*_NEUTRAL, 255))
        matte.alpha_composite(rgba)
        flat = matte.convert("RGB")
    else:
        flat = image.convert("RGB")
    flat.info.clear()
    return flat


def _fit(image: Image.Image, width: int, height: int) -> Image.Image:
    """Scale to fit whole inside ``width``×``height``, aspect kept (never cropped)."""
    scale = min(width / image.width, height / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def _ground(first: Image.Image, width: int, height: int) -> Image.Image:
    """The letterbox: the first photo cover-filled, blurred and dimmed."""
    covered = ImageOps.fit(first, (width, height), Image.Resampling.BILINEAR)
    radius = max(2.0, max(width, height) * _BLUR_SHARE)
    blurred = covered.filter(ImageFilter.GaussianBlur(radius))
    black = Image.new("RGB", (width, height), (0, 0, 0))
    return Image.blend(black, blurred, _GROUND_DIM)


def _compose(photos: Sequence[Image.Image], *, width: int, height: int) -> Image.Image:
    canvas = _ground(photos[0], width, height)
    cells = layout_cells(len(photos), width, height)
    if len(cells) > 1:
        # Paint the whole canvas's gutters first; each cell then covers its own box with the
        # ground, so only the 2 px lines between cells stay neutral.
        ground = canvas
        canvas = Image.new("RGB", (width, height), _NEUTRAL)
        for cell in cells:
            box = (cell.left, cell.top, cell.left + cell.width, cell.top + cell.height)
            canvas.paste(ground.crop(box), box[:2])
    for photo, cell in zip(photos, cells, strict=True):
        fitted = _fit(photo, cell.width, cell.height)
        left = cell.left + (cell.width - fitted.width) // 2
        top = cell.top + (cell.height - fitted.height) // 2
        canvas.paste(fitted, (left, top))
    return canvas


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()
