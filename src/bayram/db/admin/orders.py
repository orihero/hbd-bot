"""``/orders`` — the list, the detail and the derived pipeline timeline.

**This module never calls ``bayram.db.mapping.to_order``, and that is the point.** ``to_order``
delegates to ``to_brief`` → ``to_recipient_name``, which raises ``PipelineError`` the moment
``recipient_name_display IS NULL`` (``mapping.py:137-147``). That is the correct behaviour
for the render pipeline and a catastrophe for an operator console: an order older than
ninety days is *supposed* to have a null display name, so ``get_order`` cannot read one at
all, and a list page containing a single purged order would fail whole. Every read here goes
against ``OrderRow`` and ``BriefRow`` directly and models the purge as a state
(``recipient_name_display=None`` with ``identity_purged_at`` set), never as an error.

The brief is joined with an **outer** join for the same family of reasons: a ``DRAFT`` order
can exist before its brief does, and a page must not silently drop the orders it is most
likely to be opened to investigate.

No relationship is ever traversed. Every model in this schema is ``lazy="raise"``, so an
accidental ``order.assets`` would surface as a greenlet error at an unrelated await; the
detail view issues its own explicit queries instead.

**The financial half of a row is three correlated scalar subqueries, not a join.** Credits
live in ``credit_ledger``, which has an ``order_id`` index and deliberately **no** foreign
key to ``orders`` (``models/credit_ledger.py:19-22``: the gate can charge before the order
row exists, and a ledger entry must outlive the order it refers to). A ``GROUP BY`` derived
table joined to the page would look tidier and is the wrong shape on both dialects: neither
planner can push a fifty-row join predicate into a grouped subquery, so it aggregates the
*whole* ledger before the join and gets slower every month. A correlated subquery is an
index probe per row on ``ix_credit_ledger_order_id`` — three of them per row here
(:func:`_ledger_scalar`'s three: the net, the refunds and the settlements), plus the asset
count that was already there and the attempt count, which is five probes per row and one
statement for the page. That is the cost, stated so the next person weighing a sixth
aggregate knows what they are adding to.

**One thing genuinely cannot be a subquery, and it is the interesting one.** The dark-switch
top-up ``credits._cover_the_shortfall`` writes carries no ``order_id`` column on purpose —
that column is what ``net_position`` sums, and a grant hanging off the order would net it to
zero and make every comped render read as unpaid — so the only link back to the render is
its idempotency key, ``unenforced:{order}:{generation}``. Matching that from SQL would mean
``CAST(orders.id AS VARCHAR)``, and the two dialects do not agree on what that produces:
SQLAlchemy's ``Uuid`` stores 32 undashed hex characters on SQLite and a native dashed
``uuid`` on Postgres, so a prefix built in SQL would match in production and silently never
match in the test suite. :func:`_unenforced_orders` therefore builds its patterns in Python
from :func:`bayram.db.credits.unenforced_key_prefix` and asks once per page — one extra round
trip, in the idiom ``db/admin/users.py`` already uses for its rollups, rather than fifty.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, Select

from bayram.contracts import OrderState
from bayram.db.admin.attempts import attempt_view
from bayram.db.admin.page import (
    BoundedTotal,
    Cursor,
    Page,
    PageRequest,
    bounded_total,
    build_page,
    keyset_order,
    keyset_predicate,
)
from bayram.db.admin.sql import (
    CHAT_MESSAGES_TABLE,
    LIKE_ESCAPE_CHAR,
    PAYMENTS_TABLE,
    TimeWindow,
    apply_in,
    apply_window,
    count_where,
    escape_like,
    has_table,
    search_clause,
)
from bayram.db.admin.views import (
    AssetView,
    AttemptView,
    BriefView,
    OrderDetail,
    OrderLedger,
    OrderListItem,
    OrderStateTotal,
    Timeline,
    TimelineEvent,
    TimelineEventKind,
    TimelineSource,
)
from bayram.db.credits import unenforced_key_prefix
from bayram.db.enums import CreditEntryKind
from bayram.db.models.asset import AssetRow
from bayram.db.models.brief import BriefRow
from bayram.db.models.credit_ledger import CreditLedgerRow
from bayram.db.models.generation_attempt import GenerationAttemptRow
from bayram.db.models.order import OrderRow
from bayram.logging import get_logger

__all__ = [
    "OrderFilters",
    "list_orders",
    "count_orders",
    "count_orders_by_state",
    "get_order_detail",
    "order_list_item",
    "brief_view",
    "asset_view",
]

_log = get_logger(__name__)

#: A correlated ``COUNT`` rather than a join, so grouping never changes the page's row count
#: and ``hasAssets`` becomes a predicate on the same expression the column already reports.
_ASSET_COUNT: Final[sa.ScalarSelect[int]] = (
    sa.select(sa.func.count())
    .select_from(AssetRow)
    .where(AssetRow.order_id == OrderRow.id)
    .correlate(OrderRow)
    .scalar_subquery()
)

#: Rows in ``generation_attempts`` for this order — the ``retryCount`` the audit plan asks
#: for, and a number that means less than its name. See :attr:`OrderListItem.attempt_count`.
_ATTEMPT_COUNT: Final[sa.ScalarSelect[int]] = (
    sa.select(sa.func.count())
    .select_from(GenerationAttemptRow)
    .where(GenerationAttemptRow.order_id == OrderRow.id)
    .correlate(OrderRow)
    .scalar_subquery()
)


def _ledger_scalar(expression: sa.ColumnElement[int]) -> sa.ScalarSelect[int]:
    """``expression`` aggregated over exactly this order's ledger rows, correlated.

    Three of these rather than one, because a scalar subquery returns one value and the
    status algebra needs three independent ones. They share this builder so the correlation
    and the ``order_id`` predicate cannot drift between them — a subquery that forgot to
    correlate would aggregate the whole table and report every order's cost as the deployment's.
    """
    return (
        sa.select(expression)
        .select_from(CreditLedgerRow)
        .where(CreditLedgerRow.order_id == OrderRow.id)
        .correlate(OrderRow)
        .scalar_subquery()
    )


#: ``SUM(delta)`` — the exact expression ``credit_sql.net_position`` gives the authorisation
#: gate. ``COALESCE`` because ``SUM`` over no rows is ``NULL`` and an unmetered order must
#: read as 0, not as "unknown".
_CREDIT_NET: Final[sa.ScalarSelect[int]] = _ledger_scalar(
    sa.func.coalesce(sa.func.sum(CreditLedgerRow.delta), 0)
)
#: Refunds and settlements, counted separately. :func:`~bayram.db.admin.sql.count_where` rather
#: than a ``SUM(CASE …)``, so an order with neither reads ``0`` without a ``COALESCE``.
_REFUND_COUNT: Final[sa.ScalarSelect[int]] = _ledger_scalar(
    count_where(CreditLedgerRow.kind == CreditEntryKind.REFUND)
)
_CONSUME_COUNT: Final[sa.ScalarSelect[int]] = _ledger_scalar(
    count_where(CreditLedgerRow.kind == CreditEntryKind.CONSUME)
)

#: What ``?q=`` may substring-match, and the boundary is a privacy decision rather than a
#: convenience one. Both columns are printed **in full, unmasked, in every row of the same
#: response** — ``OrderView.correlationId`` and ``OrderView.telegramUserId`` — so matching a
#: substring of either discloses nothing the caller was not already handed.
#:
#: ``briefs.recipient_name_display`` is deliberately absent and the audit plan's §5.1 request
#: for "fuzzy substring search over … recipient names" is deliberately refused. That column
#: is ``M`` at all four roles in §12.3 and its plaintext is reachable only through ``POST
#: /reveal`` — step-up, reason code, audit row, record budget. A ``LIKE '%…%'`` an operator
#: steers would recover the same plaintext three characters at a time from a list endpoint
#: that charges none of those, which is a reveal bypass wearing a search box. It would also
#: return a shrinking answer set for the same input as the 90-day identity sweep runs, so
#: even an entitled operator would read it as data loss. ``db/admin/users.py``'s
#: ``_SEARCHABLE_COLUMNS`` refuses the same class of column for the same reason.
#:
#: The order id is not here either, and its absence is a portability decision, not a privacy
#: one: see :func:`_matches_order_id`, which handles a whole id exactly instead.
_SEARCHABLE_COLUMNS: Final[tuple[sa.SQLColumnExpression[str], ...]] = (
    OrderRow.correlation_id,
    sa.cast(OrderRow.telegram_user_id, sa.String),
)


#: Causal precedence for two events that share an instant. Taken from the declaration order
#: of ``TimelineEventKind`` so the tie-break is the order a reader already sees, not an
#: alphabetical accident that would put "brief_recorded" before "order_created".
_KIND_ORDER: Final[dict[TimelineEventKind, int]] = {
    kind: index for index, kind in enumerate(TimelineEventKind)
}


@dataclass(frozen=True, slots=True)
class OrderFilters:
    """§6.5's filter set. Repeated values are OR within a field, AND across fields."""

    states: tuple[OrderState, ...] = ()
    is_paid: bool | None = None
    telegram_user_id: int | None = None
    #: Exact match on the whole correlation id, and it stays exact. :attr:`search` is a
    #: separate field rather than a widening of this one because the two are asked in
    #: different situations — an id copied out of a log line is exact, a fragment read off a
    #: screenshot is not — and because an exact filter that silently became a substring match
    #: would change what every existing caller's page means.
    correlation_id: str | None = None
    #: Applied to ``orders.created_at``, half-open.
    window: TimeWindow | None = None
    has_assets: bool | None = None
    #: §6.5's ``q``. Substring over :data:`_SEARCHABLE_COLUMNS`, plus an exact match when the
    #: text is a whole order id (:func:`_matches_order_id`). Blank or ``None`` means no
    #: filter, never an empty page.
    search: str | None = None


