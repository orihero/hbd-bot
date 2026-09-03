"""Object storage, backed by the local filesystem.

No module agent owned this, and the pipeline requires a ``Storage`` to archive a finished
kit, so here it is — the simplest implementation that is actually correct.

Three things it does properly, because getting them wrong is how a storage layer becomes a
security incident rather than a bug:

* **Keys are confined.** A key is resolved under the root and the result is checked to
  still be under the root. ``../../etc/passwd`` is refused, not written.
* **Writes are atomic.** Bytes land in a temporary file in the same directory and are then
  renamed, so a crashed process leaves either the old object or none — never a truncated
  one that ``get`` would happily return.
* **Nothing raises.** Every failure is an ``Err(StorageError)`` carrying the key and the
  underlying cause, because archival failing must degrade a kit, not sink it. The single
  exception is a read that fails *after* ``open_range``'s iterator has begun yielding:
  the response is already on the wire and there is no ``Result`` left to hand back.

``size`` and ``open_range`` are the streaming half, added for the admin panel's audio
route (admin plan §12.7). They exist as *protocol* members rather than as reads through
``get`` for two reasons: ``get`` loads a whole object into memory, which is a memory
amplifier when a browser issues a range request per few seconds of audio; and the panel
must resolve a key through a public seam rather than through ``_resolve``, which is
private and would not exist at all on an S3 backend.

``signed_url`` returns a ``file://`` URL. That is honest: this backend cannot mint a
credential, and pretending otherwise would hand the bot an address it cannot send. The day
S3/R2 lands, it replaces this class behind the same protocol and nothing else moves.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat as stat_module
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import IO, Final

from hbd.contracts import Err, Result, StoredObject, err, ok
from hbd.errors import NotFoundError, StorageError, ValidationError
from hbd.logging import get_logger

__all__ = [
    "LocalFileStorage",
    "STORAGE_BACKEND_NAME",
    "RANGE_CHUNK_BYTES",
    "archive_key",
]

_LOG = get_logger(__name__)

STORAGE_BACKEND_NAME: Final[str] = "local_file"

#: Path separators and traversal are the only shapes a key may not take.
_FORBIDDEN_KEY_PARTS: Final[frozenset[str]] = frozenset({"", ".", ".."})

#: One read per ``asyncio.to_thread`` hop while streaming. 64 KiB is the size §12.7 names:
#: big enough that a three-minute song is a few hundred hops, small enough that a stalled
#: client cannot pin a worker thread on a multi-megabyte read.
RANGE_CHUNK_BYTES: Final[int] = 64 * 1024

#: Every message a range or existence failure can carry. They are CONSTANTS on purpose:
#: ``hbd.admin.errors`` puts ``HbdError.operator_message`` on the wire verbatim while it
#: drops ``context``, so a message that interpolated the key or the resolved path would
#: hand a 404 body the filesystem layout of the host (admin plan §12.1 T4).
_ABSENT_MESSAGE: Final[str] = "no such object in local storage"
_UNREADABLE_MESSAGE: Final[str] = "could not read an object from local storage"


def archive_key(order_id: object, filename: str) -> str:
    """The ONE spelling of an archived asset's object key: ``orders/{order_id}/{filename}``.

    Three call sites need this string and they must agree byte for byte, because they are
    the write, the record and the sweep of the same object: ``pipeline.assets`` puts the
    bytes here, ``db.repository._replace_assets`` records it on the row, and
    ``db.purge._purge_assets`` reconstructs it for rows written before that record existed.
    Two spellings of the key is precisely the archive-orphan bug those three exist to close,
    so it is written once, here, in the layer that owns the key namespace — outside the
    class, so it survives ``LocalFileStorage`` being replaced by an S3 backend.
    """
    return f"orders/{order_id}/{filename}"


def _invalid_key(key: str, reason: str) -> Err:
    """An ``Err``, not a ``Result[None]``: it has to slot into every method's return type."""
    return err(
        ValidationError(
            f"storage key is not usable: {reason}",
            context={"key": key, "reason": reason, "backend": STORAGE_BACKEND_NAME},
        )
    )


