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
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from PIL import Image

from bayram.audio.constants import SCRATCH_DIR_PREFIX
from bayram.audio.cover import COVER_MAX_BYTES, COVER_SIZE, render_cover
from bayram.contracts import Err

#: JPEG start-of-image. Telegram accepts nothing else as an audio thumbnail.
JPEG_MAGIC = b"\xff\xd8"
#: Start Of Frame, baseline DCT. The frame header is where the real dimensions live.
_SOF0 = 0xC0
_MARKER_PREFIX = 0xFF

#: ``tests/test_audio/test_cover.py`` -> the repository root, for the brand asset the
#: packaged cover is copied from. Three parents, and a moved test file breaks it loudly.
REPO_ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def _as_file(path: Path) -> Iterator[Path]:
    """Stand in for ``importlib.resources.as_file`` when the resource is already a path.

    The real one returns a context manager that may materialise a zip member to a temporary
    file. A test substituting a plain path still has to satisfy the ``with`` in ``_draw``,
    and ``nullcontext`` would not, because ``_draw`` unpacks the value it yields.
    """
    yield path


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


def test_the_cover_is_the_brand_artwork_and_not_a_blank(tmp_path: Path) -> None:
    # Arrange: the artwork is a photographic gradient, so the cheapest proof that the PNG
    # actually reached the JPEG is colour variety — the two-tone picture this replaced had
    # a handful of distinct colours, and a failed paste would be a flat fill.
    destination = tmp_path / "cover.jpg"

    # Act
    render_cover(destination)

    # Assert
    with Image.open(destination) as image:
        colours = image.convert("RGB").getcolors(maxcolors=COVER_SIZE * COVER_SIZE)
    assert colours is not None
    assert len(colours) > 1000, f"only {len(colours)} distinct colours — this is not the artwork"


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


def test_a_different_size_produces_a_different_picture(tmp_path: Path) -> None:
    # Arrange: `size` is the only knob left now that the cover is one shipped image, so it
    # is the only way to prove the renderer is reading its argument at all rather than
    # returning a cached or constant file.
    default = tmp_path / "default.jpg"
    smaller = tmp_path / "smaller.jpg"

    # Act
    render_cover(default)
    render_cover(smaller, size=160)

    # Assert
    assert default.read_bytes() != smaller.read_bytes()
    assert jpeg_dimensions(smaller.read_bytes()) == (160, 160)


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
# the artwork, and the copy of it that ships
# ---------------------------------------------------------------------------
def test_the_packaged_cover_is_byte_identical_to_the_brand_original() -> None:
    # Arrange: the wheel ships a COPY of brand/Logo-Bot.png, because brand/ is not packaged.
    # The copy is therefore what can rot: whoever redraws the artwork edits the brand file,
    # and nothing edits this one. This test is the entire reason copying was an acceptable
    # answer — a redraw that forgets it fails here, loudly, rather than shipping last
    # month's cover on every song for a month.
    brand = REPO_ROOT / "brand" / "Logo-Bot.png"
    packaged = Path(str(resources.files("bayram.audio.assets").joinpath("cover.png")))

    # Act / Assert
    assert brand.is_file(), "brand/Logo-Bot.png is the source of truth and is missing"
    assert packaged.read_bytes() == brand.read_bytes(), (
        "src/bayram/audio/assets/cover.png has drifted from brand/Logo-Bot.png. "
        "Re-copy it: cp brand/Logo-Bot.png src/bayram/audio/assets/cover.png"
    )


def test_an_unreadable_cover_resource_is_an_error_and_not_a_blank_picture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: the artwork IS the cover now — there is no text to fall back to, so a broken
    # wheel must produce no cover rather than a plain or empty one. `deliver_kit` ships the
    # song without artwork on an Err, which is the correct degradation; a 320x320 blank
    # would be shipped to a customer as though it were the product.
    def explode(_package: str) -> object:
        raise FileNotFoundError("no such package")

    monkeypatch.setattr(resources, "files", explode)
    destination = tmp_path / "cover.jpg"

    # Act
    result = render_cover(destination)

    # Assert
    assert isinstance(result, Err)
    assert not destination.exists(), "a failed render must leave nothing behind"


def test_the_artwork_is_not_stretched_when_the_source_is_not_square(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: brand/Logo-Bot.png is square today, so the centre crop is a no-op and would
    # never be exercised. It exists for the day the brand file is replaced with a rectangle,
    # where the alternative is a silently stretched face. Substitute a wide source whose
    # left and right thirds are red and whose centre square is green: a correct centre crop
    # yields pure green, a stretch yields all three.
    wide = tmp_path / "wide.png"
    image = Image.new("RGB", (900, 300), (255, 0, 0))
    image.paste(Image.new("RGB", (300, 300), (0, 255, 0)), (300, 0))
    image.save(wide)

    class _Stub:
        def joinpath(self, _name: str) -> Path:
            return wide

    monkeypatch.setattr(resources, "files", lambda _pkg: _Stub())
    monkeypatch.setattr(resources, "as_file", _as_file)
    destination = tmp_path / "cover.jpg"

    # Act
    render_cover(destination)

    # Assert
    with Image.open(destination) as rendered:
        red, green, blue = rendered.convert("RGB").getpixel((COVER_SIZE // 2, COVER_SIZE // 2))
    assert green > 200 and red < 60, (
        f"centre pixel is ({red},{green},{blue}) — the source was stretched, not cropped"
    )
