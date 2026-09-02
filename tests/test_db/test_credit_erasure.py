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

from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import OrderState, is_ok
from hbd.db.credit_erasure import forget_account
from hbd.db.credit_sql import stale_debits, verify_balances
from hbd.db.credits import SqlCreditLedger
from hbd.db.models import CreditAccountRow, CreditLedgerRow
from hbd.entitlements import EntitlementPolicy, SettlementOutcome
from tests.test_db.conftest import MovableClock

#: Outside the 32-bit range, like every id in ``test_credits.py``: the erasure travels
#: through the account primary key and the ledger column, and a narrowed column on that path
#: would corrupt identity rather than fail loudly.
_USER: Final[int] = 8_912_345_678_901
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
