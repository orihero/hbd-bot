"""The one path from the panel to the worker, and it is a Redis write and nothing else.

**Why this module exists at all.** Until it did, the admin process had no way to ask the
worker for anything: every job in this system is enqueued by the bot or by a cron, and
``grep -rn "enqueue_job" src/hbd/admin/`` returned nothing. A broadcast is the first admin
action whose work cannot be done inside the request — materialising forty thousand recipient
rows and then sending forty thousand messages is an hour of wall clock — so the seam had to
be built (``BROADCAST_SPEC §3.6``).

**It is a seam and not a shortcut.** The admin process is forbidden a bot token (D10, held
open by :data:`hbd.admin.app.FORBIDDEN_ENV_VARS` and by ``AdminSettings`` having no field to
put one in), so the panel cannot send a message and must not be able to. What it can do is
name a job and hand over an id. Enqueueing needs no credential, no HTTP client and no
``Bot``; the worker owns all three. Nothing in this module imports ``aiogram``, and that is
the property that keeps the split honest rather than merely conventional.

**Its own Redis handle, deliberately.** The queue's :class:`~arq.ArqRedis` is built over a
*separate* connection pool from ``AdminContainer.redis``. The panel's client is
``decode_responses=True`` because it stores sessions and CSRF tokens as text; arq's payloads
are pickled bytes, and decoding them as UTF-8 corrupts them at the first non-trivial read. A
shared pool would work for exactly as long as every payload happened to be ASCII.

**Nothing here connects at construction.** ``arq.create_pool`` pings on the way up, which
would make ``/healthz`` and the bootstrap CLI depend on a Redis that may not be running yet —
the very thing ``hbd.admin.container`` documents it will not do. So the pool is lazy and the
first command is the first connection, exactly as ``hbd.payme.container`` builds its handle,
and an unreachable Redis surfaces as a 503 on the one route that enqueues rather than as a
process that will not boot.

**A failed enqueue is not a failed campaign.** The write and its audit row commit with the
request transaction; the enqueue is the last statement in the handler. The worker's due sweep
(``BROADCAST_SPEC §4.1``) re-enqueues any campaign that is due and has no live job, so this
seam is an optimisation on the latency of the first chunk — never the only path — and a
``None`` from ARQ (the job id is already queued) is the idempotency guarantee working rather
than a failure, the same reading :class:`hbd.runtime.submitter.ArqOrderSubmitter` gives it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID, uuid4

from arq import ArqRedis
from redis.exceptions import RedisError

from hbd.contracts import Result, err, ok
from hbd.errors import StorageError
from hbd.logging import get_logger

__all__ = [
    "EXPAND_JOB_NAME",
    "SEND_JOB_NAME",
    "TEST_SEND_JOB_NAME",
    "AdminQueue",
    "ArqAdminQueue",
    "NullAdminQueue",
    "RecordedEnqueue",
    "job_id_for_expand",
    "job_id_for_send",
    "job_id_for_test_send",
]

_LOGGER: Final = get_logger(__name__)

#: ARQ dispatches by function name, so these three strings and the worker's coroutines must
#: agree exactly. They are stated here rather than imported from ``hbd.runtime.broadcast_job``
#: for the reason ``ARCHIVE_DIRNAME`` is stated twice: importing that module would pull the
#: whole runtime container — provider set, ffmpeg post-processor, ``Bot`` — into a process
#: whose entire point is that it holds none of them. The worker restates them beside its own
#: ``assert fn.__name__ == JOB_NAME``, which is what keeps the two copies from drifting.
EXPAND_JOB_NAME: Final[str] = "expand_broadcast_audience"
SEND_JOB_NAME: Final[str] = "send_broadcast_chunk"
TEST_SEND_JOB_NAME: Final[str] = "send_broadcast_test"

#: Every job id this seam mints starts here, so one ``SCAN`` shows an operator every broadcast
#: job in flight without knowing which of the three it is looking for.
_JOB_ID_PREFIX: Final[str] = "broadcast"


def job_id_for_expand(broadcast_id: UUID) -> str:
    """Deterministic: one expansion per campaign, ever.

    ``job_id_for_*`` rather than ``*_job_id``, following ``hbd.pipeline.worker.job_id_for``.
    The prefix order is not cosmetic: ``test_send_job_id`` is a module-level callable whose
    name starts with ``test_``, so pytest collects it out of the test module that imports it
    and reports it as an error with a missing fixture.

    ARQ refuses to queue an id it already holds, so a double-clicked Create costs nothing and
    two replicas racing the same request cannot both start materialising the audience.
    """
    return f"{_JOB_ID_PREFIX}:expand:{broadcast_id}"


def job_id_for_send(broadcast_id: UUID) -> str:
    """Deterministic: at most one chunk job per campaign in flight (``BROADCAST_SPEC §4.4``).

    That is what stops two workers claiming overlapping windows of the same recipient table.
    A refused duplicate is reported as success by :class:`ArqAdminQueue` — the campaign is
    already being sent, which is what the caller asked for — and a campaign whose chunk job
    has since finished is picked up by the due sweep, so the exclusivity costs no progress.
    """
    return f"{_JOB_ID_PREFIX}:send:{broadcast_id}"


def job_id_for_test_send(broadcast_id: UUID) -> str:
    """Unique per call, and that is the one place determinism would be wrong.

    An operator asks for a second test send *because* they changed the body. Under a
    deterministic id ARQ would refuse the repeat for as long as the first job's result lives
    (``keep_result``, an hour by default) and the panel would silently do nothing — so the id
    carries a fresh suffix. Minting it here rather than letting ARQ generate one keeps the id
    knowable before the call, which is what lets the failure path name the job it lost.
    """
    return f"{_JOB_ID_PREFIX}:test:{broadcast_id}:{uuid4().hex}"


class AdminQueue(Protocol):
    """The three things the panel may ask the worker to do, and no fourth.

    A protocol rather than a concrete client so a test never needs a Redis, and so the
    surface stays a list somebody has to extend on purpose. Every method returns a
    ``Result`` carrying the job id: an enqueue is I/O over a network and the repo's rule is
    that such a failure crosses a boundary as an ``Err`` and not as an exception —
    :func:`hbd.admin.errors.unwrap` turns it into the standard envelope at the handler.

    There is no ``enqueue_cancel`` or ``enqueue_pause``. Pausing is a column, read by the
    chunk job every twenty-five messages (``BROADCAST_SPEC §4.4``); enqueueing a job to stop
    a job would put the two in a race whose loser sends messages after the operator was told
    it had stopped.
    """

    async def enqueue_expand(self, broadcast_id: UUID, *, now: datetime) -> Result[str]:
        """Materialise the campaign's recipient rows, as of ``now``.

        ``now`` is the instant the audience is frozen at, passed as an argument rather than
        read by the worker, because expansion is a resumable multi-chunk job and every chunk
        must compile the segment against the *same* instant — a rule like "joined in the last
        thirty days" that re-reads the clock per chunk selects a different population each
        time, and the audience would not be frozen at all.
        """
        ...

    async def enqueue_send(self, broadcast_id: UUID) -> Result[str]:
        """Start (or resume) delivery to the rows that are already there.

        Takes no instant: the send re-checks eligibility against fresh ``users`` state by
        design, so the worker's clock is the right one and a stale one would be a lie.
        """
        ...

    async def enqueue_test_send(self, broadcast_id: UUID, *, telegram_user_id: int) -> Result[str]:
        """Send the composed body to exactly one account — the operator's own.

        The recipient is an argument and not a lookup, so the job cannot be talked into
        addressing anyone but the account the handler resolved.
        """
        ...

    async def aclose(self) -> None:
        """Release whatever the implementation holds. Called once, by the container."""
        ...


class ArqAdminQueue:
    """:class:`AdminQueue` over ARQ. Production, and the only implementation that does I/O.

    Owns the :class:`~arq.ArqRedis` it is handed: the container builds the pool, gives it to
    this object and closes it through :meth:`aclose`, so the panel never holds a second Redis
    handle it could accidentally issue a session command on.
    """

    __slots__ = ("_redis",)

    def __init__(self, redis: ArqRedis) -> None:
        self._redis = redis

    async def enqueue_expand(self, broadcast_id: UUID, *, now: datetime) -> Result[str]:
        return await self._enqueue(
            EXPAND_JOB_NAME,
            str(broadcast_id),
            now.isoformat(),
            job_id=job_id_for_expand(broadcast_id),
        )

    async def enqueue_send(self, broadcast_id: UUID) -> Result[str]:
        return await self._enqueue(
            SEND_JOB_NAME, str(broadcast_id), job_id=job_id_for_send(broadcast_id)
        )

    async def enqueue_test_send(self, broadcast_id: UUID, *, telegram_user_id: int) -> Result[str]:
        return await self._enqueue(
            TEST_SEND_JOB_NAME,
            str(broadcast_id),
            telegram_user_id,
            job_id=job_id_for_test_send(broadcast_id),
        )

    async def aclose(self) -> None:
        # ``aclose`` since redis-py 5.0.1; ``close`` is deprecated. The pinned ``types-redis``
        # 4.6 stubs predate the rename and shadow redis-py's own inline types, so the call is
        # correct at runtime and invisible to mypy — the same suppression
        # ``hbd.admin.container`` carries, for the same stub.
        await self._redis.aclose()  # type: ignore[attr-defined]

    async def _enqueue(self, job: str, *arguments: object, job_id: str) -> Result[str]:
        """One enqueue, one failure taxonomy. Never raises.

        ``RedisError`` is caught beside ``OSError`` — and ``ArqOrderSubmitter``, which catches
        the pair ``(TimeoutError, OSError)``, is the precedent this widens rather than
        contradicts. ``TimeoutError`` has subclassed ``OSError`` since 3.10, but redis-py's
        own exceptions do not: a ``ConnectionError`` or a ``ResponseError`` raised inside the
        client would otherwise leave this method as an exception, and the panel would answer a
        Redis blip with a 500 instead of the 503 that tells an operator to look at Redis.
        """
        try:
            handle = await self._redis.enqueue_job(job, *arguments, _job_id=job_id)
        except (OSError, RedisError) as exc:
            return err(
                StorageError(
                    "could not reach Redis to enqueue the broadcast job",
                    context={"job": job, "job_id": job_id},
                    cause=exc,
                )
            )
        if handle is None:
            # ARQ returns None when the id is already queued. That is the idempotency
            # guarantee doing its job, not a failure: the work is already under way.
            _LOGGER.info(
                "broadcast job was already queued; ignoring the duplicate",
                extra={"event": "admin.queue.duplicate", "job": job, "job_id": job_id},
            )
            return ok(job_id)
        return ok(str(handle.job_id))


@dataclass(frozen=True, slots=True)
class RecordedEnqueue:
    """One call :class:`NullAdminQueue` did not make, kept so a test can assert on it."""

    job: str
    broadcast_id: UUID
    job_id: str
    arguments: tuple[object, ...]


class NullAdminQueue:
    """:class:`AdminQueue` that records the call and enqueues nothing. Two uses, one class.

    **In tests** it is the default injection: a router test asserts that creating a campaign
    asked for an expansion, with the campaign's id and the request's instant, without a Redis
    and without a worker to answer. Recording rather than counting is what makes that an
    assertion about the *arguments* — a seam that enqueued the wrong id would pass a counter.

    **In a deployment with no worker** it is constructed ``refusing=True``, and then every
    call is recorded and answered with an ``Err``. Accepting a campaign nothing will ever
    send is the worse failure by a distance: the operator is told it went out, and the only
    evidence otherwise is a counter that never moves.

    The refusal carries a :class:`~hbd.errors.StorageError` and not the ``ConfigError``
    ``BROADCAST_SPEC §3.6`` names, because the spec asked for "a legible 503" and
    :data:`hbd.admin.errors.STATUS_BY_ERROR_CODE` maps ``CONFIG_INVALID`` to **422**. A
    missing worker is an unavailable dependency, not a malformed request, so the code that
    renders the status the spec asked for is the one that is used.
    """

    __slots__ = ("_refusing", "calls")

    def __init__(self, *, refusing: bool = False) -> None:
        self.calls: list[RecordedEnqueue] = []
        self._refusing = refusing

    async def enqueue_expand(self, broadcast_id: UUID, *, now: datetime) -> Result[str]:
        return self._record(
            EXPAND_JOB_NAME,
            broadcast_id,
            job_id_for_expand(broadcast_id),
            (str(broadcast_id), now.isoformat()),
        )

    async def enqueue_send(self, broadcast_id: UUID) -> Result[str]:
        return self._record(
            SEND_JOB_NAME, broadcast_id, job_id_for_send(broadcast_id), (str(broadcast_id),)
        )

    async def enqueue_test_send(self, broadcast_id: UUID, *, telegram_user_id: int) -> Result[str]:
        return self._record(
            TEST_SEND_JOB_NAME,
            broadcast_id,
            job_id_for_test_send(broadcast_id),
            (str(broadcast_id), telegram_user_id),
        )

    async def aclose(self) -> None:
        """Nothing is held, so nothing is released. Present because the protocol has it."""

    def _record(
        self, job: str, broadcast_id: UUID, job_id: str, arguments: tuple[object, ...]
    ) -> Result[str]:
        """Record first, refuse second.

        What the panel *tried* to enqueue is the interesting half of a deployment that
        cannot enqueue anything.
        """
        self.calls.append(
            RecordedEnqueue(job=job, broadcast_id=broadcast_id, job_id=job_id, arguments=arguments)
        )
        if self._refusing:
            return err(
                StorageError(
                    "this deployment has no ARQ worker, so the broadcast cannot be queued",
                    context={"job": job, "broadcast_id": str(broadcast_id)},
                )
            )
        return ok(job_id)
