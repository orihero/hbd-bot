"""Buying: what one paid button writes, and what a second tap of it must not write.

Every test here is about a WRITE the customer paid for, so every one of them asserts what
is in the tables afterwards rather than what the call returned. The four properties the
purchase layer lives or dies on:

* **A double tap is one purchase.** Both halves are idempotent on a key, and the two halves
  achieve it differently on purpose — the single song leans on ``credit_ledger``'s unique
  index, the plan on ``plan_purchases``'s own. Either could regress without the other.
* **One plan at a time, decided on ``plan_ends_at`` and NOT on ``songs_used``.** A customer
  who spent all twelve songs on day three still owns the plan until day thirty; selling them
  a second one would write a fresh end date over the one they already paid for.
* **An unpaid ``Purchase`` grants nothing.** The stub always reports paid, so nothing in the
  shipped configuration exercises this — which is exactly why it is pinned. A redirect rail
  (Payme) returns unpaid receipts as the normal first half of a payment, and granting on one
  would hand out a free song for every abandoned checkout.
* **``/forget`` anonymises a plan receipt instead of deleting it, and leaves ``songs_used``
  alone.** Deleting would make ``/forget`` mean "refund me"; resetting the counter would make
  it mean "give me my twelve songs back", repeatable for as long as the plan runs.

The schema's own refusals are asserted as real ``IntegrityError``s around real inserts,
following ``test_credit_schema.py``: a pre-flight ``SELECT`` that decided an insert would be
safe is a race with every other writer, and the CHECK is what makes the optimistic
``UPDATE … WHERE songs_used = :seen`` trustworthy even when a future writer forgets it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.checkout import Plan, Product, Purchase
from bayram.contracts import is_err, is_ok
from bayram.db.credit_erasure import forget_account
from bayram.db.enums import CreditReason, PlanKind
from bayram.db.models import CreditLedgerRow, PlanPurchaseRow
from bayram.db.purchases import CHECKOUT_ACTOR, SqlPurchaseLedger
from bayram.entitlements import EntitlementPolicy
from bayram.errors import ErrorCode
from tests.test_db.conftest import MovableClock
from tests.test_db.test_migrations import _config

#: Outside the 32-bit range, so a column that quietly became an ``Integer`` on either engine
#: fails here rather than in production.
_USER: Final[int] = 8_912_345_678_901
_SINGLE_MINOR: Final[int] = 700_000
_PLAN_MINOR: Final[int] = 4_900_000
_PLAN_SONGS: Final[int] = 12
_PLAN_DAYS: Final[int] = 30
_PLAN_PURCHASES_REVISION: Final[str] = "0015"

#: The allowance is switched off in every test here so that a balance assertion is about the
#: purchase and nothing else. That is also the shipped configuration — ``Settings`` defaults
#: ``free_allowance_credits`` to 0 because the free half of this product is the lyric.
_NO_ALLOWANCE: Final[EntitlementPolicy] = EntitlementPolicy(allowance_credits=0)


def _purchase(product: Product, *, is_paid: bool = True, reference: str = "stub-abc") -> Purchase:
    return Purchase(
        product=product,
        provider="stub",
        reference=reference,
        amount_minor=_SINGLE_MINOR if product is Product.SINGLE else _PLAN_MINOR,
        currency="UZS",
        is_paid=is_paid,
    )


def _purchases(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> SqlPurchaseLedger:
    return SqlPurchaseLedger(sessions, policy=_NO_ALLOWANCE, clock=clock)


async def _plan_rows(sessions: async_sessionmaker[AsyncSession]) -> list[PlanPurchaseRow]:
    async with sessions() as session:
        return list(
            (
                await session.execute(
                    sa.select(PlanPurchaseRow).order_by(PlanPurchaseRow.idempotency_key)
                )
            )
            .scalars()
            .all()
        )


async def _ledger_rows(sessions: async_sessionmaker[AsyncSession]) -> list[CreditLedgerRow]:
    async with sessions() as session:
        return list(
            (
                await session.execute(
                    sa.select(CreditLedgerRow).order_by(CreditLedgerRow.idempotency_key)
                )
            )
            .scalars()
            .all()
        )


async def _insert_plan_row(
    sessions: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    songs_included: int,
    songs_used: int,
    idempotency_key: str,
) -> None:
    """A plan written through the ORM, so a CHECK is the only thing that can refuse it."""
    async with sessions.begin() as session:
        session.add(
            PlanPurchaseRow(
                telegram_user_id=_USER,
                plan=PlanKind.STARTER,
                songs_included=songs_included,
                songs_used=songs_used,
                amount_minor=_PLAN_MINOR,
                currency="UZS",
                provider="stub",
                reference="stub-raw",
                idempotency_key=idempotency_key,
                plan_ends_at=now + timedelta(days=_PLAN_DAYS),
            )
        )


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------
def test_the_plan_purchases_revision_is_reachable_from_head() -> None:
    # Arrange — walk_revisions starts at head, so membership proves the chain resolves.
    script = ScriptDirectory.from_config(_config())

    # Act
    revisions = {revision.revision for revision in script.walk_revisions()}

    # Assert — a revision whose down_revision is missing makes the whole chain unusable.
    assert _PLAN_PURCHASES_REVISION in revisions


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------
async def test_a_second_start_plan_under_the_same_key_inserts_nothing_and_returns_the_plan(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — one key, two calls: a double tap, a stale message, a redelivered update.
    purchases = _purchases(sessions, clock)
    key = f"plan:starter:{_USER}:session:0"

    # Act
    first = await purchases.start_plan(
        telegram_user_id=_USER,
        purchase=_purchase(Product.STARTER),
        songs=_PLAN_SONGS,
        days=_PLAN_DAYS,
        idempotency_key=key,
    )
    second = await purchases.start_plan(
        telegram_user_id=_USER,
        purchase=_purchase(Product.STARTER),
        songs=_PLAN_SONGS,
        days=_PLAN_DAYS,
        idempotency_key=key,
    )

    # Assert
    assert is_ok(first), first
    assert is_ok(second), second
    assert second.value == first.value
    assert second.value.plan is Plan.STARTER
    assert second.value.songs_left == _PLAN_SONGS
    assert len(await _plan_rows(sessions)) == 1
    # A plan grants NOTHING up front. Twelve credits on the balance could not be expired.
    assert await _ledger_rows(sessions) == []


async def test_a_second_plan_bought_under_a_new_key_returns_the_running_one_and_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a deliberate second purchase, not a replay: a different key entirely.
    purchases = _purchases(sessions, clock)
    first = await purchases.start_plan(
        telegram_user_id=_USER,
        purchase=_purchase(Product.STARTER),
        songs=_PLAN_SONGS,
        days=_PLAN_DAYS,
        idempotency_key=f"plan:starter:{_USER}:session:0",
    )
    assert is_ok(first), first

    # Act
    second = await purchases.start_plan(
        telegram_user_id=_USER,
        purchase=_purchase(Product.STARTER, reference="stub-def"),
        songs=_PLAN_SONGS,
        days=_PLAN_DAYS,
        idempotency_key=f"plan:starter:{_USER}:session:1",
    )

    # Assert — one plan at a time. A second row would write a new end date over the one the
    # customer already paid for, and the older row would sit there minting nothing.
    assert is_ok(second), second
    assert second.value == first.value
    assert len(await _plan_rows(sessions)) == 1


async def test_a_spent_plan_still_blocks_a_second_plan_until_its_end_date_passes(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — twelve songs used on day three. The customer still OWNS the starter plan.
    purchases = _purchases(sessions, clock)
    await _insert_plan_row(
        sessions,
        now=clock.now,
        songs_included=_PLAN_SONGS,
        songs_used=_PLAN_SONGS,
        idempotency_key="plan:starter:seed",
    )

    # Act
    result = await purchases.start_plan(
        telegram_user_id=_USER,
        purchase=_purchase(Product.STARTER),
        songs=_PLAN_SONGS,
        days=_PLAN_DAYS,
        idempotency_key=f"plan:starter:{_USER}:session:0",
    )

    # Assert — `is_current` and not `is_live`: this customer is offered the single song, and
    # is told the plan brings nothing more until it ends.
    assert is_ok(result), result
    assert result.value.songs_left == 0
    assert result.value.is_current(clock.now)
    assert not result.value.is_live(clock.now)
    assert len(await _plan_rows(sessions)) == 1


async def test_plan_for_reports_the_running_plan_and_nothing_once_it_has_ended(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    purchases = _purchases(sessions, clock)
    started = await purchases.start_plan(
        telegram_user_id=_USER,
        purchase=_purchase(Product.STARTER),
        songs=_PLAN_SONGS,
        days=_PLAN_DAYS,
        idempotency_key=f"plan:starter:{_USER}:session:0",
    )
    assert is_ok(started), started

    # Act
    while_running = await purchases.plan_for(_USER)
    clock.advance(days=_PLAN_DAYS + 1)
    after_it_ends = await purchases.plan_for(_USER)

    # Assert — the row is still there; it is simply no longer THE running plan, which is the
    # whole of "use it or lose it" expressed as a read-time predicate.
    assert is_ok(while_running) and while_running.value == started.value
    assert is_ok(after_it_ends) and after_it_ends.value is None
    assert len(await _plan_rows(sessions)) == 1


# ---------------------------------------------------------------------------
# Single songs
# ---------------------------------------------------------------------------
async def test_a_bought_single_song_moves_the_balance_exactly_once_per_key(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    purchases = _purchases(sessions, clock)
    key = f"topup:{_USER}:session:0"

    # Act
    first = await purchases.fulfil_single(
        telegram_user_id=_USER, purchase=_purchase(Product.SINGLE), idempotency_key=key
    )
    second = await purchases.fulfil_single(
        telegram_user_id=_USER, purchase=_purchase(Product.SINGLE), idempotency_key=key
    )

    # Assert — the replay returns the UNCHANGED balance, which is the correct answer to a
    # double tap: nothing went wrong and the customer has what they paid for.
    assert is_ok(first) and first.value.credits == 1
    assert is_ok(second) and second.value.credits == 1
    rows = await _ledger_rows(sessions)
    assert [(row.reason, row.delta, row.actor) for row in rows] == [
        (CreditReason.TOPUP_PURCHASE, 1, CHECKOUT_ACTOR)
    ]


async def test_a_deliberate_second_single_song_under_a_new_key_adds_a_second_credit(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — buy-as-many-as-you-like is the product; only a REPLAY collapses.
    purchases = _purchases(sessions, clock)

    # Act
    balances = []
    for seq in range(2):
        result = await purchases.fulfil_single(
            telegram_user_id=_USER,
            purchase=_purchase(Product.SINGLE),
            idempotency_key=f"topup:{_USER}:session:{seq}",
        )
        assert is_ok(result), result
        balances.append(result.value.credits)

    # Assert — each key is its own purchase, so the second one really does add a song.
    assert balances == [1, 2]
    assert len(await _ledger_rows(sessions)) == 2


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------
async def test_an_unpaid_purchase_is_refused_and_writes_nothing_at_all(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the shape a redirect rail returns while a payment is merely STARTED.
    purchases = _purchases(sessions, clock)
    unpaid = _purchase(Product.SINGLE, is_paid=False)

    # Act
    single = await purchases.fulfil_single(
        telegram_user_id=_USER, purchase=unpaid, idempotency_key=f"topup:{_USER}:session:0"
    )
    plan = await purchases.start_plan(
        telegram_user_id=_USER,
        purchase=_purchase(Product.STARTER, is_paid=False),
        songs=_PLAN_SONGS,
        days=_PLAN_DAYS,
        idempotency_key=f"plan:starter:{_USER}:session:0",
    )

    # Assert — a free song for every abandoned checkout is what this refusal prevents.
    assert is_err(single) and single.error.code is ErrorCode.PAYMENT_FAILED
    assert is_err(plan) and plan.error.code is ErrorCode.PAYMENT_FAILED
    assert await _ledger_rows(sessions) == []
    assert await _plan_rows(sessions) == []


async def test_the_schema_refuses_a_plan_that_has_used_more_songs_than_it_holds(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange / Act / Assert — a real insert, not a pre-flight SELECT: the CHECK is what
    # makes `claim_plan_song`'s optimistic UPDATE trustworthy when a future writer forgets
    # the guard, and a thirteenth song has no other symptom.
    with pytest.raises(IntegrityError):
        await _insert_plan_row(
            sessions,
            now=clock.now,
            songs_included=_PLAN_SONGS,
            songs_used=_PLAN_SONGS + 1,
            idempotency_key="plan:starter:overspent",
        )


async def test_the_schema_refuses_a_plan_that_includes_no_songs(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange / Act / Assert — a paid-for nothing: it would be dead the instant it was
    # written, so the customer would be charged and immediately paywalled again.
    with pytest.raises(IntegrityError):
        await _insert_plan_row(
            sessions,
            now=clock.now,
            songs_included=0,
            songs_used=0,
            idempotency_key="plan:starter:empty",
        )


# ---------------------------------------------------------------------------
# Erasure
# ---------------------------------------------------------------------------
async def test_forget_anonymises_the_plan_receipt_and_leaves_its_counter_alone(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a plan four songs in.
    await _insert_plan_row(
        sessions,
        now=clock.now,
        songs_included=_PLAN_SONGS,
        songs_used=4,
        idempotency_key="plan:starter:seed",
    )

    # Act
    async with sessions.begin() as session:
        erased = await forget_account(session, telegram_user_id=_USER)

    # Assert — the receipt survives without a name on it. Deleting it would make /forget
    # mean "refund me"; resetting the counter would make it mean "give me my songs back",
    # repeatable for as long as the plan runs.
    assert erased.plans_anonymised == 1
    rows = await _plan_rows(sessions)
    assert len(rows) == 1
    assert rows[0].telegram_user_id is None
    assert rows[0].songs_used == 4
    assert rows[0].amount_minor == _PLAN_MINOR


async def test_forget_reports_three_zeroes_for_an_account_that_never_bought_anything(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # Arrange — most people who send /forget never confirmed an order.

    # Act
    async with sessions.begin() as session:
        erased = await forget_account(session, telegram_user_id=_USER)

    # Assert — an ordinary answer, not a failure.
    assert (erased.accounts_deleted, erased.entries_anonymised, erased.plans_anonymised) == (
        0,
        0,
        0,
    )
