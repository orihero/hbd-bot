"""The two dashboard lists that name a customer. **Identity leaves this module on purpose.**

Every other read in this package is personal-data-free by construction — ``overview.py``
and ``plan_purchases.py`` each state in their own docstrings that no ``telegram_user_id``
leaves them, only counts of them, and that statement is precisely what lets the whole
``DASHBOARD_READ`` surface skip masking, skip the reveal gate and publish no unmasked
variant of any response. This module makes the opposite promise, and it exists as a
separate file so that theirs stays true: a top-generators list bolted onto ``orders.py``'s
aggregates or a recent-subscribers list bolted onto ``plan_purchases.py`` would silently
retract a claim two other modules make about themselves.

**What is carried and under what authority.** ``telegram_user_id``, ``telegram_username``
and ``first_name`` — the ACCOUNT HOLDER's identity — travel on both views here. The owner
is the sole operator of this panel and has decided that an account holder's Telegram
identity may be shown to them directly, with an AUDIT ENTRY rather than a reveal gate: the
holder is the person who pays and whom the operator answers to, so the operator already
knows who they are the moment that customer sends a message. So both reads are served on
``RECORDS_READ`` — the permission ``/users`` already stands on — from their own route,
which writes an audit row the way every other record read does, and neither is part of the
``DASHBOARD_READ`` surface.

**Three things that decision does NOT cover, stated because a later reader will assume it
did.** The reveal / step-up machinery is untouched and stays load-bearing: free text, media
and phone numbers are still ``POST /reveal`` alone, and nothing in
``hbd.admin.routers.reveal`` may be weakened on the strength of this module existing. The
RECIPIENT's name — ``briefs.recipient_name_display``, ``name_records.grapheme`` — is not
here and must not be added: the third party a song is about consented to nothing, and their
name stays behind the masking serializer. And ``phone_e164`` is not here either; the profile
row is joined for a handle and a first name, and the column that is deliberately unindexed
in ``user_profiles`` is deliberately unselected here.

**Both reads are bounded and both are computed by the database.** ``limit`` is clamped
against a ceiling in this layer as well as validated at the boundary, so no caller can turn
either list into a full-table read; the ranking, the aggregation and the ordering are all
SQL, and the only Python in either function is constructing the view.

**Erasure is a state on these lists, never a filter.** ``/forget`` nulls
``plan_purchases.telegram_user_id`` and deletes the ``user_profiles`` row outright, so an
erased customer's receipt survives with its identity gone. :func:`recent_subscribers`
RENDERS that row rather than dropping it — a purchase that vanished from the ledger because
somebody exercised a right is a hole in the money record, and the row is the answer to "was
this customer charged for songs they never got?".

**And ``/forget`` does not reach :func:`top_generators` at all, which a reader will assume
it does.** That command anonymises the receipts, deletes the ``user_profiles`` row and keeps
the ``users`` row on purpose (an operator's block must outlast a data-subject request); it
writes nothing to ``orders``, because there is no per-user order erasure — only the
time-based sweep in :mod:`hbd.db.purge`, with ``purge_user`` planned and unwritten
(``ADMIN_PANEL_PLAN`` §9.3). ``orders.telegram_user_id`` is ``NOT NULL`` and is this list's
ranking key, so an erased account keeps ranking, under its real id, with a blank handle and
a blank first name, until its orders age out. That id is the one ``GET /api/users`` already
publishes from the surviving ``users`` row, so this discloses nothing that screen does not —
but it is a state to render honestly and NOT a row this module filters away. The day
``purge_user`` exists, the orders go and the row goes with them; nothing here needs changing.
"""

from __future__ import annotations

from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from hbd.checkout import STUB_PROVIDER_NAME
from hbd.db.admin.page import keyset_order
from hbd.db.admin.sql import TimeWindow, apply_window
from hbd.db.admin.views import RecentSubscriber, TopGenerator
from hbd.db.models.order import OrderRow
from hbd.db.models.plan_purchase import PlanPurchaseRow
from hbd.db.models.user import UserRow
from hbd.db.models.user_profile import UserProfileRow

__all__ = [
    "DEFAULT_TOP_GENERATORS",
    "MAX_TOP_GENERATORS",
    "DEFAULT_RECENT_SUBSCRIBERS",
    "MAX_RECENT_SUBSCRIBERS",
    "top_generators",
    "recent_subscribers",
]

