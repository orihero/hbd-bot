"""``/orders`` — the list, the detail and the derived pipeline timeline.

**This module never calls ``hbd.db.mapping.to_order``, and that is the point.** ``to_order``
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
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from hbd.contracts import OrderState
from hbd.db.admin.attempts import attempt_view
from hbd.db.admin.page import (
    BoundedTotal,
    Cursor,
    Page,
    PageRequest,
    bounded_total,
    build_page,
    keyset_order,
    keyset_predicate,
)
from hbd.db.admin.sql import (
    CHAT_MESSAGES_TABLE,
    PAYMENTS_TABLE,
    TimeWindow,
    apply_in,
    apply_window,
    has_table,
)
from hbd.db.admin.views import (
    AssetView,
    AttemptView,
    BriefView,
    OrderDetail,
    OrderListItem,
    Timeline,
    TimelineEvent,
    TimelineEventKind,
    TimelineSource,
)
from hbd.db.models.asset import AssetRow
from hbd.db.models.brief import BriefRow
from hbd.db.models.generation_attempt import GenerationAttemptRow
from hbd.db.models.order import OrderRow
from hbd.logging import get_logger

__all__ = [
    "OrderFilters",
    "list_orders",
    "count_orders",
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
    correlation_id: str | None = None
    #: Applied to ``orders.created_at``, half-open.
    window: TimeWindow | None = None
    has_assets: bool | None = None


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
    items = [order_list_item(order, brief, asset_count) for order, brief, asset_count in rows]
    return build_page(items, request, _cursor_of)


async def count_orders(session: AsyncSession, *, filters: OrderFilters) -> BoundedTotal:
    """``?withTotal=true`` for the same filter set. Bounded — see :func:`bounded_total`."""
    return await bounded_total(session, _filtered(filters))


async def get_order_detail(session: AsyncSession, order_id: UUID) -> OrderDetail | None:
    """The order, its brief, its assets, its attempts and the timeline they imply.

    ``None`` for an unknown id — the caller answers 404. Four statements rather than one
    join: an order with three greetings and a dozen attempts would otherwise come back as a
    cartesian product that Python has to de-duplicate, which is slower and easier to get
    wrong than four bounded queries.
    """
    row = (await session.execute(_filtered(OrderFilters()).where(OrderRow.id == order_id))).first()
    if row is None:
        return None
    order_row, brief_row, asset_count = row
    assets = await _load_assets(session, order_id)
    attempts = await _load_attempts(session, order_id)
    brief = brief_view(brief_row) if brief_row is not None else None
    return OrderDetail(
        order=order_list_item(order_row, brief_row, asset_count),
        brief=brief,
        assets=assets,
        attempts=attempts,
        timeline=build_timeline(order_row, brief_row, assets, attempts),
    )


# ---------------------------------------------------------------------------
# Row -> view model. Pure, and total over every purge state.
# ---------------------------------------------------------------------------
def order_list_item(order: OrderRow, brief: BriefRow | None, asset_count: int) -> OrderListItem:
    """Build a list row. A missing brief and a purged brief are different answers."""
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
def _filtered(filters: OrderFilters) -> Select[tuple[OrderRow, BriefRow, int]]:
    """The shared ``FROM``/``WHERE`` every orders query starts from, keyset excluded."""
    statement = sa.select(OrderRow, BriefRow, _ASSET_COUNT.label("asset_count")).outerjoin(
        BriefRow, BriefRow.order_id == OrderRow.id
    )
    statement = apply_in(statement, OrderRow.state, filters.states)
    statement = apply_window(statement, OrderRow.created_at, filters.window)
    if filters.is_paid is not None:
        statement = statement.where(OrderRow.is_paid.is_(filters.is_paid))
    if filters.telegram_user_id is not None:
        statement = statement.where(OrderRow.telegram_user_id == filters.telegram_user_id)
    if filters.correlation_id is not None:
        statement = statement.where(OrderRow.correlation_id == filters.correlation_id)
    if filters.has_assets is not None:
        statement = statement.where(_ASSET_COUNT > 0 if filters.has_assets else _ASSET_COUNT == 0)
    return statement


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