async def list_orders(
    session: AsyncSession, *, filters: OrderFilters, request: PageRequest
) -> Page[OrderListItem]:
    """One keyset page of orders, newest first, purge-aware."""
    statement = _filtered(filters)
    resume = keyset_predicate(OrderRow.created_at, OrderRow.id, request.cursor)
    if resume is not None:
        statement = statement.where(resume)
    statement = statement.order_by(*keyset_order(OrderRow.created_at, OrderRow.id)).limit(
        request.fetch_limit
    )
    rows = (await session.execute(statement)).all()
    comped = await _unenforced_orders(session, tuple(row[0].id for row in rows))
    items = [
        order_list_item(
            order,
            brief,
            asset_count=asset_count,
            attempt_count=attempt_count,
            ledger=OrderLedger(
                net=net,
                refund_count=refunds,
                consume_count=consumes,
                is_unenforced=order.id in comped,
            ),
        )
        for order, brief, asset_count, attempt_count, net, refunds, consumes in rows
    ]
    return build_page(items, request, _cursor_of)


async def count_orders(session: AsyncSession, *, filters: OrderFilters) -> BoundedTotal:
    """``?withTotal=true`` for the same filter set. Bounded — see :func:`bounded_total`."""
    return await bounded_total(session, _filtered(filters))


