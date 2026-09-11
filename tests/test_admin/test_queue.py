"""The admin→ARQ seam: what it enqueues, what it refuses, and what it cannot reach.

Three properties are load-bearing here and each has a test that would notice it breaking.

**It cannot send anything.** The panel holds no bot token by design, so the seam's whole
contract is "name a job, hand over an id". ``test_the_seam_can_reach_nothing_that_sends_a_
message`` reads this module's own imports and fails if ``aiogram`` — or the runtime job
module that constructs a ``Bot`` — ever appears in one. That is a structural assertion rather
than a behavioural one on purpose: the day someone imports ``Bot`` here to "just send the
test message directly" there is no failing behaviour to catch it, only a process that now
needs a credential D10 says it must never have.

**A duplicate is success.** ARQ answers ``None`` when the deterministic id is already
queued, and the campaign is then already being expanded or sent — which is what the caller
asked for. Reading that as a failure would make a double-clicked Send an error page over a
campaign that is going out fine.

**Its own Redis pool, not the panel's.** ``test_the_queue_does_not_share_the_panels_redis_
pool`` asserts the two pools differ and that only the panel's decodes responses. The bug it
guards is invisible until it is expensive: arq's payloads are pickled bytes, and a shared
``decode_responses=True`` pool corrupts them at the first non-ASCII job argument.

No fakeredis and no server. ``enqueue_job`` is one method, so the fake below is a dozen
lines and tests this module's own logic — the ids, the failure taxonomy, the duplicate
reading — rather than Redis's.
"""

from __future__ import annotations

import ast
import dataclasses
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast
from uuid import UUID

import pytest
from arq import ArqRedis
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

from bayram.admin import queue as queue_module
from bayram.admin.container import build_admin_container
from bayram.admin.errors import status_for
from bayram.admin.queue import (
    EXPAND_JOB_NAME,
    PAYMENT_NOTIFY_JOB_NAME,
    SEND_JOB_NAME,
    TEST_SEND_JOB_NAME,
    AdminQueue,
    ArqAdminQueue,
    NullAdminQueue,
    job_id_for_expand,
    job_id_for_payment_notification,
    job_id_for_send,
    job_id_for_test_send,
)
from bayram.contracts import Err, Ok, Result
from bayram.errors import ErrorCode, StorageError
from bayram.runtime import broadcast_job as worker_module
from bayram.runtime import payme_jobs
from tests.test_admin.conftest import FakeRedis, make_settings

#: A fixed instant, because the expansion job carries it and a test that asserts on it must
#: not be a race.
NOW: Final[datetime] = datetime(2026, 3, 21, 9, 0, 0, tzinfo=UTC)
BROADCAST_ID: Final[UUID] = UUID("0f0f6f52-1c1a-4e3b-9d21-0c4b0b1a7c11")
#: The job argument is the string, because an ARQ payload is pickled and a UUID crossing a
#: process boundary as an object is a shape the worker cannot widen later.
BROADCAST_ID_TEXT: Final[str] = str(BROADCAST_ID)
OPERATOR_TELEGRAM_ID: Final[int] = 987_654_321
#: One payment's rail-facing reference: 24 opaque hex characters, and the ONLY identifier the
#: notification seam is allowed to carry. Its counterpart, the intent's ``idempotency_key``,
#: contains ``TELEGRAM_ID`` — which is why the assertions below look for that number's absence.
PUBLIC_REF: Final[str] = "9f13c0a72b4e8d5610fa37cc"
TELEGRAM_ID: Final[int] = 770_000_123
#: What ARQ hands back for an accepted job. Different from every id this module mints, so a
#: test cannot pass by reading its own input back.
HANDLE_ID: Final[str] = "arq-generated-handle"


class _FakeJob:
    """ARQ's ``Job``, as far as this seam reads it: an id and nothing else."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id


class _FakeArq:
    """The one method the seam calls, plus the close the container calls.

    ``raises`` makes every enqueue fail, which is how the two failure paths are asserted
    without unplugging anything; ``duplicate`` makes ARQ answer ``None``, which is what a
    deterministic id already in the queue looks like from here.
    """

    def __init__(self, *, raises: Exception | None = None, duplicate: bool = False) -> None:
        self.calls: list[tuple[str, tuple[object, ...], str | None]] = []
        self.closed = False
        self._raises = raises
        self._duplicate = duplicate

    async def enqueue_job(
        self, function: str, *args: object, _job_id: str | None = None, **_: object
    ) -> _FakeJob | None:
        self.calls.append((function, args, _job_id))
        if self._raises is not None:
            raise self._raises
        if self._duplicate:
            return None
        return _FakeJob(HANDLE_ID)

    async def aclose(self) -> None:
        self.closed = True


class _ClosedRecordingRedis(FakeRedis):
    """The panel's client, with the close recorded so a failure order can be asserted."""

    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _UncloseableQueue(NullAdminQueue):
    """A queue whose release fails. One resource must not hide the others."""

    async def aclose(self) -> None:
        raise RedisConnectionError("the queue handle is already gone")


