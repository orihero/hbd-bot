"""Two invariants: no temp file survives a failure, and no destination is ever half-written."""

from __future__ import annotations

from pathlib import Path

import pytest

from bayram.audio.constants import SCRATCH_DIR_PREFIX
from bayram.audio.tempfiles import publish, scratch_dir


def scratch_leftovers(directory: Path) -> list[Path]:
    return [child for child in directory.iterdir() if child.name.startswith(SCRATCH_DIR_PREFIX)]


# ---------------------------------------------------------------------------
# scratch_dir
# ---------------------------------------------------------------------------
def test_scratch_is_created_beside_the_destination_so_the_move_is_same_device(
    tmp_path: Path,
) -> None:
    # Arrange
    destination = tmp_path / "out" / "song.ogg"

    # Act
    with scratch_dir(destination) as scratch:
        # Assert
        assert scratch.parent == destination.parent
        assert scratch.is_dir()


def test_scratch_is_removed_on_the_success_path(tmp_path: Path) -> None:
    destination = tmp_path / "song.ogg"

    with scratch_dir(destination) as scratch:
        (scratch / "partial.wav").write_bytes(b"half a render")

    assert not scratch.exists()
    assert scratch_leftovers(tmp_path) == []


def test_scratch_is_removed_when_the_render_raises(tmp_path: Path) -> None:
    # Arrange
    destination = tmp_path / "song.ogg"

    # Act
    with pytest.raises(RuntimeError), scratch_dir(destination) as scratch:
        (scratch / "partial.wav").write_bytes(b"half a render")
        raise RuntimeError("ffmpeg fell over")

    # Assert: a failed render leaves NOTHING behind.
    assert scratch_leftovers(tmp_path) == []


def test_scratch_creates_a_missing_destination_directory(tmp_path: Path) -> None:
    destination = tmp_path / "deeply" / "nested" / "song.ogg"

    with scratch_dir(destination):
        assert destination.parent.is_dir()


def test_two_concurrent_renders_get_separate_scratch_directories(tmp_path: Path) -> None:
    destination = tmp_path / "song.ogg"

    with scratch_dir(destination) as first, scratch_dir(destination) as second:
        assert first != second


def test_a_cleanup_failure_does_not_mask_the_real_outcome(tmp_path: Path) -> None:
    # Arrange: the block removes the scratch dir itself, so rmtree will fail afterwards.
    destination = tmp_path / "song.ogg"

    with scratch_dir(destination) as scratch:
        scratch.rmdir()

    # Assert: reaching here at all is the assertion — cleanup must not raise.
    assert not scratch.exists()


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------
def test_publish_moves_the_finished_file_into_place(tmp_path: Path) -> None:
    # Arrange
    staged = tmp_path / "staged.ogg"
    staged.write_bytes(b"finished audio")
    destination = tmp_path / "out" / "song.ogg"

    # Act
    published = publish(staged, destination)

    # Assert
    assert published == destination
    assert destination.read_bytes() == b"finished audio"
    assert not staged.exists()


def test_publish_replaces_an_existing_file(tmp_path: Path) -> None:
    # Arrange: a re-render of the same asset must overwrite, not fail.
    destination = tmp_path / "song.ogg"
    destination.write_bytes(b"old take")
    staged = tmp_path / "staged.ogg"
    staged.write_bytes(b"new take")

    publish(staged, destination)

    assert destination.read_bytes() == b"new take"


def test_publish_creates_the_destination_directory(tmp_path: Path) -> None:
    staged = tmp_path / "staged.ogg"
    staged.write_bytes(b"audio")

    publish(staged, tmp_path / "a" / "b" / "song.ogg")

    assert (tmp_path / "a" / "b" / "song.ogg").exists()
