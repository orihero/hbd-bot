"""The three redirect-rail tables, asserted against a real database rather than a model.

Revision 0023 carries three unique indexes and three CHECK constraints, and every one of
them exists because the alternative is a customer charged twice, a customer charged for
nothing, or a payment hold nobody can release. None of that is provable by reading the
model file: SQLAlchemy will happily construct an object that violates every constraint it
declares, and the assertion that matters is the one the ENGINE makes on ``flush``.

So each test here writes real rows through a real session and asserts a real
``IntegrityError``. That also makes each one a live check that the constraint survived
``create_all`` — which is the schema the whole unit suite runs on — and
``test_migrations.py`` separately proves that schema matches the chain.

**Every Telegram id in this file is outside the 32-bit range**, matching ``test_credits.py``
and ``test_credit_erasure.py``. An accidental ``Integer`` column on this path would not fail
loudly; it would silently truncate the id of whoever is paying, and the row would then be
anonymised on somebody else's ``/forget`` or missed entirely on their own.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import is_ok
from bayram.db.enums import IntentProduct, PaymentIntentState, PaymeState
from bayram.db.models.payme_rpc_log import PaymeRpcLogRow
from bayram.db.models.payme_transaction import PaymeTransactionRow
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.purge import purge_expired
from tests.test_db.conftest import MovableClock

#: Well outside 2**31. See the module docstring.
_USER: Final[int] = 8_912_345_678_901
#: The cashbox the placeholder configuration issues links for. A 24-character ObjectId, like
#: the real one will be, so nothing in these tests depends on the credential being absent.
_MERCHANT: Final[str] = "587f72c72cac0d162c722ae2"


def _intent(clock: MovableClock, **overrides: Any) -> PaymentIntentRow:
    """A pending single-song intent, valid in every respect the schema can check."""
    values: dict[str, Any] = {
        "public_ref": uuid4().hex[:24],
        "idempotency_key": f"topup:{_USER}:single:{uuid4().hex[:8]}",
        "telegram_user_id": _USER,
        "product": IntentProduct.SINGLE,
        "amount_minor": 700_000,
        "currency": "UZS",
        "provider": "payme",
        "merchant_id": _MERCHANT,
        "is_sandbox": True,
        "language": "uz_latn",
        "state": PaymentIntentState.PENDING,
        "valid_until": clock.now + timedelta(hours=12),
    }
    values.update(overrides)
    return PaymentIntentRow(**values)


def _transaction(clock: MovableClock, *, intent_id: UUID, **overrides: Any) -> PaymeTransactionRow:
    """A created rail-side transaction against ``intent_id``."""
    values: dict[str, Any] = {
        "payme_transaction_id": uuid4().hex[:24],
        "intent_id": intent_id,
        "payme_time": clock.now,
        "amount_minor": 700_000,
        "state": PaymeState.CREATED,
        "create_time": clock.now,
    }
    values.update(overrides)
    return PaymeTransactionRow(**values)


async def _add(sessions: async_sessionmaker[AsyncSession], *rows: object) -> None:
    async with sessions.begin() as session:
        session.add_all(list(rows))


# ---------------------------------------------------------------------------
# The unique indexes — three of them, each closing a different double charge
# ---------------------------------------------------------------------------
async def test_two_intents_cannot_share_an_idempotency_key(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A double tap in the bot must collapse onto ONE payment page, not open a second."""
    # Arrange — the same bot-minted key the ledger and both receipt tables deduplicate on.
    key = f"topup:{_USER}:single:7"
    await _add(sessions, _intent(clock, idempotency_key=key))

    # Act / Assert — two live payment pages for one purchase would leave the customer with
    # no way to tell which of them their money went into.
    with pytest.raises(IntegrityError):
        await _add(sessions, _intent(clock, idempotency_key=key))


