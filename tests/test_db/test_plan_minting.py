"""Spending a plan: one song per charge, minted lazily, and never once clawed back.

The plan ledger's whole safety argument is that nothing is granted up front. Buying the
starter plan writes ONE row and no credits; ``bayram.db.credits.charge`` takes a single song
out of that row, inside its own transaction, at the moment the render is paid for. What that
buys is stated as tests rather than as prose:

* **Twelve charges succeed and the thirteenth mints nothing.** The counter is the
  entitlement, and the optimistic ``UPDATE … WHERE songs_used = :seen`` is what makes it one
  song per charge rather than one per read.
* **A charge after ``plan_ends_at`` mints nothing at all** — no sweep runs, no compensating
  DEBIT is written, and with ``is_balance_enforced`` the customer is simply refused. That IS
  use-it-or-lose-it: a read-time predicate on a date, which cannot be got wrong, rather than
  an expiry job guessing which credits on a fungible balance were plan money.
* **A refunded plan song leaves ``songs_used`` where it is.** The refund returns an ordinary
  non-expiring credit, so a customer whose render failed keeps the value on a clock that
  cannot run out. Decrementing the counter would be strictly worse for them.
* **A replay that returns ``ALREADY_PAID`` consumes nothing**, because the mint is placed
  after the net-position short-circuit. Placed before it, every ARQ retry of a delivered
  order would have eaten another song.

``verify_balances`` is asserted after every act, exactly as ``test_credits.py`` does it. The
lazy mint writes a GRANT and moves ``credit_accounts.balance`` in the same transaction, and
``balance == SUM(credit_ledger.delta)`` is the one invariant that would catch a future
refactor doing only one of those two things.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import is_err, is_ok
from bayram.db.credit_sql import read_balance, verify_balances
from bayram.db.credits import SqlCreditLedger
from bayram.db.enums import CreditEntryKind, CreditReason, PlanKind
from bayram.db.models import CreditLedgerRow, PlanPurchaseRow
from bayram.entitlements import ChargeOutcome, EntitlementPolicy, SettlementOutcome
from bayram.errors import ErrorCode
from tests.test_db.conftest import MovableClock

_USER: Final[int] = 8_912_345_678_901
_ACTOR: Final[str] = "pipeline"
_PLAN_SONGS: Final[int] = 12
_PLAN_DAYS: Final[int] = 30

#: No free allowance anywhere in this file, so every credit that appears came out of the
#: plan and an assertion about the balance is an assertion about the plan. It is also the
#: shipped configuration: ``Settings.free_allowance_credits`` is 0 because the free half of
#: this product is the lyric.
_POLICY: Final[EntitlementPolicy] = EntitlementPolicy(allowance_credits=0)


def _ledger(sessions: async_sessionmaker[AsyncSession], clock: MovableClock) -> SqlCreditLedger:
    return SqlCreditLedger(sessions, policy=_POLICY, clock=clock)


async def _seed_plan(
    sessions: async_sessionmaker[AsyncSession],
    clock: MovableClock,
    *,
    songs_included: int = _PLAN_SONGS,
    days: int = _PLAN_DAYS,
) -> UUID:
    """A live starter plan, written straight to the table. Returns its id."""
    plan_id = uuid4()
    async with sessions.begin() as session:
        session.add(
            PlanPurchaseRow(
                id=plan_id,
                telegram_user_id=_USER,
                plan=PlanKind.STARTER,
                songs_included=songs_included,
                songs_used=0,
                amount_minor=4_900_000,
                currency="UZS",
                provider="stub",
                reference="stub-seed",
                idempotency_key=f"plan:starter:{plan_id}",
                plan_ends_at=clock.now + timedelta(days=days),
            )
        )
    return plan_id


async def _assert_no_drift(sessions: async_sessionmaker[AsyncSession]) -> None:
    """The invariant, after every act rather than only at the end of the file."""
    async with sessions() as session:
        assert await verify_balances(session) == ()


async def _songs_used(sessions: async_sessionmaker[AsyncSession], plan_id: UUID) -> int:
    async with sessions() as session:
        used: int | None = await session.scalar(
            sa.select(PlanPurchaseRow.songs_used).where(PlanPurchaseRow.id == plan_id)
        )
        assert used is not None
        return used


async def _plan_grant_keys(sessions: async_sessionmaker[AsyncSession]) -> list[str]:
    async with sessions() as session:
        rows = (
            await session.execute(
                sa.select(CreditLedgerRow.idempotency_key)
                .where(CreditLedgerRow.reason == CreditReason.PLAN_SONG)
                .order_by(CreditLedgerRow.idempotency_key)
            )
        ).scalars()
        return list(rows)


async def test_twelve_consecutive_charges_each_mint_one_song_from_a_fresh_plan(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a zero balance and a plan holding twelve songs.
    ledger = _ledger(sessions, clock)
    plan_id = await _seed_plan(sessions, clock)

    # Act — twelve separate orders, each settled so the in-flight cap lets the next through.
    for _ in range(_PLAN_SONGS):
        order_id = uuid4()
        charged = await ledger.charge(telegram_user_id=_USER, order_id=order_id, actor=_ACTOR)
        assert is_ok(charged), charged
        assert charged.value[0] is ChargeOutcome.CHARGED
        settled = await ledger.settle(
            telegram_user_id=_USER,
            order_id=order_id,
            outcome=SettlementOutcome.DELIVERED,
            actor=_ACTOR,
        )
        assert is_ok(settled), settled

    # Assert — twelve grants under twelve distinct keys, each naming one song of one plan.
    keys = await _plan_grant_keys(sessions)
    assert len(keys) == _PLAN_SONGS
    assert len(set(keys)) == _PLAN_SONGS
    assert keys[0] == f"grant:plan:{plan_id}:0"
    assert await _songs_used(sessions, plan_id) == _PLAN_SONGS
    await _assert_no_drift(sessions)


async def test_the_thirteenth_charge_mints_nothing_and_is_refused(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a plan with exactly one song, already spent.
    ledger = _ledger(sessions, clock)
    plan_id = await _seed_plan(sessions, clock, songs_included=1)
    first = uuid4()
    assert is_ok(await ledger.charge(telegram_user_id=_USER, order_id=first, actor=_ACTOR))
    assert is_ok(
        await ledger.settle(
            telegram_user_id=_USER,
            order_id=first,
            outcome=SettlementOutcome.DELIVERED,
            actor=_ACTOR,
        )
    )

    # Act
    result = await ledger.charge(telegram_user_id=_USER, order_id=uuid4(), actor=_ACTOR)

    # Assert — a spent plan mints nothing, and the refusal leaves the counter alone.
    assert is_err(result)
    assert result.error.code is ErrorCode.CREDITS_EXHAUSTED
    assert len(await _plan_grant_keys(sessions)) == 1
    assert await _songs_used(sessions, plan_id) == 1
    await _assert_no_drift(sessions)


async def test_a_charge_after_the_plan_has_ended_mints_nothing_and_refuses_the_render(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — eleven songs still unminted, and the calendar past the end date.
    ledger = _ledger(sessions, clock)
    plan_id = await _seed_plan(sessions, clock)
    clock.advance(days=_PLAN_DAYS + 1)

    # Act
    result = await ledger.charge(telegram_user_id=_USER, order_id=uuid4(), actor=_ACTOR)

    # Assert — use-it-or-lose-it, as an absence of writes. No sweep ran, no compensating
    # DEBIT was written, and there was never a credit to take back.
    assert is_err(result)
    assert result.error.code is ErrorCode.CREDITS_EXHAUSTED
    assert await _plan_grant_keys(sessions) == []
    assert await _songs_used(sessions, plan_id) == 0
    await _assert_no_drift(sessions)


async def test_read_balance_projects_a_fresh_plan_onto_an_empty_account(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the exact state a customer is in one second after paying 49 000 soʻm: a plan
    # row, and a stored balance of zero.
    await _seed_plan(sessions, clock)

    # Act
    async with sessions() as session:
        balance = await read_balance(session, telegram_user_id=_USER, now=clock.now, policy=_POLICY)

    # Assert — without this projection the read-only Confirm gate would paywall them in the
    # same message that had just thanked them for paying.
    assert balance.credits == _PLAN_SONGS
    assert balance.plan_songs_left == _PLAN_SONGS
    assert balance.plan_ends_at == clock.now + timedelta(days=_PLAN_DAYS)


async def test_read_balance_reports_a_spent_plan_as_still_running_with_nothing_left(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — one song, spent. The plan is still THE running plan.
    ledger = _ledger(sessions, clock)
    await _seed_plan(sessions, clock, songs_included=1)
    order_id = uuid4()
    assert is_ok(await ledger.charge(telegram_user_id=_USER, order_id=order_id, actor=_ACTOR))
    assert is_ok(
        await ledger.settle(
            telegram_user_id=_USER,
            order_id=order_id,
            outcome=SettlementOutcome.DELIVERED,
            actor=_ACTOR,
        )
    )

    # Act
    async with sessions() as session:
        balance = await read_balance(session, telegram_user_id=_USER, now=clock.now, policy=_POLICY)

    # Assert — "no plan" and "a plan with nothing left" are different offers, and only the
    # end date tells them apart once the songs are gone.
    assert balance.plan_songs_left == 0
    assert balance.plan_ends_at == clock.now + timedelta(days=_PLAN_DAYS)
    await _assert_no_drift(sessions)


async def test_a_refunded_plan_song_leaves_the_counter_used_and_the_credit_spendable(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange
    ledger = _ledger(sessions, clock)
    plan_id = await _seed_plan(sessions, clock)
    order_id = uuid4()
    assert is_ok(await ledger.charge(telegram_user_id=_USER, order_id=order_id, actor=_ACTOR))

    # Act — the render failed terminally, so the debit comes back.
    refunded = await ledger.settle(
        telegram_user_id=_USER,
        order_id=order_id,
        outcome=SettlementOutcome.FAILED,
        actor=_ACTOR,
    )

    # Assert — the counter stays used and the customer keeps the value as an ORDINARY,
    # non-expiring credit, which is strictly better for them than a song back on a clock.
    assert is_ok(refunded), refunded
    assert await _songs_used(sessions, plan_id) == 1
    async with sessions() as session:
        balance = await read_balance(session, telegram_user_id=_USER, now=clock.now, policy=_POLICY)
    # One refunded credit on the balance, plus the eleven the plan has still to mint.
    assert balance.credits == 1 + (_PLAN_SONGS - 1)
    assert balance.plan_songs_left == _PLAN_SONGS - 1
    await _assert_no_drift(sessions)


async def test_a_replayed_charge_reports_already_paid_and_consumes_no_second_song(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — the shape every ARQ retry of a queued render has.
    ledger = _ledger(sessions, clock)
    plan_id = await _seed_plan(sessions, clock)
    order_id = uuid4()
    assert is_ok(await ledger.charge(telegram_user_id=_USER, order_id=order_id, actor=_ACTOR))

    # Act
    replay = await ledger.charge(telegram_user_id=_USER, order_id=order_id, actor=_ACTOR)

    # Assert — the mint sits AFTER the net-position short-circuit precisely so this is true.
    assert is_ok(replay), replay
    assert replay.value[0] is ChargeOutcome.ALREADY_PAID
    assert await _songs_used(sessions, plan_id) == 1
    assert len(await _plan_grant_keys(sessions)) == 1
    await _assert_no_drift(sessions)


async def test_the_plan_pays_before_a_bought_top_up_does(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock
) -> None:
    # Arrange — a paid top-up sitting on the balance and a live plan beside it.
    ledger = _ledger(sessions, clock)
    plan_id = await _seed_plan(sessions, clock)
    granted = await ledger.grant(
        telegram_user_id=_USER, credits=1, idempotency_key=f"topup:{_USER}:0", actor="checkout"
    )
    assert is_ok(granted), granted

    # Act
    charged = await ledger.charge(telegram_user_id=_USER, order_id=uuid4(), actor=_ACTOR)

    # Assert — the plan song is minted and spent, and the top-up is still there. A plan song
    # is the only kind that can be lost to the calendar, so spending the other one first
    # would be spending the customer's money while their plan quietly ran out.
    assert is_ok(charged), charged
    assert await _songs_used(sessions, plan_id) == 1
    async with sessions() as session:
        balance = await read_balance(session, telegram_user_id=_USER, now=clock.now, policy=_POLICY)
    assert balance.credits == 1 + (_PLAN_SONGS - 1)
    await _assert_no_drift(sessions)


@pytest.mark.parametrize("is_enforced", [True, False])
async def test_the_plan_mint_writes_a_grant_row_whether_or_not_the_balance_is_enforced(
    sessions: async_sessionmaker[AsyncSession], clock: MovableClock, is_enforced: bool
) -> None:
    # Arrange — the dark configuration must not silently stop drawing on a paid plan; a
    # customer who bought twelve songs is entitled to them however the flag is set.
    ledger = SqlCreditLedger(
        sessions,
        policy=EntitlementPolicy(allowance_credits=0, is_balance_enforced=is_enforced),
        clock=clock,
    )
    plan_id = await _seed_plan(sessions, clock)

    # Act
    charged = await ledger.charge(telegram_user_id=_USER, order_id=uuid4(), actor=_ACTOR)

    # Assert — and NO unenforced top-up, because the plan already covered the render.
    assert is_ok(charged), charged
    assert await _songs_used(sessions, plan_id) == 1
    async with sessions() as session:
        reasons = set(
            (
                await session.execute(
                    sa.select(CreditLedgerRow.reason).where(
                        CreditLedgerRow.kind == CreditEntryKind.GRANT
                    )
                )
            ).scalars()
        )
    assert reasons == {CreditReason.PLAN_SONG}
    await _assert_no_drift(sessions)
