"""``/users`` — the list and the detail, named for what the data can actually prove.

**There is no "last seen" here, because there is no last seen in this database.** ``users``
has exactly one writer, ``repository._ensure_user``, and exactly one call site for it,
``_create_order`` (``repository.py:130``). Two consequences follow, and both are surfaced
rather than papered over:

* ``users.last_seen_at`` advances when an order is **created** and at no other moment. A
  column header reading "last seen" would tell an operator that someone opened the bot this
  morning when in fact they last *ordered* in March. This module reports
  :attr:`~hbd.db.admin.views.UserListItem.last_order_at`, derived from
  ``MAX(orders.created_at)`` so it stays true no matter what a later writer does to the
  column, and the panel's header reads "last order" until Phase 3's inbound middleware gives
  the column a real writer.
* **A person who walks the whole wizard and never confirms has no row at all.** They cannot
  be listed, cannot be blocked, and are not missing by accident — the ``users`` row is born
  with the first order. Anything the panel wants to say about pre-order behaviour needs
  Phase 3's chat capture, not a query here.

The per-user aggregates are one grouped query over the orders of the page's users, not one
query per row: a fifty-row page must be two round trips, never fifty-one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from hbd.contracts import Language, OrderState
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
from hbd.db.admin.sql import TimeWindow, apply_window, count_where
from hbd.db.admin.views import UserDetail, UserListItem
from hbd.db.models.order import OrderRow
from hbd.db.models.user import UserRow

__all__ = ["UserFilters", "OrderRollup", "list_users", "count_users", "get_user_detail"]

#: States that mean the customer paid, mirroring ``repository._PAID_STATES``. Restated rather
#: than imported because it is private there, and a read model must not make a private
#: constant public by using it.
_PAID_STATES: tuple[OrderState, ...] = (
    OrderState.AUTHORIZED,
    OrderState.GENERATING,
    OrderState.DELIVERED,
)


@dataclass(frozen=True, slots=True)
class UserFilters:
    """§6.6's filter set."""

    #: Exact ``telegram_user_id``. Deliberately not a name search: names live in ``briefs``
    #: and are purged on their own clock, so a name query would return a shrinking answer
    #: set for the same input and read as data loss.
    telegram_user_id: int | None = None
    is_blocked: bool | None = None
    ui_languages: tuple[Language, ...] = ()
    #: Applied to ``users.created_at`` — that is, when the person's FIRST order was created.
    window: TimeWindow | None = None


@dataclass(frozen=True, slots=True)
class OrderRollup:
    """One user's order aggregates, as the database returns them."""

    order_count: int
    paid_order_count: int
    first_order_at: datetime | None
    last_order_at: datetime | None


async def list_users(
    session: AsyncSession, *, filters: UserFilters, request: PageRequest
) -> Page[UserListItem]:
    """One keyset page of users, newest account first, with their order rollups."""
    statement = _filtered(filters)
    resume = keyset_predicate(UserRow.created_at, UserRow.id, request.cursor)
    if resume is not None:
        statement = statement.where(resume)
    statement = statement.order_by(*keyset_order(UserRow.created_at, UserRow.id)).limit(
        request.fetch_limit
    )
    rows = (await session.execute(statement)).scalars().all()
    rollups = await _rollups(session, tuple(row.telegram_user_id for row in rows))
    items = [_list_item(row, rollups.get(row.telegram_user_id)) for row in rows]
    return build_page(items, request, _cursor_of)


async def count_users(session: AsyncSession, *, filters: UserFilters) -> BoundedTotal:
    """``?withTotal=true`` for the same filter set."""
    return await bounded_total(session, _filtered(filters))


async def get_user_detail(session: AsyncSession, telegram_user_id: int) -> UserDetail | None:
    """One user plus their per-state order breakdown, or ``None`` when they have no row.

    ``None`` is the honest answer for someone who has chatted but never confirmed an order:
    they exist to Telegram and not to this database. The caller answers 404 and the panel
    says so, rather than inventing an empty profile that implies we hold nothing on them.
    """
    row = (
        await session.execute(
            sa.select(UserRow).where(UserRow.telegram_user_id == telegram_user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    rollups = await _rollups(session, (telegram_user_id,))
    by_state = await _orders_by_state(session, telegram_user_id)
    counts = dict(by_state)
    return UserDetail(
        user=_list_item(row, rollups.get(telegram_user_id)),
        orders_by_state=by_state,
        delivered_order_count=counts.get(OrderState.DELIVERED, 0),
        failed_order_count=counts.get(OrderState.FAILED, 0),
    )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _filtered(filters: UserFilters) -> Select[tuple[UserRow]]:
    statement = sa.select(UserRow)
    statement = apply_window(statement, UserRow.created_at, filters.window)
    if filters.telegram_user_id is not None:
        statement = statement.where(UserRow.telegram_user_id == filters.telegram_user_id)
    if filters.is_blocked is not None:
        statement = statement.where(UserRow.is_blocked.is_(filters.is_blocked))
    if filters.ui_languages:
        statement = statement.where(UserRow.ui_language.in_(filters.ui_languages))
    return statement


def _cursor_of(item: UserListItem) -> Cursor:
    return Cursor(at=item.account_created_at, id=item.id)


def _list_item(row: UserRow, rollup: OrderRollup | None) -> UserListItem:
    """Assemble a list row. A user with no orders is possible only through a manual insert."""
    resolved = rollup or OrderRollup(
        order_count=0, paid_order_count=0, first_order_at=None, last_order_at=None
    )
    return UserListItem(
        id=row.id,
        telegram_user_id=row.telegram_user_id,
        ui_language=row.ui_language,
        is_blocked=row.is_blocked,
        account_created_at=row.created_at,
        first_order_at=resolved.first_order_at,
        last_order_at=resolved.last_order_at,
        order_count=resolved.order_count,
        paid_order_count=resolved.paid_order_count,
    )


async def _rollups(
    session: AsyncSession, telegram_user_ids: Sequence[int]
) -> dict[int, OrderRollup]:
    """Order counts and first/last order instants for a page's users, in one grouped query."""
    if not telegram_user_ids:
        return {}
    statement = (
        sa.select(
            OrderRow.telegram_user_id,
            sa.func.count().label("order_count"),
            count_where(OrderRow.state.in_(_PAID_STATES)).label("paid_order_count"),
            sa.func.min(OrderRow.created_at).label("first_order_at"),
            sa.func.max(OrderRow.created_at).label("last_order_at"),
        )
        .where(OrderRow.telegram_user_id.in_(telegram_user_ids))
        .group_by(OrderRow.telegram_user_id)
    )
    rows = (await session.execute(statement)).all()
    return {
        int(telegram_user_id): OrderRollup(
            order_count=int(order_count),
            paid_order_count=int(paid_order_count),
            first_order_at=first_order_at,
            last_order_at=last_order_at,
        )
        for telegram_user_id, order_count, paid_order_count, first_order_at, last_order_at in rows
    }


async def _orders_by_state(
    session: AsyncSession, telegram_user_id: int
) -> tuple[tuple[OrderState, int], ...]:
    """States this user actually reached, with counts. Absent states stay absent."""
    statement = (
        sa.select(OrderRow.state, sa.func.count().label("total"))
        .where(OrderRow.telegram_user_id == telegram_user_id)
        .group_by(OrderRow.state)
    )
    rows = (await session.execute(statement)).all()
    return tuple(sorted(((state, int(total)) for state, total in rows), key=lambda pair: pair[0]))
