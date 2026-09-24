"""The hourly job that finally deletes ``var/workspace``.

Every render writes its raw vendor download and every intermediate (``song-raw``, ``song``,
``song-tagged``, the greetings' ``-raw``/``-norm`` pairs) under ``var/workspace/{order_id}/``,
and until this module nothing ever removed any of it. The retention job cannot: it deletes
through the archive-rooted ``Storage``, and the workspace is outside that root and outside
every clock. On the dev box the workspace was 2.7x the size of the archive it feeds, and
``RetentionClass.EPHEMERAL`` — "intermediate renders" — was declared and written by nothing.
The media products make that untenable rather than untidy: a video's intermediates are ten
to a hundred times a song's (IMAGE_VIDEO_SPEC §0.3), so this lands before video does (M0).

**WHAT IT DELETES** (IMAGE_VIDEO_SPEC §3.3, the ``workspace_sweep`` row). A directory is
removed only when BOTH hold:

* nothing under it has been modified for :data:`WORKSPACE_MIN_AGE` (24 h) — measured as the
  newest ``mtime`` anywhere in the tree, not the directory's own, because a re-run writes
  into an existing directory and only touches the files; and
* its owner is FINISHED — the order (or, from M2, the media job) is in a terminal state, or
  its row no longer exists at all. An absent row means retention already purged it, and the
  workspace copy of its audio has then outlived the promise the archive copy kept.

  A terminal order whose song was never sent is NOT finished. ``DELIVERED`` is written
  before Telegram is tried, so a kit the customer never received (they blocked the bot,
  Telegram was down) is terminal with ``tg_file_id`` still NULL — and archival reports its
  failures as gaps rather than failing the order, so its workspace can be the only copy of
  what was paid for. A later replay reads that workspace. Such an order is kept until
  retention removes its asset rows; that is rare enough to cost nothing.

Anything else is kept: a live order, a directory whose name is not an id, a symlink, a stray
file. The sweep deletes what it can PROVE is finished, never what it merely cannot explain.

**Two namespaces, one rule.** Legacy song workspaces are ``var/workspace/{order_id}/``;
media jobs get ``var/workspace/media/{job_id}/`` (IMAGE_VIDEO_SPEC §3.6). Each namespace has
its own "which of these ids are finished" lookup. The media one answers "none" until the
``media_jobs`` table exists (M2): with no table there is no terminal state to read, and a
sweep that guessed would be deleting a paid job's frames on a hunch.

**Why 24 hours and not the 7-day ``EPHEMERAL`` period.** The workspace is not a record, it is
scratch: delivery reads it once, archival copies it once, and both happen within minutes of
the render. What matters after that is the archive. 24 h also outlasts arq's whole retry
ladder for a kit job, so a redelivered job for a DELIVERED order — the only reader that
comes back to a finished workspace — has long since run. A FAILED order that is re-run later
simply recreates its directory; the pipeline ``mkdir``s every parent it writes into.

**The one race, and how narrow it is.** A FAILED order re-run in the instant between this
job reading its state and removing its directory would lose files written in that instant.
The tree's age is re-measured immediately before removal, so a re-run that has written even
one file is spared; what is left is a window of one ``stat`` walk, on an order that sat
untouched for a day.

**IT NEVER RAISES INTO THE SCHEDULER**, for :mod:`bayram.runtime.retention_job`'s reason. A
lookup that fails deletes nothing and returns a summary carrying the failure — fail closed:
an unreadable database must not become "every owner is finished".
"""

from __future__ import annotations

import asyncio
import os
import shutil
import stat as stat_module
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import AssetKind, OrderState
from bayram.db.base import utc_now
from bayram.db.models import AssetRow, OrderRow
from bayram.errors import PipelineError
from bayram.logging import get_logger
from bayram.runtime.container import AppContainer

__all__ = [
    "MEDIA_WORKSPACE_DIRNAME",
    "TERMINAL_ORDER_STATES",
    "WORKSPACE_MIN_AGE",
    "WORKSPACE_SWEEP_CRON_MINUTE",
    "WORKSPACE_SWEEP_JOB_NAME",
    "FinishedLookup",
    "WorkspaceSweepReport",
    "finished_media_jobs_before_m2",
    "finished_orders_lookup",
    "run_workspace_sweep",
    "sweep_workspace",
]

_LOG = get_logger(__name__)

#: ARQ dispatches by function name, so the registration in ``WorkerSettings`` and the
#: function must agree on this exact string. Asserted against the function at import.
WORKSPACE_SWEEP_JOB_NAME: Final[str] = "run_workspace_sweep"

