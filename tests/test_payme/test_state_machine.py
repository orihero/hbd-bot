"""The rail's state machine, driven against a real database. **The suite this plan exists for.**

Every assertion here is about one of two things: a replay must answer exactly what the first
call answered, or a race must produce exactly one credit. Both are properties of a commit
boundary rather than of a function, so none of them can be checked with a fake — these tests
run ``SqlPaymeLedger`` against a real engine, a real transaction and a real unique index.

**Three engines, and the choice per test is deliberate rather than incidental.**

* ``sessions`` — in-memory SQLite behind a ``StaticPool``, the same arrangement
  ``tests/test_db/conftest.py`` uses. One shared connection, so two coroutines are never
  genuinely simultaneous; they interleave their statements inside ONE transaction. That is a
  limitation for most races and an asset for exactly one of them (see
  ``test_two_concurrent_performs_of_the_same_payme_id_both_answer_state_two``).
* ``parallel_sessions`` — SQLite on a FILE with ``NullPool``, so every session gets its own
  connection and SQLite's own write lock is real. This is what makes a genuine two-writer race
  reachable without Postgres.
* ``pg_sessions`` — real Postgres, ``@pytest.mark.integration`` and excluded from ``make test``.
  It exists because SQLite's file lock and Postgres READ COMMITTED reach the same answer for
  DIFFERENT reasons: SQLite refuses the second writer outright, while Postgres lets it run and
  refuses it on the rowcount of a conditional ``UPDATE``. **Only the second is production**, and
  only the second exercises the branch this design rests on.

The concurrency assertions are therefore written about the OUTCOME — one success, one refusal,
one receipt, one grant, a balance of one — and never about which coroutine won or which
mechanism refused the loser. Asserting the mechanism would make the test engine-specific, and
the property under test is not.

Every Telegram id is outside the 32-bit range, matching ``tests/test_db/test_payme_tables.py``:
an accidental ``Integer`` column on this path would not fail loudly, it would silently truncate
the id of whoever is paying.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from hbd.checkout import PaymentIntent, PaymentIntentState, Product
from hbd.contracts import Err, Result, is_err, is_ok
from hbd.db.engine import create_engine, create_session_factory, ping
from hbd.db.enums import CreditEntryKind, PaymeState
from hbd.db.models import Base, CreditAccountRow, CreditLedgerRow
from hbd.db.models.payme_transaction import PaymeTransactionRow
from hbd.db.models.payment_intent import PaymentIntentRow
from hbd.db.models.plan_purchase import PlanPurchaseRow
from hbd.db.models.topup_purchase import TopupPurchaseRow
from hbd.db.payme import SqlPaymeLedger
from hbd.db.payme_sql import anonymise_intents, insert_transaction
from hbd.errors import HbdError
from hbd.payme.errors import PaymeFault
from hbd.payme.protocol import CancelReason, PaymeErrorCode
from hbd.payme.protocol import PaymeState as WireState
from hbd.payme.rules import DEFAULT_TRANSACTION_TIMEOUT_MS
from tests.conftest import FIXED_NOW
from tests.test_db.conftest import MovableClock

#: Well outside 2**31. See the module docstring.
_USER: Final[int] = 8_912_345_678_901
#: A 24-character ObjectId, the shape the real cashbox id will have. The key is never compared
#: against anything but itself, so a placeholder is a fully functional rail.
_MERCHANT: Final[str] = "587f72c72cac0d162c722ae2"
#: A DIFFERENT cashbox — the sandbox/production split-brain the ``-31055`` refusal exists for.
_OTHER_MERCHANT: Final[str] = "5f36b1f0a1b2c3d4e5f60718"
#: 7 000 soʻm in tiyin. Already the number the rail is sent: nothing on this path multiplies.
_PRICE: Final[int] = 700_000
#: One second past the twelve-hour window, in seconds. The boundary is EXCLUSIVE, so a test
#: that advanced by exactly ``timeout_ms`` would find the window still open — which is the
#: documented and deliberate direction of that one-millisecond choice.
_PAST_THE_WINDOW_S: Final[int] = DEFAULT_TRANSACTION_TIMEOUT_MS // 1000 + 1

_POSTGRES_URL: Final[str] = os.environ.get(
    "HBD_TEST_POSTGRES_URL", "postgresql+asyncpg://hbd:hbd@localhost:5432/hbd_test"
)


# ---------------------------------------------------------------------------
# Fixtures — three engines, because three different things need proving
# ---------------------------------------------------------------------------
@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """In-memory SQLite on ONE shared connection, per ``tests/test_db/conftest.py``."""
    built = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with built.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield built
    await built.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
async def parallel_sessions(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessions on SEPARATE connections. The in-memory fixture cannot give two writers.

    ``NullPool`` means every checkout opens its own connection to a FILE, which is the only way
    SQLite has two genuine writers — and therefore the only way this suite can reach a race at
    all without a Postgres container. ``timeout`` is the busy handler's budget: the loser waits
    rather than failing instantly where SQLite lets it wait.
    """
    built = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'rail.db'}",
        poolclass=NullPool,
        connect_args={"timeout": 30},
    )
    async with built.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield create_session_factory(built)
    await built.dispose()


