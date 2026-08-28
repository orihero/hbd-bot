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
  underlying cause, because archival failing must degrade a kit, not sink it.

``signed_url`` returns a ``file://`` URL. That is honest: this backend cannot mint a
credential, and pretending otherwise would hand the bot an address it cannot send. The day
S3/R2 lands, it replaces this class behind the same protocol and nothing else moves.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Final

from hbd.contracts import Err, Result, StoredObject, err, ok
from hbd.errors import StorageError, ValidationError
from hbd.logging import get_logger

__all__ = ["LocalFileStorage", "STORAGE_BACKEND_NAME"]

_LOG = get_logger(__name__)

STORAGE_BACKEND_NAME: Final[str] = "local_file"

#: Path separators and traversal are the only shapes a key may not take.
_FORBIDDEN_KEY_PARTS: Final[frozenset[str]] = frozenset({"", ".", ".."})


def _invalid_key(key: str, reason: str) -> Err:
    """An ``Err``, not a ``Result[None]``: it has to slot into every method's return type."""
    return err(
        ValidationError(
            f"storage key is not usable: {reason}",
            context={"key": key, "reason": reason, "backend": STORAGE_BACKEND_NAME},
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
