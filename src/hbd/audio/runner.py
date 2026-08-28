"""The one place a child process is spawned.

Every ffmpeg/ffprobe invocation in this package goes through :func:`run_command`, so the
four things that can go wrong — binary missing, non-zero exit, hang, OS refusal — are
handled once, with the stderr tail captured into the error context every time.

Nothing here raises: a failure is an ``Err(AudioProcessingError)``.
"""

from __future__ import annotations

import asyncio
from asyncio.subprocess import DEVNULL, PIPE, Process
from collections.abc import Sequence
from dataclasses import dataclass

from hbd.audio.constants import (
    MAX_CAPTURED_STDERR_CHARS,
    PROCESS_KILL_GRACE_S,
)
from hbd.contracts import Result, err, ok
from hbd.errors import AudioProcessingError
from hbd.logging import get_logger

__all__ = ["CommandResult", "run_command", "tail"]

_LOG = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """A finished child process. Immutable, and only ever built on a zero exit."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def tail(text: str, *, limit: int = MAX_CAPTURED_STDERR_CHARS) -> str:
    """Keep the END of a long stream — ffmpeg reports its failure on the last lines."""
    if len(text) <= limit:
        return text
    return f"…[{len(text) - limit} chars truncated]…{text[-limit:]}"


def _decode(raw: bytes) -> str:
    """ffmpeg emits whatever the source metadata contained; never let a decode explode."""
    return raw.decode("utf-8", errors="replace")


async def _kill(process: Process) -> None:
    """Best-effort teardown of a process that overran its deadline."""
    if process.returncode is not None:
        return
    try:
        process.kill()
        await asyncio.wait_for(process.wait(), timeout=PROCESS_KILL_GRACE_S)
    except (ProcessLookupError, TimeoutError) as exc:
        _LOG.warning(
            "audio.subprocess.kill_failed",
            extra={"pid": process.pid, "reason": type(exc).__name__},
        )


async def run_command(
    args: Sequence[str],
    *,
    operation: str,
    timeout_s: float,
) -> Result[CommandResult]:
    """Run ``args`` to completion, capturing both streams.

    ``operation`` is a short slug (``"loudnorm.measure"``) that lands in the log and in
    the error context, so a responder can tell which of four ffmpeg passes failed.
    """
    argv = tuple(args)
    context = {"operation": operation, "command": " ".join(argv), "timeout_s": timeout_s}

    try:
        process = await asyncio.create_subprocess_exec(
            *argv, stdin=DEVNULL, stdout=PIPE, stderr=PIPE
        )
    except FileNotFoundError as exc:
        return err(
            AudioProcessingError(
                f"{operation}: executable {argv[0]!r} not found. "
                "Startup should have caught this — see hbd.audio.ensure_ffmpeg_available.",
                is_retryable=False,
                context=context,
                cause=exc,
            )
        )
    except OSError as exc:
        return err(
            AudioProcessingError(
                f"{operation}: the operating system refused to start {argv[0]!r}: {exc}",
                context=context,
                cause=exc,
            )
        )

    try:
        raw_stdout, raw_stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except TimeoutError as exc:
        await _kill(process)
        return err(
            AudioProcessingError(
                f"{operation}: killed after exceeding {timeout_s}s",
                context=context,
                cause=exc,
            )
        )

    stdout, stderr = _decode(raw_stdout), _decode(raw_stderr)
    returncode = process.returncode if process.returncode is not None else -1
    if returncode != 0:
        return err(
            AudioProcessingError(
                f"{operation}: exited {returncode}",
                context={**context, "returncode": returncode, "stderr": tail(stderr)},
            )
        )

    _LOG.debug("audio.subprocess.ok", extra={"operation": operation})
    return ok(CommandResult(args=argv, returncode=returncode, stdout=stdout, stderr=stderr))
