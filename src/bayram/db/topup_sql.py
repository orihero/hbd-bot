"""The SQL primitives the top-up receipt is written through — one statement per function.

The exact sibling of :mod:`bayram.db.plan_sql`, and written to the same rule: nothing here
decides anything, every function performs exactly one statement, takes its session first
and positional, takes ``now`` as a parameter and commits nothing. The policy that uses them
lives in :mod:`bayram.db.purchases`, so that "what does a paid single song write?" reads as a
short sequence of named steps rather than as SQL embedded in a fulfiller.

**The one idea this module exists to serve: a sale and a credit movement are two different
facts, and both are written under ONE key.** ``bayram.db.purchases._fulfil_single`` writes a
``topup_purchases`` row here and a ``credit_ledger`` GRANT through
:func:`bayram.db.credits.grant`, in one transaction, stamped from one clock, keyed on one
``idempotency_key``. The receipt carries what was paid — amount, currency, rail, the rail's
own reference — which the GRANT has nowhere to hold; the GRANT carries the entitlement,
which a receipt has no business asserting. :mod:`bayram.db.models.topup_purchase` argues at
length why the money did not simply become four more columns on ``credit_ledger``.

**:func:`bayram.db.credit_sql.insert_or_ignore` is the whole concurrency story.** Two writers
of the same purchase both succeed at the statement level and exactly one is told it won, so
a double tap, a stale message and a redelivered Telegram update all collapse onto one sale.
That is what lets ``_fulfil_single`` write TWO rows under one key and stay idempotent: each
write is independently insert-or-ignore on its own unique index, so a replay writes nothing,
twice, and the caller still returns the unchanged balance.

**Every column is passed explicitly**, including ``id`` and ``created_at``. These are Core
``INSERT``s, and the Python-side ``default=`` on a mapped column fires on an ORM flush only:
omitting one earns a NOT NULL violation on Postgres and a surprise on SQLite. ``insert_plan``
carries the same note for the same reason.

These names are public to the ``bayram.db`` package and to nothing else, exactly like
``credit_sql`` and ``plan_sql``: a caller outside persistence has no business holding a
session (Rule 15).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.db.credit_sql import insert_or_ignore, rowcount_of
from bayram.db.enums import TopupKind
from bayram.db.models.topup_purchase import TopupPurchaseRow

__all__ = ["insert_topup", "topup_by_key", "anonymise_topups"]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
async def topup_by_key(session: AsyncSession, idempotency_key: str) -> TopupPurchaseRow | None:
    """The receipt written under ``idempotency_key``. The read-back after an ignored insert.

    :func:`insert_topup` reports that it lost — it cannot report WHAT it lost to, because
    ``INSERT … ON CONFLICT DO NOTHING`` returns nothing at all. The sibling
    :func:`bayram.db.plan_sql.plan_by_key` exists because the plan's caller must hand the
    winner's row back to the customer; this one exists for the narrower case of a caller or
    a test that needs to see the sale a replay collapsed onto, since the single song's own
    answer to a double tap is the balance and not the receipt.
    """
    return (
        await session.execute(
            sa.select(TopupPurchaseRow).where(TopupPurchaseRow.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
async def insert_topup(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    product: TopupKind,
    credits_granted: int,
    amount_minor: int,
    currency: str,
    provider: str,
    reference: str,
    idempotency_key: str,
    now: datetime,
) -> UUID | None:
    """Record one sale. The new row's id, or ``None`` when ``idempotency_key`` was used.

    ``None`` is not a failure — it is "this exact sale is already recorded", which is what a
    double tap looks like, and the caller answers it by returning the balance the customer
    already has rather than by charging again.

    ``amount_minor`` is written verbatim from :class:`bayram.checkout.Purchase` and is never
    derived from a setting. ``Settings.single_song_price_minor`` is what the CHECKOUT quotes;
    reading it here would price a sale at whatever the current price happens to be at write
    time, and reading it at query time would reprice every historical period the next time
    the price moves. The price that was charged is the one the rail answered for, and it
    arrives on the ``Purchase``.

    ``credits_granted`` is likewise stored rather than inferred from ``product``: a package
    change tomorrow must not retroactively rewrite what somebody already bought — the reason
    ``plan_purchases.songs_included`` is a column and not a lookup.
    """
    topup_id = uuid4()
    written = await insert_or_ignore(
        session,
        TopupPurchaseRow,
        {
            "id": topup_id,
            "telegram_user_id": telegram_user_id,
            "product": product,
            "credits_granted": credits_granted,
            "amount_minor": amount_minor,
            "currency": currency,
            "provider": provider,
            "reference": reference,
            "idempotency_key": idempotency_key,
            "created_at": now,
        },
        index_elements=["idempotency_key"],
    )
    return topup_id if written else None


async def anonymise_topups(session: AsyncSession, *, telegram_user_id: int) -> int:
    """Strip the buyer off this account's receipts, keeping every receipt. Rows touched.

    The ``credit_ledger`` treatment, not the ``credit_accounts`` one, and the argument is
    :mod:`bayram.db.credit_erasure`'s: a receipt is an audit fact that answers "was this
    customer charged 7 000 soʻm for a song they never got?" long after the recipient's name,
    the customer's note and the rendered audio are lawfully gone. Deleting it would make
    ``/forget`` mean "refund me", and would destroy that answer for everyone. The identity
    comes off; the amount, the currency, the rail, its reference, the key and the clock stay
    as an anonymous sale.

    ``idempotency_key`` is deliberately kept exactly as written, matching
    :func:`bayram.db.plan_sql.anonymise_plans` and the ledger's own treatment. It is the replay
    marker: rewriting it would let a second purchase under the same key record a second sale
    against a customer who has already asked to be forgotten — ``/forget`` as a way of
    clearing your own deduplication memory.
    """
    result = await session.execute(
        sa.update(TopupPurchaseRow)
        .where(TopupPurchaseRow.telegram_user_id == telegram_user_id)
        .values(telegram_user_id=None)
    )
    return rowcount_of(result)