#: Minute past the hour. Not ``:00``, and not a minute any other cron in this worker owns
#: (7, 17, 43, the Payme sweep's multiples of five, the broadcast sweep's ``:04, :09, …``):
#: this one reads ``orders`` and walks the disk, and has no reason to do either while the
#: retention purge holds its transaction.
WORKSPACE_SWEEP_CRON_MINUTE: Final[int] = 31

#: How long a workspace must have sat untouched before it may go (IMAGE_VIDEO_SPEC §3.3).
WORKSPACE_MIN_AGE: Final[timedelta] = timedelta(hours=24)

#: The media namespace under the workspace root: ``var/workspace/media/{job_id}/``.
MEDIA_WORKSPACE_DIRNAME: Final[str] = "media"

#: The states after which nothing will read an order's workspace again. ``OrderState``'s
#: own docstring names ``FAILED`` and ``DELIVERED``; ``CANCELLED`` never renders again either.
TERMINAL_ORDER_STATES: Final[frozenset[OrderState]] = frozenset(
    {OrderState.DELIVERED, OrderState.FAILED, OrderState.CANCELLED}
)

#: Ids per ``IN (…)`` list. Postgres takes far more; this keeps one statement small enough
#: to read in a slow-query log and is still one round trip for any realistic backlog.
_LOOKUP_BATCH: Final[int] = 500

#: The kit job's context key, re-stated rather than imported. Importing it from ``jobs``
#: would make this module depend on the one that depends on it.
CONTAINER_CTX_KEY: Final[str] = "container"

#: "Of these ids, which are finished?" — terminal, or no longer on record at all.
FinishedLookup = Callable[[frozenset[UUID]], Awaitable[frozenset[UUID]]]


@dataclass(frozen=True, slots=True)
class WorkspaceSweepReport:
    """What one pass did. Every directory it looked at lands in exactly one count."""

    deleted: int = 0
    bytes_freed: int = 0
    #: Old enough, but its order or job is still live.
    kept_live: int = 0
    #: Something under it was modified within :data:`WORKSPACE_MIN_AGE`.
    kept_recent: int = 0
    #: Not a directory named by an id — left alone, never guessed at.
    skipped_unrecognised: int = 0
    #: The filesystem refused to let it be measured or removed. Kept; logged one by one.
    failed: int = 0

    @property
    def examined(self) -> int:
        return (
            self.deleted
            + self.kept_live
            + self.kept_recent
            + self.skipped_unrecognised
            + self.failed
        )


@dataclass(frozen=True, slots=True)
class _Candidate:
    owner_id: UUID
    path: Path
    newest_mtime: float
    size_bytes: int


@dataclass(slots=True)
class _Scan:
    orders: list[_Candidate] = field(default_factory=list)
    media: list[_Candidate] = field(default_factory=list)
    unrecognised: int = 0
    #: Directories the filesystem would not let us measure. Kept, logged, and counted in
    #: :attr:`WorkspaceSweepReport.failed` — one unreadable tree must not stop the rest.
    failed: int = 0

    def add(self, into: list[_Candidate], owner: UUID, path: Path) -> None:
        try:
            into.append(_candidate(owner, path))
        except OSError as exc:
            self.failed += 1
            _LOG.error(
                "a workspace could not be measured; it is kept",
                extra={"path": str(path), "detail": str(exc)},
            )


# ---------------------------------------------------------------------------
# The filesystem half — synchronous, run in a worker thread
# ---------------------------------------------------------------------------
def _as_uuid(name: str) -> UUID | None:
    try:
        parsed = UUID(name)
    except ValueError:
        return None
    # ``UUID`` also accepts braces, ``urn:uuid:`` and hyphen-free hex. The pipeline writes
    # ``str(order_id)`` and nothing else, so anything else is not one of ours.
    return parsed if str(parsed) == name else None


def _measure_tree(path: Path) -> tuple[float, int]:
    """``(newest mtime, total bytes)`` over ``path`` and everything under it.

    ``lstat`` and ``followlinks=False`` throughout: a symlink inside a workspace is measured
    as the link, never as whatever it points at, so a link cannot make a tree look young or
    large on another directory's behalf.
    """
    newest = path.lstat().st_mtime
    total = 0
    for directory, subdirectories, files in os.walk(path, followlinks=False):
        for name in (*subdirectories, *files):
            try:
                info = (Path(directory) / name).lstat()
            except FileNotFoundError:
                continue
            newest = max(newest, info.st_mtime)
            if stat_module.S_ISREG(info.st_mode):
                total += info.st_size
    return newest, total


