"""``plan_purchases`` — the receipts table that has been fully populated and never read.

Every column this module needs has been written on every plan sold since revision 0015:
``amount_minor``, ``currency``, ``provider``, ``reference``, ``idempotency_key``,
``plan_ends_at``, ``songs_included``, ``songs_used``. There was simply no read layer, no
schema and no route, so the money has been recorded and invisible. This module is the read
half; :mod:`bayram.db.admin.topup_purchases` is its sibling for the other product, one module
per table exactly as ``credits.py`` / ``orders.py`` / ``vendor_usage.py`` are, and the
ROUTER is what joins the two sources — not the data layer.

**Every number is computed by the database.** No function here fetches rows and folds them.
The only Python arithmetic is over already-grouped results — materialising ten histogram
buckets — which is bounded by the bucket count and never by rows.

**Never sum across currencies.** ``currency`` is a column, so a naked ``SUM(amount_minor)``
over a mixed window is a fabricated number in an invented unit. Every money aggregate here
is grouped by it and every caller receives a tuple, never a scalar. Today every row is UZS
and the day that stops being true no reader has to change.

**Never collapse ``provider``.** ``StubCheckoutProvider`` stamps ``is_paid=True`` having
contacted nobody, so a figure on this surface means SALES RECORDED and never money banked,
and the rail has to travel with it at the finest grain. A window that mixed a stub row and a
real Payme row into one total would be read as one settled figure.

**The liability figure is SONGS, not soʻm.** Valuing an unconsumed song means dividing
``amount_minor`` by ``songs_included``, which is an accounting ALLOCATION policy nobody in
this codebase has chosen. :func:`plan_liability` publishes measured song counts and the
measured ``SUM(amount_minor)`` of plans still running, and refuses the pro-rata figure,
because a number that looks measured and is really a policy is worse than no number.

**``COUNT(DISTINCT telegram_user_id)`` drops the erased.** ``/forget`` nulls the column and
``COUNT(DISTINCT)`` does not count NULLs, so ``live_holders`` understates by exactly the
number of customers who exercised a right. ``live_anonymised_plans`` is returned beside it
for that reason and is the single most regressible number in this module. Note also that
``live_plans`` can exceed ``live_holders`` with no erasure at all: ``start_plan`` refuses a
second CURRENT plan, but a renewal bought before the previous one lapsed leaves two rows
current, and liability is carried by rows rather than by people.

**Utilisation covers ENDED plans only**, with ``ended_plans`` published as its denominator.
A running plan's ratio is not final and breakage is not a thing you can measure before the
clock stops. :func:`subscription_churn` restricts itself to ended plans for exactly the same
reason and pays exactly the same price: both figures are late by up to the plan length.

**Churn is INFERRED here, not recorded anywhere.** There is no renewal event in this schema
— ``start_plan`` refuses to write a second row while a plan is current and hands the running
one back — so "they renewed" can only ever mean "a later receipt exists for the same
``telegram_user_id``". :func:`subscription_churn` publishes that inference and names its two
counts ``renewed`` / ``lapsed`` rather than anything implying a link between two rows that
the data does not hold.

**Nothing here is personal data.** No ``telegram_user_id`` leaves this module — only counts
of them — which is what lets the whole surface sit on DASHBOARD_READ with no masking branch.
:data:`~bayram.db.admin.page.TOTAL_COUNT_CAP` and ``bounded_total`` are deliberately NOT used:
a dashboard count that saturated at 10 000 would silently misreport a real book.

**No new index is needed.** Bookings ride ``ix_plan_purchases_created_at`` (from
``TimestampMixin``); the liability, expiry and churn-denominator predicates ride the
standalone ``ix_plan_purchases_plan_ends_at`` — ``ix_plan_purchases_user_ends`` leads with
``telegram_user_id`` and so cannot serve a global range, but it is exactly the right shape
for the per-row renewal probe in :func:`subscription_churn`, which is an equality on that
leading column; the utilisation histogram and the liability row are whole-table aggregates
no index helps and none is added for them.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Select

from bayram.db.admin.sql import (
    SeriesGrain,
    TimeWindow,
    apply_window,
    bucket_expression,
    bucket_started_at,
    count_where,
)
from bayram.db.admin.views import (
    CurrencyAmount,
    PaymentReceipt,
    PlanLiability,
    PlanUtilisationBucket,
    RevenueBucket,
    RevenueSource,
    RevenueTotal,
    SubscriptionChurn,
)
from bayram.db.models.plan_purchase import PlanPurchaseRow

__all__ = [
    "DEFAULT_EXPIRY_HORIZON_DAYS",
    "UTILISATION_BUCKETS",
    "plan_bookings_per_bucket",
    "plan_revenue_totals",
    "plan_liability",
    "plan_utilisation",
    "subscription_churn",
    "has_recorded_plan_revenue",
    "receipt_for_key",
    "PLAN_RECEIPT_SOURCE",
]

#: What :attr:`~bayram.db.admin.views.PaymentReceipt.source` says when the sale landed here.
#: The TABLE name, for the reason :data:`~bayram.db.admin.topup_purchases.TOPUP_RECEIPT_SOURCE`
#: gives: an operator checking a row by hand needs the name they will type into ``psql``.
PLAN_RECEIPT_SOURCE: Final[str] = "plan_purchases"

#: How far ahead "expiring soon" looks, unless a caller says otherwise. A week, because that
#: is the horizon on which an operator can still act — send a reminder, offer a renewal —
#: and a longer default would fold plans nobody can do anything about yet into a number
#: meant to prompt an action.
DEFAULT_EXPIRY_HORIZON_DAYS: Final[int] = 7

#: Bars in the utilisation histogram. Ten because a percentage reads in tenths.
UTILISATION_BUCKETS: Final[int] = 10

#: The closed top bar. A plan with ``songs_used >= songs_included`` lands here rather than
#: in a spurious eleventh bucket that integer division would otherwise produce for exactly
#: 100%.
_TOP_BUCKET: Final[int] = UTILISATION_BUCKETS - 1


async def plan_bookings_per_bucket(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
    grain: SeriesGrain = SeriesGrain.DAY,
) -> tuple[RevenueBucket, ...]:
    """Plans sold per bucket, keyed by ``(plan, currency, provider)``. Oldest first.

    A bucket with no sale is ABSENT rather than present at zero — the standing rule, and
    sharper here than on an order series: a zero bar is a claim about money we did not take
    on a day this deployment may not have existed.

    INDEX: ``ix_plan_purchases_created_at``.
    """
    bucket = bucket_expression(grain, PlanPurchaseRow.created_at)
    grouping = (PlanPurchaseRow.plan, PlanPurchaseRow.currency, PlanPurchaseRow.provider)
    statement: Select[Any] = sa.select(
        bucket.label("bucket"),
        *grouping,
        sa.func.count().label("sales"),
        sa.func.sum(PlanPurchaseRow.amount_minor).label("amount_minor"),
    )
    statement = apply_window(statement, PlanPurchaseRow.created_at, window)
    rows = (
        await session.execute(statement.group_by(bucket, *grouping).order_by(bucket, *grouping))
    ).all()
    return tuple(
        RevenueBucket(
            bucket=str(row.bucket),
            started_at=bucket_started_at(grain, str(row.bucket)),
            source=RevenueSource.PLAN,
            product=row.plan.value,
            currency=row.currency,
            provider=row.provider,
            sales=int(row.sales),
            amount_minor=int(row.amount_minor),
        )
        for row in rows
    )


async def plan_revenue_totals(
    session: AsyncSession, *, window: TimeWindow | None = None
) -> tuple[RevenueTotal, ...]:
    """The window's plan sales, one row per ``(plan, currency, provider)``, largest first.

    A TUPLE and never a scalar, because there is no honest scalar: the rows carry a currency
    and a rail, and collapsing either produces a figure in an invented unit or a stub sale
    dressed as settled money. Today every row is UZS from the stub rail, so this usually
    returns one element — and the shape must stay a list anyway, or the day a second
    currency or a real rail appears the number silently becomes wrong rather than longer.

    INDEX: ``ix_plan_purchases_created_at``.
    """
    grouping = (PlanPurchaseRow.plan, PlanPurchaseRow.currency, PlanPurchaseRow.provider)
    amount = sa.func.sum(PlanPurchaseRow.amount_minor).label("amount_minor")
    statement: Select[Any] = sa.select(*grouping, sa.func.count().label("sales"), amount)
    statement = apply_window(statement, PlanPurchaseRow.created_at, window)
    rows = (
        await session.execute(statement.group_by(*grouping).order_by(amount.desc(), *grouping))
    ).all()
    return tuple(
        RevenueTotal(
            source=RevenueSource.PLAN,
            product=row.plan.value,
            currency=row.currency,
            provider=row.provider,
            sales=int(row.sales),
            amount_minor=int(row.amount_minor),
        )
        for row in rows
    )


async def plan_liability(
    session: AsyncSession,
    *,
    now: datetime,
    expiring_within_days: int = DEFAULT_EXPIRY_HORIZON_DAYS,
) -> PlanLiability:
    """What the running plans owe, as of ``now``. A STATE, and therefore never windowed.

    Three statements, because three different shapes of answer cannot share one:

    1. one ungrouped row of conditional aggregates over the live / ended / expiring
       partitions;
    2. ``COUNT(DISTINCT telegram_user_id)`` for the holder count — see the module docstring
       on why that number alone understates and why ``live_anonymised_plans`` rides beside
       it;
    3. ``SUM(amount_minor)`` grouped by currency, because there is no scalar money.

    **The expiry window is half-open below and closed above** — ``now < plan_ends_at <=
    now + horizon`` — so a plan is never counted as both live-and-expiring and already
    ended, and a plan ending exactly at ``now`` is ended.

    The three song totals come from ``SUM(CASE … ELSE NULL)`` and are ``None`` when their
    partition is empty. ``None`` means "no plan is in this partition"; ``0`` means "plans
    are, and they owe nothing". Two different screens.

    INDEX: ``ix_plan_purchases_plan_ends_at`` for the live/ended/expiring predicates. The
    conditional-aggregate row is a whole-table scan and no index helps it — correct at one
    row per plan sold and fine for years at this product's volume. Revisit at roughly a
    million rows; the fix is then a materialised snapshot, not an index.
    """
    horizon = now + timedelta(days=expiring_within_days)
    live = PlanPurchaseRow.plan_ends_at > now
    ended = PlanPurchaseRow.plan_ends_at <= now
    expiring = live & (PlanPurchaseRow.plan_ends_at <= horizon)
    remaining = PlanPurchaseRow.songs_included - PlanPurchaseRow.songs_used

    aggregates: Select[Any] = sa.select(
        count_where(live).label("live_plans"),
        count_where(live & PlanPurchaseRow.telegram_user_id.is_(None)).label("anonymised"),
        count_where(live & (PlanPurchaseRow.songs_used < PlanPurchaseRow.songs_included)).label(
            "with_songs_left"
        ),
        sa.func.sum(sa.case((live, remaining), else_=None)).label("unconsumed"),
        count_where(ended).label("ended_plans"),
        sa.func.sum(sa.case((ended, remaining), else_=None)).label("breakage"),
        count_where(expiring).label("expiring_plans"),
        sa.func.sum(sa.case((expiring, remaining), else_=None)).label("expiring_songs"),
    ).select_from(PlanPurchaseRow)
    row = (await session.execute(aggregates)).one()

    holders = int(
        await session.scalar(
            sa.select(sa.func.count(sa.distinct(PlanPurchaseRow.telegram_user_id))).where(live)
        )
        or 0
    )
    amounts = (
        await session.execute(
            sa.select(
                PlanPurchaseRow.currency,
                sa.func.sum(PlanPurchaseRow.amount_minor).label("amount_minor"),
            )
            .where(live)
            .group_by(PlanPurchaseRow.currency)
            .order_by(PlanPurchaseRow.currency)
        )
    ).all()

    return PlanLiability(
        as_of=now,
        live_plans=int(row.live_plans),
        live_holders=holders,
        live_anonymised_plans=int(row.anonymised),
        live_plans_with_songs_left=int(row.with_songs_left),
        unconsumed_songs=_as_int(row.unconsumed),
        live_amounts=tuple(
            CurrencyAmount(currency=item.currency, amount_minor=int(item.amount_minor))
            for item in amounts
        ),
        ended_plans=int(row.ended_plans),
        breakage_songs=_as_int(row.breakage),
        expiring_within_days=expiring_within_days,
        expiring_plans=int(row.expiring_plans),
        expiring_songs_left=_as_int(row.expiring_songs),
    )


async def plan_utilisation(
    session: AsyncSession, *, now: datetime
) -> tuple[PlanUtilisationBucket, ...]:
    """How much of an ENDED plan its holder actually used, in ten bars. Always ten.

    Ended plans only: a running plan's ratio is not final, and counting it would move a
    completed bar every time somebody claims a song. ``PlanLiability.ended_plans`` is the
    denominator and is published beside this so an operator can see whether the shape is
    worth reading at all.

    All ten buckets are returned even when empty, because a histogram with holes in it is
    unreadable — a ``count`` of ``0`` here is an empty BIN, which is a measurement, and not
    an absent one. The Python fold is over at most ten already-grouped rows.

    The bucket expression uses SQLAlchemy's ``//`` (``floordiv``) rather than ``/``, which is
    the whole reason ``//`` exists on columns: it renders ``FLOOR(a / b)`` on Postgres and
    integer division on SQLite, so a plan at 5 of 12 lands in bucket 4 on both dialects
    rather than being rounded differently by each. The explicit ``>= songs_included`` arm
    keeps a fully-used plan in bucket 9 instead of producing a spurious eleventh bucket.

    INDEX: ``ix_plan_purchases_plan_ends_at`` for the ended predicate; the grouping itself is
    a whole-table aggregate no index serves.
    """
    bucket = sa.case(
        (PlanPurchaseRow.songs_used >= PlanPurchaseRow.songs_included, _TOP_BUCKET),
        else_=PlanPurchaseRow.songs_used * UTILISATION_BUCKETS // PlanPurchaseRow.songs_included,
    ).label("bucket")
    statement: Select[Any] = (
        sa.select(bucket, sa.func.count().label("plans"))
        .where(PlanPurchaseRow.plan_ends_at <= now)
        .group_by(bucket)
        .order_by(bucket)
    )
    counts = {int(row.bucket): int(row.plans) for row in (await session.execute(statement)).all()}
    width = 1.0 / UTILISATION_BUCKETS
    return tuple(
        PlanUtilisationBucket(
            lower=index * width,
            upper=(index + 1) * width,
            count=counts.get(index, 0),
        )
        for index in range(UTILISATION_BUCKETS)
    )


async def subscription_churn(
    session: AsyncSession, *, now: datetime, window: TimeWindow | None = None
) -> SubscriptionChurn:
    """Of the plans that ENDED in the window, how many the holder bought again. One statement.

    **The window is on ``plan_ends_at``, never on ``created_at``.** The population is the
    plans whose outcome is settled, and a running plan's is not: its holder has not declined
    to renew, they simply have not reached the decision yet, so counting them would file
    every customer of the last thirty days as lapsed. This is the identical argument
    :func:`plan_utilisation` makes for restricting the histogram to ended plans, and it
    carries the identical price — the figure is late by up to the plan length, and is honest
    rather than early. Windowing on the ending also makes the slices tile: a plan ends once,
    so it lands in exactly one window however the caller cuts the year.

    **``now`` is a required parameter and not an alias for the window's end**, because the
    window cannot be trusted to bound the future. ``resolve_window`` returns ``None`` for a
    request that named neither bound — "the whole record" — and returns ``[from, to)`` with
    whatever ``to`` the operator typed, which may be next month. Either way an unbounded-above
    predicate on ``plan_ends_at`` sweeps in plans that have not ended yet and files every one
    of them as lapsed, which is the exact failure the paragraph above refuses. So the ending
    predicate is ``plan_ends_at <= now`` AND the window, and ``now`` wins whenever the window
    reaches past it. ``<=`` rather than ``<`` so a plan ending exactly at ``now`` is ended
    here and in :func:`plan_liability` alike; those two reads must not disagree about one row.
    The clock is a parameter for the reason every read in this layer takes one — see
    :func:`~bayram.db.admin.users.get_user_detail` — so a test can move it and a request's
    several time-dependent answers land on the same side of every boundary.

    **A renewal is INFERRED from a later receipt, because there is no renewal event.**
    Nothing in the schema records "this purchase replaced that one" — ``plan_purchases`` rows
    are independent receipts, and ``start_plan`` refuses to write a second row while a plan
    is current and hands the running one back — so a second row for the same holder can only
    have been bought once the first stopped being current. The probe is therefore a
    correlated ``EXISTS`` for a row with the same ``telegram_user_id`` and a strictly later
    ``created_at``, which is that inference spelled out and nothing more. It says the holder
    came back. It does not say when: a customer who returned after four idle months is
    ``renewed`` here and no column separates them from one who renewed the same afternoon.

    **The three counts PARTITION the denominator** — ``renewed + lapsed + anonymised_ended ==
    ended_plans``, on every window, and a test asserts it. ``/forget`` nulls
    ``telegram_user_id`` on the receipt, and a row with no identity cannot be followed to a
    later purchase by anybody, this read included; so those endings are counted in their own
    arm rather than being dropped into ``lapsed``, which would state that an erased customer
    did not come back when the truth is that nobody can tell. It is the same honesty column
    ``live_anonymised_plans`` is in :func:`plan_liability`, and it means ``lapsed`` is a floor
    on the real lapse count with ``anonymised_ended`` as the exact width of the blind spot
    above it. ``rate`` — computed by the view, never here — divides ``lapsed`` by the whole
    denominator and is therefore an understatement by at most ``anonymised_ended`` endings.

    **Read the denominator before you read the rate.** One thirty-day product, first sold
    weeks ago: for the first month ``ended_plans`` is a single-digit number and a rate over
    three ended plans is noise that a single ending swings by thirty-three points. Nothing
    here smooths that, hides it, or refuses below a threshold — a floor would be a second
    invented number. The count IS the answer at this volume: the API publishes
    ``ended_plans`` beside the rate and the panel prints it next to the percentage, so an
    operator can see how much weight the percentage carries. Below roughly thirty endings,
    treat the counts as the measurement and the rate as decoration.

    **The answer moves.** A plan that ended yesterday and is renewed tomorrow is ``lapsed``
    when read today and ``renewed`` when the same window is read next week. That is inherent
    to measuring a decision the customer is still entitled to make, and the alternative —
    withholding an ending until some grace period elapsed — would invent a deadline nobody
    was told about and would make the number late twice over.

    INDEX: ``ix_plan_purchases_plan_ends_at`` for the ``now`` cap and the window that
    together select the denominator,
    then ``ix_plan_purchases_user_ends`` for the renewal probe — it leads with
    ``telegram_user_id``, which is exactly the correlated equality, and the ``created_at``
    comparison is rechecked in the heap because the index's second column is ``plan_ends_at``.
    One probe per ended plan, so the work is bounded by the denominator and not by the table.
    """
    later_purchase = aliased(PlanPurchaseRow, name="later_purchase")
    renewal_exists = (
        sa.select(sa.literal(1))
        .select_from(later_purchase)
        .where(
            later_purchase.telegram_user_id == PlanPurchaseRow.telegram_user_id,
            later_purchase.created_at > PlanPurchaseRow.created_at,
        )
        .correlate(PlanPurchaseRow)
        .exists()
    )
    # Stated rather than relied on: ``NULL = NULL`` is unknown, so an anonymised row could
    # never satisfy the probe anyway. The explicit arm is what keeps the three counts a
    # partition when a future reader changes the join.
    identified = PlanPurchaseRow.telegram_user_id.is_not(None)

    statement: Select[Any] = sa.select(
        sa.func.count().label("ended_plans"),
        count_where(identified & renewal_exists).label("renewed"),
        count_where(identified & ~renewal_exists).label("lapsed"),
        count_where(PlanPurchaseRow.telegram_user_id.is_(None)).label("anonymised"),
    ).select_from(PlanPurchaseRow)
    # ``now`` first, then the window: an operator's ``?to=`` may reach into next month and an
    # absent window reaches everywhere, and neither may promote a running plan to an ending.
    statement = statement.where(PlanPurchaseRow.plan_ends_at <= now)
    statement = apply_window(statement, PlanPurchaseRow.plan_ends_at, window)
    row = (await session.execute(statement)).one()

    return SubscriptionChurn(
        ended_plans=int(row.ended_plans),
        renewed=int(row.renewed),
        lapsed=int(row.lapsed),
        anonymised_ended=int(row.anonymised),
    )


async def has_recorded_plan_revenue(session: AsyncSession) -> bool:
    """True once any plan has been sold here. The ``isPlanRevenue`` capability.

    A ROW probe and window-blind, exactly as
    :func:`~bayram.db.admin.vendor_usage.has_recorded_vendor_usage` is: this table's migration
    ships with the panel, so a ``has_table`` probe would report every deployment as
    revenue-instrumented the day it lands, and "nothing in the range you chose" would be
    indistinguishable from "no plan has ever been sold here".
    """
    probe = await session.scalar(sa.select(sa.literal(1)).select_from(PlanPurchaseRow).limit(1))
    return probe is not None


def _as_int(value: Any) -> int | None:
    """A ``SUM`` over a conditional. ``None`` stays ``None`` — the partition was empty."""
    return None if value is None else int(value)


async def receipt_for_key(session: AsyncSession, *, idempotency_key: str) -> PaymentReceipt | None:
    """The plan sale written under one payment's key, or ``None`` if none was.

    :func:`bayram.db.admin.topup_purchases.receipt_for_key`'s mirror image, for
    ``product = 'starter'``, and it lives here for the same reason: one module per table, and
    the ROUTER is what joins two sources.

    **``songs_used`` is the ONE place the fulfilment chain continues past the purchase.** For a
    single song it stops at the credit grant — ``credit_accounts.balance`` is a fungible scalar
    with no lot structure, so a later ``DEBIT``/``ORDER_RENDER`` cannot be attributed to the
    grant that funded it and no query can prove which song a bought credit rendered. A plan
    keeps its consumption on the receipt row itself, so "did they use what they paid for?" has
    an answer here and only here.

    ``credits_granted`` is ``None`` on this shape and that is a fact rather than a gap: a plan
    grants nothing at purchase, because it mints songs as they are used. A caller must render
    the dossier's credit step as NOT APPLICABLE for a plan, never as missing.

    **``None`` is legitimate** for the reason the sibling states: an erased buyer's settled
    intent has no receipt in either table.

    INDEX: the unique ``ix_plan_purchases_idempotency_key`` — one index-only probe.
    """
    row = (
        await session.execute(
            sa.select(
                PlanPurchaseRow.amount_minor,
                PlanPurchaseRow.currency,
                PlanPurchaseRow.provider,
                PlanPurchaseRow.reference,
                PlanPurchaseRow.songs_included,
                PlanPurchaseRow.songs_used,
                PlanPurchaseRow.plan_ends_at,
                PlanPurchaseRow.created_at,
            ).where(PlanPurchaseRow.idempotency_key == idempotency_key)
        )
    ).one_or_none()
    if row is None:
        return None
    return PaymentReceipt(
        source=PLAN_RECEIPT_SOURCE,
        amount_minor=int(row.amount_minor),
        currency=str(row.currency),
        provider=str(row.provider),
        reference=None if row.reference is None else str(row.reference),
        credits_granted=None,
        songs_included=int(row.songs_included),
        songs_used=int(row.songs_used),
        plan_ends_at=row.plan_ends_at,
        created_at=row.created_at,
    )
