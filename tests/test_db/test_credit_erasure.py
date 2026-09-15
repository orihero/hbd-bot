"""``/forget`` against the credit tables: the balance goes, the receipt stays anonymous.

``/privacy`` promises deletion on a schedule and enumerates four clocks. ``credit_accounts``
and ``credit_ledger`` are on none of them, which made the notice false the moment the
entitlement layer landed. These tests pin the shape that makes it true again — and, more
importantly, the three things that shape breaks if nobody looks.

* **The aggregate survives.** ``SUM(delta)`` over the erased account's history is unchanged,
  because a receipt that erases itself on request cannot answer the billing question it
  exists for. Only the identity comes off.
* **The allowance cannot be re-farmed.** ``grant:period:{id}:{index}`` keeps the id it was
  built from, so a ``/forget`` followed by a fresh order does NOT mint a second allowance
  for a window already paid for. Without that, ``/forget`` would be "reset my free songs",
  repeatable, forever — a strictly better exploit than any this whole layer was built to
  stop, shipped by the feature meant to protect people.
* **The two NULL-blind readers stay closed.** ``verify_balances`` and the hourly stale-debit
  sweep both group and select on ``telegram_user_id``, and both would have met a ``NULL``
  for the first time in production, months after this merged, on a customer's request.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import (
    BotBlockSource,
    BroadcastKind,
    BroadcastRecipientState,
    BroadcastState,
    Language,
    OrderState,
    is_ok,
)
from bayram.db.churn import SqlBotBlocks
from bayram.db.credit_erasure import forget_account
from bayram.db.credit_sql import stale_debits, verify_balances
from bayram.db.credits import SqlCreditLedger
from bayram.db.enums import IntentProduct, PaymentIntentState, TopupKind
from bayram.db.models import (
    BroadcastRecipientRow,
    BroadcastRow,
    CreditAccountRow,
    CreditLedgerRow,
)
from bayram.db.models.bot_membership_event import BotMembershipEventRow
from bayram.db.models.payment_intent import PaymentIntentRow
from bayram.db.models.user import UserRow
from bayram.db.topup_sql import insert_topup, topup_by_key
from bayram.entitlements import EntitlementPolicy, SettlementOutcome
from tests.test_db.conftest import MovableClock

#: Outside the 32-bit range, like every id in ``test_credits.py``: the erasure travels
#: through the account primary key and the ledger column, and a narrowed column on that path
#: would corrupt identity rather than fail loudly.
_USER: Final[int] = 8_912_345_678_901

#: A stand-in for the UUID5 the bot records on an intent when it builds a payment link. A
#: literal rather than a computed one: what is under test here is that erasure NULLS the
#: column, not how the id is derived.
_RENDER: Final[UUID] = UUID("8bd6c9f4-2f1a-5b7e-9c3d-1a2b3c4d5e6f")
_OTHER_USER: Final[int] = 7_112_345_678_902
_ACTOR: Final[str] = "pipeline"


def _ledger(sessions: async_sessionmaker[AsyncSession], clock: MovableClock) -> SqlCreditLedger:
    return SqlCreditLedger(sessions, clock=clock, policy=EntitlementPolicy())


async def _spend_one_song(
    ledger: SqlCreditLedger, telegram_user_id: int, *, order_id: UUID
) -> None:
    """A whole completed order: the allowance is minted, a credit is taken, the kit lands."""
    charged = await ledger.charge(
        telegram_user_id=telegram_user_id, order_id=order_id, actor=_ACTOR
    )
    assert is_ok(charged), charged
    settled = await ledger.settle(
        telegram_user_id=telegram_user_id,
        order_id=order_id,
        outcome=SettlementOutcome.DELIVERED,
        actor=_ACTOR,
    )
    assert is_ok(settled), settled


async def _totals(sessions: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    """``(rows, SUM(delta))`` over the whole ledger, whoever the rows belong to."""
    async with sessions() as session:
        rows = await session.scalar(sa.select(sa.func.count()).select_from(CreditLedgerRow))
        total = await session.scalar(
            sa.select(sa.func.coalesce(sa.func.sum(CreditLedgerRow.delta), 0))
        )
        return int(rows or 0), int(total or 0)


async def _owners(sessions: async_sessionmaker[AsyncSession]) -> list[int | None]:
    async with sessions() as session:
        return list(
            (
                await session.execute(
                    sa.select(CreditLedgerRow.telegram_user_id).order_by(
                        CreditLedgerRow.idempotency_key
                    )
                )
            ).scalars()
        )


async def _account_exists(
    sessions: async_sessionmaker[AsyncSession], telegram_user_id: int
) -> bool:
    async with sessions() as session:
        return (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(CreditAccountRow)
                .where(CreditAccountRow.telegram_user_id == telegram_user_id)
            )
        ) == 1


def test_the_ledger_owner_column_is_nullable_because_erasure_needs_somewhere_to_go() -> None:
    """A ``NOT NULL`` here reads as good hygiene and would silently break ``/forget``.

    Every writer supplies an id, so nothing in the ordinary suite would notice the column
    being tightened — the first symptom would be an ``IntegrityError`` on a real customer's
    erasure request, which is the one moment the product cannot afford one.
    """
    # Arrange / Act / Assert
    assert CreditLedgerRow.__table__.c.telegram_user_id.nullable is True


# ---------------------------------------------------------------------------
# The erasure itself
# ---------------------------------------------------------------------------
async def test_the_balance_row_is_removed_while_the_audit_aggregate_survives(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The whole asymmetry in one assertion: a balance is not an audit fact, a receipt is."""
    # Arrange — one account that was granted three and spent one
    ledger = _ledger(sessions, clock)
    await _spend_one_song(ledger, _USER, order_id=uuid4())
    rows_before, total_before = await _totals(sessions)
    assert rows_before == 3, "grant, debit, consume"

    # Act
    async with sessions.begin() as session:
        erased = await forget_account(session, telegram_user_id=_USER)

    # Assert — the spendable balance is gone, every movement that explains it is not
    assert erased.accounts_deleted == 1
    assert erased.entries_anonymised == 3
    assert not await _account_exists(sessions, _USER)
    assert await _totals(sessions) == (rows_before, total_before)
    assert await _owners(sessions) == [None, None, None]