def _owned_directories(parent: Path) -> tuple[list[tuple[UUID, Path]], int]:
    """Every real directory under ``parent`` named by an id, plus a count of the rest."""
    owned: list[tuple[UUID, Path]] = []
    unrecognised = 0
    with os.scandir(parent) as entries:
        for entry in entries:
            owner = _as_uuid(entry.name)
            if owner is None or not entry.is_dir(follow_symlinks=False):
                unrecognised += 1
                continue
            owned.append((owner, Path(entry.path)))
    return owned, unrecognised


def _scan(root: Path) -> _Scan:
    scan = _Scan()
    if not root.is_dir():
        return scan
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.name == MEDIA_WORKSPACE_DIRNAME and entry.is_dir(follow_symlinks=False):
                try:
                    media, unrecognised = _owned_directories(Path(entry.path))
                except OSError as exc:
                    scan.failed += 1
                    _LOG.error(
                        "the media workspace could not be listed; it is kept",
                        extra={"path": entry.path, "detail": str(exc)},
                    )
                    continue
                scan.unrecognised += unrecognised
                for media_owner, path in media:
                    scan.add(scan.media, media_owner, path)
                continue
            owner = _as_uuid(entry.name)
            if owner is None or not entry.is_dir(follow_symlinks=False):
                scan.unrecognised += 1
                continue
            scan.add(scan.orders, owner, Path(entry.path))
    return scan


def _candidate(owner: UUID, path: Path) -> _Candidate:
    newest, size = _measure_tree(path)
    return _Candidate(owner_id=owner, path=path, newest_mtime=newest, size_bytes=size)


def _remove_if_still_idle(path: Path, *, cutoff: float) -> bool:
    """Remove ``path`` unless something under it was written since the owner was read.

    Returns ``False`` when the tree turned out to be live after all. Raises ``OSError``
    when removal was attempted and refused; the caller counts and logs that.
    """
    try:
        newest, _ = _measure_tree(path)
    except FileNotFoundError:
        return True
    if newest > cutoff:
        return False
    shutil.rmtree(path)
    return True


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------
async def sweep_workspace(
    root: Path,
    *,
    now: datetime,
    finished_orders: FinishedLookup,
    finished_media_jobs: FinishedLookup,
    min_age: timedelta = WORKSPACE_MIN_AGE,
) -> WorkspaceSweepReport:
    """One pass over ``root``: delete every idle directory whose owner is finished.

    The lookups are injected rather than built here so the rule — idle AND finished — can
    be tested against a directory tree without a database, and so M2 can hand in the
    ``media_jobs`` lookup without touching the rule. A lookup that raises propagates: the
    caller decides that it means "delete nothing", which is the only safe reading.
    """
    cutoff = (now - min_age).timestamp()
    scan = await asyncio.to_thread(_scan, root)

    kept_recent = 0
    deletable: list[_Candidate] = []
    kept_live = 0
    for candidates, lookup in ((scan.orders, finished_orders), (scan.media, finished_media_jobs)):
        idle = [c for c in candidates if c.newest_mtime <= cutoff]
        kept_recent += len(candidates) - len(idle)
        if not idle:
            continue
        finished = await lookup(frozenset(c.owner_id for c in idle))
        for candidate in idle:
            if candidate.owner_id in finished:
                deletable.append(candidate)
            else:
                kept_live += 1

    deleted = 0
    bytes_freed = 0
    failed = scan.failed
    for candidate in deletable:
        try:
            removed = await asyncio.to_thread(_remove_if_still_idle, candidate.path, cutoff=cutoff)
        except OSError as exc:
            failed += 1
            # One line per failure, with the path: it is the only handle an operator has
            # for removing it by hand, and a workspace path carries no customer data.
            _LOG.error(
                "a finished workspace could not be removed",
                extra={"path": str(candidate.path), "detail": str(exc)},
            )
            continue
        if not removed:
            kept_recent += 1
            continue
        deleted += 1
        bytes_freed += candidate.size_bytes

    return WorkspaceSweepReport(
        deleted=deleted,
        bytes_freed=bytes_freed,
        kept_live=kept_live,
        kept_recent=kept_recent,
        skipped_unrecognised=scan.unrecognised,
        failed=failed,
    )


# ---------------------------------------------------------------------------
# The lookups
# ---------------------------------------------------------------------------
def _batches(ids: Iterable[UUID]) -> Iterable[list[UUID]]:
    ordered = sorted(ids)
    for start in range(0, len(ordered), _LOOKUP_BATCH):
        yield ordered[start : start + _LOOKUP_BATCH]


