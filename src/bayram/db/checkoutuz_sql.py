"""The SQL the checkout.uz rail is made of — one statement per function.

The sibling of :mod:`bayram.db.payme_sql`, written to the same rule: nothing here decides
anything, every function performs exactly one statement, takes its session FIRST and
POSITIONAL, takes ``now`` as a parameter and commits nothing. The policy that sequences them —
the provider that mints a link, the settlement that claims one — lives in
:mod:`bayram.checkoutuz`, so "what does a checkout.uz settlement write?" reads as a short list
of named steps rather than as SQL embedded in an HTTP flow (DECISIONS.md D28).

**THE ROWCOUNT IS THE LOCK**, exactly as in :mod:`bayram.db.payme_sql`, whose docstring makes the
argument in full and rejects ``SELECT … FOR UPDATE`` (a silent no-op on SQLite) and savepoints
(different on aiosqlite and Postgres) on this repository's own recorded evidence. Every write
below is a conditional ``UPDATE`` that names the state it expects and reports whether it
touched a row; the caller treats ``False`` as "somebody else got there first", never as an
error to retry.

**THE WEBHOOK NEVER REACHES THIS FILE'S WRITES DIRECTLY.** checkout.uz's callback is unsigned
and comes from the open internet. The gateway may READ (:func:`payment_with_intent`, to decide
whether an order is worth a worker job) and nothing else; every write here is called by the
worker after it has asked checkout.uz itself and checked the answer.

**The single-row lookups carry ``populate_existing=True``** for the reason
:mod:`bayram.db.payme_sql` states: every state change here is a Core ``UPDATE`` the identity map
knows nothing about, and a read-back inside the same session must see the row as it now is.

These names are public to the ``bayram.db`` package and to the rail's own settlement and nothing
else (Rule 15).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.db.credit_sql import insert_or_ignore, rowcount_of
from bayram.db.enums import CheckoutUzPaymentState, PaymentIntentState
from bayram.db.models.checkoutuz_payment import CheckoutUzPaymentRow
from bayram.db.models.payment_intent import PaymentIntentRow

__all__ = [
    "CHECKOUTUZ_INTENT_PROVIDER",
    "CLAIMABLE_INTENT_STATES",
    # Reads
    "payment_by_order",
    "payment_with_intent",
    "live_payment_for_intent",
    "pollable_payments",
    "final_check_payments",
    # Writes
    "insert_payment",
    "mark_payment",
    "stamp_polled",
    "claim_intent_for_checkoutuz",
]

#: The ``payment_intents.provider`` value of an intent opened for this rail. Spelled here
#: rather than imported from :mod:`bayram.checkoutuz.ports` because persistence sits BELOW the
#: rail packages and does not import them — :mod:`bayram.db.payme_sql` spells ``'payme'`` the same
#: way. ``tests/test_db/test_checkoutuz_sql.py`` pins the two spellings together.
CHECKOUTUZ_INTENT_PROVIDER: Final[str] = "checkoutuz"

#: The intent states a confirmed checkout.uz payment may settle FROM.
#:
#: ``EXPIRED`` is in it, and that is the departure from every other rail and a decision rather
#: than a slip (DECISIONS.md D28). Payme asks us before it charges, so an expired intent can be
#: refused before money moves. checkout.uz does not ask: it takes the money on its own page and
#: tells us afterwards, and a link may outlive the twelve-hour intent window it was minted
#: inside. Refusing the claim then would not refuse the payment — it would only make sure the
#: customer got nothing for it. ``CANCELLED`` and ``PAID`` stay out: the first is a Payme-only
#: terminal state no checkout.uz intent reaches, and the second is the double payment that
#: :class:`~bayram.db.enums.CheckoutUzPaymentState.ORPHAN_PAID` records instead of granting.
CLAIMABLE_INTENT_STATES: Final[tuple[PaymentIntentState, ...]] = (
    PaymentIntentState.PENDING,
    PaymentIntentState.AWAITING,
    PaymentIntentState.EXPIRED,
)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
async def payment_by_order(session: AsyncSession, order_id: int) -> CheckoutUzPaymentRow | None:
    """The payment checkout.uz knows as ``order_id``, or ``None``. A primary-key probe."""
    return (
        await session.execute(
            sa.select(CheckoutUzPaymentRow)
            .where(CheckoutUzPaymentRow.order_id == order_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def payment_with_intent(
    session: AsyncSession, order_id: int
) -> tuple[CheckoutUzPaymentRow, PaymentIntentRow] | None:
    """The payment and the intent it pays for, in one statement, or ``None`` when unknown.

    One join rather than two reads, because both callers — the webhook gate deciding whether an
    order is worth a worker job, and the settlement deciding what to grant — need the pair and
    nothing less. The caller still checks ``intent.provider``: this function answers "what is
    on file for this order id?", and the answer to "is that a checkout.uz purchase?" belongs to
    the policy, where a refusal can be logged with a reason.
    """
    row = (
        await session.execute(
            sa.select(CheckoutUzPaymentRow, PaymentIntentRow)
            .join(PaymentIntentRow, PaymentIntentRow.id == CheckoutUzPaymentRow.intent_id)
            .where(CheckoutUzPaymentRow.order_id == order_id)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if row is None:
        return None
    return (row[0], row[1])


async def live_payment_for_intent(
    session: AsyncSession, intent_id: UUID, *, now: datetime, margin_s: int
) -> CheckoutUzPaymentRow | None:
    """The newest PENDING link for ``intent_id`` with at least ``margin_s`` seconds left.

    What a re-press reuses, so a customer who taps the button twice gets the same page rather
    than two live checkout.uz orders for one purchase. The margin is the point: a link with
    thirty seconds left is technically live and practically useless, because the customer has
    to open it, read it and type a card number before it lapses. Such a link is left alone —
    still pollable, still settleable — and the caller mints a fresh one beside it.
    """
    return (
        await session.execute(
            sa.select(CheckoutUzPaymentRow)
            .where(
                CheckoutUzPaymentRow.intent_id == intent_id,
                CheckoutUzPaymentRow.state == CheckoutUzPaymentState.PENDING,
                CheckoutUzPaymentRow.link_valid_until > now + timedelta(seconds=margin_s),
            )
            .order_by(CheckoutUzPaymentRow.created_at.desc(), CheckoutUzPaymentRow.order_id.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def pollable_payments(
    session: AsyncSession, *, now: datetime, grace_s: int, limit: int
) -> Sequence[CheckoutUzPaymentRow]:
    """PENDING links that are live, or lapsed by less than ``grace_s`` — the poller's batch.

    The grace is there because checkout.uz's page may finish a payment that started a moment
    before the link's advertised end, and our clock and theirs are not the same clock.

    Ordered ``last_polled_at NULLS FIRST, created_at``: a link never asked about goes before
    one asked about a minute ago, so a burst of new payments cannot be starved by a long tail
    of abandoned ones, and the batch rotates through the rest oldest-asked first. ``order_id``
    breaks the remaining ties so a batch is deterministic.

    INDEX: ``ix_checkoutuz_payments_state_valid_until``.
    """
    return (
        (
            await session.execute(
                sa.select(CheckoutUzPaymentRow)
                .where(
                    CheckoutUzPaymentRow.state == CheckoutUzPaymentState.PENDING,
                    CheckoutUzPaymentRow.link_valid_until > now - timedelta(seconds=grace_s),
                )
                .order_by(
                    CheckoutUzPaymentRow.last_polled_at.asc().nulls_first(),
                    CheckoutUzPaymentRow.created_at.asc(),
                    CheckoutUzPaymentRow.order_id.asc(),
                )
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def final_check_payments(
    session: AsyncSession, *, now: datetime, grace_s: int, limit: int
) -> Sequence[CheckoutUzPaymentRow]:
    """PENDING links lapsed by ``grace_s`` or more — owed one last status check, then closing.

    The exact complement of :func:`pollable_payments` over the pending set, split on the same
    boundary, so a link is in exactly one of the two batches at any instant. The caller asks
    checkout.uz once more and, unless the answer is ``paid``, moves the row to ``expired`` with
    :func:`mark_payment` — never the intent, whose own clock is the Payme sweep's business.

    Ordered ``last_polled_at NULLS FIRST, link_valid_until``, like the poll batch, so the batch
    ROTATES: an order checkout.uz keeps failing to answer for is stamped on each attempt
    (``bayram.checkoutuz.settle``) and goes to the back, rather than the oldest failing rows
    filling every batch forever and starving newer lapsed links of their last check.

    INDEX: ``ix_checkoutuz_payments_state_valid_until``.
    """
    return (
        (
            await session.execute(
                sa.select(CheckoutUzPaymentRow)
                .where(
                    CheckoutUzPaymentRow.state == CheckoutUzPaymentState.PENDING,
                    CheckoutUzPaymentRow.link_valid_until <= now - timedelta(seconds=grace_s),
                )
                .order_by(
                    CheckoutUzPaymentRow.last_polled_at.asc().nulls_first(),
                    CheckoutUzPaymentRow.link_valid_until.asc(),
                    CheckoutUzPaymentRow.order_id.asc(),
                )
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
async def insert_payment(
    session: AsyncSession,
    *,
    order_id: int,
    intent_id: UUID,
    payment_uuid: str,
    pay_url: str,
    amount_som: int,
    link_valid_until: datetime,
    now: datetime,
    pay_via: Sequence[tuple[str, str]] = (),
) -> bool:
    """Record a link checkout.uz just minted. ``True`` when THIS caller wrote it.

    Insert-or-ignore on ``order_id``, the primitive :func:`bayram.db.payme_sql.insert_intent`
    uses. ``False`` means the order id is already on file — checkout.uz handing the same id out
    twice, or a retried record of one create — and the row that is there is left exactly as it
    was: it may already have been polled or paid, and overwriting it would rewind it.

    ``state`` is written explicitly as ``pending`` and every column is passed, including the
    two clocks: this is a Core ``INSERT`` and the model's Python-side defaults fire on an ORM
    flush only. ``pay_via`` is stored as ``[[method, url], ...]``, or NULL when empty.
    """
    return await insert_or_ignore(
        session,
        CheckoutUzPaymentRow,
        {
            "order_id": order_id,
            "intent_id": intent_id,
            "payment_uuid": payment_uuid,
            "pay_url": pay_url,
            "pay_via": [[key, url] for key, url in pay_via] or None,
            "amount_som": amount_som,
            "state": CheckoutUzPaymentState.PENDING,
            "link_valid_until": link_valid_until,
            "last_polled_at": None,
            "paid_at": None,
            "created_at": now,
            "updated_at": now,
        },
        index_elements=["order_id"],
    )


async def mark_payment(
    session: AsyncSession,
    order_id: int,
    *,
    frm: CheckoutUzPaymentState | tuple[CheckoutUzPaymentState, ...],
    to: CheckoutUzPaymentState,
    now: datetime,
    paid_at: datetime | None = None,
) -> bool:
    """Move one link ``frm -> to``. ``False`` means it was not in ``frm`` — somebody else moved it.

    The one transition primitive for this table. The settlement calls it as ``pending -> paid``
    FIRST inside its transaction, and a ``False`` there is the replay answer: another worker, or
    an earlier run of this one, already settled the order, so nothing else may be written. The
    final check calls it as ``pending -> expired``, and the same ``False`` means the order was
    settled between the read and the write — which is exactly the race the conditional form
    exists to make harmless.

    ``paid_at`` is written only when given, so expiring a row never blanks a clock and marking
    one paid never has to be followed by a second statement. ``last_polled_at`` is stamped too:
    every caller of this function has just asked checkout.uz about the order.

    ``frm`` may be a tuple: the settlement moves ``(pending, expired) -> paid``, because a link
    the final check closed can still be paid on a page left open (``DECISIONS.md D28``).
    """
    from_states = frm if isinstance(frm, tuple) else (frm,)
    values: dict[str, object] = {"state": to, "last_polled_at": now, "updated_at": now}
    if paid_at is not None:
        values["paid_at"] = paid_at
    result = await session.execute(
        sa.update(CheckoutUzPaymentRow)
        .where(
            CheckoutUzPaymentRow.order_id == order_id,
            CheckoutUzPaymentRow.state.in_(from_states),
        )
        .values(**values)
    )
    return rowcount_of(result) == 1


async def stamp_polled(session: AsyncSession, order_id: int, now: datetime) -> bool:
    """Record that checkout.uz was asked about a PENDING order and did not say paid.

    Conditional on ``pending`` so a stamp that loses a race with the settlement cannot touch a
    row that has already moved on. ``False`` is not an error — it means the row is no longer
    the poller's business. What this buys is the rotation in :func:`pollable_payments`: a row
    stamped now goes to the back of the next batch.
    """
    result = await session.execute(
        sa.update(CheckoutUzPaymentRow)
        .where(
            CheckoutUzPaymentRow.order_id == order_id,
            CheckoutUzPaymentRow.state == CheckoutUzPaymentState.PENDING,
        )
        .values(last_polled_at=now, updated_at=now)
    )
    return rowcount_of(result) == 1


async def claim_intent_for_checkoutuz(
    session: AsyncSession, *, intent_id: UUID, now: datetime, note: str
) -> bool:
    """The money landed through checkout.uz: claim the intent ``-> paid``. ``False`` means orphan.

    The settlement's second conditional ``UPDATE``, issued after :func:`mark_payment` has
    taken the link ``pending -> paid`` in the same transaction. It matches the three
    :data:`CLAIMABLE_INTENT_STATES` — including ``expired``, argued on that constant — and an
    intent whose ``provider`` is this rail; it names no holder, because checkout.uz has no
    transaction of ours to hold one.

    ``False`` is the double payment: the intent is already ``paid``, through an earlier link
    of the same purchase. The caller marks the link ``orphan_paid`` and grants nothing, and the
    sale is written under the intent's own idempotency key in any case, so even a caller that
    ignored this answer would land on the unique indexes rather than grant twice.

    ``settled_at`` is stamped from the caller's ``now``, the same instant the receipt and the
    link's ``paid_at`` carry. ``note`` arrives already shaped as ``checkoutuz:<order_id>``.
    """
    result = await session.execute(
        sa.update(PaymentIntentRow)
        .where(
            PaymentIntentRow.id == intent_id,
            PaymentIntentRow.provider == CHECKOUTUZ_INTENT_PROVIDER,
            PaymentIntentRow.state.in_(CLAIMABLE_INTENT_STATES),
        )
        .values(
            state=PaymentIntentState.PAID,
            settled_at=now,
            settle_note=note,
            updated_at=now,
        )
    )
    return rowcount_of(result) == 1