def queue_over(fake: _FakeArq) -> ArqAdminQueue:
    return ArqAdminQueue(cast("ArqRedis", fake))


def value_of(result: Result[str]) -> str:
    assert isinstance(result, Ok), f"expected a job id, got {result}"
    return result.value


def error_of(result: Result[str]) -> Err:
    assert isinstance(result, Err), f"expected a refusal, got {result}"
    return result


# ---------------------------------------------------------------------------
# What goes on the queue
# ---------------------------------------------------------------------------
async def test_expanding_an_audience_carries_the_campaign_and_the_frozen_instant() -> None:
    fake = _FakeArq()

    result = await queue_over(fake).enqueue_expand(BROADCAST_ID, now=NOW)

    assert value_of(result) == HANDLE_ID
    function, arguments, job_id = fake.calls[0]
    assert function == EXPAND_JOB_NAME
    # The instant is an argument and not the worker's clock: every chunk of a resumable
    # expansion must compile the segment against the same instant, or "joined in the last
    # thirty days" selects a different population on each chunk and nothing is frozen.
    assert arguments == (BROADCAST_ID_TEXT, NOW.isoformat())
    assert job_id == job_id_for_expand(BROADCAST_ID)


async def test_sending_names_the_campaign_and_nothing_else() -> None:
    fake = _FakeArq()

    result = await queue_over(fake).enqueue_send(BROADCAST_ID)

    assert value_of(result) == HANDLE_ID
    function, arguments, job_id = fake.calls[0]
    assert function == SEND_JOB_NAME
    assert arguments == (BROADCAST_ID_TEXT,)
    assert job_id == job_id_for_send(BROADCAST_ID)


async def test_a_test_send_addresses_exactly_the_account_it_was_handed() -> None:
    fake = _FakeArq()

    result = await queue_over(fake).enqueue_test_send(
        BROADCAST_ID, telegram_user_id=OPERATOR_TELEGRAM_ID
    )

    assert value_of(result) == HANDLE_ID
    function, arguments, _ = fake.calls[0]
    assert function == TEST_SEND_JOB_NAME
    assert arguments == (BROADCAST_ID_TEXT, OPERATOR_TELEGRAM_ID)


async def test_a_double_clicked_send_asks_for_the_same_job_twice() -> None:
    """Deterministic ids are the exclusivity: one chunk job per campaign, ever, in flight."""
    fake = _FakeArq()
    queue = queue_over(fake)

    await queue.enqueue_send(BROADCAST_ID)
    await queue.enqueue_send(BROADCAST_ID)

    assert fake.calls[0][2] == fake.calls[1][2]


async def test_a_second_test_send_is_a_second_job() -> None:
    """An operator asks for another test *because* they changed the body.

    Under a deterministic id ARQ would refuse the repeat for as long as the first job's
    result lives, and the panel would silently do nothing at the exact moment the operator is
    checking their fix.
    """
    fake = _FakeArq()
    queue = queue_over(fake)

    await queue.enqueue_test_send(BROADCAST_ID, telegram_user_id=OPERATOR_TELEGRAM_ID)
    await queue.enqueue_test_send(BROADCAST_ID, telegram_user_id=OPERATOR_TELEGRAM_ID)

    first, second = fake.calls[0][2], fake.calls[1][2]
    assert first != second
    assert first is not None and second is not None
    assert first.startswith(f"broadcast:test:{BROADCAST_ID_TEXT}:")


def test_every_job_id_this_seam_mints_shares_one_prefix() -> None:
    """So one ``SCAN broadcast:*`` shows an operator every broadcast job in flight."""
    minted = (
        job_id_for_expand(BROADCAST_ID),
        job_id_for_send(BROADCAST_ID),
        job_id_for_test_send(BROADCAST_ID),
    )
    assert all(job_id.startswith("broadcast:") for job_id in minted)
    assert all(BROADCAST_ID_TEXT in job_id for job_id in minted)