async def test_two_intents_cannot_share_a_public_reference(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The rail's account number has to resolve to exactly one intent."""
    # Arrange
    ref = "a1b2c3d4e5f6a7b8c9d0e1f2"
    await _add(sessions, _intent(clock, public_ref=ref))

    # Act / Assert — an ambiguous account number is "which payment is this?" being
    # unanswerable at the moment money is actually moving.
    with pytest.raises(IntegrityError):
        await _add(sessions, _intent(clock, public_ref=ref))


async def test_two_transactions_cannot_share_a_payme_transaction_id(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The entire retry story: a resent create is a replay, never a second charge."""
    # Arrange
    intent = _intent(clock)
    await _add(sessions, intent)
    payme_id = "62733a1e7b0d4a0f9c11aa02"
    await _add(sessions, _transaction(clock, intent_id=intent.id, payme_transaction_id=payme_id))

    # Act / Assert — the rail resends every call until it likes the answer.
    with pytest.raises(IntegrityError):
        await _add(
            sessions, _transaction(clock, intent_id=intent.id, payme_transaction_id=payme_id)
        )


async def test_one_intent_may_accumulate_more_than_one_transaction(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """``intent_id`` is deliberately NOT unique, and the reason is a declined card.

    The rail cancels the transaction, our side releases the hold, and the customer pays with
    a second card seconds later. A unique index here would refuse that retry and turn a
    declined card into a dead payment page for the life of the validity window.
    """
    # Arrange
    intent = _intent(clock)
    await _add(sessions, intent)

    # Act
    await _add(
        sessions,
        _transaction(clock, intent_id=intent.id, state=PaymeState.CANCELLED, cancel_reason=2),
        _transaction(clock, intent_id=intent.id),
    )

    # Assert
    async with sessions() as session:
        found = (
            await session.execute(
                sa.select(sa.func.count())
                .select_from(PaymeTransactionRow)
                .where(PaymeTransactionRow.intent_id == intent.id)
            )
        ).scalar_one()
    assert found == 2


# ---------------------------------------------------------------------------
# The CHECK constraints — each one refusing a state the code must never write
# ---------------------------------------------------------------------------
async def test_a_starter_intent_without_plan_fields_is_refused_by_the_schema(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A plan is a song count that runs out on a date; an intent for one must carry both.

    Reaching settlement without them would either fail on ``plan_purchases.songs_included``
    (NOT NULL) inside the money transaction, or invite a future reader to "repair" it by
    looking the package up from settings at settle time — which is the retroactive shrink
    revision 0015 stores ``songs_included`` on the row to prevent.
    """
    # Arrange / Act / Assert
    with pytest.raises(IntegrityError):
        await _add(sessions, _intent(clock, product=IntentProduct.STARTER))


@pytest.mark.parametrize(("songs", "days"), [(12, None), (None, 30)])
async def test_a_starter_intent_with_only_half_the_plan_is_refused_too(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
    songs: int | None,
    days: int | None,
) -> None:
    """Both-or-neither, not at-least-one: a song count with no end date is not a plan."""
    # Arrange / Act / Assert
    with pytest.raises(IntegrityError):
        await _add(
            sessions,
            _intent(clock, product=IntentProduct.STARTER, plan_songs=songs, plan_days=days),
        )


async def test_a_starter_intent_carrying_both_plan_fields_is_accepted(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The positive half. A constraint that refused everything would pass every test above."""
    # Arrange / Act
    await _add(sessions, _intent(clock, product=IntentProduct.STARTER, plan_songs=12, plan_days=30))

    # Assert
    async with sessions() as session:
        row = (await session.execute(sa.select(PaymentIntentRow))).scalar_one()
    assert row.product is IntentProduct.STARTER
    assert (row.plan_songs, row.plan_days) == (12, 30)


async def test_an_awaiting_intent_without_a_holder_is_refused_by_the_schema(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """An ``awaiting`` row with a NULL holder is a hold nobody can ever release.

    Every conditional ``UPDATE`` out of that state names the transaction id, so none of them
    would match; and the expiry sweep reads ``pending`` only, so it cannot see the row
    either. It would be stuck, silently, for the life of the row.
    """
    # Arrange / Act / Assert
    with pytest.raises(IntegrityError):
        await _add(sessions, _intent(clock, state=PaymentIntentState.AWAITING))


async def test_an_awaiting_intent_naming_its_holder_is_accepted(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The positive half of the hold constraint."""
    # Arrange
    holder = uuid4()

    # Act
    await _add(
        sessions,
        _intent(clock, state=PaymentIntentState.AWAITING, active_transaction_id=holder),
    )

    # Assert
    async with sessions() as session:
        row = (await session.execute(sa.select(PaymentIntentRow))).scalar_one()
    assert row.state is PaymentIntentState.AWAITING
    assert row.active_transaction_id == holder


async def test_a_negative_amount_is_refused_on_the_intent(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Zero is a legal promo price; a negative is a refund wearing an offer's shape."""
    # Arrange / Act / Assert
    with pytest.raises(IntegrityError):
        await _add(sessions, _intent(clock, amount_minor=-1))


async def test_a_negative_amount_is_refused_on_the_transaction(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Same constraint one table along, and it matters more here: this number arrives from
    the public internet rather than from our own settings."""
    # Arrange
    intent = _intent(clock)
    await _add(sessions, intent)

    # Act / Assert
    with pytest.raises(IntegrityError):
        await _add(sessions, _transaction(clock, intent_id=intent.id, amount_minor=-1))


async def test_an_amount_of_zero_is_accepted_on_both_tables(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A promo priced at nothing is a real offer and a real charge — ``ge=0``, not ``gt=0``."""
    # Arrange
    intent = _intent(clock, amount_minor=0)

    # Act
    await _add(sessions, intent)
    await _add(sessions, _transaction(clock, intent_id=intent.id, amount_minor=0))

    # Assert
    async with sessions() as session:
        stored = (await session.execute(sa.select(PaymeTransactionRow))).scalar_one()
    assert stored.amount_minor == 0


# ---------------------------------------------------------------------------
# The columns themselves
# ---------------------------------------------------------------------------
async def test_a_telegram_id_beyond_the_32_bit_range_round_trips_intact(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """An ``Integer`` column here would truncate the id of whoever is paying, silently."""
    # Arrange / Act
    await _add(sessions, _intent(clock))

    # Assert
    async with sessions() as session:
        row = (await session.execute(sa.select(PaymentIntentRow))).scalar_one()
    assert row.telegram_user_id == _USER


async def test_a_freshly_opened_intent_has_settled_notified_and_note_all_null(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Three separate absences, and none of them defaulted into a false statement.

    ``settled_at`` NULL means no money landed; ``notified_at`` NULL means nobody was told;
    ``settle_note`` NULL means nobody has claimed to have settled it. A default on any of
    the three would be the row asserting something that has not happened.
    """
    # Arrange / Act
    await _add(sessions, _intent(clock))

    # Assert
    async with sessions() as session:
        row = (await session.execute(sa.select(PaymentIntentRow))).scalar_one()
    assert (row.settled_at, row.notified_at, row.settle_note) == (None, None, None)
    assert row.active_transaction_id is None


async def test_the_rails_creation_instant_is_stored_apart_from_our_own(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """``payme_time`` is THEIRS and ``created_at`` is OURS, and the timeout runs off theirs.

    Running the twelve-hour window off our clock would cancel transactions the rail still
    considers live — a customer whose money moved against a payment we had already refused.
    """
    # Arrange — the rail created the transaction ten minutes before our row was written.
    intent = _intent(clock)
    await _add(sessions, intent)
    rail_instant = clock.now - timedelta(minutes=10)

    # Act
    await _add(sessions, _transaction(clock, intent_id=intent.id, payme_time=rail_instant))

    # Assert
    async with sessions() as session:
        row = (await session.execute(sa.select(PaymeTransactionRow))).scalar_one()
    assert row.payme_time == rail_instant
    assert row.created_at > row.payme_time


async def test_the_three_replay_clocks_start_out_as_one_instant_and_two_nulls(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A replayed method must return the ORIGINAL answer, so all three are persisted."""
    # Arrange
    intent = _intent(clock)
    await _add(sessions, intent)

    # Act
    await _add(sessions, _transaction(clock, intent_id=intent.id))

    # Assert
    async with sessions() as session:
        row = (await session.execute(sa.select(PaymeTransactionRow))).scalar_one()
    assert isinstance(row.create_time, datetime)
    assert row.perform_time is None
    assert row.cancel_time is None
    assert row.cancel_reason is None


async def test_the_rpc_journal_holds_no_column_that_could_name_a_person(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The absence is the design, so it is asserted rather than left to a reviewer.

    Adding ``telegram_user_id``, a request body or a header here would drag the one table an
    operator reads DURING an incident into ``test_privacy_constraints.py``'s
    ``tables_with_personal_data`` — onto a retention clock, deleting itself on a schedule.
    """
    # Arrange / Act
    columns = {column.name for column in PaymeRpcLogRow.__table__.columns}

    # Assert
    assert columns == {
        "id",
        "at",
        "method",
        "payme_transaction_id",
        "public_ref",
        "reply_code",
        "peer_ip",
        "duration_ms",
    }


async def test_a_journal_row_survives_a_call_that_named_neither_reference(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A failed authentication has no transaction and no account — and is the row that matters.

    If either identifier were NOT NULL, the calls an incident is actually about would be the
    only ones the journal could not record.
    """
    # Arrange / Act
    await _add(
        sessions,
        PaymeRpcLogRow(
            at=clock.now,
            method="CheckPerformTransaction",
            reply_code=-32504,
            peer_ip="185.234.113.1",
            duration_ms=3,
        ),
    )

    # Assert
    async with sessions() as session:
        row = (await session.execute(sa.select(PaymeRpcLogRow))).scalar_one()
    assert (row.payme_transaction_id, row.public_ref) == (None, None)
    assert row.reply_code == -32504


# ---------------------------------------------------------------------------
# The retention shapes — which rows the sweep may take, and which it may never
# ---------------------------------------------------------------------------
async def test_the_rpc_journal_is_swept_at_ninety_days_and_the_money_table_is_never_swept(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Two tables written by the same inbound call, on deliberately opposite bounds.

    The journal is chatter: bounded growth on a table the rail can fill by resending a call
    it does not like the answer to. ``payme_transactions`` is an audit fact about MONEY — it
    is what the rail says it charged — and it is on no bound at all, because a row deleted
    on a schedule is a real payment we would have to answer "never existed" about.
    """
    # Arrange — one journalled call either side of the ninety-day cutoff, and one
    # transaction old enough that any cutoff at all would have taken it.
    intent = _intent(clock)
    await _add(sessions, intent)
    await _add(
        sessions,
        PaymeRpcLogRow(
            at=clock.now - timedelta(days=91),
            method="CheckTransaction",
            reply_code=0,
            duration_ms=4,
        ),
        PaymeRpcLogRow(
            at=clock.now - timedelta(days=89),
            method="CheckTransaction",
            reply_code=0,
            duration_ms=4,
        ),
        _transaction(
            clock,
            intent_id=intent.id,
            payme_time=clock.now - timedelta(days=900),
            created_at=clock.now - timedelta(days=900),
        ),
    )

    # Act
    outcome = await purge_expired(sessions, now=clock.now)

    # Assert
    assert is_ok(outcome), outcome
    assert outcome.value.payme_rpc_rows_deleted == 1
    async with sessions() as session:
        journalled = (await session.execute(sa.select(PaymeRpcLogRow))).scalars().all()
        charges = (await session.execute(sa.select(PaymeTransactionRow))).scalars().all()
    assert len(journalled) == 1
    assert len(charges) == 1, "payme_transactions is on no retention bound at all"


@pytest.mark.parametrize(
    ("state", "survives"),
    [
        (PaymentIntentState.CANCELLED, False),
        (PaymentIntentState.EXPIRED, False),
        (PaymentIntentState.PAID, True),
        (PaymentIntentState.PENDING, True),
    ],
)
async def test_only_a_terminal_unpaid_intent_is_taken_by_the_four_hundred_day_cutoff(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
    state: PaymentIntentState,
    survives: bool,
) -> None:
    """**A ``paid`` intent is never purged**, and the sweep may not touch a live one either.

    A paid intent is the join between a rail-side transaction and the receipt and credit
    grant written in the same commit, and the rail may still ask about that transaction over
    an arbitrary period. A ``pending`` one is simply still live: it is expiry's job to move
    it to ``expired`` first, on ``valid_until``, which is a business clock this job does not
    read.
    """
    # Arrange — old enough that the cutoff alone would take it; only the state decides.
    old = clock.now - timedelta(days=401)
    await _add(sessions, _intent(clock, state=state, created_at=old, updated_at=old))

    # Act
    outcome = await purge_expired(sessions, now=clock.now)

    # Assert
    assert is_ok(outcome), outcome
    assert outcome.value.payment_intents_deleted == (0 if survives else 1)
    async with sessions() as session:
        remaining = (
            await session.execute(sa.select(sa.func.count()).select_from(PaymentIntentRow))
        ).scalar_one()
    assert remaining == (1 if survives else 0)


# ---------------------------------------------------------------------------
# The three mirrored enums
# ---------------------------------------------------------------------------
def test_the_three_column_enums_mirror_their_application_counterparts_value_for_value() -> None:
    """The column enums are copies, and nothing but this file can see both halves.

    ``bayram.db.enums`` deliberately does not import ``bayram.checkout`` or ``bayram.payme.protocol``,
    and neither of those may import ``bayram.db`` — the layering is the whole architecture of
    this rail. The cost is that every one of these three pairs is a value-for-value copy held
    together by nothing at runtime, and a drift is silent in the worst possible way: a member
    added on one side is written into a ``VARCHAR`` column that the reading side then cannot
    construct, so the row is unreadable only for the customer it belongs to.

    ``tests/test_db`` is the one place in the repository where importing both sides is legal,
    which is why the assertion lives here rather than beside either enum.

    ``IntentProduct`` mirrors the WHOLE of ``Product`` rather than a subset, unlike
    ``TopupKind`` — an intent is a payment for something not yet sold and both products are
    sold down this rail, so a subset here would be an unsellable plan rather than a tidier
    enum.
    """
    # Arrange
    from bayram.checkout import PaymentIntentState as AppIntentState
    from bayram.checkout import Product as AppProduct
    from bayram.payme.protocol import PaymeState as WirePaymeState

    # Act / Assert
    assert {member.value for member in IntentProduct} == {member.value for member in AppProduct}
    assert {member.value for member in PaymentIntentState} == {
        member.value for member in AppIntentState
    }
    assert {member.value for member in PaymeState} == {member.value for member in WirePaymeState}