async def count_orders_by_state(
    session: AsyncSession, *, filters: OrderFilters
) -> tuple[OrderStateTotal, ...]:
    """Per-state totals over the WHOLE filter set, zero-filled, in enum order.

    **This is not a page statistic and it is not bounded.** The Orders hub's distribution bar
    used to be computed in the browser from the fifty rows it had, which told an operator that
    the system was 40% ``FAILED`` when the fifty newest orders were and the other eleven
    thousand were not. Answering that honestly means one ``GROUP BY`` over every row the
    filters match, and there is no version of this that is both cheap and true:
    :func:`~bayram.db.admin.page.bounded_total`'s ``LIMIT`` trick cannot be borrowed here,
    because an arbitrary ten thousand rows have an arbitrary distribution and a bar drawn
    from them would be a *differently* wrong bar with no way to see that it was.

    So the cost is real and is paid deliberately: an index-only scan of
    ``ix_orders_state_created_at`` when a window narrows it, a full one when nothing does.
    What keeps that acceptable is **where it is called from** — a sibling route rather than
    ``meta`` on the list — so it runs once when the operator changes a filter and never when
    they merely turn a page. See ``routers/orders.py`` for that argument in full.

    Zero-filled over every :class:`~bayram.contracts.OrderState` in declaration order, so the
    bar's segments and their order do not depend on which states happen to have rows: a
    segment that appears from nowhere as data arrives is a bar that re-lays-out under the
    operator's cursor. :class:`~bayram.db.admin.views.OrderStateTotal` argues why this is the
    opposite contract to ``UserDetail.orders_by_state`` and therefore a separate type.
    """
    statement = (
        _filtered(filters)
        .with_only_columns(
            OrderRow.state, sa.func.count().label("total"), maintain_column_froms=True
        )
        .group_by(OrderRow.state)
    )
    counted = {state: int(total) for state, total in (await session.execute(statement)).all()}
    return tuple(OrderStateTotal(state=state, count=counted.get(state, 0)) for state in OrderState)


