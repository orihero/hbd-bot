"""The entitlement ledger: what it charges, what it refuses, and what it never mints.

Two properties are asserted over and over rather than once, because both are the kind of
thing a plausible-looking refactor breaks silently:

* **``credit_accounts.balance == SUM(credit_ledger.delta)`` after EVERY operation.** The
  authoritative balance column is a second representation of the ledger, bought so the
  debit can be one lock-free portable statement. :func:`_assert_no_drift` runs
  ``verify_balances`` after each act, so a write that moves one and not the other fails
  here instead of in a billing dispute months later.
* **A refusal writes NOTHING.** Not a partial debit, not an orphan account row, not a
  minted allowance. Every refusal is raised inside the transaction so the whole thing rolls
  back, and the tests assert the empty table rather than trusting the pattern.

The sharpest test in the file is
:func:`test_a_refunded_order_is_charged_again_and_not_rendered_for_free`. Every candidate
design for this layer keyed replay on "was this order ever debited", which is not the same
question as "is this order currently paid for": a refund followed by a re-authorisation
(an ARQ requeue, a sweep-then-redelivery) then rendered a song for nothing. The
net-position probe is the fix, and ``generation`` is what lets the second debit exist
alongside the first without colliding with its own idempotency key.

What this file CANNOT prove is the concurrent race, because ``conftest.py`` runs SQLite
in-memory through a ``StaticPool`` with a single shared connection — two sessions here are
never genuinely simultaneous. The conditional ``UPDATE … WHERE balance >= :cost`` is
asserted against real Postgres in ``test_postgres_integration.py`` under the
``integration`` marker, so in a plain ``make test`` that guarantee is argued rather than
asserted. The gap is deliberate and recorded, not overlooked.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import Language, is_err, is_ok
from hbd.db.credit_sql import upsert_statement, verify_balances
from hbd.db.credits import SqlCreditLedger
from hbd.db.enums import CreditEntryKind, CreditReason
from hbd.db.models import CreditAccountRow, CreditLedgerRow
from hbd.entitlements import (
    BalanceDrift,
    ChargeOutcome,
    CreditBalance,
    EntitlementPolicy,
    EntitlementStore,
    SettlementOutcome,
    TooManyOrdersInFlightError,
    period_index_for,
)
from hbd.errors import ConfigError, ErrorCode
from tests.test_db.conftest import MovableClock

# The constants and helpers this module shares with ``test_credit_refusals.py``. One copy,
# in ``credit_helpers.py``, because the invariant they assert has to be the same invariant
# in both files — see that module's docstring for why the split exists at all.
from tests.test_db.credit_helpers import (
    _ACTOR,
    _OTHER_USER,
    _PERIOD_DAYS,
    _USER,
    _assert_no_drift,
    _charge,
    _entries,
    _grant_key,
    _ledger,
    _of_kind,
    _settle,
    _stored_balance,
    _user_row,
)


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------
async def test_a_first_charge_opens_the_account_mints_the_allowance_and_debits_once(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — nobody has ever seen this Telegram id: no account row, no users row, and
    # (deliberately) no foreign key that would require either to exist first.
    ledger = _ledger(sessions, clock)
    order_id = uuid4()

    # Act
    outcome, balance = await _charge(ledger, order_id)

    # Assert
    assert outcome is ChargeOutcome.CHARGED
    assert balance == CreditBalance(
        telegram_user_id=_USER, credits=2, in_flight=1, is_blocked=False
    )
    assert await _stored_balance(sessions) == 2
    index = period_index_for(clock.now, period_days=_PERIOD_DAYS)
    assert await _entries(sessions) == [
        (CreditEntryKind.DEBIT, CreditReason.ORDER_RENDER, -1, 0, f"debit:{order_id}:0"),
        # The very first mint for an account is the welcome allowance; every later window is
        # a period allowance. Same key shape, different fact for an operator reading it.
        (CreditEntryKind.GRANT, CreditReason.SIGNUP_ALLOWANCE, 3, 0, _grant_key(index)),
    ]
    await _assert_no_drift(sessions)


async def test_the_allowance_is_minted_once_per_window_and_again_in_the_next_one(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a rolling allowance, not a lifetime grant: an account coming back a month
    # later must be able to render again, or the product's own "Make another" button walks
    # every customer into a permanent refusal. Each order is settled so the in-flight cap is
    # never what is being measured here.
    ledger = _ledger(sessions, clock)
    first_index = period_index_for(clock.now, period_days=_PERIOD_DAYS)
    for _ in range(2):
        order_id = uuid4()
        await _charge(ledger, order_id)
        await _settle(ledger, order_id, SettlementOutcome.DELIVERED)
    grants_in_first_window = _of_kind(await _entries(sessions), CreditEntryKind.GRANT)
    await _assert_no_drift(sessions)

    # Act
    clock.advance(days=_PERIOD_DAYS)
    _, balance = await _charge(ledger, uuid4())

    # Assert — two charges in one window minted once; the new window minted a fresh three.
    assert grants_in_first_window == [
        (CreditEntryKind.GRANT, CreditReason.SIGNUP_ALLOWANCE, 3, 0, _grant_key(first_index))
    ]
    assert _of_kind(await _entries(sessions), CreditEntryKind.GRANT) == [
        (CreditEntryKind.GRANT, CreditReason.SIGNUP_ALLOWANCE, 3, 0, _grant_key(first_index)),
        (
            CreditEntryKind.GRANT,
            CreditReason.PERIOD_ALLOWANCE,
            3,
            0,
            _grant_key(first_index + 1),
        ),
    ]
    # Three granted, two spent, three granted again, one spent.
    assert balance.credits == 3
    assert await _stored_balance(sessions) == 3
    await _assert_no_drift(sessions)


async def test_one_accounts_allowance_is_not_another_accounts(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the period index is shared by everyone, so the Telegram id has to be part of
    # the grant key or the second account of every window would silently get nothing.
    ledger = _ledger(sessions, clock)
    index = period_index_for(clock.now, period_days=_PERIOD_DAYS)

    # Act
    await _charge(ledger, uuid4())
    await _charge(ledger, uuid4(), telegram_user_id=_OTHER_USER)

    # Assert
    keys = {entry[4] for entry in _of_kind(await _entries(sessions), CreditEntryKind.GRANT)}
    assert keys == {_grant_key(index), _grant_key(index, telegram_user_id=_OTHER_USER)}
    assert await _stored_balance(sessions) == 2
    assert await _stored_balance(sessions, telegram_user_id=_OTHER_USER) == 2
    await _assert_no_drift(sessions)


# ---------------------------------------------------------------------------
# Idempotency and replay
# ---------------------------------------------------------------------------
async def test_charging_the_same_order_twice_moves_nothing_and_writes_no_row(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the gate runs at least twice per order (the Confirm tap, then the worker,
    # then once more on every ARQ retry), so this is the ordinary case, not an edge one.
    ledger = _ledger(sessions, clock)
    order_id = uuid4()
    await _charge(ledger, order_id)
    before = await _entries(sessions)

    # Act
    outcome, balance = await _charge(ledger, order_id)

    # Assert
    assert outcome is ChargeOutcome.ALREADY_PAID
    assert balance.credits == 2
    assert await _entries(sessions) == before
    assert await _stored_balance(sessions) == 2
    await _assert_no_drift(sessions)


async def test_a_refunded_order_is_charged_again_and_not_rendered_for_free(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — THE test this module exists for. Keying replay on "was this order ever
    # debited" rather than "is it currently paid for" makes the second charge a no-op and
    # renders the song for nothing, which is what every candidate design shipped.
    ledger = _ledger(sessions, clock)
    order_id = uuid4()
    await _charge(ledger, order_id)
    assert await _settle(ledger, order_id, SettlementOutcome.FAILED) is True
    assert await _stored_balance(sessions) == 3
    await _assert_no_drift(sessions)

    # Act
    outcome, balance = await _charge(ledger, order_id)

    # Assert — a real second debit, at the next generation, with an idempotency key of its
    # own so it cannot collide with the first attempt it is replacing.
    assert outcome is ChargeOutcome.CHARGED
    assert balance.credits == 2
    assert await _stored_balance(sessions) == 2
    assert _of_kind(await _entries(sessions), CreditEntryKind.DEBIT) == [
        (CreditEntryKind.DEBIT, CreditReason.ORDER_RENDER, -1, 0, f"debit:{order_id}:0"),
        (CreditEntryKind.DEBIT, CreditReason.ORDER_RENDER, -1, 1, f"debit:{order_id}:1"),
    ]
    assert _of_kind(await _entries(sessions), CreditEntryKind.REFUND) == [
        (CreditEntryKind.REFUND, CreditReason.ORDER_FAILED, 1, 0, f"refund:{order_id}:0")
    ]
    await _assert_no_drift(sessions)


async def test_a_second_generation_debit_still_counts_against_the_in_flight_cap(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the settlement probe matches (order_id, generation), not order_id alone. If
    # it matched the order only, the generation-0 refund would make the live generation-1
    # debit look settled and the account could stack a second render.
    ledger = _ledger(sessions, clock)
    order_id = uuid4()
    await _charge(ledger, order_id)
    await _settle(ledger, order_id, SettlementOutcome.FAILED)
    await _charge(ledger, order_id)

    # Act
    result = await ledger.charge(telegram_user_id=_USER, order_id=uuid4(), actor=_ACTOR)

    # Assert
    assert is_err(result)
    assert isinstance(result.error, TooManyOrdersInFlightError)
    await _assert_no_drift(sessions)


async def test_settling_the_same_order_twice_writes_one_row(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a redelivered job settles an order that is already settled.
    ledger = _ledger(sessions, clock)
    order_id = uuid4()
    await _charge(ledger, order_id)

    # Act
    first = await _settle(ledger, order_id, SettlementOutcome.DELIVERED)
    second = await _settle(ledger, order_id, SettlementOutcome.DELIVERED)

    # Assert — the first call wrote it; the second found the order already settled, which is
    # reported as "nothing to do" rather than as a failure.
    assert first is True
    assert second is False
    assert _of_kind(await _entries(sessions), CreditEntryKind.CONSUME) == [
        (CreditEntryKind.CONSUME, CreditReason.ORDER_DELIVERED, 0, 0, f"consume:{order_id}:0")
    ]
    await _assert_no_drift(sessions)


# ---------------------------------------------------------------------------
# Grants, blocks and touches
# ---------------------------------------------------------------------------
async def test_an_operator_grant_is_idempotent_on_its_own_key(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the CLI owns the key so an invocation retried after a timeout tops the
    # account up once rather than twice.
    ledger = _ledger(sessions, clock)
    key = f"grant:admin:{uuid4()}"

    # Act
    first = await ledger.grant(
        telegram_user_id=_USER, credits=5, idempotency_key=key, actor="admin:orihero"
    )
    second = await ledger.grant(
        telegram_user_id=_USER, credits=5, idempotency_key=key, actor="admin:orihero"
    )

    # Assert — 5 stored, plus the 3 the reader projects for the window not yet minted.
    assert is_ok(first) and first.value.credits == 8
    assert is_ok(second) and second.value.credits == 8
    assert await _stored_balance(sessions) == 5
    assert len(await _entries(sessions)) == 1
    await _assert_no_drift(sessions)


async def test_a_grant_of_nothing_is_refused_at_the_boundary(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the check constraint would reject a non-positive grant anyway, but an
    # operator deserves a message about their input rather than a constraint name.
    ledger = _ledger(sessions, clock)

    # Act
    result = await ledger.grant(
        telegram_user_id=_USER, credits=0, idempotency_key="grant:admin:zero", actor="admin:x"
    )

    # Assert
    assert is_err(result)
    assert result.error.error_code is ErrorCode.INVALID_INPUT
    assert await _entries(sessions) == []
    await _assert_no_drift(sessions)


async def test_an_over_long_operator_name_is_truncated_rather_than_failing_the_write(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — admin usernames are 64 characters wide and the actor column is 32. The actor
    # is diagnostic attribution, not a key, so a long name must not cost a customer their
    # grant; SQLite would store the over-length value and only Postgres would raise.
    ledger = _ledger(sessions, clock)

    # Act
    result = await ledger.grant(
        telegram_user_id=_USER,
        credits=1,
        idempotency_key="grant:admin:long",
        actor="admin:" + "n" * 60,
    )

    # Assert
    assert is_ok(result)
    async with sessions() as session:
        actor = await session.scalar(sa.select(CreditLedgerRow.actor))
    assert actor is not None
    assert len(actor) == 32
    await _assert_no_drift(sessions)


async def test_blocking_works_for_someone_who_never_confirmed_an_order(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — users rows are written only by repository._ensure_user when an order is
    # created, so the accounts most worth blocking have no row at all and a rowcount-checked
    # UPDATE would silently do nothing.
    ledger = _ledger(sessions, clock)

    # Act
    result = await ledger.set_blocked(_USER, is_blocked=True)

    # Assert
    assert is_ok(result)
    row = await _user_row(sessions)
    assert row is not None
    assert row.is_blocked is True
    assert row.ui_language is Language.UZ_LATN


async def test_unblocking_an_account_lets_it_charge_again(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a block is reversible, and the upsert has to update the existing row rather
    # than fail on its unique index the second time.
    ledger = _ledger(sessions, clock)
    await ledger.set_blocked(_USER, is_blocked=True)

    # Act
    result = await ledger.set_blocked(_USER, is_blocked=False)
    outcome, _ = await _charge(ledger, uuid4())

    # Assert
    assert is_ok(result)
    assert outcome is ChargeOutcome.CHARGED
    await _assert_no_drift(sessions)


async def test_a_touch_refreshes_the_language_and_the_clock_but_never_unblocks(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a touch arrives on every inbound update, so one that reset is_blocked would
    # unblock an abuser the moment they sent their next message.
    ledger = _ledger(sessions, clock)
    await ledger.set_blocked(_USER, is_blocked=True)
    first_seen = clock.now

    # Act
    clock.advance(days=1)
    result = await ledger.touch(_USER, ui_language=Language.RU)

    # Assert
    assert is_ok(result)
    row = await _user_row(sessions)
    assert row is not None
    assert row.ui_language is Language.RU
    assert row.last_seen_at > first_seen
    assert row.is_blocked is True


async def test_a_touch_creates_the_row_for_an_account_the_bot_has_never_recorded(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — this is the first writer in the system that gives a wizard-only visitor a
    # users row, which is what makes them blockable at all.
    ledger = _ledger(sessions, clock)

    # Act
    result = await ledger.touch(_USER, ui_language=Language.EN)

    # Assert
    assert is_ok(result)
    row = await _user_row(sessions)
    assert row is not None
    assert row.ui_language is Language.EN
    assert row.is_blocked is False


# ---------------------------------------------------------------------------
# Reads that must not write
# ---------------------------------------------------------------------------
async def test_reading_a_balance_projects_the_unminted_allowance_and_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the bot-side gate is read-only by design. Without the projection it would
    # refuse every brand-new customer with a balance of 0 that charge() tops up to three a
    # second later — i.e. it would refuse exactly the people the allowance exists for.
    ledger = _ledger(sessions, clock)

    # Act
    result = await ledger.balance_for(_USER)

    # Assert
    assert is_ok(result)
    assert result.value == CreditBalance(
        telegram_user_id=_USER, credits=3, in_flight=0, is_blocked=False
    )
    assert await _stored_balance(sessions) is None
    assert await _entries(sessions) == []
    await _assert_no_drift(sessions)


async def test_a_balance_read_can_exclude_the_order_it_is_about_to_submit(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the bot re-reads the gate for an order it may already have charged (the order
    # id is a UUID5 over the draft, so a second tap reuses it). Counting that order's own
    # debit would refuse the customer with their own render.
    ledger = _ledger(sessions, clock)
    order_id = uuid4()
    await _charge(ledger, order_id)

    # Act
    counted = await ledger.balance_for(_USER)
    excluded = await ledger.balance_for(_USER, exclude_order_id=order_id)

    # Assert
    assert is_ok(counted) and counted.value.in_flight == 1
    assert is_ok(excluded) and excluded.value.in_flight == 0
    await _assert_no_drift(sessions)


async def test_a_blocked_account_is_visible_in_the_balance_read(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the read-only gate refuses a blocked account before it ever reaches the
    # worker, so is_blocked travels with the balance rather than needing a second call.
    ledger = _ledger(sessions, clock)
    await ledger.set_blocked(_USER, is_blocked=True)

    # Act
    result = await ledger.balance_for(_USER)

    # Assert
    assert is_ok(result)
    assert result.value.is_blocked is True


async def test_a_spent_window_reads_as_empty_rather_than_re_projecting_the_allowance(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the projection must fire once per window and not once per read, or the gate
    # would show three credits forever to an account that has already spent them.
    ledger = _ledger(sessions, clock)
    order_id = uuid4()
    await _charge(ledger, order_id)
    await _settle(ledger, order_id, SettlementOutcome.DELIVERED)

    # Act
    result = await ledger.balance_for(_USER)

    # Assert
    assert is_ok(result)
    assert result.value.credits == 2
    await _assert_no_drift(sessions)


# ---------------------------------------------------------------------------
# Integrity and plumbing
# ---------------------------------------------------------------------------
async def test_verify_balances_reports_an_account_edited_behind_the_ledgers_back(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the two-representation trade-off is honest only if drift is detectable. An
    # operator's hand-written UPDATE is the one way it still happens.
    ledger = _ledger(sessions, clock)
    await _charge(ledger, uuid4())

    # Act
    async with sessions.begin() as session:
        await session.execute(
            sa.update(CreditAccountRow)
            .where(CreditAccountRow.telegram_user_id == _USER)
            .values(balance=99)
        )
    async with sessions() as session:
        drifts = await verify_balances(session)

    # Assert
    assert drifts == (BalanceDrift(telegram_user_id=_USER, balance=99, ledger_total=2),)


async def test_verify_balances_reports_ledger_movement_with_no_account_behind_it(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the mirror-image drift: entries exist, the account row does not, so every
    # reader would report a balance of zero for an account that is owed credits.
    async with sessions.begin() as session:
        session.add(
            CreditLedgerRow(
                telegram_user_id=_USER,
                kind=CreditEntryKind.GRANT,
                reason=CreditReason.ADMIN_GRANT,
                delta=4,
                idempotency_key="grant:admin:orphan",
                actor="admin:x",
            )
        )

    # Act
    async with sessions() as session:
        drifts = await verify_balances(session)

    # Assert
    assert drifts == (BalanceDrift(telegram_user_id=_USER, balance=0, ledger_total=4),)


def test_an_engine_with_no_upsert_dialect_is_refused_rather_than_silently_downgraded() -> None:
    # Arrange — a plain-INSERT fallback would turn every idempotency guarantee in the module
    # into a duplicate-key crash on the first replay, in production, on an engine nobody ever
    # tested. A mock engine is enough here: the statement is never executed.
    class _MysqlSession:
        """Just enough of an ``AsyncSession`` for the dialect dispatch to read."""

        def get_bind(self) -> Any:
            return sa.create_mock_engine("mysql://", lambda *_args, **_kwargs: None)

    # Act / Assert
    with pytest.raises(ConfigError) as caught:
        upsert_statement(
            cast("AsyncSession", _MysqlSession()),
            CreditAccountRow,
            {"telegram_user_id": _USER},
            index_elements=["telegram_user_id"],
            set_=None,
        )
    assert caught.value.context["dialect"] == "mysql"
    assert caught.value.context["table"] == "credit_accounts"


def test_the_sql_ledger_satisfies_the_entitlement_store_seam(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange / Act
    ledger = _ledger(sessions, clock)

    # Assert — member presence only; mypy --strict over tests is what checks the signatures.
    assert isinstance(ledger, EntitlementStore)
    assert ledger.policy.allowance_credits == 3


def test_the_store_constructs_with_no_clock_and_no_policy(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — the composition root builds it from the session factory alone, so the
    # defaults have to be usable rather than placeholders.
    ledger = SqlCreditLedger(sessions)

    # Act / Assert
    assert ledger.policy == EntitlementPolicy()
    assert ledger.policy.max_orders_in_flight == 1