def finished_orders_lookup(session_factory: async_sessionmaker[AsyncSession]) -> FinishedLookup:
    """Orders that are terminal or gone. Only the LIVE ones are read, and subtracted.

    Reading the live set rather than the terminal one is what makes "gone" count as
    finished without a second query: an id with no row is simply never in the live set.
    "Live" also takes in a terminal order holding a song Telegram never received — see the
    module docstring: its workspace may be the only copy a replay can send.
    """

    async def lookup(ids: frozenset[UUID]) -> frozenset[UUID]:
        live: set[UUID] = set()
        async with session_factory() as session:
            for batch in _batches(ids):
                unsent_song = (
                    sa.select(AssetRow.id)
                    .where(
                        AssetRow.order_id == OrderRow.id,
                        AssetRow.kind == AssetKind.SONG,
                        AssetRow.tg_file_id.is_(None),
                    )
                    .exists()
                )
                rows = await session.execute(
                    sa.select(OrderRow.id).where(
                        OrderRow.id.in_(batch),
                        sa.or_(
                            OrderRow.state.not_in(tuple(TERMINAL_ORDER_STATES)),
                            unsent_song,
                        ),
                    )
                )
                live.update(rows.scalars().all())
        return frozenset(ids - live)

    return lookup


async def finished_media_jobs_before_m2(ids: frozenset[UUID]) -> frozenset[UUID]:
    """No media job is finished, because no media job table exists yet.

    Nothing writes ``var/workspace/media/`` before M2 either, so this keeps nothing that
    anyone made. M2.4 replaces it with a ``media_jobs`` read shaped like
    :func:`finished_orders_lookup` (IMAGE_VIDEO_SPEC §3.3); until then, keep — never guess.
    """
    del ids
    return frozenset()


# ---------------------------------------------------------------------------
# The cron entry point
# ---------------------------------------------------------------------------
def _require_container(ctx: Mapping[str, Any]) -> AppContainer:
    container = ctx.get(CONTAINER_CTX_KEY)
    if not isinstance(container, AppContainer):
        raise PipelineError(
            "worker context is missing a usable 'container'",
            context={"key": CONTAINER_CTX_KEY, "found": type(container).__name__},
        )
    return container


def _summary(
    report: WorkspaceSweepReport, *, duration_ms: int, error: str | None
) -> dict[str, Any]:
    """The JSON-safe dict ARQ stores as the job result, and the log line's body."""
    return {
        "duration_ms": duration_ms,
        "examined": report.examined,
        "deleted": report.deleted,
        "bytes_freed": report.bytes_freed,
        "kept_live": report.kept_live,
        "kept_recent": report.kept_recent,
        "skipped_unrecognised": report.skipped_unrecognised,
        "failed": report.failed,
        "error": error,
    }


async def run_workspace_sweep(
    ctx: Mapping[str, Any],
    *,
    now: datetime | None = None,
    finished_media_jobs: FinishedLookup | None = None,
) -> dict[str, Any]:
    """Sweep the worker's workspace once and return a JSON-safe summary.

    ``now`` is injectable so a test can move a day forward instead of waiting for it, and
    ``finished_media_jobs`` so a test can stand in for the M2 lookup. ARQ's ``cron()``
    passes neither. Raises only ``PipelineError`` for a mis-wired worker.
    """
    container = _require_container(ctx)
    started = time.monotonic()
    error: str | None = None
    try:
        report = await sweep_workspace(
            container.workspace_root,
            now=now or utc_now(),
            finished_orders=finished_orders_lookup(container.require_session_factory()),
            finished_media_jobs=finished_media_jobs or finished_media_jobs_before_m2,
        )
    except Exception as exc:
        # Fail closed. Every lookup runs before the first removal, so a database that did
        # not answer removed nothing at all; a refused removal never reaches here (it is
        # counted in ``failed``). The next hour is the retry.
        _LOG.error("the workspace sweep failed", extra={"failure": repr(exc)}, exc_info=exc)
        report = WorkspaceSweepReport()
        error = type(exc).__name__
    summary = _summary(report, duration_ms=int((time.monotonic() - started) * 1000), error=error)
    _LOG.info("workspace sweep finished", extra=summary)
    return summary


assert run_workspace_sweep.__name__ == WORKSPACE_SWEEP_JOB_NAME, (
    "the enqueue name and the job function have drifted apart; ARQ would never dispatch"
)