#: How many customers the top-generators card shows without being asked for more. Ten,
#: because the card is a glance and an eleventh row is one nobody reads — and because a
#: longer default would put more identified people on the screen than the question needs,
#: which on an identified surface is a cost and not just clutter.
DEFAULT_TOP_GENERATORS: Final[int] = 10
#: The ceiling a caller-supplied limit is clamped to. Validation belongs at the boundary;
#: this is the backstop behind it, and on this module it is also the thing that stops
#: ``?limit=100000`` from being a bulk export of identified accounts through a card.
MAX_TOP_GENERATORS: Final[int] = 100

#: The same glance, for the subscribers card. "The last ten" is what the caption says.
DEFAULT_RECENT_SUBSCRIBERS: Final[int] = 10
#: The same backstop, for the same reason — see :data:`MAX_TOP_GENERATORS`.
MAX_RECENT_SUBSCRIBERS: Final[int] = 100


async def top_generators(
    session: AsyncSession,
    *,
    window: TimeWindow | None = None,
    limit: int = DEFAULT_TOP_GENERATORS,
) -> tuple[TopGenerator, ...]:
    """The accounts that had the most songs DELIVERED, most first. Identified.

    **The ranking key is deliveries, not orders and not money.** An account that opens
    forty orders and ships three is not at the top of this list; it is a support case, and
    :attr:`~hbd.db.admin.views.TopGenerator.orders_created` is published beside the ranking
    key so the gap between them is visible on the row rather than inferable from another
    screen. Ranking by orders would put exactly that account first, and ranking by money
    would answer a different question — ``plan_purchases`` already answers it, grouped by
    currency and rail because a money ranking cannot be a single scalar.

    **Delivery is ``delivered_at IS NOT NULL``, not ``state = 'delivered'``**, which is the
    spelling ``metrics.delivered_per_bucket`` and ``metrics.delivered_counts`` use and the
    reason is theirs: ``delivered_at`` has exactly one writer — ``repository.set_state``,
    inside ``if state is OrderState.DELIVERED`` — and is never cleared, so the column IS the
    delivery event. A state predicate beside it could not exclude a row the timestamp
    already included and would only cost the heap fetch the index scan avoids. The
    ``IS NOT NULL`` guard is therefore applied only when no window narrows the column,
    because a range predicate already implies it.

    **The window applies to the ORDERS, and specifically to the DELIVERY instant.** Not to
    when the account was created: "top generators of all time" and "top generators this
    week" are different lists, and a caption that names a period is describing songs that
    shipped in it. Windowing on ``delivered_at`` rather than on ``created_at`` is also what
    makes this list reconcile with the "Songs delivered" card standing beside it — that
    card counts on ``delivered_at`` too, so these rows sum into it. A created-at cohort
    would be a second population two hundred pixels away, which is the defect
    ``metrics.delivered_latency`` exists to correct.

    **``orders_created`` is counted over the SAME window**, on ``created_at``, which is a
    deviation from the field's own comment ("every order this account ever created") and is
    deliberate: a lifetime number under a caption that names a week WILL be read as a
    number about that week. Two consequences follow and neither is a bug. The pair is not a
    conversion rate — an order created on Monday and delivered on Tuesday is in both counts,
    one created before the window and delivered inside it is in only the second — so the
    ratio must never be rendered as one. And ``orders_created`` can be ``0`` beside a
    positive delivery count, for an account whose work was all commissioned earlier; that
    zero is a measurement ("created nothing in this period"), not a missing number.

    ``last_delivered_at`` is the ``MAX`` over the same windowed rows, so it is the last
    delivery IN THE PERIOD and, unwindowed, the last one ever. It cannot be ``None`` from
    this read — presence on this list requires a delivery — even though the view types it
    optional for a caller assembling the shape over a wider population.

    ``users`` is joined INNER and ``user_profiles`` OUTER, and the asymmetry is not an
    oversight. ``TopGenerator.ui_language`` and ``.first_seen_at`` are non-optional and both
    come from ``users``; an outer join would hand this read a ``NULL`` it could only resolve
    by inventing a language and a date of first contact. It cannot fire in any case:
    ``orders.user_id`` is a ``FOREIGN KEY … ON DELETE CASCADE`` to ``users``, and the
    ``users`` row is designed to SURVIVE ``/forget`` (``models/user.py`` argues why), so an
    order whose account is gone is an order that is gone too. The profile join is outer
    because that row is precisely what ``/forget`` deletes outright, and because most
    Telegram accounts have no ``@handle`` to begin with — a ``None`` username here is
    "never had one or no longer known", never a failed write.

    INDEX: ``ix_orders_delivered_at`` for the windowed range (a range scan is what that
    index was added in revision 0021 to serve). The grouping itself is served by no index —
    ``ix_orders_telegram_user_id_created_at`` leads with the right column but sorts on the
    wrong second one — so an unwindowed call aggregates the delivered rows of the whole
    table; that is one row per song ever shipped and is fine for years at this product's
    volume. The lookups hanging off the ranked rows are index probes and bounded by
    ``limit``: ``ix_orders_telegram_user_id`` for each account's order count,
    ``uq_users_telegram_user_id`` and ``uq_user_profiles_telegram_user_id`` for the two
    joins.
    """
    bounded = max(1, min(limit, MAX_TOP_GENERATORS))
    delivered = sa.func.count().label("delivered_songs")
    ranking: Select[Any] = sa.select(
        OrderRow.telegram_user_id.label("telegram_user_id"),
        delivered,
        sa.func.max(OrderRow.delivered_at).label("last_delivered_at"),
    )
    if window is None:
        ranking = ranking.where(OrderRow.delivered_at.is_not(None))
    ranking = apply_window(ranking, OrderRow.delivered_at, window)
    # The tie-break is the account id and it is load-bearing rather than tidy: ``ORDER BY
    # delivered DESC`` alone leaves every tied group in whatever order the plan happened to
    # produce, so a card that polls on a timer reshuffles its own rows between ticks and an
    # operator watching it sees movement that is not there.
    top = (
        ranking.group_by(OrderRow.telegram_user_id)
        .order_by(delivered.desc(), OrderRow.telegram_user_id)
        .limit(bounded)
        .subquery()
    )

    # A correlated probe per ranked row — at most ``limit`` of them — rather than a second
    # grouped aggregate joined to this one. The same trade ``orders.py`` records for the
    # ledger columns: a ``GROUP BY`` derived table would aggregate every order in the table
    # before the join could narrow it, and would get slower every month, while this is an
    # index probe on ``ix_orders_telegram_user_id`` ten times.
    created_count: Select[Any] = (
        sa.select(sa.func.count())
        .select_from(OrderRow)
        .where(OrderRow.telegram_user_id == top.c.telegram_user_id)
    )
    created_count = apply_window(created_count, OrderRow.created_at, window)
    orders_created = created_count.correlate(top).scalar_subquery()

    statement: Select[Any] = (
        sa.select(
            top.c.telegram_user_id,
            top.c.delivered_songs,
            top.c.last_delivered_at,
            orders_created.label("orders_created"),
            UserRow.ui_language,
            UserRow.created_at.label("first_seen_at"),
            UserProfileRow.telegram_username,
            UserProfileRow.first_name,
        )
        .select_from(top)
        .join(UserRow, UserRow.telegram_user_id == top.c.telegram_user_id)
        .outerjoin(UserProfileRow, UserProfileRow.telegram_user_id == top.c.telegram_user_id)
        # Restated after the joins: a subquery's ordering is not a promise the enclosing
        # query inherits, on either dialect.
        .order_by(top.c.delivered_songs.desc(), top.c.telegram_user_id)
    )
    rows = (await session.execute(statement)).all()
    return tuple(
        TopGenerator(
            telegram_user_id=int(row.telegram_user_id),
            telegram_username=row.telegram_username,
            first_name=row.first_name,
            delivered_songs=int(row.delivered_songs),
            orders_created=int(row.orders_created),
            ui_language=row.ui_language,
            first_seen_at=row.first_seen_at,
            last_delivered_at=row.last_delivered_at,
        )
        for row in rows
    )