async def test_the_erasure_touches_nobody_else(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A ``WHERE`` that lost its predicate would empty the ledger for every customer."""
    # Arrange
    ledger = _ledger(sessions, clock)
    await _spend_one_song(ledger, _USER, order_id=uuid4())
    await _spend_one_song(ledger, _OTHER_USER, order_id=uuid4())

    # Act
    async with sessions.begin() as session:
        await forget_account(session, telegram_user_id=_USER)

    # Assert
    assert await _account_exists(sessions, _OTHER_USER)
    owners = await _owners(sessions)
    assert len(owners) == 6, "both histories are still three rows each"
    assert owners.count(None) == 3
    assert owners.count(_OTHER_USER) == 3


async def test_erasing_twice_is_a_second_successful_erasure_and_not_a_failure(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """``/forget`` is a command a person may send twice; the second must not be an error."""
    # Arrange
    ledger = _ledger(sessions, clock)
    await _spend_one_song(ledger, _USER, order_id=uuid4())
    async with sessions.begin() as session:
        await forget_account(session, telegram_user_id=_USER)

    # Act
    async with sessions.begin() as session:
        again = await forget_account(session, telegram_user_id=_USER)

    # Assert
    assert (again.accounts_deleted, again.entries_anonymised) == (0, 0)


async def test_forgetting_an_account_that_never_ordered_anything_erases_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Most people who send ``/forget`` never confirmed an order. That is an ordinary run."""
    # Arrange / Act
    async with sessions.begin() as session:
        erased = await forget_account(session, telegram_user_id=_USER)

    # Assert
    assert (erased.accounts_deleted, erased.entries_anonymised) == (0, 0)


async def test_the_store_facade_erases_in_one_transaction_and_never_raises(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The seam the bot holds. ``Result`` in, ``Result`` out — a gate never wraps a ``try``."""
    # Arrange
    ledger = _ledger(sessions, clock)
    await _spend_one_song(ledger, _USER, order_id=uuid4())

    # Act
    erased = await ledger.forget(_USER)

    # Assert
    assert is_ok(erased), erased
    assert not await _account_exists(sessions, _USER)


# ---------------------------------------------------------------------------
# The exploit the erasure must not open
# ---------------------------------------------------------------------------
async def test_forgetting_does_not_re_open_an_allowance_that_was_already_minted(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The reason ``idempotency_key`` keeps the id ``telegram_user_id`` just lost.

    ``_mint_due_allowance`` decides from ``credit_accounts.allowance_period_index``, and the
    erasure has just deleted the row that holds it — so the ONLY thing standing between
    ``/forget`` and an unlimited supply of free songs is the unique index on
    ``grant:period:{id}:{index}``. Anonymising that string would make this test go green on a
    fresh allowance, which is why it asserts the balance and not merely the absence of an
    error.
    """
    # Arrange — three granted, one spent, then erased
    ledger = _ledger(sessions, clock)
    await _spend_one_song(ledger, _USER, order_id=uuid4())
    async with sessions.begin() as session:
        await forget_account(session, telegram_user_id=_USER)

    # Act — the same account orders again inside the same 30-day window
    charged = await ledger.charge(telegram_user_id=_USER, order_id=uuid4(), actor=_ACTOR)

    # Assert — the account re-opened at zero and the charge was refused, not re-granted
    assert not is_ok(charged), "an erased account must not be handed a second allowance"
    grants = [owner for owner in await _owners(sessions) if owner is not None]
    assert grants == [], "the re-authorisation minted a new row for an erased account"


async def test_the_balance_shown_after_forgetting_is_the_one_the_charge_will_honour(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The read and the mint have to agree, and for a while they did not.

    ``read_balance`` decided an allowance was "due" from ``credit_accounts`` —
    ``allowance_period_index`` — which the test above deletes on purpose, while the mint
    defers to the grant's idempotency key, which the erasure deliberately keeps. So after
    ``/forget`` every read-only surface (``/balance``, the Confirm-screen note, the bot's
    gate) promised three songs and the WORKER then refused the render at AUTHORIZING, after
    the progress bar, for the rest of the 30-day window — an ``InsufficientCreditsError``
    whose own context said ``balance: 3``. The projection now asks the same authority the
    mint does.
    """
    # Arrange
    ledger = _ledger(sessions, clock)
    await _spend_one_song(ledger, _USER, order_id=uuid4())
    async with sessions.begin() as session:
        await forget_account(session, telegram_user_id=_USER)

    # Act
    shown = await ledger.balance_for(_USER)
    charged = await ledger.charge(telegram_user_id=_USER, order_id=uuid4(), actor=_ACTOR)

    # Assert — the number a customer is shown is the number the render gate will honour.
    assert is_ok(shown), shown
    assert shown.value.credits == 0
    assert not is_ok(charged)


async def test_a_render_that_fails_after_an_erasure_settles_quietly_instead_of_raising(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """``/forget`` mid-render, then a terminal failure. There is nobody left to refund.

    ``refund`` used to write the REFUND row and then call ``add_credits``, whose rowcount-0
    guard raised ``StorageError`` — rolling the whole settlement back, so the refund row was
    never written either, logging an ERROR with a traceback on every attempt, and leaving the
    debit open forever, because ``stale_debits`` skips erased debits by design. The customer
    had already been told "you have not lost anything" by a sentence that could not come
    true. Nothing is owed here: the balance that credit belonged to was deleted at the
    customer's own request, so the honest answer is ``Ok(False)``.
    """
    # Arrange — charged, then erased while the render was still running.
    ledger = _ledger(sessions, clock)
    order_id = uuid4()
    charged = await ledger.charge(telegram_user_id=_USER, order_id=order_id, actor=_ACTOR)
    assert is_ok(charged), charged
    erased = await ledger.forget(_USER)
    assert is_ok(erased), erased

    # Act
    settled = await ledger.settle(
        telegram_user_id=_USER,
        order_id=order_id,
        outcome=SettlementOutcome.FAILED,
        actor=_ACTOR,
    )

    # Assert
    assert is_ok(settled), settled
    assert settled.value is False
    assert not await _account_exists(sessions, _USER), "the erasure was not undone"


# ---------------------------------------------------------------------------
# The two readers that had never seen a NULL owner
# ---------------------------------------------------------------------------
async def test_an_erased_account_is_not_reported_to_an_operator_as_balance_drift(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Ledger movement with no account row is exactly the shape ``/forget`` leaves behind.

    ``_ledger_only_drifts`` was written to catch that shape as a bug. Left alone it would
    report every erasure as drift — and would raise doing it, because ``BalanceDrift``
    requires an ``int``.
    """
    # Arrange
    ledger = _ledger(sessions, clock)
    await _spend_one_song(ledger, _USER, order_id=uuid4())

    # Act
    async with sessions.begin() as session:
        await forget_account(session, telegram_user_id=_USER)

    # Assert
    async with sessions() as session:
        assert await verify_balances(session) == ()


async def test_the_stale_debit_sweep_leaves_an_erased_debit_alone(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """An open debit that ``/forget`` caught mid-render has no owner to refund.

    Settling it would write a FRESH row carrying the very id the erasure removed, and
    building the sweep's ``StaleDebit`` for it would raise inside the hourly purge
    transaction and take the whole retention run down with it. It is skipped, and skipping
    costs nothing: ``count_in_flight`` filters on the id too, so it holds nobody's slot.
    """
    # Arrange — a debit is open, then the customer asks to be forgotten
    ledger = _ledger(sessions, clock)
    charged = await ledger.charge(telegram_user_id=_USER, order_id=uuid4(), actor=_ACTOR)
    assert is_ok(charged), charged
    async with sessions.begin() as session:
        await forget_account(session, telegram_user_id=_USER)

    # Act — the sweep runs long after any grace could have expired
    async with sessions() as session:
        found = await stale_debits(session, cutoff=clock.advance(days=365), limit=100)

    # Assert
    assert found == ()


async def test_a_live_debit_is_still_swept_after_an_unrelated_erasure(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The other half: the NULL filter must not be a filter that catches everything."""
    # Arrange
    ledger = _ledger(sessions, clock)
    assert is_ok(await ledger.charge(telegram_user_id=_USER, order_id=uuid4(), actor=_ACTOR))
    order = uuid4()
    assert is_ok(await ledger.charge(telegram_user_id=_OTHER_USER, order_id=order, actor=_ACTOR))
    async with sessions.begin() as session:
        await forget_account(session, telegram_user_id=_USER)

    # Act
    async with sessions() as session:
        found = await stale_debits(session, cutoff=clock.advance(days=365), limit=100)

    # Assert
    assert [(debit.telegram_user_id, debit.order_id) for debit in found] == [(_OTHER_USER, order)]
    assert found[0].order_state in (None, OrderState.FAILED, OrderState.CANCELLED)


# ---------------------------------------------------------------------------
# The top-up receipt: a fourth table, and a fourth counter
# ---------------------------------------------------------------------------
async def test_forget_anonymises_the_topup_receipt_and_keeps_every_other_column(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A sales receipt that survived ``/forget`` with a name on it is the whole failure."""
    # Arrange — one recorded sale, exactly as `_fulfil_single` writes it.
    async with sessions.begin() as session:
        await insert_topup(
            session,
            telegram_user_id=_USER,
            product=TopupKind.SINGLE,
            credits_granted=1,
            amount_minor=700_000,
            currency="UZS",
            provider="stub",
            reference="stub-c0ffee",
            idempotency_key="topup:seed:session:0",
            now=clock.now,
        )

    # Act
    async with sessions.begin() as session:
        erased = await forget_account(session, telegram_user_id=_USER)

    # Assert — the identity comes off and the money stays. Deleting the row would make
    # /forget mean "refund me" and would destroy the answer to a billing dispute; rewriting
    # the key would let a second purchase under it record a second sale.
    assert erased.topups_anonymised == 1
    async with sessions() as session:
        row = await topup_by_key(session, "topup:seed:session:0")
    assert row is not None
    assert row.telegram_user_id is None
    assert (row.amount_minor, row.currency) == (700_000, "UZS")
    assert (row.provider, row.reference) == ("stub", "stub-c0ffee")
    assert row.credits_granted == 1
    assert row.created_at == clock.now


async def test_forget_reports_four_zeroes_for_an_account_that_bought_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The fourth counter is reported on its own, not summed into the plan one.

    A plan dispute and a single-song dispute are different conversations with different
    amounts, so an operator reading the log line needs to know WHICH receipt survived.
    """
    # Arrange / Act — a second erasure of an account that never bought anything at all.
    async with sessions.begin() as session:
        await forget_account(session, telegram_user_id=_USER)
    async with sessions.begin() as session:
        again = await forget_account(session, telegram_user_id=_USER)

    # Assert
    assert (
        again.accounts_deleted,
        again.entries_anonymised,
        again.plans_anonymised,
        again.topups_anonymised,
        again.intents_anonymised,
    ) == (0, 0, 0, 0, 0)


async def test_forget_anonymises_the_payment_intent_and_keeps_it_answerable(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """A deleted intent would make us tell the payment rail one of its payments never existed.

    The rail keeps its own copy permanently and can ask us about any transaction it created,
    over an arbitrary period, through its statement call. So the identity comes off and the
    account object stays renderable: ``public_ref``, every money column, the merchant
    account, the settlement note and all four clocks survive.
    """
    # Arrange — one settled intent, exactly as the gateway leaves it after a Perform.
    async with sessions.begin() as session:
        session.add(
            PaymentIntentRow(
                public_ref="c0ffee11c0ffee22c0ffee33",
                idempotency_key="topup:seed:session:0",
                telegram_user_id=_USER,
                product=IntentProduct.SINGLE,
                amount_minor=700_000,
                currency="UZS",
                provider="payme",
                merchant_id="587f72c72cac0d162c722ae2",
                is_sandbox=False,
                language="uz_latn",
                state=PaymentIntentState.PAID,
                valid_until=clock.now + timedelta(hours=12),
                settled_at=clock.now,
                settle_note="payme",
                resume_order_id=_RENDER,
                resumed_at=clock.now,
            )
        )

    # Act
    async with sessions.begin() as session:
        erased = await forget_account(session, telegram_user_id=_USER)

    # Assert — the person is gone and the payment is not.
    assert erased.intents_anonymised == 1
    async with sessions() as session:
        row = (await session.execute(sa.select(PaymentIntentRow))).scalar_one()
    assert row.telegram_user_id is None
    assert row.public_ref == "c0ffee11c0ffee22c0ffee33"
    assert (row.amount_minor, row.currency) == (700_000, "UZS")
    assert (row.provider, row.merchant_id) == ("payme", "587f72c72cac0d162c722ae2")
    assert row.state is PaymentIntentState.PAID
    assert (row.settled_at, row.settle_note) == (clock.now, "payme")
    assert row.idempotency_key == "topup:seed:session:0"
    # The one non-identity column that DOES come off. It is a UUID5 over the customer's own
    # answers — a name, a note, a lyric — so although it is irreversible it is the only value
    # on this row that could re-link an anonymised payment back to a draft. The rail has never
    # seen it and will never quote it back, so GetStatement loses nothing.
    assert row.resume_order_id is None
    # ``resumed_at`` STAYS: it is a clock like the other four, and says only that a decision
    # was taken.
    assert row.resumed_at == clock.now


async def test_forget_leaves_another_customers_payment_intent_alone(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """The anonymising UPDATE is keyed on one account, and this is what proves it."""
    # Arrange
    async with sessions.begin() as session:
        for owner, ref in (
            (_USER, "aaaa1111aaaa1111aaaa1111"),
            (_OTHER_USER, "bbbb2222bbbb2222bbbb2222"),
        ):
            session.add(
                PaymentIntentRow(
                    public_ref=ref,
                    idempotency_key=f"topup:{owner}:single:0",
                    telegram_user_id=owner,
                    product=IntentProduct.SINGLE,
                    amount_minor=700_000,
                    currency="UZS",
                    provider="payme",
                    merchant_id="587f72c72cac0d162c722ae2",
                    is_sandbox=True,
                    language="ru",
                    state=PaymentIntentState.PENDING,
                    valid_until=clock.now + timedelta(hours=12),
                )
            )

    # Act
    async with sessions.begin() as session:
        erased = await forget_account(session, telegram_user_id=_USER)

    # Assert
    assert erased.intents_anonymised == 1
    async with sessions() as session:
        survivors = (
            (
                await session.execute(
                    sa.select(PaymentIntentRow.telegram_user_id).order_by(
                        PaymentIntentRow.public_ref
                    )
                )
            )
            .scalars()
            .all()
        )
    assert list(survivors) == [None, _OTHER_USER]


async def test_forget_anonymises_the_churn_history_without_shrinking_it(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """THE PROPERTY THE EVENTS TABLE EXISTS FOR, asserted across an erasure.

    ``bot_membership_events`` is the fifth table this function reaches, and the only one
    that holds no money. Deleting its rows on request would make the daily block counts
    shrink retroactively by the number of people who asked to be forgotten — last March's
    churn would stop being last March's churn, which is precisely the defect an append-only
    passage log is for. So the id comes off and everything else is byte-identical.
    """
    # Arrange — one departure and one win-back.
    store = SqlBotBlocks(sessions)
    assert is_ok(
        await store.record_bot_blocked(_USER, at=clock.now, source=BotBlockSource.MEMBERSHIP_UPDATE)
    )
    assert is_ok(
        await store.record_bot_unblocked(
            _USER, at=clock.now, source=BotBlockSource.DELIVERY_REFUSAL
        )
    )

    async def rows() -> list[BotMembershipEventRow]:
        async with sessions() as session:
            found = await session.scalars(
                sa.select(BotMembershipEventRow).order_by(BotMembershipEventRow.event)
            )
            return list(found)

    before = [(row.event, row.source, row.at) for row in await rows()]
    assert len(before) == 2

    # Act
    async with sessions.begin() as session:
        erasure = await forget_account(session, telegram_user_id=_USER)

    # Assert — the count is reported, the rows are all still there, only the id is gone.
    assert erasure.membership_events_anonymised == 2
    after = await rows()
    assert len(after) == 2
    assert [(row.event, row.source, row.at) for row in after] == before
    assert all(row.telegram_user_id is None for row in after)


async def test_forget_leaves_the_churn_gauge_alone(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """``users.blocked_bot_at`` is NOT cleared, on the same footing as ``is_blocked``.

    The ``users`` row exists precisely so a block can outlive an erasure. A forgotten
    customer who still has the bot blocked is still unreachable, and clearing the column
    would make the gauge count them as reachable — a number that is wrong in the one
    direction an operator would act on.
    """
    # Arrange
    store = SqlBotBlocks(sessions)
    assert is_ok(
        await store.record_bot_blocked(_USER, at=clock.now, source=BotBlockSource.MEMBERSHIP_UPDATE)
    )

    # Act
    async with sessions.begin() as session:
        await forget_account(session, telegram_user_id=_USER)

    # Assert
    async with sessions() as session:
        blocked_at = await session.scalar(
            sa.select(UserRow.blocked_bot_at).where(UserRow.telegram_user_id == _USER)
        )
    assert blocked_at == clock.now


# ---------------------------------------------------------------------------
# ``broadcast_recipients`` — the delivery ledger, anonymised and kept
# ---------------------------------------------------------------------------
def _campaign(clock: MovableClock) -> BroadcastRow:
    return BroadcastRow(
        # The id is minted here rather than left to the column default: the helper's callers
        # read ``campaign.id`` to build the child rows in the same ``session.add`` batch, and
        # the ORM default is not applied until the flush that INSERTs them.
        id=uuid4(),
        title="September announcement",
        kind=BroadcastKind.SERVICE,
        state=BroadcastState.COMPLETED,
        segment={"v": 1, "match": "all", "rules": []},
        segment_hash="0" * 64,
        audience_size=2,
        audience_evaluated_at=clock.now,
        recipient_count=2,
        sent_count=2,
    )


def _delivery(broadcast_id: UUID, telegram_user_id: int, *, at: datetime) -> BroadcastRecipientRow:
    return BroadcastRecipientRow(
        broadcast_id=broadcast_id,
        telegram_user_id=telegram_user_id,
        language=Language.RU,
        state=BroadcastRecipientState.SENT,
        settled_at=at,
    )


async def test_forget_anonymises_the_delivery_rows_and_keeps_the_campaign_arithmetic(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """THE PROPERTY A COMPLETED CAMPAIGN'S COUNTERS DEPEND ON, asserted across an erasure.

    ``broadcast_recipients`` is the seventh table this function reaches and the second that
    holds no money. Deleting its rows on request would make a send that has already gone out
    shrink retroactively by the number of people who have since asked to be forgotten — a
    number an operator has already read — so the id comes off and everything else is
    byte-identical. Only the erased account's rows are touched.
    """
    # Arrange — two accounts on one campaign.
    campaign = _campaign(clock)
    async with sessions.begin() as session:
        session.add(campaign)
        session.add(_delivery(campaign.id, _USER, at=clock.now))
        session.add(_delivery(campaign.id, _OTHER_USER, at=clock.now))

    async def rows() -> list[BroadcastRecipientRow]:
        async with sessions() as session:
            found = await session.scalars(
                sa.select(BroadcastRecipientRow).order_by(BroadcastRecipientRow.created_at)
            )
            return list(found)

    before = {(row.state, row.settled_at, row.attempts) for row in await rows()}
    assert len(before) == 1

    # Act
    async with sessions.begin() as session:
        erasure = await forget_account(session, telegram_user_id=_USER)

    # Assert — the count is reported, both rows are still there, only one id is gone.
    assert erasure.recipients_anonymised == 1
    after = await rows()
    assert len(after) == 2
    assert {(row.state, row.settled_at, row.attempts) for row in after} == before
    assert [row.telegram_user_id for row in after] == [None, _OTHER_USER]
    async with sessions() as session:
        campaign_after = await session.get(BroadcastRow, campaign.id)
    assert campaign_after is not None
    assert (campaign_after.recipient_count, campaign_after.sent_count) == (2, 2)


async def test_a_second_forget_touches_no_delivery_row(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """Idempotent by construction: an anonymised row no longer matches the predicate."""
    # Arrange
    campaign = _campaign(clock)
    async with sessions.begin() as session:
        session.add(campaign)
        session.add(_delivery(campaign.id, _USER, at=clock.now))
    async with sessions.begin() as session:
        assert (await forget_account(session, telegram_user_id=_USER)).recipients_anonymised == 1

    # Act
    async with sessions.begin() as session:
        erasure = await forget_account(session, telegram_user_id=_USER)

    # Assert
    assert erasure.recipients_anonymised == 0


async def test_an_anonymised_delivery_row_does_not_block_a_later_expansion(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    """``UNIQUE (broadcast_id, telegram_user_id)`` tolerates any number of NULLs.

    The constraint is the campaign's idempotency authority, so the anonymising ``UPDATE``
    has to be able to leave several NULLs behind on one campaign without either raising or
    stopping a later account from being materialised onto it. That is exactly what a
    nullable column in a unique index buys, and it is asserted rather than assumed.
    """
    # Arrange — two accounts erased off the same campaign.
    campaign = _campaign(clock)
    async with sessions.begin() as session:
        session.add(campaign)
        session.add(_delivery(campaign.id, _USER, at=clock.now))
        session.add(_delivery(campaign.id, _OTHER_USER, at=clock.now))
    for erased in (_USER, _OTHER_USER):
        async with sessions.begin() as session:
            await forget_account(session, telegram_user_id=erased)

    # Act — a third account joins the same campaign afterwards.
    async with sessions.begin() as session:
        session.add(_delivery(campaign.id, _USER + 1, at=clock.now))

    # Assert
    async with sessions() as session:
        remaining = await session.scalar(
            sa.select(sa.func.count()).select_from(BroadcastRecipientRow)
        )
    assert remaining == 3