def _invalid_range(key: str, reason: str) -> Err:
    """A refused byte range. ``reason`` is a constant, never the offsets or the path."""
    return err(
        ValidationError(
            f"byte range is not usable: {reason}",
            context={"key": key, "reason": reason, "backend": STORAGE_BACKEND_NAME},
        )
    )


def _absent(key: str) -> Err:
    """``NotFoundError``, not ``StorageError``: "gone" and "broken" are different answers.

    ``get`` answers a missing object with a retryable ``StorageError`` and that is left
    alone — changing it would move an existing, tested contract. The streaming seam is new
    and can be honest: a caller mapping this to 404 must not also map a disk fault to 404.
    """
    return err(
        NotFoundError(
            _ABSENT_MESSAGE,
            context={"key": key, "backend": STORAGE_BACKEND_NAME},
        )
    )


class LocalFileStorage:
    """Filesystem-backed ``hbd.contracts.Storage``. Safe to share across tasks."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    @property
    def root(self) -> Path:
        return self._root

    # -- key handling -------------------------------------------------------
    def _resolve(self, key: str) -> Path | Err:
        """Map a key to a path under the root, or explain why it cannot be."""
        trimmed = key.strip()
        if not trimmed:
            return _invalid_key(key, "empty")
        if trimmed.startswith("/") or "\\" in trimmed or "\x00" in trimmed:
            return _invalid_key(key, "absolute or contains an illegal character")
        parts = trimmed.split("/")
        if any(part in _FORBIDDEN_KEY_PARTS for part in parts):
            return _invalid_key(key, "contains an empty or traversing segment")
        candidate = (self._root / trimmed).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            return _invalid_key(key, "escapes the storage root")
        return candidate

    # -- protocol -----------------------------------------------------------
    async def put(self, key: str, data: bytes, *, content_type: str) -> Result[StoredObject]:
        resolved = self._resolve(key)
        if not isinstance(resolved, Path):
            return resolved
        try:
            await asyncio.to_thread(_write_atomically, resolved, data)
        except OSError as exc:
            return err(
                StorageError(
                    "could not write an object to local storage",
                    context={"key": key, "path": str(resolved), "detail": str(exc)},
                    cause=exc,
                )
            )
        stored = StoredObject(
            key=key,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            content_type=content_type,
        )
        _LOG.info(
            "object stored",
            extra={"key": key, "size_bytes": stored.size_bytes, "backend": STORAGE_BACKEND_NAME},
        )
        return ok(stored)

    async def get(self, key: str) -> Result[bytes]:
        resolved = self._resolve(key)
        if not isinstance(resolved, Path):
            return resolved
        try:
            data = await asyncio.to_thread(resolved.read_bytes)
        except OSError as exc:
            return err(
                StorageError(
                    "could not read an object from local storage",
                    context={"key": key, "path": str(resolved), "detail": str(exc)},
                    cause=exc,
                )
            )
        return ok(data)

    async def signed_url(self, key: str, *, ttl_s: int) -> Result[str]:
        """A ``file://`` URL. This backend has no credential to sign with, and says so."""
        resolved = self._resolve(key)
        if not isinstance(resolved, Path):
            return resolved
        if not resolved.exists():
            return err(
                StorageError(
                    "cannot address an object that is not stored",
                    context={"key": key, "backend": STORAGE_BACKEND_NAME},
                )
            )
        return ok(resolved.as_uri())

    async def delete(self, key: str) -> Result[None]:
        """Removing something that is already gone is success, not an error."""
        resolved = self._resolve(key)
        if not isinstance(resolved, Path):
            return resolved
        try:
            await asyncio.to_thread(resolved.unlink, True)
        except OSError as exc:
            return err(
                StorageError(
                    "could not delete an object from local storage",
                    context={"key": key, "path": str(resolved), "detail": str(exc)},
                    cause=exc,
                )
            )
        return ok(None)

    # -- streaming ----------------------------------------------------------
    async def size(self, key: str) -> Result[int]:
        """The object's length in bytes, or why it has none."""
        resolved = self._resolve(key)
        if not isinstance(resolved, Path):
            return resolved
        measured = await self._measure(key, resolved)
        if isinstance(measured, Err):
            return measured
        return ok(measured)

    async def open_range(self, key: str, *, start: int, end: int) -> Result[AsyncIterator[bytes]]:
        """A bounded slice of one object, read in :data:`RANGE_CHUNK_BYTES` chunks.

        Confinement is delegated to ``_resolve`` and to nothing else. That is the whole
        point of the seam (admin plan §12.7): the panel gets a public member to stream
        through, so it never has to reach into a private method of this class nor restate
        the traversal rules somewhere they can drift out of agreement with these ones.

        Never built on :meth:`get`, which reads the whole object: one range request for
        the first hundred bytes of a song would otherwise load the entire song, and a
        browser's ``<audio>`` element issues many range requests per play.

        The returned iterator OWNS an open file handle. Exhausting it closes it, and so
        does ``aclose()`` — which is what a caller that abandons the stream half way must
        do, and what Starlette's ``StreamingResponse`` does on a client disconnect.
        """
        resolved = self._resolve(key)
        if not isinstance(resolved, Path):
            return resolved
        if start < 0:
            return _invalid_range(key, "start is negative")
        if end < start:
            return _invalid_range(key, "end precedes start")
        measured = await self._measure(key, resolved)
        if isinstance(measured, Err):
            return measured
        if start >= measured:
            # Includes the empty object, for which every range is unsatisfiable.
            return _invalid_range(key, "start is at or past the end of the object")
        try:
            handle = await asyncio.to_thread(_open_for_read, resolved)
        except OSError as exc:
            return err(
                StorageError(
                    _UNREADABLE_MESSAGE,
                    context={"key": key, "path": str(resolved), "detail": str(exc)},
                    cause=exc,
                )
            )
        return ok(_stream(handle, key=key, start=start, last=min(end, measured - 1)))

    async def _measure(self, key: str, resolved: Path) -> int | Err:
        """``st_size``, or an ``Err``. ``int | Err`` mirrors ``_resolve``'s shape."""
        try:
            info = await asyncio.to_thread(resolved.stat)
        except FileNotFoundError:
            return _absent(key)
        except OSError as exc:
            return err(
                StorageError(
                    _UNREADABLE_MESSAGE,
                    context={"key": key, "path": str(resolved), "detail": str(exc)},
                    cause=exc,
                )
            )
        if not stat_module.S_ISREG(info.st_mode):
            # A directory key resolves and stats perfectly well. It is still not an object.
            return _absent(key)
        return info.st_size