async def recent_subscribers(
    session: AsyncSession, *, limit: int = DEFAULT_RECENT_SUBSCRIBERS
) -> tuple[RecentSubscriber, ...]:
    """The last ``limit`` plans sold, newest first, with the buyer's identity. Identified.

    **This read takes NO window, and the omission is the contract rather than a gap.**
    Everything else on this screen is windowed, so a reader will assume this is too: it is
    not. "The last ten" is a RECENCY list — it answers "who just bought", and it answers it
    identically whether the last sale was an hour ago or in March. A window would turn it
    into a flow, and a flow of plan sales already exists as
    ``plan_purchases.plan_bookings_per_bucket`` (grouped by plan, currency and provider, as
    money must be) and ``plan_revenue_totals``. On a quiet week a windowed version of this
    card would render empty while ten real customers sat one row below the cut-off, which is
    the failure this shape exists to avoid.

    **``is_stub_rail`` travels with every row.** ``StubCheckoutProvider`` stamps
    ``is_paid=True`` having contacted nobody and settled nothing, so a stub sale is
    indistinguishable from a real one on every column except ``provider`` — and a card that
    shows an amount without the rail turns a demo run into revenue on a screen somebody
    makes decisions from. The flag is derived here, once, as ``provider ==
    hbd.checkout.STUB_PROVIDER_NAME``, so no later layer has to know the constant to stay
    honest; the raw ``provider`` is carried beside it because the rail's own name is half of
    what an operator needs to find a charge in somebody else's dashboard. ``currency`` rides
    along for the same family of reasons and these amounts are never summed: a total over
    two currencies is a figure in an invented unit, which is why this function returns rows
    and no total at all.

    **An erased customer's receipt is rendered, not filtered.** ``/forget`` nulls
    ``plan_purchases.telegram_user_id`` and deletes the ``user_profiles`` row, so such a row
    arrives here with all three identity fields ``None`` — and it stays in the list. The
    join is ``LEFT`` and on ``telegram_user_id``, so a ``NULL`` id matches no profile (SQL
    equality never matches ``NULL`` to ``NULL``) and needs no special case. Dropping the row
    would be worse than a blank name: the receipt is the ledger, and a sale that disappears
    from it because somebody exercised a right is money this deployment can no longer
    account for. Render it as an erased customer.

    **An expired plan with songs left is BREAKAGE; a running one is an OBLIGATION.**
    ``songs_included - songs_used`` is the same arithmetic and opposite facts, so
    ``plan_ends_at`` has to be read against the clock before the remainder means anything.
    This read publishes all three columns and computes none of them, because the clock it
    would need is ``now`` and ``now`` is a parameter this function does not take — see
    ``plan_purchases.plan_liability``, which does take it and keeps the two apart as
    ``breakage_songs`` and ``unconsumed_songs``.

    Ordering is ``(created_at DESC, id DESC)`` via
    :func:`~hbd.db.admin.page.keyset_order` — reused rather than respelled even though this
    list is not paged, because it is the same requirement: two plans bought in the same
    millisecond must not swap places between two polls of the card.

    INDEX: ``ix_plan_purchases_created_at`` for the ordering — a backwards scan of ten rows
    and no sort — and ``uq_user_profiles_telegram_user_id`` for the ten profile probes.
    """
    bounded = max(1, min(limit, MAX_RECENT_SUBSCRIBERS))
    statement: Select[Any] = (
        sa.select(
            PlanPurchaseRow.telegram_user_id,
            PlanPurchaseRow.plan,
            PlanPurchaseRow.amount_minor,
            PlanPurchaseRow.currency,
            PlanPurchaseRow.provider,
            PlanPurchaseRow.created_at.label("purchased_at"),
            PlanPurchaseRow.plan_ends_at,
            PlanPurchaseRow.songs_included,
            PlanPurchaseRow.songs_used,
            UserProfileRow.telegram_username,
            UserProfileRow.first_name,
        )
        .select_from(PlanPurchaseRow)
        .outerjoin(
            UserProfileRow,
            UserProfileRow.telegram_user_id == PlanPurchaseRow.telegram_user_id,
        )
        .order_by(*keyset_order(PlanPurchaseRow.created_at, PlanPurchaseRow.id))
        .limit(bounded)
    )
    rows = (await session.execute(statement)).all()
    return tuple(
        RecentSubscriber(
            telegram_user_id=row.telegram_user_id,
            telegram_username=row.telegram_username,
            first_name=row.first_name,
            plan=row.plan,
            amount_minor=int(row.amount_minor),
            currency=row.currency,
            provider=row.provider,
            is_stub_rail=row.provider == STUB_PROVIDER_NAME,
            purchased_at=row.purchased_at,
            plan_ends_at=row.plan_ends_at,
            songs_included=int(row.songs_included),
            songs_used=int(row.songs_used),
        )
        for row in rows
    )