async def get_order_detail(session: AsyncSession, order_id: UUID) -> OrderDetail | None:
    """The order, its brief, its assets, its attempts and the timeline they imply.

    ``None`` for an unknown id — the caller answers 404. Five statements rather than one
    join: an order with three greetings and a dozen attempts would otherwise come back as a
    cartesian product that Python has to de-duplicate, which is slower and easier to get
    wrong than five bounded queries. The fifth is :func:`_unenforced_orders`, which is a
    separate round trip here for the reason the module docstring gives — its rows are found
    by idempotency key, and a key built in SQL would not survive the dialect gap.
    """
    row = (await session.execute(_filtered(OrderFilters()).where(OrderRow.id == order_id))).first()
    if row is None:
        return None
    order_row, brief_row, asset_count, attempt_count, net, refunds, consumes = row
    comped = await _unenforced_orders(session, (order_id,))
    assets = await _load_assets(session, order_id)
    attempts = await _load_attempts(session, order_id)
    brief = brief_view(brief_row) if brief_row is not None else None
    return OrderDetail(
        order=order_list_item(
            order_row,
            brief_row,
            asset_count=asset_count,
            attempt_count=attempt_count,
            ledger=OrderLedger(
                net=net,
                refund_count=refunds,
                consume_count=consumes,
                is_unenforced=order_id in comped,
            ),
        ),
        brief=brief,
        assets=assets,
        attempts=attempts,
        timeline=build_timeline(order_row, brief_row, assets, attempts),
    )


# ---------------------------------------------------------------------------
# Row -> view model. Pure, and total over every purge state.
# ---------------------------------------------------------------------------
def order_list_item(
    order: OrderRow,
    brief: BriefRow | None,
    *,
    asset_count: int,
    attempt_count: int,
    ledger: OrderLedger,
) -> OrderListItem:
    """Build a list row. A missing brief and a purged brief are different answers.

    The three counts are keyword-only because they are three bare integers of the same type:
    positionally, transposing the asset count and the attempt count is a silent bug that
    every type checker and every test with equal fixtures would wave through.
    """
    return OrderListItem(
        id=order.id,
        telegram_user_id=order.telegram_user_id,
        state=order.state,
        is_paid=order.is_paid,
        correlation_id=order.correlation_id,
        created_at=order.created_at,
        updated_at=order.updated_at,
        delivered_at=order.delivered_at,
        failed_reason=order.failed_reason,
        is_brief_present=brief is not None,
        recipient_name_display=brief.recipient_name_display if brief else None,
        identity_purged_at=brief.identity_purged_at if brief else None,
        note_purged_at=brief.note_purged_at if brief else None,
        occasion=brief.occasion if brief else None,
        genre=brief.genre if brief else None,
        output_language=brief.output_language if brief else None,
        asset_count=asset_count,
        ledger=ledger,
        attempt_count=attempt_count,
    )


def brief_view(brief: BriefRow) -> BriefView:
    """Build the brief view. Free text becomes a length; the name itself is kept for masking."""
    return BriefView(
        id=brief.id,
        occasion=brief.occasion,
        genre=brief.genre,
        vocal_gender=brief.vocal_gender,
        ui_language=brief.ui_language,
        output_language=brief.output_language,
        event_day=brief.event_day,
        event_month=brief.event_month,
        recipient_name_display=brief.recipient_name_display,
        recipient_script=brief.recipient_script,
        recipient_language=brief.recipient_language,
        candidate_count=_candidate_count(brief),
        identity_expires_at=brief.identity_expires_at,
        identity_purged_at=brief.identity_purged_at,
        note_chars=len(brief.note) if brief.note is not None else None,
        has_approved_lyrics=brief.approved_lyrics is not None,
        note_expires_at=brief.note_expires_at,
        note_purged_at=brief.note_purged_at,
    )


