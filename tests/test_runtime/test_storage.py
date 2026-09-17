"""Local object storage: confinement, atomicity, and never raising."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from bayram.contracts import Err, Ok
from bayram.errors import ErrorCode
from bayram.storage import RANGE_CHUNK_BYTES, LocalFileStorage

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


# ---------------------------------------------------------------------------
# The range seam (admin plan §12.7). Confinement is asserted here rather than in
# the panel because the panel is forbidden from resolving a key itself.
# ---------------------------------------------------------------------------
BIG = bytes(range(256)) * 1024  # 256 KiB, so a 64 KiB chunk boundary is crossed four times


async def _collect(stream: AsyncIterator[bytes]) -> list[bytes]:
    return [chunk async for chunk in stream]


async def test_a_range_returns_exactly_the_bytes_asked_for(storage: LocalFileStorage) -> None:
    # Arrange
    await storage.put("orders/abc/song.mp3", BIG, content_type=MIME)

    # Act
    opened = await storage.open_range("orders/abc/song.mp3", start=0, end=99)

    # Assert — inclusive end, so bytes=0-99 is a hundred bytes, not ninety-nine.
    assert isinstance(opened, Ok)
    assert b"".join(await _collect(opened.value)) == BIG[:100]


async def test_a_range_that_overruns_the_object_is_clamped_not_refused(
    storage: LocalFileStorage,
) -> None:
    """``bytes=N-`` is spelled with an end past the tail; asking for more is not an error."""
    # Arrange
    await storage.put("k", PAYLOAD, content_type=MIME)

    # Act
    opened = await storage.open_range("k", start=2, end=10_000)

    # Assert
    assert isinstance(opened, Ok)
    assert b"".join(await _collect(opened.value)) == PAYLOAD[2:]


async def test_a_range_arrives_in_sixty_four_kibibyte_chunks(storage: LocalFileStorage) -> None:
    """A whole-object read would be one chunk — and one song in memory per range request."""
    # Arrange
    await storage.put("k", BIG, content_type=MIME)

    # Act
    opened = await storage.open_range("k", start=0, end=len(BIG) - 1)

    # Assert
    assert isinstance(opened, Ok)
    chunks = await _collect(opened.value)
    assert [len(chunk) for chunk in chunks] == [RANGE_CHUNK_BYTES] * (len(BIG) // RANGE_CHUNK_BYTES)
    assert b"".join(chunks) == BIG


async def test_streaming_never_goes_through_the_whole_object_read(
    storage: LocalFileStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T4 names ``get`` specifically: it loads the entire object and must back no stream."""

    # Arrange
    async def forbidden(self: LocalFileStorage, key: str) -> object:
        raise AssertionError("open_range must not read the whole object")

    await storage.put("k", BIG, content_type=MIME)
    monkeypatch.setattr(LocalFileStorage, "get", forbidden)

    # Act
    opened = await storage.open_range("k", start=0, end=63)

    # Assert
    assert isinstance(opened, Ok)
    assert b"".join(await _collect(opened.value)) == BIG[:64]


async def test_a_start_past_the_last_byte_is_refused(storage: LocalFileStorage) -> None:
    """The source of the router's 416: nothing to hand back, and saying so is not a 404."""
    # Arrange
    await storage.put("k", PAYLOAD, content_type=MIME)

    # Act
    opened = await storage.open_range("k", start=len(PAYLOAD), end=len(PAYLOAD) + 10)

    # Assert
    assert isinstance(opened, Err)
    assert opened.error.error_code is ErrorCode.INVALID_INPUT


async def test_every_range_on_an_empty_object_is_unsatisfiable(storage: LocalFileStorage) -> None:
    # Arrange
    await storage.put("k", b"", content_type=MIME)

    # Act
    opened = await storage.open_range("k", start=0, end=0)

    # Assert
    assert isinstance(opened, Err)
    assert opened.error.error_code is ErrorCode.INVALID_INPUT