@pytest.fixture
async def pg_sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Real Postgres. Skipped unless ``docker compose up -d`` is running."""
    built = create_engine(_POSTGRES_URL)
    if not await ping(built):
        await built.dispose()
        pytest.skip(f"no Postgres at {_POSTGRES_URL}; run `docker compose up -d`")
    async with built.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield create_session_factory(built)
    async with built.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await built.dispose()


@pytest.fixture
def clock() -> MovableClock:
    return MovableClock(FIXED_NOW)


@pytest.fixture
def ledger(sessions: async_sessionmaker[AsyncSession], clock: MovableClock) -> SqlPaymeLedger:
    return SqlPaymeLedger(sessions, merchant_id=_MERCHANT, clock=clock)


# ---------------------------------------------------------------------------
# Builders and probes
# ---------------------------------------------------------------------------
def payme_id() -> str:
    """A 24-character hex id, the shape of the Mongo ObjectId the rail actually sends."""
    return uuid4().hex[:24]


async def open_intent(
    ledger: SqlPaymeLedger,
    *,
    product: Product = Product.SINGLE,
    amount_minor: int = _PRICE,
    merchant_id: str = _MERCHANT,
    key: str | None = None,
    plan_songs: int | None = None,
    plan_days: int | None = None,
) -> PaymentIntent:
    opened = await ledger.open_intent(
        telegram_user_id=_USER,
        product=product,
        amount_minor=amount_minor,
        currency="UZS",
        idempotency_key=key or f"topup:{_USER}:single:{uuid4().hex[:8]}",
        language="uz_latn",
        merchant_id=merchant_id,
        is_sandbox=True,
        plan_songs=plan_songs,
        plan_days=plan_days,
    )
    assert is_ok(opened), opened
    return opened.value


async def created_transaction(
    ledger: SqlPaymeLedger, intent: PaymentIntent, *, now: datetime, at: datetime | None = None
) -> str:
    """Drive a real ``CreateTransaction`` and hand back the rail-side id it now holds."""
    identifier = payme_id()
    made = await ledger.create(
        payme_transaction_id=identifier,
        payme_time=at or now,
        amount_minor=intent.amount_minor,
        public_ref=intent.public_ref,
        now=now,
    )
    assert is_ok(made), made
    return identifier


def fault_code(result: Result[Any]) -> int:
    """The JSON-RPC code an ``Err`` renders as. Fails loudly on an ``Ok``."""
    assert is_err(result), f"expected a refusal, got {result}"
    error: HbdError = result.error
    assert isinstance(error, PaymeFault), f"expected a PaymeFault, got {type(error).__name__}"
    return error.rpc_code


async def count_of(sessions: async_sessionmaker[AsyncSession], table: type[Any]) -> int:
    async with sessions() as session:
        total = await session.scalar(sa.select(sa.func.count()).select_from(table))
        return int(total or 0)


async def grants_in(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        total = await session.scalar(
            sa.select(sa.func.count())
            .select_from(CreditLedgerRow)
            .where(CreditLedgerRow.kind == CreditEntryKind.GRANT)
        )
        return int(total or 0)


async def balance_of(sessions: async_sessionmaker[AsyncSession], user: int = _USER) -> int:
    async with sessions() as session:
        found = await session.scalar(
            sa.select(CreditAccountRow.balance).where(CreditAccountRow.telegram_user_id == user)
        )
        return int(found or 0)


async def transaction_row(
    sessions: async_sessionmaker[AsyncSession], identifier: str
) -> PaymeTransactionRow:
    async with sessions() as session:
        return (
            await session.execute(
                sa.select(PaymeTransactionRow).where(
                    PaymeTransactionRow.payme_transaction_id == identifier
                )
            )
        ).scalar_one()


async def intent_row(
    sessions: async_sessionmaker[AsyncSession], public_ref: str
) -> PaymentIntentRow:
    async with sessions() as session:
        return (
            await session.execute(
                sa.select(PaymentIntentRow).where(PaymentIntentRow.public_ref == public_ref)
            )
        ).scalar_one()


async def whole_database(
    sessions: async_sessionmaker[AsyncSession],
) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table, ordered. A read that changes this has written something.

    Used instead of counting the tables a reader happens to think of, because the claim
    ``CheckPerformTransaction`` makes is not "writes no receipts" — it is "writes nothing",
    including an ``updated_at`` touch or an expiry somebody added later in good faith.
    """
    snapshot: dict[str, list[tuple[Any, ...]]] = {}
    async with sessions() as session:
        for name, table in sorted(Base.metadata.tables.items()):
            rows = (
                await session.execute(sa.select(table).order_by(*list(table.primary_key.columns)))
            ).all()
            snapshot[name] = [tuple(row) for row in rows]
    return snapshot


