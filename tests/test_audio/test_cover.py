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

import stat
from pathlib import Path

from hbd.audio.constants import SCRATCH_DIR_PREFIX
from hbd.audio.cover import COVER_MAX_BYTES, COVER_SIZE, render_cover
from hbd.contracts import Err
from hbd.watermark import COVER_LINES, WATERMARK_HANDLE

#: JPEG start-of-image. Telegram accepts nothing else as an audio thumbnail.
JPEG_MAGIC = b"\xff\xd8"
#: Start Of Frame, baseline DCT. The frame header is where the real dimensions live.
_SOF0 = 0xC0
_MARKER_PREFIX = 0xFF


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
    # local decision — it comes from hbd.watermark like the tags and the captions do.
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
