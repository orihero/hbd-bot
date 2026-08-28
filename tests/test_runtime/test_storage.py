"""Local object storage: confinement, atomicity, and never raising."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hbd.contracts import Err, Ok
from hbd.errors import ErrorCode
from hbd.storage import LocalFileStorage

PAYLOAD = b"\xff\xfb\x10\xc0 pretend this is a song"
MIME = "audio/mpeg"


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(tmp_path / "archive")


async def test_a_stored_object_reports_its_own_size_and_digest(
    storage: LocalFileStorage,
) -> None:
    # Arrange / Act
    result = await storage.put("orders/abc/song.mp3", PAYLOAD, content_type=MIME)

    # Assert
    assert isinstance(result, Ok)
    assert result.value.size_bytes == len(PAYLOAD)
    assert result.value.sha256 == hashlib.sha256(PAYLOAD).hexdigest()
    assert result.value.content_type == MIME


async def test_what_was_put_can_be_got_back_byte_for_byte(storage: LocalFileStorage) -> None:
    # Arrange
    await storage.put("orders/abc/song.mp3", PAYLOAD, content_type=MIME)

    # Act
    result = await storage.get("orders/abc/song.mp3")

    # Assert
    assert isinstance(result, Ok)
    assert result.value == PAYLOAD


async def test_nested_keys_create_their_own_directories(storage: LocalFileStorage) -> None:
    # Arrange / Act
    result = await storage.put("a/b/c/d/e.txt", b"deep", content_type="text/plain")

    # Assert
    assert isinstance(result, Ok)
    assert (storage.root / "a/b/c/d/e.txt").read_bytes() == b"deep"


async def test_overwriting_a_key_replaces_it_rather_than_appending(
    storage: LocalFileStorage,
) -> None:
    # Arrange
    await storage.put("k", b"first", content_type="text/plain")

    # Act
    await storage.put("k", b"second", content_type="text/plain")

    # Assert
    got = await storage.get("k")
    assert isinstance(got, Ok)
    assert got.value == b"second"


@pytest.mark.parametrize(
    "key",
    [
        "../escape.txt",
        "a/../../escape.txt",
        "/etc/passwd",
        "",
        "   ",
        "a//b",
        "a/./b",
        "windows\\path",
        "nul\x00byte",
    ],
)
async def test_a_key_that_escapes_or_confuses_the_root_is_refused(
    storage: LocalFileStorage, key: str
) -> None:
    # Act
    result = await storage.put(key, b"x", content_type="text/plain")

    # Assert: refused as invalid input, and nothing was written anywhere.
    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.INVALID_INPUT
    assert not (storage.root.parent / "escape.txt").exists()


async def test_reading_a_key_that_was_never_stored_is_a_typed_error_not_a_raise(
    storage: LocalFileStorage,
) -> None:
    # Act
    result = await storage.get("never/written")

    # Assert
    assert isinstance(result, Err)
    assert result.error.error_code is ErrorCode.STORAGE_FAILED
    assert result.error.is_retryable


async def test_deleting_something_absent_is_success(storage: LocalFileStorage) -> None:
    # Act / Assert: idempotent deletes keep a purge job from failing on a re-run.
    assert isinstance(await storage.delete("never/written"), Ok)


async def test_delete_removes_a_stored_object(storage: LocalFileStorage) -> None:
    # Arrange
    await storage.put("k", PAYLOAD, content_type=MIME)

    # Act
    await storage.delete("k")

    # Assert
    assert isinstance(await storage.get("k"), Err)


async def test_a_signed_url_addresses_the_stored_file(storage: LocalFileStorage) -> None:
    # Arrange
    await storage.put("orders/abc/song.mp3", PAYLOAD, content_type=MIME)

    # Act
    result = await storage.signed_url("orders/abc/song.mp3", ttl_s=60)

    # Assert
    assert isinstance(result, Ok)
    assert result.value.startswith("file://")
    assert result.value.endswith("song.mp3")


async def test_a_url_is_refused_for_an_object_that_is_not_stored(
    storage: LocalFileStorage,
) -> None:
    # Act / Assert: handing the bot an address to nothing is worse than saying no.
    result = await storage.signed_url("missing", ttl_s=60)
    assert isinstance(result, Err)


async def test_no_partial_file_survives_a_failed_write(
    storage: LocalFileStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange: make the rename fail after the bytes are already on disk.
    def explode(self: Path, target: Path) -> Path:
        raise OSError("disk went away")

    monkeypatch.setattr(Path, "replace", explode)

    # Act
    result = await storage.put("k", PAYLOAD, content_type=MIME)

    # Assert: a typed error, and no ".partial" litter left behind.
    assert isinstance(result, Err)
    assert not list(storage.root.glob("*.partial"))