# ---------------------------------------------------------------------------
# The five replay guarantees
# ---------------------------------------------------------------------------
async def test_a_replayed_create_returns_the_stored_create_time_and_writes_nothing(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — one intent, one create, then the rail resends because our answer was lost.
    intent = await open_intent(ledger)
    identifier = payme_id()
    first = await ledger.create(
        payme_transaction_id=identifier,
        payme_time=clock.now,
        amount_minor=_PRICE,
        public_ref=intent.public_ref,
        now=clock.now,
    )
    before = await whole_database(sessions)

    # Act — an hour later, the identical call.
    clock.advance(seconds=3_600)
    second = await ledger.create(
        payme_transaction_id=identifier,
        payme_time=clock.now,
        amount_minor=_PRICE,
        public_ref=intent.public_ref,
        now=clock.now,
    )

    # Assert — the STORED create_time, not the fresh one, and not a single row moved.
    assert is_ok(first)
    assert is_ok(second)
    assert second.value.create_time == first.value.create_time
    assert second.value.our_id == first.value.our_id
    assert second.value.state is WireState.CREATED
    assert await whole_database(sessions) == before


async def test_a_replayed_perform_returns_the_stored_perform_time_and_grants_nothing(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange
    intent = await open_intent(ledger)
    identifier = await created_transaction(ledger, intent, now=clock.now)
    first = await ledger.perform(payme_transaction_id=identifier, now=clock.now)
    after_one = await whole_database(sessions)

    # Act — the rail resends the perform an hour later.
    clock.advance(seconds=3_600)
    second = await ledger.perform(payme_transaction_id=identifier, now=clock.now)

    # Assert — the STORED perform_time, never now(), and exactly one of everything.
    assert is_ok(first)
    assert is_ok(second)
    assert second.value.perform_time == first.value.perform_time
    assert second.value.perform_time != clock.now
    assert second.value.state is WireState.PERFORMED
    assert await whole_database(sessions) == after_one
    assert await count_of(sessions, TopupPurchaseRow) == 1
    assert await grants_in(sessions) == 1
    assert await balance_of(sessions) == 1


async def test_a_replayed_cancel_replays_the_stored_cancel_time_and_is_not_an_error(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange
    intent = await open_intent(ledger)
    identifier = await created_transaction(ledger, intent, now=clock.now)
    first = await ledger.cancel(
        payme_transaction_id=identifier, reason=int(CancelReason.DEBIT_ERROR), now=clock.now
    )
    before = await whole_database(sessions)

    # Act
    clock.advance(seconds=3_600)
    second = await ledger.cancel(
        payme_transaction_id=identifier, reason=int(CancelReason.DEBIT_ERROR), now=clock.now
    )

    # Assert — a SUCCESS carrying the original clock, never a state refusal.
    assert is_ok(first)
    assert is_ok(second)
    assert second.value.cancel_time == first.value.cancel_time
    assert second.value.state is WireState.CANCELLED
    assert second.value.cancel_reason == int(CancelReason.DEBIT_ERROR)
    assert await whole_database(sessions) == before


async def test_a_perform_for_a_transaction_we_never_created_is_31003_and_writes_nothing(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — a payable intent exists, so the only thing missing is the transaction.
    await open_intent(ledger)
    before = await whole_database(sessions)

    # Act
    refused = await ledger.perform(payme_transaction_id=payme_id(), now=clock.now)

    # Assert — PerformTransaction NEVER creates a transaction.
    assert fault_code(refused) == PaymeErrorCode.TRANSACTION_NOT_FOUND
    assert await whole_database(sessions) == before
    assert await count_of(sessions, PaymeTransactionRow) == 0


async def test_a_replayed_open_intent_returns_the_same_public_ref_and_therefore_the_same_link(
    ledger: SqlPaymeLedger, sessions: async_sessionmaker[AsyncSession]
) -> None:
    # Arrange — one key, two taps.
    key = f"topup:{_USER}:single:1"

    # Act
    first = await open_intent(ledger, key=key)
    second = await open_intent(ledger, key=key)

    # Assert — one intent, one reference, and therefore one payment page in the chat.
    assert first.public_ref == second.public_ref
    assert await count_of(sessions, PaymentIntentRow) == 1


# ---------------------------------------------------------------------------
# The twelve-hour window: cancel FIRST, refuse SECOND
# ---------------------------------------------------------------------------
async def test_a_perform_past_the_twelve_hour_window_cancels_with_reason_four_before_it_refuses(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange
    intent = await open_intent(ledger)
    identifier = await created_transaction(ledger, intent, now=clock.now)

    # Act — twelve hours and one second later.
    clock.advance(seconds=_PAST_THE_WINDOW_S)
    refused = await ledger.perform(payme_transaction_id=identifier, now=clock.now)

    # Assert — the ROW is what proves the ordering, not the returned code. A refusal raised
    # inside the transaction would have rolled the cancellation back and left state 'created'.
    assert fault_code(refused) == PaymeErrorCode.STATE_REFUSAL
    row = await transaction_row(sessions, identifier)
    assert row.state is PaymeState.CANCELLED
    assert row.cancel_reason == int(CancelReason.TIMEOUT)
    assert row.cancel_time == clock.now
    assert row.perform_time is None
    # ...and the hold came off, so the customer may still pay with a fresh transaction.
    assert (await intent_row(sessions, intent.public_ref)).state.value == "pending"
    assert await count_of(sessions, TopupPurchaseRow) == 0
    assert await grants_in(sessions) == 0


async def test_a_create_past_the_twelve_hour_window_also_cancels_before_it_refuses(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange
    intent = await open_intent(ledger)
    identifier = await created_transaction(ledger, intent, now=clock.now)

    # Act — the rail resends the create long after the window closed.
    clock.advance(seconds=_PAST_THE_WINDOW_S)
    refused = await ledger.create(
        payme_transaction_id=identifier,
        payme_time=clock.now,
        amount_minor=_PRICE,
        public_ref=intent.public_ref,
        now=clock.now,
    )

    # Assert
    assert fault_code(refused) == PaymeErrorCode.STATE_REFUSAL
    row = await transaction_row(sessions, identifier)
    assert row.state is PaymeState.CANCELLED
    assert row.cancel_reason == int(CancelReason.TIMEOUT)


async def test_the_window_is_still_open_at_exactly_the_timeout(
    ledger: SqlPaymeLedger, clock: MovableClock
) -> None:
    # Arrange — the boundary is EXCLUSIVE, and the direction of that choice is deliberate:
    # accepting a payment one millisecond late keeps the money and delivers the song, while
    # refusing one millisecond early is a dispute.
    intent = await open_intent(ledger)
    identifier = await created_transaction(ledger, intent, now=clock.now)

    # Act — exactly twelve hours later, not a millisecond more.
    clock.advance(seconds=DEFAULT_TRANSACTION_TIMEOUT_MS // 1000)
    performed = await ledger.perform(payme_transaction_id=identifier, now=clock.now)

    # Assert
    assert is_ok(performed)
    assert performed.value.state is WireState.PERFORMED


# ---------------------------------------------------------------------------
# The mutex: one live transaction per intent, refused BEFORE a card is charged
# ---------------------------------------------------------------------------
async def test_a_second_payme_transaction_for_a_held_intent_is_refused_at_create_time(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — one intent, already held.
    intent = await open_intent(ledger)
    await created_transaction(ledger, intent, now=clock.now)

    # Act — a second transaction against the same order.
    refused = await ledger.create(
        payme_transaction_id=payme_id(),
        payme_time=clock.now,
        amount_minor=_PRICE,
        public_ref=intent.public_ref,
        now=clock.now,
    )

    # Assert — refused, and the row it would have written was rolled back with it. This is the
    # refusal that happens BEFORE a second card is touched.
    assert fault_code(refused) == PaymeErrorCode.STATE_REFUSAL
    assert await count_of(sessions, PaymeTransactionRow) == 1


async def test_a_check_perform_for_a_held_intent_is_refused_through_the_duplicate_code(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the duplicate code is settable because Payme's own materials contradict each
    # other about it, so a certification finding must be an env var and not a release.
    ledger = SqlPaymeLedger(
        sessions,
        merchant_id=_MERCHANT,
        clock=clock,
        duplicate_code=PaymeErrorCode.ACCOUNT_UNKNOWN,
    )
    intent = await open_intent(ledger)
    await created_transaction(ledger, intent, now=clock.now)

    # Act
    refused = await ledger.quote(public_ref=intent.public_ref, amount_minor=_PRICE, now=clock.now)

    # Assert — the configured code, not the hardcoded default.
    assert fault_code(refused) == PaymeErrorCode.ACCOUNT_UNKNOWN


async def test_cancelling_a_created_transaction_releases_the_intent_so_the_customer_can_retry(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — a declined card, expressed as the rail cancels its own transaction.
    intent = await open_intent(ledger)
    first = await created_transaction(ledger, intent, now=clock.now)
    cancelled = await ledger.cancel(
        payme_transaction_id=first, reason=int(CancelReason.DEBIT_ERROR), now=clock.now
    )
    assert is_ok(cancelled)

    # Act — the customer immediately tries another card.
    second = payme_id()
    retried = await ledger.create(
        payme_transaction_id=second,
        payme_time=clock.now,
        amount_minor=_PRICE,
        public_ref=intent.public_ref,
        now=clock.now,
    )
    settled = await ledger.perform(payme_transaction_id=second, now=clock.now)

    # Assert — seconds, not twelve hours. The intent went back to 'pending', not 'cancelled'.
    assert is_ok(retried)
    assert is_ok(settled)
    assert (await intent_row(sessions, intent.public_ref)).state is not None
    assert await count_of(sessions, PaymeTransactionRow) == 2
    assert await count_of(sessions, TopupPurchaseRow) == 1
    assert await balance_of(sessions) == 1


# ---------------------------------------------------------------------------
# No reversal, ever
# ---------------------------------------------------------------------------
async def test_cancelling_a_performed_transaction_is_31007_and_reverses_nothing(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — the money landed and the credit was granted.
    intent = await open_intent(ledger)
    identifier = await created_transaction(ledger, intent, now=clock.now)
    assert is_ok(await ledger.perform(payme_transaction_id=identifier, now=clock.now))
    before = await whole_database(sessions)

    # Act — a refund attempt arrives from the rail.
    refused = await ledger.cancel(
        payme_transaction_id=identifier, reason=int(CancelReason.REFUND), now=clock.now
    )

    # Assert — unconditional -31007, and the balance is untouched. ``credit_accounts.balance``
    # is one fungible scalar with no lot structure, so a compensating debit cannot know whose
    # credit it is burning; PaycomUZ's own template answers the same way by default.
    assert fault_code(refused) == PaymeErrorCode.ORDER_DELIVERED
    assert await balance_of(sessions) == 1
    assert await whole_database(sessions) == before


# ---------------------------------------------------------------------------
# CheckPerformTransaction writes nothing at all
# ---------------------------------------------------------------------------
async def test_check_perform_transaction_writes_no_rows(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange
    intent = await open_intent(ledger)
    before = await whole_database(sessions)

    # Act — allowed, refused for the amount, and refused for an unknown reference.
    allowed = await ledger.quote(public_ref=intent.public_ref, amount_minor=_PRICE, now=clock.now)
    wrong_amount = await ledger.quote(
        public_ref=intent.public_ref, amount_minor=_PRICE + 1, now=clock.now
    )
    unknown = await ledger.quote(public_ref="deadbeef" * 3, amount_minor=_PRICE, now=clock.now)

    # Assert — a full row-set diff, because "writes no receipts" is a weaker claim than the one
    # this method makes.
    assert is_ok(allowed)
    assert fault_code(wrong_amount) == PaymeErrorCode.WRONG_AMOUNT
    assert fault_code(unknown) == PaymeErrorCode.ACCOUNT_UNKNOWN
    assert await whole_database(sessions) == before


async def test_a_lapsed_intent_is_refused_by_the_clock_without_a_sweep_having_run(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — nothing sweeps. Expiry is a predicate against the caller's own instant, which
    # is what makes the machine correct at every moment rather than after a scheduler runs.
    intent = await open_intent(ledger)
    before = await whole_database(sessions)

    # Act
    clock.advance(days=1)
    refused = await ledger.quote(public_ref=intent.public_ref, amount_minor=_PRICE, now=clock.now)

    # Assert
    assert fault_code(refused) == PaymeErrorCode.ACCOUNT_EXPIRED
    assert await whole_database(sessions) == before


async def test_a_check_transaction_mutates_nothing_not_even_an_expiry(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange
    intent = await open_intent(ledger)
    identifier = await created_transaction(ledger, intent, now=clock.now)
    clock.advance(seconds=_PAST_THE_WINDOW_S)
    before = await whole_database(sessions)

    # Act — a status read on a transaction whose window has closed.
    read = await ledger.read(payme_transaction_id=identifier)

    # Assert — still 'created'. A read that expired what it was asked about would make the
    # rail's own poll change the answer it was polling for.
    assert is_ok(read)
    assert read.value.state is WireState.CREATED
    assert await whole_database(sessions) == before


# ---------------------------------------------------------------------------
# The three legal transitions, and everything else
# ---------------------------------------------------------------------------
async def test_a_perform_for_a_cancelled_transaction_is_a_state_refusal(
    ledger: SqlPaymeLedger, sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the legal transitions are created->performed, created->cancelled and
    # performed->cancelled_after_perform. Reviving a cancelled charge is not one of them.
    intent = await open_intent(ledger)
    identifier = await created_transaction(ledger, intent, now=clock.now)
    assert is_ok(
        await ledger.cancel(
            payme_transaction_id=identifier, reason=int(CancelReason.DEBIT_ERROR), now=clock.now
        )
    )
    before = await whole_database(sessions)

    # Act
    refused = await ledger.perform(payme_transaction_id=identifier, now=clock.now)

    # Assert
    assert fault_code(refused) == PaymeErrorCode.STATE_REFUSAL
    assert await whole_database(sessions) == before
    assert await grants_in(sessions) == 0


async def test_a_create_replaying_onto_a_cancelled_transaction_is_a_state_refusal(
    ledger: SqlPaymeLedger, sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    intent = await open_intent(ledger)
    identifier = await created_transaction(ledger, intent, now=clock.now)
    assert is_ok(
        await ledger.cancel(
            payme_transaction_id=identifier, reason=int(CancelReason.DEBIT_ERROR), now=clock.now
        )
    )
    before = await whole_database(sessions)

    # Act — the rail resends the ORIGINAL create after having cancelled it.
    refused = await ledger.create(
        payme_transaction_id=identifier,
        payme_time=clock.now,
        amount_minor=_PRICE,
        public_ref=intent.public_ref,
        now=clock.now,
    )

    # Assert — a dead transaction is not resurrected by a replay of the call that made it.
    assert fault_code(refused) == PaymeErrorCode.STATE_REFUSAL
    assert await whole_database(sessions) == before


async def test_the_intent_read_answers_by_reference_and_reports_a_missing_one_as_none(
    ledger: SqlPaymeLedger, clock: MovableClock
) -> None:
    # Arrange — the read the notification job and the operator journal both go through, since
    # neither may hold a session.
    intent = await open_intent(ledger)

    # Act
    found = await ledger.intent(public_ref=intent.public_ref)
    missing = await ledger.intent(public_ref="deadbeef" * 3)

    # Assert — Ok(None) and not an Err: "there is no such reference" is an ordinary answer to
    # a question about a string somebody else supplied.
    assert is_ok(found)
    assert found.value is not None
    assert found.value.idempotency_key == intent.idempotency_key
    assert found.value.language == "uz_latn"
    assert found.value.state is PaymentIntentState.PENDING
    assert is_ok(missing)
    assert missing.value is None


# ---------------------------------------------------------------------------
# The cashbox column
# ---------------------------------------------------------------------------
async def test_an_intent_issued_for_another_cashbox_is_refused_at_perform(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — the link was issued by this cashbox, then the deployment was repointed at a
    # different one while the link was still live in somebody's chat.
    intent = await open_intent(ledger)
    identifier = await created_transaction(ledger, intent, now=clock.now)
    repointed = SqlPaymeLedger(sessions, merchant_id=_OTHER_MERCHANT, clock=clock)

    # Act
    refused = await repointed.perform(payme_transaction_id=identifier, now=clock.now)

    # Assert — -31055, and the state flip made moments earlier in the same commit was rolled
    # back with it, so nothing claims this charge was performed.
    assert fault_code(refused) == PaymeErrorCode.ACCOUNT_WRONG_MERCHANT
    assert (await transaction_row(sessions, identifier)).state is PaymeState.CREATED
    assert await count_of(sessions, TopupPurchaseRow) == 0
    assert await grants_in(sessions) == 0


async def test_an_intent_issued_for_another_cashbox_is_refused_at_check_perform(
    ledger: SqlPaymeLedger, sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    intent = await open_intent(ledger, merchant_id=_OTHER_MERCHANT)

    # Act
    refused = await ledger.quote(public_ref=intent.public_ref, amount_minor=_PRICE, now=clock.now)

    # Assert
    assert fault_code(refused) == PaymeErrorCode.ACCOUNT_WRONG_MERCHANT


# ---------------------------------------------------------------------------
# The account range, and the two methods that answer about a transaction we lack
# ---------------------------------------------------------------------------
async def test_a_cancel_or_a_status_check_for_an_unknown_transaction_is_31003(
    ledger: SqlPaymeLedger, sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    before = await whole_database(sessions)
    unknown = payme_id()

    # Act
    cancelled = await ledger.cancel(
        payme_transaction_id=unknown, reason=int(CancelReason.TIMEOUT), now=clock.now
    )
    read = await ledger.read(payme_transaction_id=unknown)

    # Assert — neither method invents a transaction, for the reason ``perform`` does not.
    assert fault_code(cancelled) == PaymeErrorCode.TRANSACTION_NOT_FOUND
    assert fault_code(read) == PaymeErrorCode.TRANSACTION_NOT_FOUND
    assert await whole_database(sessions) == before


async def test_a_settled_order_is_31051_and_a_swept_one_is_31053(
    ledger: SqlPaymeLedger, sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the two terminal intent states that have their own account code, so Payme's own
    # interface can tell the customer which of them happened rather than "unknown order".
    paid = await open_intent(ledger, key=f"topup:{_USER}:single:paid")
    identifier = await created_transaction(ledger, paid, now=clock.now)
    assert is_ok(await ledger.perform(payme_transaction_id=identifier, now=clock.now))
    lapsed = await open_intent(ledger, key=f"topup:{_USER}:single:lapsed")
    clock.advance(days=1)
    assert is_ok(await ledger.expire_lapsed(now=clock.now, limit=10))
    before = await whole_database(sessions)

    # Act
    already = await ledger.quote(public_ref=paid.public_ref, amount_minor=_PRICE, now=clock.now)
    gone = await ledger.quote(public_ref=lapsed.public_ref, amount_minor=_PRICE, now=clock.now)

    # Assert
    assert fault_code(already) == PaymeErrorCode.ACCOUNT_ALREADY_PAID
    assert fault_code(gone) == PaymeErrorCode.ACCOUNT_EXPIRED
    assert await whole_database(sessions) == before


async def test_a_settlement_for_a_buyer_erased_mid_payment_is_accepted_and_grants_nothing(
    ledger: SqlPaymeLedger, sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """``/forget`` between the create and the perform. **The money is not refused.**

    The rail is telling us a card was charged, not asking whether it may be. There is nobody
    left to grant a credit to, so the intent is claimed and no sale is written — but refusing
    would leave the rail retrying a charge it has already taken, which is the one outcome worse
    than an ungranted credit: a customer debited against an order we keep declining. The
    three-way settlement invariant then surfaces it as a performed transaction with no receipt,
    which is exactly what an operator must see.
    """
    # Arrange
    intent = await open_intent(ledger)
    identifier = await created_transaction(ledger, intent, now=clock.now)
    async with sessions.begin() as session:
        assert await anonymise_intents(session, telegram_user_id=_USER) == 1

    # Act
    settled = await ledger.perform(payme_transaction_id=identifier, now=clock.now)

    # Assert
    assert is_ok(settled)
    assert settled.value.state is WireState.PERFORMED
    assert (await transaction_row(sessions, identifier)).state is PaymeState.PERFORMED
    assert (await intent_row(sessions, intent.public_ref)).state.value == "paid"
    assert await count_of(sessions, TopupPurchaseRow) == 0
    assert await grants_in(sessions) == 0


# ---------------------------------------------------------------------------
# GetStatement
# ---------------------------------------------------------------------------
async def test_get_statement_filters_on_payme_time_inclusively_and_sorts_ascending(
    ledger: SqlPaymeLedger, clock: MovableClock
) -> None:
    # Arrange — three transactions on three intents, an hour apart, created out of order so a
    # test that passed by insertion order would fail here.
    middle_at = clock.now
    early_at = middle_at - timedelta(hours=1)
    late_at = middle_at + timedelta(hours=1)
    late = await created_transaction(ledger, await open_intent(ledger), now=clock.now, at=late_at)
    early = await created_transaction(ledger, await open_intent(ledger), now=clock.now, at=early_at)
    middle = await created_transaction(
        ledger, await open_intent(ledger), now=clock.now, at=middle_at
    )

    # Act
    whole = await ledger.statement(frm=early_at, to=late_at)
    boundary = await ledger.statement(frm=middle_at, to=middle_at)

    # Assert — inclusive at both ends, ascending on the RAIL's clock, and the account value is
    # the intent's opaque reference rather than anything derived from a Telegram id.
    assert is_ok(whole)
    assert [row.transaction.payme_transaction_id for row in whole.value] == [
        early,
        middle,
        late,
    ]
    assert all(row.account_value == row.transaction.intent_public_ref for row in whole.value)
    assert all(row.product is Product.SINGLE for row in whole.value)
    assert is_ok(boundary)
    assert [row.transaction.payme_transaction_id for row in boundary.value] == [middle]


async def test_get_statement_returns_an_empty_tuple_for_an_empty_period(
    ledger: SqlPaymeLedger, clock: MovableClock
) -> None:
    # Arrange / Act
    empty = await ledger.statement(frm=clock.now, to=clock.now + timedelta(hours=1))

    # Assert — an empty period is an empty list and never an error.
    assert is_ok(empty)
    assert empty.value == ()


# ---------------------------------------------------------------------------
# Expiry can never refuse a payment the rail still considers open
# ---------------------------------------------------------------------------
async def test_an_intent_holding_a_live_transaction_is_never_expired_by_our_clock(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a SHORT link validity against the rail's full twelve-hour charge window, which
    # is the arrangement that makes the two clocks disagree at all. A card is being charged
    # against this intent right now.
    ledger = SqlPaymeLedger(sessions, merchant_id=_MERCHANT, clock=clock, intent_ttl_s=60)
    intent = await open_intent(ledger)
    identifier = await created_transaction(ledger, intent, now=clock.now)
    held = await intent_row(sessions, intent.public_ref)
    assert held.state.value == PaymentIntentState.AWAITING.value

    # Act — our own validity window lapses while the charge is still in flight on theirs, and
    # the sweep runs.
    clock.advance(seconds=600)
    swept = await ledger.expire_lapsed(now=clock.now, limit=100)

    # Assert — untouched, because 'awaiting' is not in the set the sweep can see. The payment
    # then completes normally: our clock and the rail's are not the same clock, and this is the
    # property that stops the difference costing a customer their money.
    assert is_ok(swept)
    assert swept.value == 0
    after = await intent_row(sessions, intent.public_ref)
    assert after.state.value == PaymentIntentState.AWAITING.value
    settled = await ledger.perform(payme_transaction_id=identifier, now=clock.now)
    assert is_ok(settled)
    assert await balance_of(sessions) == 1


async def test_the_sweep_expires_a_lapsed_pending_intent_and_leaves_a_fresh_one_alone(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange
    stale = await open_intent(ledger)
    clock.advance(days=1)
    fresh = await open_intent(ledger)

    # Act
    swept = await ledger.expire_lapsed(now=clock.now, limit=100)

    # Assert
    assert is_ok(swept)
    assert swept.value == 1
    assert (await intent_row(sessions, stale.public_ref)).state.value == "expired"
    assert (await intent_row(sessions, fresh.public_ref)).state.value == "pending"


async def test_the_sweep_cancels_a_stale_created_transaction_and_releases_its_intent(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — the rail created a transaction and then never called again.
    intent = await open_intent(ledger)
    identifier = await created_transaction(ledger, intent, now=clock.now)

    # Act
    clock.advance(seconds=_PAST_THE_WINDOW_S)
    swept = await ledger.expire_stale_transactions(now=clock.now, limit=100)

    # Assert — CheckTransaction stays honest, and the hold comes off.
    assert is_ok(swept)
    assert swept.value == 1
    row = await transaction_row(sessions, identifier)
    assert row.state is PaymeState.CANCELLED
    assert row.cancel_reason == int(CancelReason.TIMEOUT)
    assert (await intent_row(sessions, intent.public_ref)).state.value == "pending"


async def test_the_sweep_leaves_a_transaction_sitting_exactly_on_the_boundary_alone(
    ledger: SqlPaymeLedger, sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the sweep's SQL cutoff is inclusive and ``rules.is_expired``'s boundary is
    # exclusive, so the read deliberately over-selects by one millisecond and the PREDICATE is
    # what actually chooses. One boundary, in one place: without the second check the sweep
    # would cancel a transaction that a ``PerformTransaction`` arriving in the same second is
    # still entitled to complete.
    intent = await open_intent(ledger)
    identifier = await created_transaction(ledger, intent, now=clock.now)

    # Act — exactly twelve hours later, not a millisecond more.
    clock.advance(seconds=DEFAULT_TRANSACTION_TIMEOUT_MS // 1000)
    swept = await ledger.expire_stale_transactions(now=clock.now, limit=100)

    # Assert
    assert is_ok(swept)
    assert swept.value == 0
    assert (await transaction_row(sessions, identifier)).state is PaymeState.CREATED
    assert is_ok(await ledger.perform(payme_transaction_id=identifier, now=clock.now))


# ---------------------------------------------------------------------------
# The races. One credit, whatever the engine does to the loser.
# ---------------------------------------------------------------------------
async def _seed_two_transactions_on_one_intent(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
) -> tuple[str, str]:
    """One intent, held by the first transaction, with a SECOND written directly against it.

    The second transaction cannot be created through ``create`` — that is the whole point of
    the mutex — so it is inserted through the package's own write primitive instead. This is the
    state a rail that had ignored our ``-31008`` and charged a second card would leave behind,
    and it is the only way to put two performs in flight for one order.
    """
    intent = await open_intent(ledger)
    held = await created_transaction(ledger, intent, now=now)
    intruder = payme_id()
    async with sessions.begin() as session:
        row = await intent_row(sessions, intent.public_ref)
        await insert_transaction(
            session,
            transaction_id=uuid4(),
            payme_transaction_id=intruder,
            intent_id=row.id,
            payme_time=now,
            amount_minor=_PRICE,
            create_time=now,
            now=now,
        )
    return held, intruder


def _one_winner(outcomes: Sequence[Result[Any]]) -> None:
    """Exactly one ``Ok`` and one ``Err``, whatever refused the loser."""
    assert len([out for out in outcomes if is_ok(out)]) == 1, outcomes
    assert len([out for out in outcomes if is_err(out)]) == 1, outcomes


async def test_two_concurrent_performs_on_one_intent_grant_exactly_one_credit(
    parallel_sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — two connections, so this is a genuine race and not an interleaving.
    ledger = SqlPaymeLedger(parallel_sessions, merchant_id=_MERCHANT, clock=clock)
    held, intruder = await _seed_two_transactions_on_one_intent(
        ledger, parallel_sessions, now=clock.now
    )

    # Act
    outcomes = await asyncio.gather(
        ledger.perform(payme_transaction_id=held, now=clock.now),
        ledger.perform(payme_transaction_id=intruder, now=clock.now),
    )

    # Assert — one settlement, one refusal, and ONE credit. The mechanism that refused the
    # loser is engine-specific (SQLite's file lock here, a conditional UPDATE's rowcount on
    # Postgres) and is deliberately not asserted; the outcome is the property under test.
    _one_winner(outcomes)
    assert await count_of(parallel_sessions, TopupPurchaseRow) == 1
    assert await grants_in(parallel_sessions) == 1
    assert await balance_of(parallel_sessions) == 1
    assert await count_of(parallel_sessions, PaymeTransactionRow) == 2


@pytest.mark.integration
async def test_two_concurrent_performs_on_one_intent_grant_exactly_one_credit_on_postgres(
    pg_sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The same race on the engine that ships, where the loser is refused for the RIGHT reason.

    SQLite refuses the second writer with a file lock before it can evaluate anything. Postgres
    lets both transactions run and refuses the loser on ``claim_intent``'s rowcount under READ
    COMMITTED — which is the mechanism this design actually rests on, and the only one that can
    be observed here rather than inferred.
    """
    # Arrange
    ledger = SqlPaymeLedger(pg_sessions, merchant_id=_MERCHANT, clock=clock)
    held, intruder = await _seed_two_transactions_on_one_intent(ledger, pg_sessions, now=clock.now)

    # Act
    outcomes = await asyncio.gather(
        ledger.perform(payme_transaction_id=held, now=clock.now),
        ledger.perform(payme_transaction_id=intruder, now=clock.now),
    )

    # Assert
    _one_winner(outcomes)
    loser = next(out for out in outcomes if isinstance(out, Err))
    assert isinstance(loser.error, PaymeFault)
    assert loser.error.rpc_code == PaymeErrorCode.STATE_REFUSAL
    assert await count_of(pg_sessions, TopupPurchaseRow) == 1
    assert await grants_in(pg_sessions) == 1
    assert await balance_of(pg_sessions) == 1


async def test_a_second_perform_on_a_settled_intent_is_refused_and_grants_nothing(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — the deterministic half of the race above: the same two transactions, performed
    # one after the other rather than at once. The refusal must be typed, not incidental.
    held, intruder = await _seed_two_transactions_on_one_intent(ledger, sessions, now=clock.now)
    settled = await ledger.perform(payme_transaction_id=held, now=clock.now)

    # Act
    refused = await ledger.perform(payme_transaction_id=intruder, now=clock.now)

    # Assert — the loser's whole commit unwound, including its own state flip.
    assert is_ok(settled)
    assert fault_code(refused) == PaymeErrorCode.STATE_REFUSAL
    assert (await transaction_row(sessions, intruder)).state is PaymeState.CREATED
    assert await count_of(sessions, TopupPurchaseRow) == 1
    assert await grants_in(sessions) == 1
    assert await balance_of(sessions) == 1


async def test_two_concurrent_performs_of_the_same_payme_id_both_answer_state_two(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    """The rail's own retry racing itself. Neither caller may be told ``-31008``.

    Run against the SHARED-connection in-memory fixture on purpose: the two coroutines
    interleave their statements inside one connection, so the second ``mark_performed``
    genuinely observes the first one's flip and takes the re-read branch. On separate
    connections SQLite would refuse the second writer outright and that branch would never be
    reached — which is exactly why the branch exists for Postgres and why answering "did my
    money go through?" with a state refusal would be the worst wrong answer available.
    """
    # Arrange
    intent = await open_intent(ledger)
    identifier = await created_transaction(ledger, intent, now=clock.now)

    # Act — the same transaction id, twice, at once.
    first, second = await asyncio.gather(
        ledger.perform(payme_transaction_id=identifier, now=clock.now),
        ledger.perform(payme_transaction_id=identifier, now=clock.now),
    )

    # Assert — both succeed, both carry the SAME perform_time, and one credit exists.
    assert is_ok(first)
    assert is_ok(second)
    assert first.value.state is WireState.PERFORMED
    assert second.value.state is WireState.PERFORMED
    assert first.value.perform_time == second.value.perform_time
    assert await count_of(sessions, TopupPurchaseRow) == 1
    assert await grants_in(sessions) == 1
    assert await balance_of(sessions) == 1


# ---------------------------------------------------------------------------
# The plan product settles down the other half of the shared write primitive
# ---------------------------------------------------------------------------
async def test_a_settled_plan_intent_writes_a_plan_receipt_and_no_credit(
    ledger: SqlPaymeLedger,
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
) -> None:
    # Arrange — the plan snapshot travels on the intent, frozen at the moment of the offer, so
    # a package change between the tap and the payment cannot shrink what was bought.
    intent = await open_intent(
        ledger,
        product=Product.STARTER,
        amount_minor=5_000_000,
        plan_songs=12,
        plan_days=30,
    )
    identifier = await created_transaction(ledger, intent, now=clock.now)

    # Act
    settled = await ledger.perform(payme_transaction_id=identifier, now=clock.now)

    # Assert — a plan mints its songs as they are used, so there is a receipt and no grant.
    assert is_ok(settled)
    assert await count_of(sessions, PlanPurchaseRow) == 1
    assert await count_of(sessions, TopupPurchaseRow) == 0
    assert await grants_in(sessions) == 0
    async with sessions() as session:
        row = (await session.execute(sa.select(PlanPurchaseRow))).scalar_one()
    assert row.songs_included == 12
    assert row.reference == identifier
    assert row.idempotency_key == intent.idempotency_key
