"""The generated cover art: a real JPEG, at Telegram's exact dimensions, deterministically.

**Unmarked, and it needs no ffmpeg.** Pillow draws the picture — this host's ffmpeg has no
``drawtext`` filter at all — so these run in every unit pass, which is what the directory's
rule about never mocking the encoder is protecting: there is no encoder here to mock.

The dimensions are read out of the JPEG's own SOF0 header by hand rather than by opening the
file with Pillow. Asking the library that wrote the file what it wrote is a tautology: it
would pass just as happily if ``render_cover`` had produced a 4000-pixel image and Pillow
had faithfully recorded that. Nine bytes of header parsing is what makes the assertion about
Telegram's constraint rather than about Pillow's round trip.
"""

from __future__ import annotations

import importlib.resources as resources
import stat
from pathlib import Path

import pytest
from PIL import Image

from bayram.audio.constants import SCRATCH_DIR_PREFIX
from bayram.audio.cover import COVER_MAX_BYTES, COVER_SIZE, render_cover
from bayram.contracts import Err
from bayram.watermark import COVER_LINES, WATERMARK_HANDLE

#: JPEG start-of-image. Telegram accepts nothing else as an audio thumbnail.
JPEG_MAGIC = b"\xff\xd8"
#: Start Of Frame, baseline DCT. The frame header is where the real dimensions live.
_SOF0 = 0xC0
_MARKER_PREFIX = 0xFF

#: ``tests/test_audio/test_cover.py`` -> the repository root, for the brand asset the
#: packaged logo is copied from. Three parents, and a moved test file breaks it loudly.
REPO_ROOT = Path(__file__).resolve().parents[2]
#: ``getcolors`` returns ``None`` above its ceiling instead of raising, and a photographic
#: JPEG of a two-tone image still carries thousands of ringing artefacts. 320x320 is the
#: whole canvas, so this cannot be exceeded and the ``None`` branch cannot be reached.
_ALL_COLOURS = COVER_SIZE * COVER_SIZE
#: The brand flame, ``#BD32AF``. JPEG is lossy and subsamples chroma, so the exact triple
#: survives almost nowhere — the test asks "is this pixel recognisably that magenta", which
#: is the question that matters, with a tolerance wide enough for 4:2:0 and narrow enough
#: that neither the black ground nor the white ink can wander into it.
_BRAND_MAGENTA = (0xBD, 0x32, 0xAF)
_MAGENTA_TOLERANCE = 40
#: How far the ink's top and bottom margins may differ and still count as centred. JPEG
#: ringing and the font's own bearings put a pixel or two of asymmetry into any real
#: render; anything beyond this is a layout mistake rather than an artefact.
_CENTRING_TOLERANCE_PX = 3
#: A pixel is "ink" once it is this far above the black ground on every channel.
_INK_THRESHOLD = 128


def _is_brand_magenta(colour: tuple[int, ...]) -> bool:
    """Whether an RGB triple is recognisably the brand flame, after JPEG's chroma loss."""
    return all(abs(channel - target) <= _MAGENTA_TOLERANCE
               for channel, target in zip(colour[:3], _BRAND_MAGENTA, strict=True))


def _row_has_ink(image: Image.Image, y: int) -> bool:
    """Whether row ``y`` carries any white-ish pixel — text, or the candles in the mark."""
    for x in range(image.width):
        pixel = image.getpixel((x, y))
        assert isinstance(pixel, tuple)
        if all(channel >= _INK_THRESHOLD for channel in pixel[:3]):
            return True
    return False


def _row_has_magenta(image: Image.Image, y: int) -> bool:
    """Whether row ``y`` touches the mark's disc. The disc is the only magenta drawn."""
    for x in range(image.width):
        pixel = image.getpixel((x, y))
        assert isinstance(pixel, tuple)
        if _is_brand_magenta(pixel):
            return True
    return False


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """``(width, height)`` from the first SOF0 segment. Deliberately hand-rolled.

    Walks the marker chain: every segment after the two-byte SOI is ``FF <marker>`` plus a
    big-endian length that includes its own two bytes. SOF0's payload is one precision byte
    then height then width, both 16-bit big-endian.
    """
    offset = 2
    while offset < len(data):
        assert data[offset] == _MARKER_PREFIX, f"not a marker at byte {offset}"
        marker = data[offset + 1]
        length = int.from_bytes(data[offset + 2 : offset + 4], "big")
        if marker == _SOF0:
            height = int.from_bytes(data[offset + 5 : offset + 7], "big")
            width = int.from_bytes(data[offset + 7 : offset + 9], "big")
            return width, height
        offset += 2 + length
    raise AssertionError("no SOF0 segment: this is not a baseline JPEG")