def _open_for_read(path: Path) -> IO[bytes]:
    """Named so ``asyncio.to_thread`` gets an unambiguous, non-overloaded callable."""
    return path.open("rb")


async def _stream(handle: IO[bytes], *, key: str, start: int, last: int) -> AsyncIterator[bytes]:
    """Yield ``[start, last]`` inclusive, one chunk per thread hop, then close the handle.

    ``finally`` rather than a context manager: the consumer may abandon this generator
    half way through (a client that seeks, or disconnects, mid-song), and the file handle
    has to be released when the generator is closed rather than only when it is exhausted.
    """
    remaining = last - start + 1
    try:
        await asyncio.to_thread(handle.seek, start)
        while remaining > 0:
            chunk = await asyncio.to_thread(handle.read, min(RANGE_CHUNK_BYTES, remaining))
            if not chunk:
                # The object shrank under us. Stopping short beats looping forever.
                break
            remaining -= len(chunk)
            yield chunk
    except OSError as exc:
        # The one place this module raises: the response is already in flight, so there is
        # no Result left to return and truncating silently would look like a shorter song.
        raise StorageError(
            _UNREADABLE_MESSAGE,
            context={"key": key, "detail": str(exc)},
            cause=exc,
        ) from exc
    finally:
        await asyncio.to_thread(handle.close)


def _write_atomically(destination: Path, data: bytes) -> None:
    """Write to a sibling temp file, flush to disk, then rename over the target."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=destination.parent, suffix=".partial")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(destination)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