def asset_view(asset: AssetRow) -> AssetView:
    """Build the asset view. Metadata only — ``payload`` (the lyric sheet) never crosses."""
    return AssetView(
        id=asset.id,
        order_id=asset.order_id,
        kind=asset.kind,
        variant_index=asset.variant_index,
        mime=asset.mime,
        size_bytes=asset.size_bytes,
        duration_s=asset.duration_s,
        sha256=asset.sha256,
        loudness_lufs=asset.loudness_lufs,
        persona_id=asset.persona_id,
        storage_key=asset.storage_key,
        has_telegram_file_id=asset.tg_file_id is not None,
        name_candidate_strategy=asset.name_candidate_strategy,
        name_candidate_rank=asset.name_candidate_rank,
        retention_class=asset.retention_class,
        expires_at=asset.expires_at,
        created_at=asset.created_at,
    )


def build_timeline(
    order: OrderRow,
    brief: BriefRow | None,
    assets: Sequence[AssetView],
    attempts: Sequence[AttemptView],
) -> Timeline:
    """Merge everything this deployment can date into one ordered list.

    Every ``ORDER`` event is flagged ``is_inferred`` because there is no order-event table:
    ``orders`` carries only ``created_at``, ``updated_at``, ``delivered_at`` and the current
    ``state``, so "reached GENERATING at 12:04" is not a fact this schema holds. Saying so on
    the wire is what stops an operator reading a mutable ``updated_at`` as a transition.
    """
    events = [
        TimelineEvent(
            at=order.created_at,
            kind=TimelineEventKind.ORDER_CREATED,
            source=TimelineSource.ORDER,
            is_inferred=False,
            label=str(order.state) if order.state is OrderState.DRAFT else None,
            reference_id=order.id,
        ),
        *_brief_events(brief),
        *_attempt_events(attempts),
        *_asset_events(assets),
        *_order_outcome_events(order),
    ]
    return Timeline(
        events=tuple(sorted(events, key=lambda event: (event.at, _KIND_ORDER[event.kind]))),
        available_sources=(TimelineSource.ORDER, TimelineSource.ATTEMPTS, TimelineSource.ASSETS),
        unavailable_sources=_unavailable_sources(),
    )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _filtered(filters: OrderFilters) -> Select[tuple[OrderRow, BriefRow, int, int, int, int, int]]:
    """The shared ``FROM``/``WHERE`` every orders query starts from, keyset excluded.

    The financial columns ride in the ``SELECT`` list rather than the ``WHERE``, which is why
    ``count_orders`` does not pay for any of them: ``bounded_total`` replaces the column list
    with ``literal(1)`` and every correlated subquery goes with it.
    :func:`count_orders_by_state` does the same. The search predicate, by contrast, is a
    ``WHERE`` clause and therefore narrows all three — which it must, or ``?withTotal=true``
    and the per-state bar would both label a two-row page with the unfiltered count.
    """
    statement = sa.select(
        OrderRow,
        BriefRow,
        _ASSET_COUNT.label("asset_count"),
        _ATTEMPT_COUNT.label("attempt_count"),
        _CREDIT_NET.label("credit_net"),
        _REFUND_COUNT.label("refund_count"),
        _CONSUME_COUNT.label("consume_count"),
    ).outerjoin(BriefRow, BriefRow.order_id == OrderRow.id)
    statement = apply_in(statement, OrderRow.state, filters.states)
    statement = apply_window(statement, OrderRow.created_at, filters.window)
    search = _search_predicate(filters.search)
    if search is not None:
        statement = statement.where(search)
    if filters.is_paid is not None:
        statement = statement.where(OrderRow.is_paid.is_(filters.is_paid))
    if filters.telegram_user_id is not None:
        statement = statement.where(OrderRow.telegram_user_id == filters.telegram_user_id)
    if filters.correlation_id is not None:
        statement = statement.where(OrderRow.correlation_id == filters.correlation_id)
    if filters.has_assets is not None:
        statement = statement.where(_ASSET_COUNT > 0 if filters.has_assets else _ASSET_COUNT == 0)
    return statement


