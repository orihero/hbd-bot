"""The stale-debit sweep: the backstop for every debit no job ever came back to close.

``jobs._settle`` runs inside the job, so it cannot close a debit whose worker was SIGKILLed,
whose enqueue never landed, or whose settle call the database refused. Two modules already
pointed at this sweep in their docstrings before it existed — ``jobs.py:478`` and
``credit_sql.count_in_flight`` — so until it ran, "the sweep closes it" was a promise nobody
kept.

Every test here is about the SELECTION, because that is where the money is. Two of them are
the ones an exploit would live behind:

* :func:`test_a_debit_whose_order_is_still_running_and_young_is_left_alone` — a requeued job
  is not a dead one. Refunding it hands back a credit for a render that then delivers.
* :func:`test_a_delivered_order_whose_settlement_never_landed_is_consumed_not_refunded` —
  ``orchestrator`` writes ``DELIVERED`` when the kit is PERSISTED, before the Telegram send,
  so this is also the ``NOT_DELIVERED`` case. Refunding it would give the credit back for a
  kit that exists and is redeliverable, which is exactly the free-song path WU5's settlement
  policy exists to close; a sweep that reopened it would have undone that policy in the dark.

The invariant from ``test_credits.py`` — ``credit_accounts.balance == SUM(delta)`` — is
asserted after every sweep here too, because the sweep is the only writer that moves a
balance without a customer in the loop.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import OrderState, is_ok
from bayram.db.credit_sql import verify_balances
from bayram.db.credits import SWEEP_ACTOR, SqlCreditLedger, settle_stale_debits
from bayram.db.enums import CreditEntryKind, CreditReason
from bayram.db.models import CreditLedgerRow
from bayram.db.purge import purge_expired
from bayram.db.repository import SqlKitRepository
from bayram.entitlements import DEFAULT_ENTITLEMENT_POLICY, EntitlementPolicy, SettlementOutcome
from tests.test_db.conftest import MovableClock, new_order

_ACTOR: Final[str] = "pipeline"
#: Comfortably past ``DEFAULT_ENTITLEMENT_POLICY.settlement_grace_s`` (4550s, derived from
#: the shipped queue ladder). Stated as a multiple of the policy rather than as a literal so
#: a change to the ladder moves this with it instead of quietly making the test vacuous.
_PAST_THE_GRACE: Final[int] = DEFAULT_ENTITLEMENT_POLICY.settlement_grace_s + 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _charged_order(
    repository: SqlKitRepository,
    ledger: SqlCreditLedger,
    *,
    telegram_user_id: int,
    state: OrderState,
    is_persisted: bool = True,
) -> UUID:
    """One order in ``state`` with exactly one open debit against it.

    ``is_persisted=False`` skips the ``orders`` row entirely: the gate charges before the
    worker has necessarily written one, so a debit with nothing to join to is a real shape.
    """
    order = new_order(state=state, telegram_user_id=telegram_user_id)
    if is_persisted:
        created = await repository.create_order(order)
        assert is_ok(created), created
    charged = await ledger.charge(
        telegram_user_id=telegram_user_id, order_id=order.id, actor=_ACTOR
    )
    assert is_ok(charged), charged
    return order.id


async def _sweep(
    sessions: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    limit: int = 100,
    policy: EntitlementPolicy = DEFAULT_ENTITLEMENT_POLICY,
) -> int:
    """Run one pass in its own transaction, the way ``purge_expired`` hosts it."""
    async with sessions.begin() as session:
        return await settle_stale_debits(session, now=now, limit=limit, policy=policy)


async def _entries_for(
    sessions: async_sessionmaker[AsyncSession], order_id: UUID
) -> list[tuple[CreditEntryKind, CreditReason, int, str]]:
    async with sessions() as session:
        rows = (
            await session.execute(
                sa.select(CreditLedgerRow)
                .where(CreditLedgerRow.order_id == order_id)
                .order_by(CreditLedgerRow.idempotency_key)
            )
        ).scalars()
        return [(row.kind, row.reason, row.delta, row.actor or "") for row in rows]


async def _credits_of(ledger: SqlCreditLedger, user: int) -> int:
    """Spendable credits as the account itself reports them."""
    result = await ledger.balance_for(user)
    assert is_ok(result), result
    return result.value.credits


async def _assert_no_drift(sessions: async_sessionmaker[AsyncSession]) -> None:
    async with sessions() as session:
        assert await verify_balances(session) == ()


@pytest.fixture
def ledger(sessions: async_sessionmaker[AsyncSession], clock: MovableClock) -> SqlCreditLedger:
    return SqlCreditLedger(sessions, clock=clock)


# ---------------------------------------------------------------------------
# What the sweep closes
# ---------------------------------------------------------------------------
async def test_a_debit_whose_order_died_is_refunded_exactly_once(
    sessions: async_sessionmaker[AsyncSession],
    repository: SqlKitRepository,
    ledger: SqlCreditLedger,
    clock: MovableClock,
) -> None:
    # Arrange — a terminally failed order whose settle call never landed. It is swept once
    # the ORDER ROW has been quiet for the grace, not on sight: ``orchestrator._fail`` writes
    # FAILED for retryable failures too, so the state alone says "the last attempt failed",
    # never "the job is gone". See the mirror test below.
    user = 5_100_000_000_001
    order_id = await _charged_order(
        repository, ledger, telegram_user_id=user, state=OrderState.FAILED
    )
    assert await _credits_of(ledger, user) == 2

    # Act
    quiet = clock.advance(seconds=_PAST_THE_GRACE)
    closed = await _sweep(sessions, now=quiet)
    again = await _sweep(sessions, now=quiet)

    # Assert — the credit is back, signed by the sweep, and the second pass finds nothing:
    # ``refund`` keys on ``refund:{order}:{generation}`` and the order's net position is 0
    # once it has been given back, so a sweep that runs hourly forever writes one row.
    assert (closed, again) == (1, 0)
    assert await _entries_for(sessions, order_id) == [
        (CreditEntryKind.DEBIT, CreditReason.ORDER_RENDER, -1, _ACTOR),
        (CreditEntryKind.REFUND, CreditReason.STALE_SETTLEMENT, 1, SWEEP_ACTOR),
    ]
    assert await _credits_of(ledger, user) == 3
    await _assert_no_drift(sessions)


async def test_a_debit_whose_order_is_still_running_and_young_is_left_alone(
    sessions: async_sessionmaker[AsyncSession],
    repository: SqlKitRepository,
    ledger: SqlCreditLedger,
    clock: MovableClock,
) -> None:
    # Arrange — the exploitable one. An AUTHORIZED order inside the grace is an order arq
    # may still be holding between attempts; refunding it hands the credit back to someone
    # whose song is about to arrive.
    user = 5_100_000_000_002
    order_id = await _charged_order(
        repository, ledger, telegram_user_id=user, state=OrderState.AUTHORIZED
    )

    # Act — one second short of the grace, then past it.
    inside = await _sweep(sessions, now=clock.now)
    outside = await _sweep(sessions, now=clock.advance(seconds=_PAST_THE_GRACE))

    # Assert
    assert (inside, outside) == (0, 1)
    assert [entry[0] for entry in await _entries_for(sessions, order_id)] == [
        CreditEntryKind.DEBIT,
        CreditEntryKind.REFUND,
    ]
    await _assert_no_drift(sessions)


async def test_a_failed_order_still_inside_its_retry_ladder_is_left_alone(
    sessions: async_sessionmaker[AsyncSession],
    repository: SqlKitRepository,
    ledger: SqlCreditLedger,
    clock: MovableClock,
) -> None:
    """The sharpest one, and the reason ``FAILED`` is no longer swept on sight.

    ``orchestrator._fail`` advances the row to FAILED for EVERY error, retryable included,
    and only afterwards does ``jobs._run_pipeline`` raise ``Retry`` — so between attempts the
    row reads FAILED while the job is alive in arq's backoff. Sweeping on the state alone
    refunded that debit; the retry then delivered, its CONSUME found ``net_position == 0``
    and wrote nothing, and the customer kept the song AND the credit. Reproduced before this
    predicate changed.
    """
    # Arrange — the failure was written a moment ago: the next attempt is still to come.
    user = 5_100_000_000_009
    order_id = await _charged_order(
        repository, ledger, telegram_user_id=user, state=OrderState.FAILED
    )

    # Act — the cron fires while the job sits in backoff, then once the ladder is long over.
    inside = await _sweep(sessions, now=clock.advance(seconds=60))
    outside = await _sweep(sessions, now=clock.advance(seconds=_PAST_THE_GRACE))

    # Assert — untouched while it could still come back, closed once it plainly cannot.
    assert (inside, outside) == (0, 1)
    assert await _entries_for(sessions, order_id) == [
        (CreditEntryKind.DEBIT, CreditReason.ORDER_RENDER, -1, _ACTOR),
        (CreditEntryKind.REFUND, CreditReason.STALE_SETTLEMENT, 1, SWEEP_ACTOR),
    ]
    await _assert_no_drift(sessions)


async def test_a_live_order_survives_a_grace_far_shorter_than_its_own_retry_ladder(
    sessions: async_sessionmaker[AsyncSession],
    repository: SqlKitRepository,
    ledger: SqlCreditLedger,
    clock: MovableClock,
) -> None:
    """A misconfigured grace must not be able to refund a job that is still working.

    The cron caller (``bayram.runtime.retention_job``, fenced) passes no ``entitlements``, so
    the sweep runs on ``DEFAULT_ENTITLEMENT_POLICY`` while the container resolves the
    ledger's from ``Settings``. A deployment that raises ``BAYRAM_QUEUE_JOB_TIMEOUT_S`` used to
    make the sweep's grace shorter than its own ladder and refund live renders. The selection
    now also demands that ``orders.updated_at`` be older than the cutoff, and every stage
    transition stamps it — so the order below is protected by its own progress, not by the
    number in the policy.
    """
    # Arrange — an order charged long ago that has just moved a stage.
    user = 5_100_000_000_010
    order_id = await _charged_order(
        repository, ledger, telegram_user_id=user, state=OrderState.AUTHORIZED
    )
    clock.advance(seconds=_PAST_THE_GRACE)
    progressed = await repository.set_order_state(order_id, OrderState.GENERATING, now=clock.now)
    assert is_ok(progressed), progressed

    # Act — a sweep whose grace is far too short for this deployment's ladder.
    closed = await _sweep(sessions, now=clock.now, policy=EntitlementPolicy(settlement_grace_s=60))

    # Assert
    assert closed == 0
    assert [entry[0] for entry in await _entries_for(sessions, order_id)] == [CreditEntryKind.DEBIT]
    await _assert_no_drift(sessions)


async def test_a_debit_already_settled_by_a_consume_is_never_refunded(
    sessions: async_sessionmaker[AsyncSession],
    repository: SqlKitRepository,
    ledger: SqlCreditLedger,
    clock: MovableClock,
) -> None:
    # Arrange — a delivered kit the worker DID settle. Its net position stays at -1 (a
    # CONSUME moves delta 0 on purpose), so the settlement MARKER is the only thing standing
    # between this row and a refund; a sweep that asked "is this order still negative?"
    # instead would hand a credit back for every song ever delivered.
    user = 5_100_000_000_003
    order_id = await _charged_order(
        repository, ledger, telegram_user_id=user, state=OrderState.DELIVERED
    )
    settled = await ledger.settle(
        telegram_user_id=user,
        order_id=order_id,
        outcome=SettlementOutcome.DELIVERED,
        actor=_ACTOR,
    )
    assert is_ok(settled), settled
    assert settled.value

    # Act — long past the grace, so only the marker can be what spared it.
    closed = await _sweep(sessions, now=clock.advance(seconds=_PAST_THE_GRACE))

    # Assert
    assert closed == 0
    assert await _entries_for(sessions, order_id) == [
        (CreditEntryKind.CONSUME, CreditReason.ORDER_DELIVERED, 0, _ACTOR),
        (CreditEntryKind.DEBIT, CreditReason.ORDER_RENDER, -1, _ACTOR),
    ]
    assert await _credits_of(ledger, user) == 2
    await _assert_no_drift(sessions)


async def test_a_delivered_order_whose_settlement_never_landed_is_consumed_not_refunded(
    sessions: async_sessionmaker[AsyncSession],
    repository: SqlKitRepository,
    ledger: SqlCreditLedger,
    clock: MovableClock,
) -> None:
    # Arrange — the second exploitable one. ``orchestrator`` writes DELIVERED when the kit is
    # PERSISTED (orchestrator.py:473), before the Telegram send, so this state covers both a
    # delivered kit and one Telegram refused — and WU5 consumes BOTH. A sweep that refunded
    # on "terminal or stale" alone would quietly reverse that policy for anyone who could
    # make one settle call fail.
    user = 5_100_000_000_004
    order_id = await _charged_order(
        repository, ledger, telegram_user_id=user, state=OrderState.DELIVERED
    )

    # Act
    closed = await _sweep(sessions, now=clock.advance(seconds=_PAST_THE_GRACE))

    # Assert — the debit is closed and the balance does NOT go back up.
    assert closed == 1
    assert await _entries_for(sessions, order_id) == [
        (CreditEntryKind.CONSUME, CreditReason.STALE_SETTLEMENT, 0, SWEEP_ACTOR),
        (CreditEntryKind.DEBIT, CreditReason.ORDER_RENDER, -1, _ACTOR),
    ]
    assert await _credits_of(ledger, user) == 2
    await _assert_no_drift(sessions)


async def test_a_debit_with_no_order_row_at_all_is_refunded_once_it_is_stale(
    sessions: async_sessionmaker[AsyncSession],
    repository: SqlKitRepository,
    ledger: SqlCreditLedger,
    clock: MovableClock,
) -> None:
    # Arrange — the ledger has no foreign key to ``orders`` on purpose (the gate can charge
    # before the row exists, and the abandoned-draft sweep deletes rows the ledger outlives),
    # so an orphaned debit is a shape the sweep must handle rather than skip. An INNER join
    # here would strand this credit forever.
    user = 5_100_000_000_005
    order_id = await _charged_order(
        repository, ledger, telegram_user_id=user, state=OrderState.AUTHORIZED, is_persisted=False
    )

    # Act
    closed = await _sweep(sessions, now=clock.advance(seconds=_PAST_THE_GRACE))

    # Assert
    assert closed == 1
    assert [entry[1] for entry in await _entries_for(sessions, order_id)] == [
        CreditReason.ORDER_RENDER,
        CreditReason.STALE_SETTLEMENT,
    ]
    assert await _credits_of(ledger, user) == 3
    await _assert_no_drift(sessions)


# ---------------------------------------------------------------------------
# The bound
# ---------------------------------------------------------------------------
async def test_the_sweep_is_bounded_per_pass_and_works_the_backlog_off_across_passes(
    sessions: async_sessionmaker[AsyncSession],
    repository: SqlKitRepository,
    ledger: SqlCreditLedger,
    clock: MovableClock,
) -> None:
    # Arrange — five dead orders, one per account (the in-flight cap is one render at a
    # time, so five debits cannot belong to one customer). A first run against a backlog
    # must not take a lock on the whole ledger, which is why the limit exists at all.
    users = [5_100_000_001_000 + index for index in range(5)]
    for user in users:
        await _charged_order(repository, ledger, telegram_user_id=user, state=OrderState.FAILED)

    # Act
    quiet = clock.advance(seconds=_PAST_THE_GRACE)
    passes = [await _sweep(sessions, now=quiet, limit=2) for _ in range(3)]
    exhausted = await _sweep(sessions, now=quiet, limit=2)

    # Assert — 2, 2, 1 and then nothing: bounded per pass, and finished.
    assert passes == [2, 2, 1]
    assert exhausted == 0
    for user in users:
        assert await _credits_of(ledger, user) == 3
    await _assert_no_drift(sessions)


async def test_a_shorter_grace_closes_a_debit_the_shipped_one_would_still_be_holding(
    sessions: async_sessionmaker[AsyncSession],
    repository: SqlKitRepository,
    ledger: SqlCreditLedger,
    clock: MovableClock,
) -> None:
    # Arrange — the grace is injected, never ambient, so an operator running a shorter queue
    # ladder gets a sweep that matches it.
    user = 5_100_000_000_006
    await _charged_order(repository, ledger, telegram_user_id=user, state=OrderState.GENERATING)
    now = clock.advance(seconds=120)

    # Act
    shipped = await _sweep(sessions, now=now)
    impatient = await _sweep(sessions, now=now, policy=EntitlementPolicy(settlement_grace_s=60))

    # Assert
    assert (shipped, impatient) == (0, 1)
    await _assert_no_drift(sessions)


# ---------------------------------------------------------------------------
# Hosting: the sweep rides the purge's transaction and shows up in its report
# ---------------------------------------------------------------------------
async def test_the_purge_run_settles_stale_debits_and_reports_how_many(
    sessions: async_sessionmaker[AsyncSession],
    repository: SqlKitRepository,
    ledger: SqlCreditLedger,
    clock: MovableClock,
) -> None:
    # Arrange — this is the whole point of WU6: ``purge_expired`` is the only bounded,
    # scheduled transaction the worker has, and the cron that fires it is what makes the
    # sweep real rather than a function nobody calls.
    user = 5_100_000_000_007
    await _charged_order(repository, ledger, telegram_user_id=user, state=OrderState.FAILED)

    # Act
    outcome = await purge_expired(sessions, now=clock.advance(seconds=_PAST_THE_GRACE))

    # Assert — counted on its own field AND folded into the total the retention job logs and
    # the panel renders, so a run that only settled debits does not read as a run that did
    # nothing.
    assert is_ok(outcome), outcome
    report = outcome.value
    assert report.stale_debits_settled == 1
    assert report.total_rows_affected == 1
    assert await _credits_of(ledger, user) == 3
    await _assert_no_drift(sessions)


async def test_the_sweep_commits_nothing_of_its_own_so_a_failed_purge_takes_it_back(
    sessions: async_sessionmaker[AsyncSession],
    repository: SqlKitRepository,
    ledger: SqlCreditLedger,
    clock: MovableClock,
) -> None:
    # Arrange — the sweep takes a session instead of opening one, so that it composes inside
    # ``purge_expired``'s transaction. If it committed independently, a purge that blew up
    # around it would leave credits handed back for a run that never happened — so the
    # property under test is that a ROLLBACK by the owner of the transaction undoes it whole.
    user = 5_100_000_000_008
    await _charged_order(repository, ledger, telegram_user_id=user, state=OrderState.FAILED)

    # Act
    async with sessions() as session:
        closed = await settle_stale_debits(
            session, now=clock.advance(seconds=_PAST_THE_GRACE), limit=10
        )
        await session.rollback()

    # Assert — it did the work, and none of it survived the caller's rollback.
    assert closed == 1
    assert await _credits_of(ledger, user) == 2
    await _assert_no_drift(sessions)