@pytest.mark.parametrize(("start", "end"), [(-1, 10), (5, 4), (-10, -5)])
async def test_a_backwards_or_negative_range_is_refused(
    storage: LocalFileStorage, start: int, end: int
) -> None:
    # Arrange
    await storage.put("k", PAYLOAD, content_type=MIME)

    # Act
    opened = await storage.open_range("k", start=start, end=end)

    # Assert
    assert isinstance(opened, Err)
    assert opened.error.error_code is ErrorCode.INVALID_INPUT


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
async def test_a_traversing_key_is_refused_by_open_range_too(
    storage: LocalFileStorage, key: str
) -> None:
    """Same list as ``put``: one confinement rule, asserted on every door into it."""
    # Arrange — a real file one level above the root, which the escapes above aim at.
    storage.root.mkdir(parents=True, exist_ok=True)
    (storage.root.parent / "escape.txt").write_bytes(b"secrets")

    # Act
    opened = await storage.open_range(key, start=0, end=10)

    # Assert
    assert isinstance(opened, Err)
    assert opened.error.error_code is ErrorCode.INVALID_INPUT


async def test_a_valid_key_resolves_under_the_root_and_streams(storage: LocalFileStorage) -> None:
    """The other half of the traversal assertion: refusing everything would also pass it."""
    # Arrange
    await storage.put("orders/abc/song.mp3", PAYLOAD, content_type=MIME)

    # Act
    opened = await storage.open_range("orders/abc/song.mp3", start=0, end=len(PAYLOAD) - 1)

    # Assert
    assert isinstance(opened, Ok)
    assert b"".join(await _collect(opened.value)) == PAYLOAD
    assert (storage.root / "orders/abc/song.mp3").is_relative_to(storage.root)


async def test_streaming_an_object_that_was_never_stored_is_not_found(
    storage: LocalFileStorage,
) -> None:
    """``NOT_FOUND``, not ``STORAGE_FAILED``: "gone" and "the disk broke" are different 5xx."""
    # Act
    opened = await storage.open_range("never/written", start=0, end=10)

    # Assert
    assert isinstance(opened, Err)
    assert opened.error.error_code is ErrorCode.NOT_FOUND
    assert not opened.error.is_retryable


async def test_a_directory_is_not_an_object(storage: LocalFileStorage) -> None:
    """A directory key resolves and stats fine. Streaming it would be an OS-level surprise."""
    # Arrange
    await storage.put("orders/abc/song.mp3", PAYLOAD, content_type=MIME)

    # Act
    opened = await storage.open_range("orders/abc", start=0, end=10)

    # Assert
    assert isinstance(opened, Err)
    assert opened.error.error_code is ErrorCode.NOT_FOUND


async def test_size_reports_what_was_stored(storage: LocalFileStorage) -> None:
    """``assets.size_bytes`` is 0 on every row ever written; this is the honest number."""
    # Arrange
    await storage.put("k", BIG, content_type=MIME)

    # Act
    measured = await storage.size("k")

    # Assert
    assert isinstance(measured, Ok)
    assert measured.value == len(BIG)


async def test_size_of_an_absent_object_is_not_found(storage: LocalFileStorage) -> None:
    # Act
    measured = await storage.size("never/written")

    # Assert
    assert isinstance(measured, Err)
    assert measured.error.error_code is ErrorCode.NOT_FOUND


async def test_a_traversing_key_is_refused_by_size_too(storage: LocalFileStorage) -> None:
    # Act
    measured = await storage.size("../escape.txt")

    # Assert
    assert isinstance(measured, Err)
    assert measured.error.error_code is ErrorCode.INVALID_INPUT


async def test_no_streaming_failure_names_a_filesystem_path(storage: LocalFileStorage) -> None:
    """The 404 body is rendered from ``operator_message`` verbatim (admin ``errors.py``).

    ``context`` is dropped on the way to the wire, so the path in it never crosses; the
    message is the one field that does, and a message that interpolated the key or the
    resolved path would publish the host's filesystem layout to anyone who can guess an id.
    """
    # Arrange
    await storage.put("orders/abc/song.mp3", PAYLOAD, content_type=MIME)
    root = str(storage.root)

    # Act
    failures = [
        await storage.open_range("never/written", start=0, end=10),
        await storage.open_range("../escape.txt", start=0, end=10),
        await storage.open_range("orders/abc/song.mp3", start=9_999, end=10_000),
        await storage.size("never/written"),
    ]

    # Assert
    for failure in failures:
        assert isinstance(failure, Err)
        message = failure.error.operator_message
        assert root not in message
        assert "/" not in message
        assert "escape.txt" not in message and "song.mp3" not in message
