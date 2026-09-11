"""The one path from the panel to the worker, and it is a Redis write and nothing else.

**Why this module exists at all.** Until it did, the admin process had no way to ask the
worker for anything: every job in this system is enqueued by the bot or by a cron, and
``grep -rn "enqueue_job" src/bayram/admin/`` returned nothing. A broadcast is the first admin
action whose work cannot be done inside the request — materialising forty thousand recipient
rows and then sending forty thousand messages is an hour of wall clock — so the seam had to
be built (``BROADCAST_SPEC §3.6``).

**It is a seam and not a shortcut.** The admin process is forbidden a bot token (D10, held
open by :data:`bayram.admin.app.FORBIDDEN_ENV_VARS` and by ``AdminSettings`` having no field to
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
the very thing ``bayram.admin.container`` documents it will not do. So the pool is lazy and the
first command is the first connection, exactly as ``bayram.payme.container`` builds its handle,
and an unreachable Redis surfaces as a 503 on the one route that enqueues rather than as a
process that will not boot.

**A failed enqueue is not a failed campaign.** The write and its audit row commit with the
request transaction; the enqueue is the last statement in the handler. The worker's due sweep
(``BROADCAST_SPEC §4.1``) re-enqueues any campaign that is due and has no live job, so this
seam is an optimisation on the latency of the first chunk — never the only path — and a
``None`` from ARQ (the job id is already queued) is the idempotency guarantee working rather
than a failure, the same reading :class:`bayram.runtime.submitter.ArqOrderSubmitter` gives it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID, uuid4

from arq import ArqRedis
from redis.exceptions import RedisError

from bayram.contracts import Result, err, is_err, ok
from bayram.errors import StorageError
from bayram.logging import get_logger

__all__ = [
    "EXPAND_JOB_NAME",
    "SEND_JOB_NAME",
    "TEST_SEND_JOB_NAME",
    "PAYMENT_NOTIFY_JOB_NAME",
    "AdminQueue",
    "ArqAdminQueue",
    "NullAdminQueue",
    "RecordedEnqueue",
    "job_id_for_expand",
    "job_id_for_send",
    "job_id_for_test_send",
    "job_id_for_payment_notification",
]

_LOGGER: Final = get_logger(__name__)

#: ARQ dispatches by function name, so these three strings and the worker's coroutines must
#: agree exactly. They are stated here rather than imported from ``bayram.runtime.broadcast_job``
#: for the reason ``ARCHIVE_DIRNAME`` is stated twice: importing that module would pull the
#: whole runtime container — provider set, ffmpeg post-processor, ``Bot`` — into a process
#: whose entire point is that it holds none of them. The worker restates them beside its own
#: ``assert fn.__name__ == JOB_NAME``, which is what keeps the two copies from drifting.
EXPAND_JOB_NAME: Final[str] = "expand_broadcast_audience"
SEND_JOB_NAME: Final[str] = "send_broadcast_chunk"
TEST_SEND_JOB_NAME: Final[str] = "send_broadcast_test"

#: The fourth, and restated for a HARDER version of the same reason. ``bayram.runtime.payme_jobs``
#: — where the worker's ``notify_payment_settled`` lives, beside ``PAYME_NOTIFY_JOB_NAME`` and
#: ``payme_notify_job_id`` — imports ``aiogram.Bot`` at module level, because sending the
#: message is its whole job. Importing it here to reuse those two symbols would put the
#: Telegram client in the admin process's import graph, which is the exact thing D10 forbids
#: and which ``test_the_seam_can_reach_nothing_that_sends_a_message`` fails on by reading this
#: file's ``import`` statements. So the string is spelled twice, on opposite sides of a process
#: boundary, and ``test_the_restated_job_names_match_the_ones_the_worker_registers`` is what
#: keeps the two copies equal — ARQ dispatches by name, so a rename that compiled on both sides
#: would leave customers unannounced with the money already banked.
PAYMENT_NOTIFY_JOB_NAME: Final[str] = "notify_payment_settled"

#: Every job id this seam mints starts here, so one ``SCAN`` shows an operator every broadcast
#: job in flight without knowing which of the three it is looking for.
_JOB_ID_PREFIX: Final[str] = "broadcast"


def job_id_for_expand(broadcast_id: UUID) -> str:
    """Deterministic: one expansion per campaign, ever.

    ``job_id_for_*`` rather than ``*_job_id``, following ``bayram.pipeline.worker.job_id_for``.
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


