"""``/assets`` — the delivered-file explorer, as metadata and never as bytes.

Two things this module deliberately does not do.

**It does not read the filesystem.** §6.7 asks ``/assets/{id}`` for ``isFilePresent``, and
answering that means stat-ing the mounted volume once per row. The ``Storage`` seam of §12.7
now exists — ``bayram.admin.services.assets`` streams through it — but this layer still does not
use it, and that is a decision rather than a leftover: a list page that stats one file per
row puts the volume behind every page load, and the flag is only honest for as long as it
takes to render. This layer reports what the *row* knows and nothing else, because a presence
flag derived from a column would be a claim about a file nobody looked at. What the row does
know is
:attr:`~bayram.db.admin.views.AssetView.storage_key`, and its absence is the operationally
load-bearing fact: the retention sweep cannot delete archived bytes it has no key for
(``purge.py:194`` filters ``if key``), so an asset with no key is one whose file outlives
its row. The panel surfaces that rather than hiding it behind a green tick.

**It does not carry ``payload``.** That column holds the lyric sheet — the whole song, in
the customer's own words when they pasted their own lyric — and §6.7 routes free text
through ``POST /reveal`` alone. ``asset_view`` (shared with ``bayram.db.admin.orders``, so
there is exactly one projection of an ``AssetRow`` in the codebase) drops it.

``expiring_within_days`` is the filter the retention screen is built on, and it is a
half-open window ending at ``now + days`` with **no lower bound**: an asset already past its
expiry has not been swept yet and is the most urgent row on the page, so excluding it would
hide precisely the backlog the filter exists to show.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from bayram.contracts import AssetKind
from bayram.db.admin.orders import asset_view
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
from bayram.db.admin.sql import TimeWindow, apply_in, apply_window
from bayram.db.admin.views import AssetView
from bayram.db.models.asset import AssetRow
from bayram.db.retention import RetentionClass

__all__ = [
    "AssetFilters",
    "MAX_EXPIRING_WITHIN_DAYS",
    "list_assets",
    "count_assets",
    "get_asset",
]

#: A year. Past this the filter selects the whole table, and a filter that selects
#: everything is one an operator believes narrowed something.
MAX_EXPIRING_WITHIN_DAYS: int = 365


@dataclass(frozen=True, slots=True)
class AssetFilters:
    """§6.7's filter set. Repeated values are OR within a field, AND across fields."""

    kinds: tuple[AssetKind, ...] = ()
    retention_classes: tuple[RetentionClass, ...] = ()
    order_id: UUID | None = None
    #: Rows whose ``expires_at`` falls at or before ``now + days``, including rows already
    #: past it. Requires ``now`` — a module-level clock read here would make the filter
    #: untestable and the boundary of the window a function of import time.
    expiring_within_days: int | None = None
    #: Applied to ``assets.created_at``, half-open.
    window: TimeWindow | None = None


async def list_assets(
    session: AsyncSession, *, filters: AssetFilters, request: PageRequest, now: datetime
) -> Page[AssetView]:
    """One keyset page of assets, newest first."""
    statement = _filtered(filters, now=now)
    resume = keyset_predicate(AssetRow.created_at, AssetRow.id, request.cursor)
    if resume is not None:
        statement = statement.where(resume)
    statement = statement.order_by(*keyset_order(AssetRow.created_at, AssetRow.id)).limit(
        request.fetch_limit
    )
    rows = (await session.execute(statement)).scalars().all()
    return build_page([asset_view(row) for row in rows], request, _cursor_of)


async def count_assets(
    session: AsyncSession, *, filters: AssetFilters, now: datetime
) -> BoundedTotal:
    """``?withTotal=true`` for the same filter set."""
    return await bounded_total(session, _filtered(filters, now=now))


async def get_asset(session: AsyncSession, asset_id: UUID) -> AssetView | None:
    """One asset by id, or ``None`` — the caller answers 404."""
    row = await session.get(AssetRow, asset_id)
    return None if row is None else asset_view(row)


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _filtered(filters: AssetFilters, *, now: datetime) -> Select[tuple[AssetRow]]:
    statement = sa.select(AssetRow)
    statement = apply_in(statement, AssetRow.kind, filters.kinds)
    statement = apply_in(statement, AssetRow.retention_class, filters.retention_classes)
    statement = apply_window(statement, AssetRow.created_at, filters.window)
    if filters.order_id is not None:
        statement = statement.where(AssetRow.order_id == filters.order_id)
    if filters.expiring_within_days is not None:
        horizon = now + timedelta(days=filters.expiring_within_days)
        statement = statement.where(AssetRow.expires_at <= horizon)
    return statement


def _cursor_of(item: AssetView) -> Cursor:
    return Cursor(at=item.created_at, id=item.id)