# ---------------------------------------------------------------------------
# Failure, and the one non-failure that looks like one
# ---------------------------------------------------------------------------
async def test_a_duplicate_job_id_is_success_because_the_work_is_already_running(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = _FakeArq(duplicate=True)

    with caplog.at_level(logging.INFO, logger="bayram.admin.queue"):
        result = await queue_over(fake).enqueue_send(BROADCAST_ID)

    assert value_of(result) == job_id_for_send(BROADCAST_ID)
    assert any("already queued" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(OSError("redis is unreachable"), id="socket"),
        pytest.param(TimeoutError("redis did not answer"), id="timeout"),
        # Not an OSError. ``ArqOrderSubmitter`` catches ``(TimeoutError, OSError)`` only, so
        # this is the one case this seam widens: redis-py's own exceptions escape that pair,
        # and an escaped one is a 500 on a route whose honest answer is "Redis is down".
        pytest.param(RedisConnectionError("connection reset"), id="redis-protocol"),
    ],
)
async def test_an_unreachable_redis_is_a_refusal_and_never_an_exception(
    failure: Exception,
) -> None:
    fake = _FakeArq(raises=failure)

    result = await queue_over(fake).enqueue_expand(BROADCAST_ID, now=NOW)

    error = error_of(result).error
    assert isinstance(error, StorageError)
    assert error.error_code is ErrorCode.STORAGE_FAILED
    # 503, because the dependency is down and the request was not wrong.
    assert status_for(error) == 503
    # The cause is kept, so the log line under the 503 names the exception that caused it.
    assert error.__cause__ is failure


async def test_a_lost_enqueue_names_the_job_it_lost_and_nothing_more() -> None:
    fake = _FakeArq(raises=OSError("redis is unreachable"))

    result = await queue_over(fake).enqueue_expand(BROADCAST_ID, now=NOW)

    context = error_of(result).error.context
    assert set(context) == {"job", "job_id"}
    assert context["job"] == EXPAND_JOB_NAME
    assert context["job_id"] == job_id_for_expand(BROADCAST_ID)


async def test_closing_the_queue_closes_the_handle_it_owns() -> None:
    fake = _FakeArq()

    await queue_over(fake).aclose()

    assert fake.closed is True


# ---------------------------------------------------------------------------
# The null queue: the default in tests, and the answer where there is no worker
# ---------------------------------------------------------------------------
async def test_the_null_queue_records_every_call_it_did_not_make() -> None:
    queue = NullAdminQueue()

    await queue.enqueue_expand(BROADCAST_ID, now=NOW)
    await queue.enqueue_send(BROADCAST_ID)
    await queue.enqueue_test_send(BROADCAST_ID, telegram_user_id=OPERATOR_TELEGRAM_ID)

    assert [call.job for call in queue.calls] == [
        EXPAND_JOB_NAME,
        SEND_JOB_NAME,
        TEST_SEND_JOB_NAME,
    ]
    assert [call.broadcast_id for call in queue.calls] == [BROADCAST_ID] * 3
    assert queue.calls[0].arguments == (BROADCAST_ID_TEXT, NOW.isoformat())
    assert queue.calls[2].arguments == (BROADCAST_ID_TEXT, OPERATOR_TELEGRAM_ID)


async def test_the_null_queue_reports_the_job_id_it_would_have_used() -> None:
    queue = NullAdminQueue()

    result = await queue.enqueue_expand(BROADCAST_ID, now=NOW)

    assert value_of(result) == job_id_for_expand(BROADCAST_ID)
    assert queue.calls[0].job_id == job_id_for_expand(BROADCAST_ID)


async def test_a_deployment_with_no_worker_refuses_and_still_records_the_attempt() -> None:
    """The refusal is the point, and so is the record: "it tried" is the diagnosis."""
    queue = NullAdminQueue(refusing=True)

    result = await queue.enqueue_send(BROADCAST_ID)

    error = error_of(result).error
    assert isinstance(error, StorageError)
    # A 503 and not the 422 a ``ConfigError`` would render: a missing worker is an
    # unavailable dependency, not a malformed request.
    assert status_for(error) == 503
    assert [call.job for call in queue.calls] == [SEND_JOB_NAME]


async def test_closing_the_null_queue_releases_nothing_and_raises_nothing() -> None:
    await NullAdminQueue().aclose()