def job_id_for_payment_notification(public_ref: str) -> str:
    """Deterministic, and the determinism is doing two jobs rather than one.

    Byte-for-byte ``bayram.runtime.payme_jobs.payme_notify_job_id``, restated for the reason
    :data:`PAYMENT_NOTIFY_JOB_NAME` is. The two callers are now THREE processes — the Payme
    gateway's post-commit enqueue, the worker's own five-minute backstop sweep, and this panel
    — and ARQ refuses an id it already holds, so all three collapse onto ONE job rather than
    three messages to one customer. A second spelling would not break a build; it would quietly
    disable that collapse, and the symptom would be a customer told three times.

    Keyed on ``public_ref`` and never on the intent's ``idempotency_key``: that key is shaped
    ``topup:{telegram_user_id}:{scope}:{seq}``, so keying on it would write a customer's
    Telegram id into a Redis key name and into the worker's log lines — which is precisely what
    ``public_ref`` was minted to avoid.
    """
    return f"{PAYMENT_NOTIFY_JOB_NAME}:{public_ref}"


class AdminQueue(Protocol):
    """The four things the panel may ask the worker to do, and no fifth.

    A protocol rather than a concrete client so a test never needs a Redis, and so the
    surface stays a list somebody has to extend on purpose. Every method returns a
    ``Result`` carrying the job id: an enqueue is I/O over a network and the repo's rule is
    that such a failure crosses a boundary as an ``Err`` and not as an exception —
    :func:`bayram.admin.errors.unwrap` turns it into the standard envelope at the handler.

    There is no ``enqueue_cancel`` or ``enqueue_pause``. Pausing is a column, read by the
    chunk job every twenty-five messages (``BROADCAST_SPEC §4.4``); enqueueing a job to stop
    a job would put the two in a race whose loser sends messages after the operator was told
    it had stopped.

    **The fourth method widened a surface that was closed at three, so here is the argument.**
    The sentence above used to read "three things … and no fourth", and that was not
    decoration: a protocol somebody has to edit on purpose is the mechanism that keeps the
    panel from growing a general "run this job" hole. :meth:`enqueue_payment_notification`
    earns the edit because the population it serves is already ON the board —
    ``paidNeverAnnounced`` is a first-class count on the rail screen (``BILLING_RAIL_BOARD
    §4``) — and a finding whose remedy lives in a different tool over SSH is a finding that
    stays unactioned. Putting the remedy next to the finding is how a backlog stops being
    permanent.

    The rejected alternative was enqueuing ARQ from the handler directly, which would have
    needed no protocol change at all. It breaks the seam that lets every test in
    ``tests/test_admin`` run with no Redis and no worker — ``NullAdminQueue`` records the call
    that was not made, and a router test asserts on its ARGUMENTS — and it would put a second
    ARQ client in a process that already documents why it holds exactly one.
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

    async def enqueue_payment_notification(self, public_ref: str) -> Result[str | None]:
        """Re-announce ONE settled payment, named by the reference that crosses to the rail.

        **``Result[str | None]`` where its three siblings return ``Result[str]``, and the
        ``None`` is the point.** ARQ answers ``None`` when the deterministic job id is already
        queued, and for the broadcast trio that is read as success — the campaign is already
        being sent, which is what the caller asked for. Here the same fact is the ANSWER: the
        operator pressed "re-send the confirmation" and needs to know whether they queued a
        message or landed on one that was already in flight, which the response reports as
        ``isReplay``. Collapsing it to the job id, as :meth:`enqueue_send` does, would leave
        the panel unable to say which happened without asking ARQ a second question — and that
        second question races the worker, which may have finished the job between the two.

        ``public_ref`` and never the intent's ``idempotency_key`` or Telegram id: see
        :func:`job_id_for_payment_notification`. This method therefore cannot carry a customer
        identifier into Redis even if a caller had one to hand.
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

    async def enqueue_payment_notification(self, public_ref: str) -> Result[str | None]:
        """The one caller of :meth:`_dispatch` that keeps the duplicate as a duplicate."""
        return await self._dispatch(
            PAYMENT_NOTIFY_JOB_NAME,
            public_ref,
            job_id=job_id_for_payment_notification(public_ref),
        )

    async def aclose(self) -> None:
        # ``aclose`` since redis-py 5.0.1; ``close`` is deprecated. The pinned ``types-redis``
        # 4.6 stubs predate the rename and shadow redis-py's own inline types, so the call is
        # correct at runtime and invisible to mypy — the same suppression
        # ``bayram.admin.container`` carries, for the same stub.
        await self._redis.aclose()  # type: ignore[attr-defined]

    async def _dispatch(self, job: str, *arguments: object, job_id: str) -> Result[str | None]:
        """One enqueue, one failure taxonomy, and the duplicate reported AS a duplicate.

        Never raises. ``RedisError`` is caught beside ``OSError`` — and ``ArqOrderSubmitter``,
        which catches the pair ``(TimeoutError, OSError)``, is the precedent this widens rather
        than contradicts. ``TimeoutError`` has subclassed ``OSError`` since 3.10, but redis-py's
        own exceptions do not: a ``ConnectionError`` or a ``ResponseError`` raised inside the
        client would otherwise leave this method as an exception, and the panel would answer a
        Redis blip with a 500 instead of the 503 that tells an operator to look at Redis.

        ``ok(None)`` means ARQ already held this id. Split out of :meth:`_enqueue` rather than
        given a boolean flag, because the two readings are two different sentences to an
        operator and the type is what stops one being mistaken for the other: the broadcast
        trio reads a duplicate as success and says so in :meth:`_enqueue`, while
        :meth:`enqueue_payment_notification` reports it as ``isReplay``.
        """
        try:
            handle = await self._redis.enqueue_job(job, *arguments, _job_id=job_id)
        except (OSError, RedisError) as exc:
            return err(
                StorageError(
                    "could not reach Redis to enqueue the job",
                    context={"job": job, "job_id": job_id},
                    cause=exc,
                )
            )
        return ok(None if handle is None else str(handle.job_id))

    async def _enqueue(self, job: str, *arguments: object, job_id: str) -> Result[str]:
        """:meth:`_dispatch` for the three campaign jobs, where a duplicate IS success."""
        outcome = await self._dispatch(job, *arguments, job_id=job_id)
        if is_err(outcome):
            return err(outcome.error)
        if outcome.value is None:
            # ARQ returns None when the id is already queued. That is the idempotency
            # guarantee doing its job, not a failure: the work is already under way.
            _LOGGER.info(
                "broadcast job was already queued; ignoring the duplicate",
                extra={"event": "admin.queue.duplicate", "job": job, "job_id": job_id},
            )
            return ok(job_id)
        return ok(outcome.value)