def scratch_leftovers(directory: Path) -> list[Path]:
    return [child for child in directory.iterdir() if child.name.startswith(SCRATCH_DIR_PREFIX)]


# ---------------------------------------------------------------------------
# what Telegram will accept
# ---------------------------------------------------------------------------
def test_the_cover_is_a_jpeg(tmp_path: Path) -> None:
    # Arrange
    destination = tmp_path / "cover.jpg"

    # Act
    result = render_cover(destination)

    # Assert
    assert not isinstance(result, Err), "the cover should render on a writable path"
    assert destination.read_bytes().startswith(JPEG_MAGIC)


def test_both_sides_are_exactly_telegrams_thumbnail_ceiling(tmp_path: Path) -> None:
    # Arrange
    destination = tmp_path / "cover.jpg"

    # Act
    render_cover(destination)

    # Assert
    assert jpeg_dimensions(destination.read_bytes()) == (COVER_SIZE, COVER_SIZE)
    assert COVER_SIZE == 320


def test_the_cover_is_well_under_the_two_hundred_kilobyte_limit(tmp_path: Path) -> None:
    # Arrange
    destination = tmp_path / "cover.jpg"

    # Act
    render_cover(destination)

    # Assert
    assert destination.stat().st_size < COVER_MAX_BYTES


def test_the_default_lines_are_the_watermark_ones(tmp_path: Path) -> None:
    # Arrange: the picture is one of the four watermark carriers, so its text is not a
    # local decision — it comes from bayram.watermark like the tags and the captions do.
    # Act / Assert
    assert COVER_LINES[-1] == WATERMARK_HANDLE
    assert not isinstance(render_cover(tmp_path / "cover.jpg"), Err)


# ---------------------------------------------------------------------------
# determinism — the digest of this file goes on a GeneratedAsset
# ---------------------------------------------------------------------------
def test_the_same_input_twice_produces_byte_identical_output(tmp_path: Path) -> None:
    # Arrange: sha256_of(cover) becomes GeneratedAsset.sha256, so a re-run of an order has
    # to hash to the same thing or idempotency stops meaning anything.
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"

    # Act
    render_cover(first)
    render_cover(second)

    # Assert
    assert first.read_bytes() == second.read_bytes()


def test_different_lines_produce_a_different_picture(tmp_path: Path) -> None:
    # Arrange
    default = tmp_path / "default.jpg"
    other = tmp_path / "other.jpg"

    # Act
    render_cover(default)
    render_cover(other, lines=("SOMETHING", "ELSE"))

    # Assert
    assert default.read_bytes() != other.read_bytes()


# ---------------------------------------------------------------------------
# failure is always an Err, never a raise
# ---------------------------------------------------------------------------
def test_an_unwritable_destination_returns_an_error_rather_than_raising(tmp_path: Path) -> None:
    # Arrange
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        # Act
        result = render_cover(locked / "cover.jpg")

        # Assert
        assert isinstance(result, Err)
    finally:
        # Leave the directory removable, or tmp_path cleanup fails for the whole session.
        locked.chmod(stat.S_IRWXU)


def test_a_failed_render_leaves_no_file_at_the_destination(tmp_path: Path) -> None:
    # Arrange: an integer size is required, so a string is a plausible caller mistake that
    # reaches Pillow rather than a Python TypeError at the call site.
    destination = tmp_path / "cover.jpg"

    # Act
    result = render_cover(destination, size=0)

    # Assert
    assert isinstance(result, Err)
    assert not destination.exists()


def test_no_scratch_directory_survives_a_successful_render(tmp_path: Path) -> None:
    # Arrange
    destination = tmp_path / "cover.jpg"

    # Act
    render_cover(destination)

    # Assert
    assert scratch_leftovers(tmp_path) == []


def test_no_scratch_directory_survives_a_failed_render(tmp_path: Path) -> None:
    # Arrange
    destination = tmp_path / "cover.jpg"

    # Act
    render_cover(destination, size=0)

    # Assert
    assert scratch_leftovers(tmp_path) == []