def _search_predicate(text: str | None) -> ColumnElement[bool] | None:
    """``?q=`` as a substring over the safe columns, widened to an exact whole-order-id match.

    Not :func:`~bayram.db.admin.sql.apply_search` alone, because ``orders.id`` cannot be in
    :data:`_SEARCHABLE_COLUMNS`: matching a substring of a UUID needs ``CAST(id AS VARCHAR)``,
    and SQLAlchemy's ``Uuid`` renders 32 undashed hex characters on SQLite against a native
    dashed value on Postgres — so ``q=0a5d-4f61`` would match in production and never in a
    test, which is the worst possible place for a dialect difference to live. A whole id is
    matched exactly instead: it needs no cast, it is served by the primary key rather than by
    a scan, and "a fragment of an order id is not searchable, a whole one is" is a rule an
    operator can hold in their head. Everything else — the escaping, the length cap, the
    blank-means-no-filter asymmetry — is :func:`~bayram.db.admin.sql.search_clause`'s.
    """
    substring = search_clause(text, _SEARCHABLE_COLUMNS)
    if text is None or substring is None:
        # ``search_clause`` has already decided that an absent or blank ``q`` means NO FILTER
        # rather than an empty page, and neither an absent nor a blank value parses as a UUID,
        # so there is nothing the exact arm below could add to that answer.
        return None
    exact = _matches_order_id(text)
    return substring if exact is None else sa.or_(substring, exact)


def _matches_order_id(text: str) -> ColumnElement[bool] | None:
    """``orders.id = q`` when ``q`` parses as a UUID, and ``None`` when it does not.

    ``UUID()`` is deliberately the parser rather than a regex: it accepts the dashed form, the
    bare hex form and the URN form, which is exactly the set of spellings an operator can end
    up with after copying an id out of a log line, a URL or a JSON body.
    """
    try:
        parsed = UUID(text.strip())
    except ValueError:
        return None
    return OrderRow.id == parsed


async def _unenforced_orders(session: AsyncSession, order_ids: Sequence[UUID]) -> frozenset[UUID]:
    """Which of ``order_ids`` had their render comped by the dark switch. One statement.

    The predicate is an OR of prefix ``LIKE``s built in Python — one per order on the page —
    rather than a correlated subquery, because the link between a top-up grant and its render
    lives in the idempotency key and a key assembled in SQL would not survive the UUID
    dialect gap (module docstring). A prefix pattern has no leading wildcard, so each arm is
    an index range scan on ``credit_ledger.idempotency_key``'s unique index rather than the
    table scan a ``%…%`` would force; Postgres plans the set as one bitmap OR.

    The keys are escaped through :func:`~bayram.db.admin.sql.escape_like` even though a UUID
    contains no ``LIKE`` metacharacter. That is not defensive noise: it is the one line that
    keeps this correct if the key shape ever gains a segment that does, and it costs a
    ``str.replace`` over 48 characters.

    Returns a set rather than a mapping because the caller asks one boolean question per
    order; the empty tuple short-circuits so that an empty page issues no statement at all.
    """
    if not order_ids:
        return frozenset()
    patterns = [
        CreditLedgerRow.idempotency_key.like(
            f"{escape_like(unenforced_key_prefix(order_id))}%", escape=LIKE_ESCAPE_CHAR
        )
        for order_id in order_ids
    ]
    statement = sa.select(CreditLedgerRow.idempotency_key).where(sa.or_(*patterns))
    keys = (await session.execute(statement)).scalars().all()
    # Back to prefixes by dropping the generation, which the prefix's own contract puts after
    # its final colon — a set intersection rather than a prefix comparison per (order, key)
    # pair, so a two-hundred-row page stays linear.
    matched = {key.rsplit(":", 1)[0] + ":" for key in keys}
    return frozenset(
        order_id for order_id in order_ids if unenforced_key_prefix(order_id) in matched
    )


def _cursor_of(item: OrderListItem) -> Cursor:
    return Cursor(at=item.created_at, id=item.id)


async def _load_assets(session: AsyncSession, order_id: UUID) -> tuple[AssetView, ...]:
    rows = (
        (
            await session.execute(
                sa.select(AssetRow)
                .where(AssetRow.order_id == order_id)
                .order_by(AssetRow.kind, AssetRow.variant_index)
            )
        )
        .scalars()
        .all()
    )
    return tuple(asset_view(row) for row in rows)


async def _load_attempts(session: AsyncSession, order_id: UUID) -> tuple[AttemptView, ...]:
    rows = (
        (
            await session.execute(
                sa.select(GenerationAttemptRow)
                .where(GenerationAttemptRow.order_id == order_id)
                .order_by(GenerationAttemptRow.created_at, GenerationAttemptRow.attempt)
            )
        )
        .scalars()
        .all()
    )
    return tuple(attempt_view(row) for row in rows)


