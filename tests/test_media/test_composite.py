"""The collage builder (IMAGE_VIDEO_SPEC §4.4, §10 M2.3).

Acceptance: 1–4 inputs × 3 aspects produce the target size; EXIF stripped. Everything is
built from real JPEG/PNG files written by Pillow under ``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from bayram.contracts import is_err, is_ok
from bayram.db.enums import MediaAspect
from bayram.errors import StorageError, ValidationError
from bayram.media.composite import (
    COLLAGE_MIME,
    GUTTER_PX,
    IMAGE_SIZES,
    MAX_COLLAGE_PHOTOS,
    VIDEO_SIZES,
    Cell,
    build_collage,
    layout_cells,
    needs_collage,
    target_size,
)

_ORIENTATION = 0x0112
_MAKE = 0x010F
_GPS_IFD = 0x8825

_COLOURS = ((220, 20, 20), (20, 200, 20), (20, 20, 220), (230, 200, 20))


def _photo(
    directory: Path,
    name: str,
    *,
    size: tuple[int, int] = (300, 200),
    colour: tuple[int, int, int] = (220, 20, 20),
    orientation: int | None = None,
    with_gps: bool = False,
) -> Path:
    image = Image.new("RGB", size, colour)
    exif = Image.Exif()
    exif[_MAKE] = "PhoneCo"
    if orientation is not None:
        exif[_ORIENTATION] = orientation
    if with_gps:
        exif[_GPS_IFD] = {1: "N", 2: (41.0, 18.0, 0.0), 3: "E", 4: (69.0, 16.0, 0.0)}
    path = directory / name
    image.save(path, format="JPEG", quality=95, exif=exif)
    return path


def _photos(directory: Path, count: int) -> list[Path]:
    return [
        _photo(directory, f"p{index}.jpg", colour=_COLOURS[index], with_gps=True)
        for index in range(count)
    ]


def _close(pixel: object, colour: tuple[int, int, int], tolerance: int = 40) -> bool:
    assert isinstance(pixel, tuple)
    return all(abs(int(a) - b) <= tolerance for a, b in zip(pixel[:3], colour, strict=True))


# -- the acceptance matrix ---------------------------------------------------


@pytest.mark.parametrize("aspect", list(MediaAspect))
@pytest.mark.parametrize("count", range(1, MAX_COLLAGE_PHOTOS + 1))
@pytest.mark.parametrize("sizes", [IMAGE_SIZES, VIDEO_SIZES], ids=["image", "video"])
def test_every_count_and_aspect_produces_the_target_size_with_no_exif(
    tmp_path: Path, sizes: dict[MediaAspect, tuple[int, int]], count: int, aspect: MediaAspect
) -> None:
    width, height = sizes[aspect]
    sources = _photos(tmp_path, count)
    with Image.open(sources[0]) as source:
        assert source.getexif()  # the fixture really carries EXIF, GPS included
        assert _GPS_IFD in source.getexif()

    destination = tmp_path / "out" / "collage.jpg"
    result = build_collage(sources, destination, width=width, height=height)

    assert is_ok(result), result
    collage = result.value
    assert collage.path == destination
    assert (collage.width, collage.height, collage.photo_count) == (width, height, count)
    assert collage.mime == COLLAGE_MIME
    assert collage.size_bytes == destination.stat().st_size
    with Image.open(destination) as out:
        assert out.format == "JPEG"
        assert out.size == (width, height)
        assert out.mode == "RGB"
        assert len(out.getexif()) == 0
        assert "exif" not in out.info
        assert "icc_profile" not in out.info
    # No EXIF/APP1 marker anywhere in the file, not merely none Pillow chose to parse.
    raw = destination.read_bytes()
    assert b"Exif\x00\x00" not in raw
    assert b"PhoneCo" not in raw
    # The scratch directory is gone: only the published file remains.
    assert [p.name for p in destination.parent.iterdir()] == ["collage.jpg"]


@pytest.mark.parametrize("count", range(1, MAX_COLLAGE_PHOTOS + 1))
def test_each_photo_is_visible_in_its_cell(tmp_path: Path, count: int) -> None:
    width, height = IMAGE_SIZES[MediaAspect.SQUARE]
    destination = tmp_path / "collage.jpg"
    result = build_collage(_photos(tmp_path, count), destination, width=width, height=height)
    assert is_ok(result)
    with Image.open(destination) as out:
        rgb = out.convert("RGB")
        for colour, cell in zip(_COLOURS, layout_cells(count, width, height), strict=False):
            centre = (cell.left + cell.width // 2, cell.top + cell.height // 2)
            assert _close(rgb.getpixel(centre), colour), (count, cell)


# -- orientation -------------------------------------------------------------


def _half_and_half(directory: Path, *, orientation: int) -> Path:
    """Stored landscape: left half red, right half blue, tagged with ``orientation``."""
    image = Image.new("RGB", (400, 200), (220, 20, 20))
    image.paste((20, 20, 220), (200, 0, 400, 200))
    exif = Image.Exif()
    exif[_ORIENTATION] = orientation
    path = directory / "sideways.jpg"
    image.save(path, format="JPEG", quality=95, exif=exif)
    return path


def test_the_orientation_tag_is_applied_before_it_is_dropped(tmp_path: Path) -> None:
    # Orientation 6: display rotated 90° clockwise, so the stored left edge becomes the top.
    source = _half_and_half(tmp_path, orientation=6)
    destination = tmp_path / "collage.jpg"
    assert is_ok(build_collage([source], destination, width=1024, height=1024))
    with Image.open(destination) as out:
        rgb = out.convert("RGB")
        assert _close(rgb.getpixel((512, 150)), (220, 20, 20))
        assert _close(rgb.getpixel((512, 870)), (20, 20, 220))
        assert _ORIENTATION not in out.getexif()


def test_an_untagged_photo_is_fitted_not_cropped_or_stretched(tmp_path: Path) -> None:
    source = _photo(tmp_path, "wide.jpg", size=(400, 200), colour=(220, 20, 20))
    destination = tmp_path / "collage.jpg"
    assert is_ok(build_collage([source], destination, width=1024, height=1024))
    with Image.open(destination) as out:
        rgb = out.convert("RGB")
        # 2:1 fitted into 1:1 → 1024×512 centred: the band above it is the dimmed ground.
        assert _close(rgb.getpixel((512, 512)), (220, 20, 20))
        top = rgb.getpixel((512, 60))
        assert isinstance(top, tuple)
        assert top[0] < 200


# -- layout ------------------------------------------------------------------


def test_two_photos_stack_on_portrait_and_sit_side_by_side_otherwise() -> None:
    portrait = layout_cells(2, 768, 1344)
    assert [c.left for c in portrait] == [0, 0]
    assert portrait[1].top == portrait[0].height + GUTTER_PX
    for width, height in ((1024, 1024), (1344, 768)):
        cells = layout_cells(2, width, height)
        assert [c.top for c in cells] == [0, 0]
        assert cells[1].left == cells[0].width + GUTTER_PX


def test_three_photos_are_one_large_and_two_small() -> None:
    for width, height in ((768, 1344), (1024, 1024), (1344, 768)):
        large, *smalls = layout_cells(3, width, height)
        assert len(smalls) == 2
        for small in smalls:
            assert large.width * large.height > small.width * small.height


@pytest.mark.parametrize("count", range(1, MAX_COLLAGE_PHOTOS + 1))
@pytest.mark.parametrize("size", [*IMAGE_SIZES.values(), *VIDEO_SIZES.values(), (17, 31)])
def test_cells_tile_the_canvas_with_exact_gutters(count: int, size: tuple[int, int]) -> None:
    width, height = size
    cells = layout_cells(count, width, height)
    assert len(cells) == count
    covered: set[tuple[int, int]] = set()
    for cell in cells:
        assert cell.width > 0 and cell.height > 0
        assert cell.left + cell.width <= width and cell.top + cell.height <= height
        box = {
            (x, y)
            for x in range(cell.left, cell.left + cell.width)
            for y in range(cell.top, cell.top + cell.height)
        }
        assert not box & covered  # no overlap
        covered |= box
    gutters = {1: 0, 2: 1, 3: 2, 4: 2}[count]
    uncovered = width * height - len(covered)
    # Every uncovered pixel is gutter: one 2 px line per split.
    assert uncovered <= gutters * GUTTER_PX * max(width, height)
    if count == 1:
        assert cells == (Cell(0, 0, width, height),)


def test_layout_refuses_a_count_it_has_no_layout_for() -> None:
    with pytest.raises(ValueError):
        layout_cells(0, 100, 100)
    with pytest.raises(ValueError):
        layout_cells(MAX_COLLAGE_PHOTOS + 1, 100, 100)


# -- sizes and routing -------------------------------------------------------


def test_target_sizes_are_the_spec_table_and_multiples_of_16() -> None:
    assert target_size("image", MediaAspect.PORTRAIT) == (768, 1344)
    assert target_size("image", MediaAspect.SQUARE) == (1024, 1024)
    assert target_size("image", MediaAspect.LANDSCAPE) == (1344, 768)
    assert target_size("video", MediaAspect.PORTRAIT) == (720, 1280)
    assert target_size("video", MediaAspect.SQUARE) == (960, 960)
    assert target_size("video", MediaAspect.LANDSCAPE) == (1280, 720)
    for sizes in (IMAGE_SIZES, VIDEO_SIZES):
        assert set(sizes) == set(MediaAspect)
        for width, height in sizes.values():
            assert width % 16 == 0 and height % 16 == 0


def test_a_collage_is_made_only_when_the_backend_takes_fewer_refs() -> None:
    assert not needs_collage(0, 1)
    assert not needs_collage(1, 1)  # one photo goes natively
    assert needs_collage(2, 1)
    assert needs_collage(4, 1)
    assert not needs_collage(3, 4)  # a multi-ref backend takes the originals
    assert needs_collage(4, 3)


# -- inputs we refuse, and determinism ---------------------------------------


def test_transparency_is_matted_and_the_output_is_still_a_jpeg(tmp_path: Path) -> None:
    path = tmp_path / "clear.png"
    Image.new("RGBA", (64, 64), (255, 0, 0, 0)).save(path, format="PNG")
    destination = tmp_path / "collage.jpg"
    assert is_ok(build_collage([path, path], destination, width=720, height=1280))
    with Image.open(destination) as out:
        assert out.format == "JPEG" and out.size == (720, 1280)


def test_a_multi_frame_image_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "animated.gif"
    frames = [Image.new("RGB", (32, 32), colour) for colour in _COLOURS[:2]]
    frames[0].save(path, format="GIF", save_all=True, append_images=frames[1:])
    destination = tmp_path / "collage.jpg"
    result = build_collage([_photo(tmp_path, "a.jpg"), path], destination, width=64, height=64)
    assert is_err(result)
    assert isinstance(result.error, ValidationError)
    assert result.error.context["reason"] == "multi_frame"
    assert result.error.context["photo_index"] == 1
    assert not destination.exists()


def test_an_undecodable_file_is_refused_not_raised(tmp_path: Path) -> None:
    path = tmp_path / "junk.jpg"
    path.write_bytes(b"\xff\xd8\xff not really a jpeg")
    result = build_collage([path], tmp_path / "c.jpg", width=64, height=64)
    assert is_err(result)
    assert isinstance(result.error, ValidationError)
    assert result.error.context["reason"] == "undecodable"


def test_a_missing_file_is_refused_not_raised(tmp_path: Path) -> None:
    result = build_collage([tmp_path / "gone.jpg"], tmp_path / "c.jpg", width=64, height=64)
    assert is_err(result)
    assert isinstance(result.error, ValidationError)


@pytest.mark.parametrize("count", [0, MAX_COLLAGE_PHOTOS + 1])
def test_a_count_outside_one_to_four_is_refused(tmp_path: Path, count: int) -> None:
    sources = [_photo(tmp_path, f"p{i}.jpg") for i in range(count)]
    result = build_collage(sources, tmp_path / "c.jpg", width=64, height=64)
    assert is_err(result)
    assert isinstance(result.error, ValidationError)


def test_a_failed_write_is_a_storage_error(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    result = build_collage([_photo(tmp_path, "a.jpg")], blocker / "c.jpg", width=64, height=64)
    assert is_err(result)
    assert isinstance(result.error, StorageError)


def test_the_same_inputs_give_the_same_bytes(tmp_path: Path) -> None:
    sources = _photos(tmp_path, 3)
    first = build_collage(sources, tmp_path / "a.jpg", width=720, height=1280)
    second = build_collage(sources, tmp_path / "b.jpg", width=720, height=1280)
    assert is_ok(first) and is_ok(second)
    assert first.value.sha256 == second.value.sha256
    assert (tmp_path / "a.jpg").read_bytes() == (tmp_path / "b.jpg").read_bytes()