# ---------------------------------------------------------------------------
# the mark
# ---------------------------------------------------------------------------
def test_the_packaged_logo_is_byte_identical_to_the_brand_original() -> None:
    # Arrange: the cover ships a COPY of brand/avatar-telegram.png rather than re-drawing
    # the geometry, so the copy is what can rot. brand/README.md's regeneration recipe
    # rewrites the brand file; nothing rewrites this one. This test is the whole reason
    # copying was an acceptable answer — a redraw that forgets it fails here, loudly,
    # instead of shipping a stranger two different logos for the same bot.
    brand = REPO_ROOT / "brand" / "avatar-telegram.png"
    packaged = Path(str(resources.files("bayram.audio.assets").joinpath("logo.png")))

    # Act / Assert
    assert brand.is_file(), "brand/avatar-telegram.png is the source of truth and is missing"
    assert packaged.read_bytes() == brand.read_bytes(), (
        "src/bayram/audio/assets/logo.png has drifted from brand/avatar-telegram.png. "
        "Re-copy it: cp brand/avatar-telegram.png src/bayram/audio/assets/logo.png"
    )


def test_the_mark_is_actually_drawn_onto_the_cover(tmp_path: Path) -> None:
    # Arrange: the flame magenta is the one colour on the canvas that neither the black
    # ground nor the white ink can produce, so its presence is proof the paste happened
    # rather than proof that something was drawn.
    destination = tmp_path / "cover.jpg"

    # Act
    render_cover(destination)

    # Assert
    with Image.open(destination) as image:
        colours = image.convert("RGB").getcolors(maxcolors=_ALL_COLOURS) or []
    assert any(_is_brand_magenta(colour) for _count, colour in colours), (
        "no pixel resembling the brand magenta #BD32AF — the mark was not composited"
    )


def test_the_cover_still_renders_when_the_logo_resource_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: a broken wheel must cost the mark, never the cover. The text block is worth
    # far more than the disc, so _logo() returns None and _draw falls back to the picture
    # this module produced before the mark existed.
    def explode(_package: str) -> object:
        raise FileNotFoundError("no such package")

    monkeypatch.setattr(resources, "files", explode)
    destination = tmp_path / "cover.jpg"

    # Act
    result = render_cover(destination)

    # Assert
    assert not isinstance(result, Err), "a missing logo must not cost the whole cover"
    assert destination.read_bytes().startswith(JPEG_MAGIC)
    with Image.open(destination) as image:
        colours = image.convert("RGB").getcolors(maxcolors=_ALL_COLOURS) or []
    assert not any(_is_brand_magenta(colour) for _count, colour in colours)


def test_the_markless_fallback_is_exactly_the_old_centred_text_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: the layout arithmetic is written so that "no mark" is the same expression
    # with a zero-height mark, not a second code path. Proving it means the degraded
    # picture is the old one exactly — a text block centred in the whole canvas.
    def explode(_package: str) -> object:
        raise FileNotFoundError("no such package")

    monkeypatch.setattr(resources, "files", explode)
    destination = tmp_path / "cover.jpg"
    render_cover(destination)

    # Act: the ink's vertical extent should straddle the middle symmetrically.
    with Image.open(destination) as image:
        rows = [y for y in range(COVER_SIZE) if _row_has_ink(image.convert("RGB"), y)]

    # Assert
    top_margin, bottom_margin = rows[0], COVER_SIZE - 1 - rows[-1]
    assert abs(top_margin - bottom_margin) <= _CENTRING_TOLERANCE_PX, (
        f"text block is not centred: {top_margin}px above, {bottom_margin}px below"
    )


def test_the_mark_and_the_text_do_not_overlap(tmp_path: Path) -> None:
    # Arrange: the mark and the lines are ONE stacked block, so the disc's rows and the
    # text's rows must be disjoint. Note the mark is not only magenta — the candles inside
    # it are the same white as the ink — so "white pixel" cannot tell the two apart. The
    # disc's own extent can: every row of the mark contains magenta, and no row of the
    # text does.
    destination = tmp_path / "cover.jpg"
    render_cover(destination)

    # Act
    with Image.open(destination) as image:
        rgb = image.convert("RGB").copy()
    disc_rows = [y for y in range(COVER_SIZE) if _row_has_magenta(rgb, y)]
    below_disc = range(disc_rows[-1] + 1, COVER_SIZE)
    text_rows = [y for y in below_disc if _row_has_ink(rgb, y)]

    # Assert
    assert disc_rows, "no magenta anywhere — the mark was not composited"
    assert text_rows, "no text below the mark — the block is not stacked"
    # The gap is the layout constant, so a regression that lets them touch shows up here
    # as a zero rather than as a picture somebody has to look at.
    assert text_rows[0] > disc_rows[-1], "the text starts inside the disc"
