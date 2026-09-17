"""The SQL primitives the plan ledger is built out of — one statement per function.

The sibling of :mod:`bayram.db.credit_sql`, and written to the same rule: nothing here decides
anything, every function performs exactly one statement, takes its session first, takes
``now`` as a parameter and commits nothing. The policy that uses them lives in
:mod:`bayram.db.purchases` (buying a plan) and :mod:`bayram.db.credits` (spending one), so that
"when may a song be minted?" reads as a short sequence of named steps.

**The one idea this module exists to serve: plan songs are minted LAZILY.** Buying the
starter plan writes one row here and NOT twelve credits. A song leaves the plan one at a
time, inside the charge's own transaction, by :func:`claim_plan_song` — the same shape
``bayram.db.credits._mint_due_allowance`` already uses for the rolling allowance. The
alternative, granting all twelve up front, needs a sweep to burn what is left when the
thirty days run out; ``credit_accounts.balance`` is a single fungible scalar with no lot
structure and ``verify_balances`` asserts ``balance == SUM(credit_ledger.delta)`` after
every operation, so that sweep would have to write a compensating DEBIT while GUESSING
whether it was burning plan money or a top-up the customer paid cash for. Lazily,
use-it-or-lose-it is a read-time predicate on ``plan_ends_at`` and there is nothing to
compensate, ever.

**Why there are two "is there a plan?" reads and not one.** :func:`current_plan` ignores
``songs_used`` and :func:`live_plan` does not, and the difference is the entire top-up
story. A customer who spent all twelve songs on day three still OWNS the starter plan until
day thirty: :func:`current_plan` says so, which is what stops a second plan being sold over
the end date they already paid for, while :func:`live_plan` says there is nothing left to
mint, which is what puts the single-song button on the screen. One function answering both
questions would have to pick one of those two behaviours and get the other wrong.

These names are public to the ``bayram.db`` package and to nothing else, exactly like
``credit_sql``: a caller outside persistence has no business holding a session (Rule 15).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.db.credit_sql import insert_or_ignore, rowcount_of
from bayram.db.enums import PlanKind
from bayram.db.models.plan_purchase import PlanPurchaseRow

__all__ = [
    "current_plan",
    "live_plan",
    "claim_plan_song",
    "insert_plan",
    "plan_by_key",
    "anonymise_plans",
]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
async def current_plan(
    session: AsyncSession, *, telegram_user_id: int, now: datetime
) -> PlanPurchaseRow | None:
    """The plan this account is RUNNING, spent or not. ``None`` when none is.

    Deliberately says nothing about ``songs_used``: this is the question "does a plan already
    cover this customer?", and the answer for someone who used all twelve songs yesterday is
    still yes until the end date arrives. ``bayram.db.purchases.start_plan`` refuses to sell a
    second plan on the strength of exactly this read, so a customer cannot pay 49 000 soʻm to
    overwrite an end date they have already paid for.

    Ordered by ``plan_ends_at`` DESC and limited to one so that a history of plans — a
    renewal bought before the previous one lapsed, say — always resolves to the one that runs
    longest, which is the one the customer would say they are on.
    """
    return (
        await session.execute(
            sa.select(PlanPurchaseRow)
            .where(
                PlanPurchaseRow.telegram_user_id == telegram_user_id,
                PlanPurchaseRow.plan_ends_at > now,
            )
            .order_by(PlanPurchaseRow.plan_ends_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def live_plan(
    session: AsyncSession, *, telegram_user_id: int, now: datetime
) -> PlanPurchaseRow | None:
    """The plan that still has a song to mint. ``None`` when there is none.

    :func:`current_plan` plus ``songs_used < songs_included``. This is the read the mint and
    the balance projection both take, and the two MUST agree — a projection that counted a
    song the mint would decline to write is how the Confirm screen came to promise a render
    the worker then refused, which is the defect ``credit_sql.read_balance`` documents at
    length for the rolling allowance.
    """
    return (
        await session.execute(
            sa.select(PlanPurchaseRow)
            .where(
                PlanPurchaseRow.telegram_user_id == telegram_user_id,
                PlanPurchaseRow.plan_ends_at > now,
                PlanPurchaseRow.songs_used < PlanPurchaseRow.songs_included,
            )
            .order_by(PlanPurchaseRow.plan_ends_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def plan_by_key(session: AsyncSession, idempotency_key: str) -> PlanPurchaseRow | None:
    """The plan written under ``idempotency_key``. The read-back after an ignored insert.

    :func:`insert_plan` reports that it lost — it cannot report WHAT it lost to, because
    ``INSERT … ON CONFLICT DO NOTHING`` returns nothing at all. The winner's row is what the
    caller has to hand back to the customer, so a double tap is answered with the plan they
    actually have rather than with an error about a race they did not cause.
    """
    return (
        await session.execute(
            sa.select(PlanPurchaseRow).where(PlanPurchaseRow.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
async def claim_plan_song(session: AsyncSession, *, plan_id: UUID, songs_used: int) -> bool:
    """Take ONE song out of a plan. ``False`` means somebody else took it first.

    ``UPDATE … SET songs_used = songs_used + 1 WHERE id = :plan_id AND songs_used = :seen``
    with a rowcount check — the same optimistic shape, and for the same reason, as
    ``credit_sql.debit_balance``'s ``WHERE balance >= :cost``. Two concurrent charges read
    the same row a moment apart; under Postgres READ COMMITTED only one of them can see a
    rowcount of 1, so only one writes the GRANT that follows. A read-then-write, or a
    ``SELECT … FOR UPDATE`` (verified a silent no-op in SQLAlchemy's SQLite dialect), would
    be the very race this removes.

    The caller must treat ``False`` as "no song was minted", never as an error: losing the
    race is an ordinary outcome, and the loser's charge simply falls through to the balance
    it already had.

    ``updated_at`` is stamped by hand because ``TimestampMixin``'s ``onupdate`` fires on an
    ORM flush only and this is Core, and it is stamped from the DATABASE's clock rather than
    from an injected ``now``. That is the one place in this module a wall clock is not a
    parameter, and it is deliberate: this function takes no ``now`` because nothing it
    DECIDES depends on the time — the guard is ``songs_used``, and the calendar was already
    consulted by :func:`live_plan` before the caller got here. ``updated_at`` on this row is
    diagnostic ("when was this plan last drawn on?"), so a clock a test cannot move costs
    nothing, whereas threading one in would invite a reader to think the mint decision itself
    was time-dependent.
    """
    result = await session.execute(
        sa.update(PlanPurchaseRow)
        .where(PlanPurchaseRow.id == plan_id, PlanPurchaseRow.songs_used == songs_used)
        .values(songs_used=PlanPurchaseRow.songs_used + 1, updated_at=sa.func.now())
    )
    return rowcount_of(result) == 1


async def insert_plan(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    plan: PlanKind,
    songs_included: int,
    amount_minor: int,
    currency: str,
    provider: str,
    reference: str,
    idempotency_key: str,
    plan_ends_at: datetime,
    now: datetime,
) -> UUID | None:
    """Open a plan. The new row's id, or ``None`` when ``idempotency_key`` was already used.

    Insert-or-ignore on the key, so a double tap, a stale message and a redelivered Telegram
    update all collapse onto one plan. ``None`` is not a failure — it is "somebody already
    bought this exact plan", and the caller answers it by reading the winner back with
    :func:`plan_by_key` rather than by charging again.

    Every column is passed explicitly because this is a Core ``INSERT``: the Python-side
    ``default=`` on ``id``, ``songs_used``, ``created_at`` and ``updated_at`` fires on an ORM
    flush only, so omitting one earns a NOT NULL violation on Postgres and a surprise on
    SQLite.
    """
    plan_id = uuid4()
    written = await insert_or_ignore(
        session,
        PlanPurchaseRow,
        {
            "id": plan_id,
            "telegram_user_id": telegram_user_id,
            "plan": plan,
            "songs_included": songs_included,
            "songs_used": 0,
            "amount_minor": amount_minor,
            "currency": currency,
            "provider": provider,
            "reference": reference,
            "idempotency_key": idempotency_key,
            "plan_ends_at": plan_ends_at,
            "created_at": now,
            "updated_at": now,
        },
        index_elements=["idempotency_key"],
    )
    return plan_id if written else None


async def anonymise_plans(session: AsyncSession, *, telegram_user_id: int) -> int:
    """Strip the owner off this account's plans, keeping every plan. Rows touched.

    The ``credit_ledger`` treatment, not the ``credit_accounts`` one, and the asymmetry is
    argued in :mod:`bayram.db.credit_erasure`: a receipt is an audit fact that answers "was this
    customer charged for songs that never arrived?" long after the songs are gone, so
    deleting it would make ``/forget`` mean "refund me". The identity comes off; the amount,
    the rail's reference, the counter and the clock stay as an anonymous aggregate.

    ``songs_used`` is deliberately left where it is. Resetting it would turn ``/forget`` into
    "give me my twelve songs back", repeatable for as long as the plan runs — the same
    exploit the ledger's kept ``idempotency_key`` closes for the rolling allowance.
    """
    result = await session.execute(
        sa.update(PlanPurchaseRow)
        .where(PlanPurchaseRow.telegram_user_id == telegram_user_id)
        .values(telegram_user_id=None)
    )
    return rowcount_of(result)
