"""The render gate as the worker actually meets it: a real ledger, a real pipeline.

``tests/test_runtime/test_payments.py`` proves the decorator's own logic against an
in-memory store. This module proves the two things that only the assembled worker can
prove, and that a fake store would let pass by construction:

* a refusal happens BEFORE any vendor is called, which is the whole reason the AUTHORIZING
  stage moved to second place in ``STAGE_ORDER``; and
* one delivered run costs exactly one credit against the real ``SqlCreditLedger`` — the
  same class, the same transaction and the same idempotency the production worker runs.

The database is in-memory SQLite on a ``StaticPool``, the shape ``tests/test_db/conftest.py``
uses: one shared connection, so ``create_all`` and the ledger see the same ``:memory:``.
It is built here rather than borrowed because a ``conftest`` fixture is visible only inside
its own directory, and duplicating six lines beats moving a database fixture into the shared
root where every pipeline test would pay for it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio import AsyncSession as SaSession
from sqlalchemy.pool import StaticPool

from bayram.contracts import Brief, Err, Order, PaymentProvider, Result, ok
from bayram.db.credits import SqlCreditLedger
from bayram.db.engine import create_session_factory
from bayram.db.models import Base
from bayram.entitlements import (
    EntitlementPolicy,
    EntitlementStore,
    InsufficientCreditsError,
)
from bayram.errors import ErrorCode, ProviderTimeoutError
from bayram.payments import CreditGatedPaymentProvider
from bayram.pipeline.events import PipelineStage
from tests.conftest import make_order
from tests.test_pipeline.conftest import Studio, failure_of

#: No free allowance, so the account starts at zero and a test decides what it may spend by
#: granting. With the shipped 3-per-30-days the very first charge would mint its own credits
#: and "a customer with nothing left" would be unreachable without moving the clock a month.
_NO_ALLOWANCE = EntitlementPolicy(allowance_credits=0)

_GRANT_KEY = "grant:admin:test"


class RecordingModerator:
    """Allows everything and counts. The vendor call that used to precede the charge."""

    def __init__(self) -> None:
        self.reviews: list[Brief] = []

    async def review(self, brief: Brief) -> Result[None]:
        self.reviews.append(brief)
        return ok(None)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[SaSession]:
    return create_session_factory(engine)


@pytest.fixture
def ledger(sessions: async_sessionmaker[SaSession]) -> SqlCreditLedger:
    return SqlCreditLedger(sessions, policy=_NO_ALLOWANCE)


@pytest.fixture
def dark_ledger(sessions: async_sessionmaker[SaSession]) -> SqlCreditLedger:
    """The SHIPPED configuration: ``BAYRAM_CREDITS_ENFORCED`` unset.

    The flag lives on the policy rather than on the decorator, and that is the whole point:
    a gate that owned it could only say "do not call the store", which took the block gate
    and the in-flight cap down with the balance check. Here the store runs in full and only
    the out-of-credits refusal is switched off.
    """
    return SqlCreditLedger(
        sessions, policy=EntitlementPolicy(allowance_credits=0, is_balance_enforced=False)
    )


def gated(studio: Studio, ledger: EntitlementStore) -> PaymentProvider:
    """The worker's provider: the studio's fake rail with the credit gate wrapped round it."""
    return CreditGatedPaymentProvider(studio.payment, ledger)


async def credits_of(ledger: EntitlementStore, order: Order) -> int:
    balance = await ledger.balance_for(order.telegram_user_id)
    assert not isinstance(balance, Err), balance
    return balance.value.credits


async def row_counts(sessions: async_sessionmaker[SaSession]) -> tuple[int, int]:
    """(accounts, ledger entries). Raw SQL on purpose — see the ``*Row`` rule in bayram.db.

    A mapped row must not leave persistence, and a test that imported one to count it would
    be the first exception to that. ``COUNT(*)`` needs no mapping and says the one thing
    this module asks of the tables directly: whether anything was written at all.
    """
    async with sessions() as session:
        accounts = await session.scalar(sa.text("SELECT COUNT(*) FROM credit_accounts"))
        entries = await session.scalar(sa.text("SELECT COUNT(*) FROM credit_ledger"))
    return int(accounts or 0), int(entries or 0)


async def grant(ledger: EntitlementStore, order: Order, credits: int) -> None:
    result = await ledger.grant(
        telegram_user_id=order.telegram_user_id,
        credits=credits,
        idempotency_key=_GRANT_KEY,
        actor="test",
    )
    assert not isinstance(result, Err), result


# ---------------------------------------------------------------------------
# The refusal costs nothing
# ---------------------------------------------------------------------------
async def test_an_account_with_no_credits_is_refused_before_a_single_vendor_is_called(
    studio: Studio, ready_order: Order, ledger: SqlCreditLedger
) -> None:
    """This is what moving AUTHORIZING ahead of MODERATING bought.

    With the gate fifth, an account that could never render still paid for a moderation
    call and a script-writing call on every confirm — real vendor money, spent on an answer
    the ledger already knew. VALIDATING is local, so refusing right after it costs one
    database round trip and nothing else.
    """
    # Arrange
    moderator = RecordingModerator()

    # Act
    result = await studio.pipeline(payment=gated(studio, ledger), moderator=moderator).run(
        ready_order
    )

    # Assert
    error = failure_of(result)
    assert isinstance(error, InsufficientCreditsError)
    assert error.error_code is ErrorCode.CREDITS_EXHAUSTED
    assert moderator.reviews == []
    assert studio.music.compose_calls == []
    assert studio.tts.calls == []


async def test_the_refusal_is_not_retryable_so_the_queue_stops_asking(
    studio: Studio, ready_order: Order, ledger: SqlCreditLedger
) -> None:
    """``Err.is_retryable`` drives the ARQ ladder in ``bayram.runtime.jobs``.

    A retryable refusal would re-run the whole pipeline against one customer on a schedule,
    for an answer that cannot change until the calendar or an operator changes it.
    """
    # Arrange / Act
    result = await studio.pipeline(payment=gated(studio, ledger)).run(ready_order)

    # Assert
    assert isinstance(result, Err)
    assert not result.is_retryable
    assert failure_of(result).user_message_key == "error.credits_exhausted"


async def test_the_refusal_names_the_stage_it_died_in_on_the_order_row(
    studio: Studio, ready_order: Order, ledger: SqlCreditLedger
) -> None:
    # Arrange / Act — an operator reading the row must see WHERE the run stopped, and the
    # gate is now the second stage rather than the fifth.
    await studio.pipeline(payment=gated(studio, ledger)).run(ready_order)

    # Assert
    reason = studio.repository.failed_reasons[-1]
    assert reason is not None
    assert PipelineStage.AUTHORIZING.value in reason


# ---------------------------------------------------------------------------
# The happy path costs exactly one credit
# ---------------------------------------------------------------------------
async def test_a_delivered_run_spends_exactly_one_credit(
    studio: Studio, ready_order: Order, ledger: SqlCreditLedger
) -> None:
    # Arrange
    await grant(ledger, ready_order, 2)

    # Act
    result = await studio.pipeline(payment=gated(studio, ledger)).run(ready_order)

    # Assert
    assert not isinstance(result, Err), result
    assert await credits_of(ledger, ready_order) == 1


async def test_a_requeued_job_recharges_nothing_for_the_order_it_already_paid_for(
    studio: Studio, ready_order: Order, ledger: SqlCreditLedger
) -> None:
    """The gate runs once per ATTEMPT, and ARQ makes several attempts per order.

    Sabotage the song on the first pass so the run dies AFTER the charge and leaves no kit
    behind — which is precisely the state a requeued job wakes up in, with the orchestrator's
    replay short-circuit unable to help it. The second attempt must find the order already
    paid for and take nothing more. Replay is decided by the order's NET position rather
    than by the presence of a debit row, which is what keeps a REFUNDED order chargeable
    while a paid one is not.
    """
    # Arrange — two credits, so "charged twice" and "charged once" are different numbers.
    await grant(ledger, ready_order, 2)
    gate = gated(studio, ledger)
    # Exactly as many failures as the first run's retry ladder will consume
    # (``provider_max_attempts`` is 2 in ``pipeline_settings``), so the first attempt dies
    # and the second one finds a working vendor — the shape of a real requeue.
    studio.music.failures = [
        ProviderTimeoutError("the studio went dark", provider="fake-music") for _ in range(2)
    ]

    # Act
    first = await studio.pipeline(payment=gate).run(ready_order)
    spent_after_the_failure = await credits_of(ledger, ready_order)
    second = await studio.pipeline(payment=gate).run(ready_order)

    # Assert — two authorisations, one debit, and the retry still delivers.
    assert isinstance(first, Err)
    assert not isinstance(second, Err), second
    assert studio.payment.calls == [ready_order.id, ready_order.id]
    assert spent_after_the_failure == 1
    assert await credits_of(ledger, ready_order) == 1


@pytest.mark.parametrize("is_dark", [False, True])
async def test_a_blocked_account_cannot_render_even_with_credits_in_hand(
    studio: Studio,
    ready_order: Order,
    ledger: SqlCreditLedger,
    dark_ledger: SqlCreditLedger,
    is_dark: bool,
) -> None:
    """The block gate is NOT behind ``credits_enforced``-style caution for a reason.

    A block refuses abuse rather than a customer, and it has to stop work the bot already
    queued — otherwise blocking someone mid-render still renders their song.

    Parametrised over the flag because the version that only ran ENFORCED proved nothing
    about what ships: with the flag on the decorator, the dark path returned before the
    store was touched, and a blocked account rendered and shipped a full Gemini +
    ElevenLabs kit. That was reproduced against these very fixtures.
    """
    # Arrange
    store = dark_ledger if is_dark else ledger
    await grant(store, ready_order, 3)
    blocked = await store.set_blocked(ready_order.telegram_user_id, is_blocked=True)
    assert not isinstance(blocked, Err), blocked

    # Act
    result = await studio.pipeline(payment=gated(studio, store)).run(ready_order)

    # Assert
    assert failure_of(result).error_code is ErrorCode.ACCOUNT_BLOCKED
    assert await credits_of(store, ready_order) == 3
    assert studio.music.compose_calls == []


# ---------------------------------------------------------------------------
# The shipped default
# ---------------------------------------------------------------------------
async def test_the_dark_default_delivers_for_an_account_with_nothing_but_still_meters_it(
    studio: Studio,
    ready_order: Order,
    dark_ledger: SqlCreditLedger,
    sessions: async_sessionmaker[SaSession],
) -> None:
    """``BAYRAM_CREDITS_ENFORCED=false`` is what merges, so it is what has to be proven.

    The account below has no credits at all and renders anyway — nobody is refused for
    having run out, which is the entire purpose of the flag. What it does NOT mean any more
    is that the ledger stays empty: the in-flight cap counts unsettled DEBIT rows, so a dark
    mode that wrote none made the cap (and the worker's block check, which lives in the same
    call) refuse nobody in the only configuration that ships. The meter therefore runs in
    full and the shortfall is covered by a grant, which leaves the balance where it was and
    keeps ``balance == SUM(delta)`` true.
    """
    # Arrange / Act
    result = await studio.pipeline(payment=gated(studio, dark_ledger)).run(ready_order)

    # Assert
    assert not isinstance(result, Err), result
    assert studio.payment.calls == [ready_order.id]
    accounts, entries = await row_counts(sessions)
    assert accounts == 1
    # The cover grant and the debit. Net zero, so the customer is no worse off.
    assert entries == 2
    assert await credits_of(dark_ledger, ready_order) == 0


async def test_the_in_flight_cap_still_refuses_a_second_render_while_the_meter_is_dark(
    studio: Studio, ready_order: Order, dark_ledger: SqlCreditLedger
) -> None:
    """The cap is an abuse rail, and D-B says an abuse rail never ships switched off.

    It used to. ``count_in_flight`` counts unsettled debits and the dark path wrote none, so
    ``in_flight`` was permanently 0 and one account could hold unlimited concurrent renders
    — exactly the queue-filling abuse the cap exists to stop.
    """
    # Arrange — the first order is charged and never settled, so its debit is open.
    first = await studio.pipeline(payment=gated(studio, dark_ledger)).run(ready_order)
    assert not isinstance(first, Err), first

    # Act — a second order from the SAME account, walked from scratch.
    second_order = studio.enrol(make_order(telegram_user_id=ready_order.telegram_user_id))
    second = await studio.pipeline(payment=gated(studio, dark_ledger)).run(second_order)

    # Assert
    assert failure_of(second).error_code is ErrorCode.TOO_MANY_IN_FLIGHT