# ---------------------------------------------------------------------------
# The fourth method: one payment's confirmation, where a duplicate is the ANSWER
# ---------------------------------------------------------------------------
async def test_a_payment_notification_names_the_reference_and_the_deterministic_id() -> None:
    """The reference and nothing else crosses the seam.

    ``public_ref`` is 24 opaque hex characters; the intent's ``idempotency_key`` is shaped
    ``topup:{telegram_user_id}:{scope}:{seq}`` and would have put a customer's Telegram id into
    a Redis key name and into the worker's own log lines. That is what ``public_ref`` was minted
    to prevent, so it is asserted here rather than trusted.
    """
    fake = _FakeArq()

    result = await queue_over(fake).enqueue_payment_notification(PUBLIC_REF)

    assert isinstance(result, Ok)
    assert result.value == HANDLE_ID
    [(function, args, job_id)] = fake.calls
    assert (function, args) == (PAYMENT_NOTIFY_JOB_NAME, (PUBLIC_REF,))
    assert job_id == job_id_for_payment_notification(PUBLIC_REF)
    assert str(TELEGRAM_ID) not in f"{args}{job_id}"


async def test_a_duplicate_notification_is_reported_as_a_duplicate_and_not_as_success() -> None:
    """The one place this seam does NOT read ARQ's ``None`` as "the work is under way".

    For the three campaign jobs a duplicate IS what the caller asked for. Here the operator
    pressed "re-send the confirmation" and has to be told whether they queued a message or
    landed on one already in flight — the panel reports it as ``isReplay``, and collapsing it
    to the job id would leave that unanswerable without asking ARQ a second question that races
    the worker.
    """
    fake = _FakeArq(duplicate=True)

    result = await queue_over(fake).enqueue_payment_notification(PUBLIC_REF)

    assert isinstance(result, Ok)
    assert result.value is None


async def test_an_unreachable_redis_refuses_the_notification_rather_than_raising() -> None:
    """An ``Err``, so ``unwrap`` renders the 503 that sends an operator to look at Redis.

    Worth asserting separately from the campaign path: this method does not go through
    ``_enqueue``, so its failure taxonomy is only shared by construction.
    """
    fake = _FakeArq(raises=RedisConnectionError("no route to host"))

    result = await queue_over(fake).enqueue_payment_notification(PUBLIC_REF)

    assert isinstance(result, Err)
    assert isinstance(result.error, StorageError)
    assert status_for(result.error) == 503


async def test_the_null_queue_records_a_notification_by_its_reference() -> None:
    """``public_ref`` and never ``broadcast_id``: two nullable subject fields, one set per row.

    A single stringly ``subject`` would let a test that meant to assert on a campaign pass on a
    reference that happened to be equal.
    """
    queue = NullAdminQueue()

    result = await queue.enqueue_payment_notification(PUBLIC_REF)

    assert isinstance(result, Ok)
    assert result.value == job_id_for_payment_notification(PUBLIC_REF)
    [call] = queue.calls
    assert (call.job, call.public_ref, call.broadcast_id) == (
        PAYMENT_NOTIFY_JOB_NAME,
        PUBLIC_REF,
        None,
    )


async def test_a_deployment_with_no_worker_refuses_the_notification_and_records_it() -> None:
    queue = NullAdminQueue(refusing=True)

    result = await queue.enqueue_payment_notification(PUBLIC_REF)

    assert isinstance(result, Err)
    assert status_for(result.error) == 503
    assert [call.public_ref for call in queue.calls] == [PUBLIC_REF]


def test_the_restated_notification_job_name_and_id_match_the_workers_own() -> None:
    """The price of the import ban, paid twice and guarded once.

    ``bayram.runtime.payme_jobs`` imports ``aiogram.Bot`` at module level — sending the message
    IS its job — so importing it from :mod:`bayram.admin.queue` would put the Telegram client in
    the admin process's import graph, which is what D10 forbids and what
    ``test_the_seam_can_reach_nothing_that_sends_a_message`` fails on. So the job name and the
    id function are spelled twice, on opposite sides of a process boundary, and ARQ dispatches
    by string: a rename that compiled on both sides would leave customers unannounced with the
    money already banked, and the deduplication that collapses the gateway's enqueue, the
    worker's backstop sweep and the panel's press onto ONE job would silently stop working.

    This file may import both, so the comparison lives here — the duplication is
    ``bayram.admin.queue``'s, and so is the guard.
    """
    # Arrange / Act / Assert
    assert PAYMENT_NOTIFY_JOB_NAME == payme_jobs.PAYME_NOTIFY_JOB_NAME
    assert job_id_for_payment_notification(PUBLIC_REF) == payme_jobs.payme_notify_job_id(PUBLIC_REF)
    assert payme_jobs.notify_payment_settled.__name__ == PAYMENT_NOTIFY_JOB_NAME