@dataclass(frozen=True, slots=True)
class RecordedEnqueue:
    """One call :class:`NullAdminQueue` did not make, kept so a test can assert on it.

    **Two nullable subject fields rather than one ``subject: str``.** The four jobs are about
    two different kinds of thing — three campaigns and one payment — and a single stringly
    subject would let a test that meant to assert on a campaign id pass on a public reference
    that happened to be equal. Exactly one of the two is set on any row, and which one says
    which job family the call belongs to without parsing :attr:`job`.
    """

    job: str
    job_id: str
    arguments: tuple[object, ...]
    #: The campaign, for the three broadcast jobs; ``None`` for a payment notification.
    broadcast_id: UUID | None = None
    #: The intent's rail-facing reference, for a payment notification; ``None`` otherwise.
    #: Never an idempotency key and never a Telegram id — see
    #: :func:`job_id_for_payment_notification`.
    public_ref: str | None = None


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

    The refusal carries a :class:`~bayram.errors.StorageError` and not the ``ConfigError``
    ``BROADCAST_SPEC §3.6`` names, because the spec asked for "a legible 503" and
    :data:`bayram.admin.errors.STATUS_BY_ERROR_CODE` maps ``CONFIG_INVALID`` to **422**. A
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

    async def enqueue_payment_notification(self, public_ref: str) -> Result[str | None]:
        """Records the call and answers ``ok(job_id)`` — i.e. **never a replay**.

        A fake that returned ``ok(None)`` on the second call would be modelling ARQ's job
        registry, which this class deliberately does not have: ``NullAdminQueue`` keeps a list
        of calls, not a queue, and a duplicate-detection rule invented here would be asserted
        by tests and true of nothing. A router test that needs the replay branch overrides this
        method (see ``tests/test_admin/test_billing_router.py``), which keeps the branch's own
        behaviour asserted without this class growing a second, fictional idempotency store.
        """
        entry = RecordedEnqueue(
            job=PAYMENT_NOTIFY_JOB_NAME,
            job_id=job_id_for_payment_notification(public_ref),
            arguments=(public_ref,),
            public_ref=public_ref,
        )
        self.calls.append(entry)
        if self._refusing:
            return err(
                StorageError(
                    "this deployment has no ARQ worker, so the announcement cannot be queued",
                    context={"job": entry.job, "public_ref": public_ref},
                )
            )
        return ok(entry.job_id)

    async def aclose(self) -> None:
        """Nothing is held, so nothing is released. Present because the protocol has it."""

    def _record(
        self, job: str, broadcast_id: UUID, job_id: str, arguments: tuple[object, ...]
    ) -> Result[str]:
        """Record first, refuse second. The three campaign jobs only.

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
