"""Scratch space that is always cleaned up, and writes that are never half-finished.

Two invariants this module exists to hold:

* A failed render leaves NO temp file behind — the scratch directory is removed in a
  ``finally``, on the success path and on every exception path alike.
* A failed render leaves NO partial destination either. ffmpeg writes into the scratch
  directory and the result is moved into place only once the process exited zero, so a
  reader can never observe a truncated file at the destination path.

The scratch directory is created NEXT TO the destination, which keeps the final move a
same-device rename rather than a copy that could itself fail halfway.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from hbd.audio.constants import SCRATCH_DIR_PREFIX
from hbd.logging import get_logger

__all__ = ["scratch_dir", "publish"]

_LOG = get_logger(__name__)


@contextmanager
def scratch_dir(destination: Path) -> Iterator[Path]:
    """Yield a private directory beside ``destination``, removed however the block ends."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix=SCRATCH_DIR_PREFIX, dir=destination.parent))
    try:
        yield path
    finally:
        _remove(path)


def _remove(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except OSError as exc:
        # Cleanup failure must never mask the real outcome, but it is never silent either.
        _LOG.warning(
            "audio.scratch.cleanup_failed",
            extra={"path": str(path), "reason": str(exc)},
        )


def publish(staged: Path, destination: Path) -> Path:
    """Move a finished file into place. Atomic within a filesystem; raises ``OSError``."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged.replace(destination)
    return destination