# ---------------------------------------------------------------------------
# The container: two Redis handles, and one release per resource
# ---------------------------------------------------------------------------
async def test_the_container_holds_an_arq_queue() -> None:
    container = await build_admin_container(make_settings())
    try:
        assert isinstance(container.queue, ArqAdminQueue)
    finally:
        await container.aclose()


async def test_the_queue_does_not_share_the_panels_redis_pool() -> None:
    """The pickled-payload hazard, asserted rather than trusted.

    Reaching for ``_redis`` is deliberate: the whole claim is about an object the protocol
    does not expose, and there is no public way to ask "is this the same pool?".
    """
    container = await build_admin_container(make_settings())
    try:
        queue = container.queue
        assert isinstance(queue, ArqAdminQueue)
        queue_pool = queue._redis.connection_pool
        assert queue_pool is not container.redis.connection_pool
        assert container.redis.connection_pool.connection_kwargs.get("decode_responses") is True
        assert queue_pool.connection_kwargs.get("decode_responses") is not True
    finally:
        await container.aclose()


async def test_a_queue_that_will_not_close_does_not_take_the_other_handles_with_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    built = await build_admin_container(make_settings())
    panel_redis = _ClosedRecordingRedis()
    container = dataclasses.replace(
        built, redis=cast("Redis[str]", panel_redis), queue=_UncloseableQueue()
    )

    with caplog.at_level(logging.WARNING, logger="bayram.admin.container"):
        await container.aclose()

    assert panel_redis.closed is True
    assert any(
        record.__dict__.get("event") == "admin.container.queue_close_failed"
        for record in caplog.records
    )
    await built.queue.aclose()


# ---------------------------------------------------------------------------
# The property that has no behaviour to catch it
# ---------------------------------------------------------------------------
def test_the_seam_can_reach_nothing_that_sends_a_message() -> None:
    """D10, as a structural fact about this module's imports.

    ``FORBIDDEN_ENV_VARS`` keeps a bot token out of the process; nothing keeps an ``import``
    out of a file. So the file is read: an ``aiogram`` import, or an import of the runtime
    job module that builds the ``Bot``, fails here rather than in production, where the
    symptom would be a panel that needs a credential it is forbidden to hold.
    """
    source = Path(queue_module.__file__).read_text(encoding="utf-8")
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.append(node.module)

    assert imported, "the module imports nothing, so this test is asserting nothing"
    forbidden = [
        name
        for name in imported
        if name.startswith(("aiogram", "bayram.bot", "bayram.runtime", "bayram.pipeline"))
    ]
    assert not forbidden, f"the admin queue must not import {forbidden}"


def test_the_restated_job_names_match_the_ones_the_worker_registers() -> None:
    """The other half of the import ban above: three literals nothing compiles together.

    ``test_the_seam_can_reach_nothing_that_sends_a_message`` forbids this module from
    importing ``bayram.runtime``, which is the only thing that could have let one side read the
    other's constants. The price of that ban is that the three job names are spelled TWICE,
    on opposite sides of a process boundary, and ARQ dispatches by string — so a rename that
    compiled on both sides would leave every campaign enqueued under a name the worker does
    not answer to. The panel would report 202, the job id would be real, and nothing would
    ever run it.

    The test file may import both, so the comparison lives here rather than in the worker's
    suite: the duplication is this module's, and so is the guard.
    ``test_the_worker_registers_the_job_the_submitter_enqueues`` proves those four names are
    the ones the worker actually registers; this proves the panel asks for the same ones.
    """
    # Arrange / Act / Assert
    assert (EXPAND_JOB_NAME, SEND_JOB_NAME, TEST_SEND_JOB_NAME) == (
        worker_module.EXPAND_JOB_NAME,
        worker_module.SEND_JOB_NAME,
        worker_module.TEST_SEND_JOB_NAME,
    )


def test_both_implementations_satisfy_the_protocol() -> None:
    """Structural conformance, checked by mypy here and by the assignment at runtime."""
    implementations: tuple[AdminQueue, ...] = (
        ArqAdminQueue(cast("ArqRedis", _FakeArq())),
        NullAdminQueue(),
    )

    assert len(implementations) == 2