def _candidate_count(brief: BriefRow) -> int:
    """How many ranked orthographies the JSON column holds.

    ``recipient_candidates`` is a stored JSON column — external data written by an older
    version of this code — so it is read tolerantly here rather than validated through
    ``mapping.candidates_from_json``, which raises. This module exists precisely so an
    operator can look at a damaged or purged row; failing the page would defeat that. The
    anomaly is logged rather than swallowed.
    """
    # Deliberately widened to ``object``. The mapped annotation says ``list | None``, but that
    # is a claim about what the WRITER intended, not about what the column holds — the value
    # was serialised by an older revision and is external data on the way back in.
    raw: object = brief.recipient_candidates
    if raw is None:
        return 0
    if not isinstance(raw, list):
        _log.warning(
            "brief has a non-list candidates column",
            extra={"brief_id": str(brief.id), "stored_type": type(raw).__name__},
        )
        return 0
    return len(raw)


def _brief_events(brief: BriefRow | None) -> tuple[TimelineEvent, ...]:
    if brief is None:
        return ()
    return (
        TimelineEvent(
            at=brief.created_at,
            kind=TimelineEventKind.BRIEF_RECORDED,
            source=TimelineSource.ORDER,
            is_inferred=False,
            label=str(brief.occasion),
            reference_id=brief.id,
        ),
    )


def _attempt_events(attempts: Sequence[AttemptView]) -> tuple[TimelineEvent, ...]:
    return tuple(
        TimelineEvent(
            at=attempt.created_at,
            kind=(
                TimelineEventKind.ATTEMPT_SUCCEEDED
                if attempt.is_success
                else TimelineEventKind.ATTEMPT_FAILED
            ),
            source=TimelineSource.ATTEMPTS,
            is_inferred=False,
            # Closed vocabulary only: an enum value, a vendor name or our own error code.
            label=attempt.error_code or attempt.provider or str(attempt.kind),
            reference_id=attempt.id,
        )
        for attempt in attempts
    )


def _asset_events(assets: Sequence[AssetView]) -> tuple[TimelineEvent, ...]:
    return tuple(
        TimelineEvent(
            at=asset.created_at,
            kind=TimelineEventKind.ASSET_STORED,
            source=TimelineSource.ASSETS,
            is_inferred=False,
            label=str(asset.kind),
            reference_id=asset.id,
        )
        for asset in assets
    )


def _order_outcome_events(order: OrderRow) -> tuple[TimelineEvent, ...]:
    """Delivery, failure and the last touch — all read off mutable columns, so all inferred."""
    events: list[TimelineEvent] = []
    if order.delivered_at is not None:
        events.append(
            TimelineEvent(
                at=order.delivered_at,
                kind=TimelineEventKind.ORDER_DELIVERED,
                source=TimelineSource.ORDER,
                is_inferred=True,
                label=None,
                reference_id=order.id,
            )
        )
    if order.state is OrderState.FAILED:
        events.append(
            TimelineEvent(
                at=order.updated_at,
                kind=TimelineEventKind.ORDER_FAILED,
                source=TimelineSource.ORDER,
                is_inferred=True,
                label=order.failed_reason,
                reference_id=order.id,
            )
        )
        return tuple(events)
    # A last touch that coincides with delivery is the delivery, not a second event.
    if order.updated_at > order.created_at and order.updated_at != order.delivered_at:
        events.append(
            TimelineEvent(
                at=order.updated_at,
                kind=TimelineEventKind.ORDER_LAST_TOUCHED,
                source=TimelineSource.ORDER,
                is_inferred=True,
                label=str(order.state),
                reference_id=order.id,
            )
        )
    return tuple(events)


def _unavailable_sources() -> tuple[TimelineSource, ...]:
    """Sources the SPA must render as "not enabled here" rather than as "nothing happened"."""
    missing: list[TimelineSource] = []
    if not has_table(CHAT_MESSAGES_TABLE):
        missing.append(TimelineSource.CHAT)
    if not has_table(PAYMENTS_TABLE):
        missing.append(TimelineSource.PAYMENTS)
    # The audit log records what OPERATORS did; it is never a source of order events, so it
    # is always absent from an order timeline regardless of whether the table exists.
    missing.append(TimelineSource.AUDIT)
    return tuple(missing)
