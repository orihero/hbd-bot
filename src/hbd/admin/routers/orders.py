"""``/orders`` — the list, one order, and the three collections that hang off it.

**Nothing here reaches past :mod:`hbd.db.admin.orders`, and that is the entire reason this
module is thin.** ``hbd.db.mapping.to_order`` delegates to ``to_brief`` →
``to_recipient_name``, which raises ``PipelineError`` the moment ``recipient_name_display IS
NULL`` (``db/mapping.py:137-147``) — precisely the state the 90-day identity sweep leaves a
lawfully purged order in. A handler that called the repository to save itself a query would
therefore fail a *whole page* because one row on it was erased on schedule, and the order an
operator most needs to look at is the old one. Every read below goes through the admin query
layer, which models a purge as a state and never as an error.

**Masking is not a decision made here.** ``hbd.admin.schemas.orders`` has one projection per
view model and no ``is_unmasked`` parameter, because §12.2 gives ``RECORDS_READ`` as **M** to
all four roles including OWNER. So there is no role to branch on, no grant to read, and the
handlers take no ``Admin`` — taking the operator in order to ignore them would imply a
masking decision this namespace does not have. Plaintext is reachable only through ``POST
/reveal`` in Phase 2, which is a different permission, a step-up and an audit row.

**Every route is a ``GET`` and writes nothing**, which is what makes ``SameSite=Lax`` safe and
what the route-enumeration test asserts (§12.1 T8). Retry and force-deliver are Phase 2+ and
are POSTs when they arrive.

**``/orders/state-counts`` is a sibling of the list and not a field on it.** The argument is
in :func:`order_state_counts` and it is about when the aggregate runs rather than about REST
aesthetics: paging must not re-count the dataset. It shares the list's filter dependency
verbatim so the two cannot describe different populations, and it is a literal path segment
declared before ``/orders/{order_id}`` so route matching reaches it.

**The three sub-collections do not 404 on an unknown order id**, deliberately.
``/orders/{id}/attempts`` is ``/attempts?orderId={id}`` with the scope moved into the path;
an empty page is the right answer to a filter that matched nothing, exactly as it is on the
global collection. ``/orders/{id}`` and ``/orders/{id}/timeline`` do 404, because both claim
to return *an order* rather than rows about one. Probing for existence on a paged route would
buy a second round trip per page load to change an empty list into an error the SPA never
navigates to — it reaches these routes from a detail screen that already answered 404.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from hbd.admin.deps import API_PREFIX, Db, require_permission
from hbd.admin.errors import AdminProblem, ProblemError
from hbd.admin.schemas.orders import (
    AssetsPage,
    AttemptsPage,
    OrderDetailView,
    OrdersPage,
    OrderStateCountsView,
    TimelineView,
    to_asset_view,
    to_attempt_view,
    to_order_detail_view,
    to_order_state_counts_view,
    to_order_view,
    to_timeline_view,
)
from hbd.admin.schemas.page import Paging, page_meta
from hbd.admin.security.permissions import Permission
from hbd.admin.window import resolve_window
from hbd.contracts import OrderState
from hbd.db.admin.assets import AssetFilters, count_assets, list_assets
from hbd.db.admin.attempts import AttemptFilters, count_attempts, list_attempts
from hbd.db.admin.orders import (
    OrderFilters,
    count_orders,
    count_orders_by_state,
    get_order_detail,
    list_orders,
)
from hbd.db.admin.sql import MAX_SEARCH_CHARS, TimeWindow
from hbd.db.base import utc_now
from hbd.db.enums import GenerationKind
from hbd.db.models.order import CORRELATION_ID_LENGTH
from hbd.errors import ErrorCode

__all__ = [
    "ORDERS_PATH",
    "ORDER_STATE_COUNTS_PATH",
    "ORDER_PATH",
    "ORDER_ASSETS_PATH",
    "ORDER_ATTEMPTS_PATH",
    "ORDER_TIMELINE_PATH",
    "build_query",
    "build_orders_router",
]

ORDERS_PATH: Final[str] = f"{API_PREFIX}/orders"
#: A literal segment under ``/orders``, and it must be **declared before** ``ORDER_PATH``
#: below or Starlette will never reach it: routes match in registration order, and while
#: ``state-counts`` is not a ``UUID`` and would fail ``/orders/{order_id}``'s coercion, the
#: caller would get a 422 about a malformed path parameter rather than their counts.
ORDER_STATE_COUNTS_PATH: Final[str] = f"{ORDERS_PATH}/state-counts"
#: One identifier name per namespace. Every ``/orders/**`` route below takes ``{order_id}``
#: typed ``UUID``, so a malformed id is a 422 from FastAPI rather than a query that runs.
ORDER_PATH: Final[str] = f"{ORDERS_PATH}/{{order_id}}"
ORDER_ATTEMPTS_PATH: Final[str] = f"{ORDER_PATH}/attempts"
ORDER_ASSETS_PATH: Final[str] = f"{ORDER_PATH}/assets"
ORDER_TIMELINE_PATH: Final[str] = f"{ORDER_PATH}/timeline"


def _not_found() -> ProblemError:
    """404, without echoing what was asked for. An id is not a hint worth confirming."""
    return ProblemError(AdminProblem(code=ErrorCode.NOT_FOUND, message="no order with that id"))


def _window(since: datetime | None, until: datetime | None) -> TimeWindow | None:
    """``from``/``to`` as one half-open interval, or nothing at all.

    Three lines rather than a shared FastAPI dependency, because of the ``utc_now()`` in it:
    the clock is resolved from *this module's* globals, which is this package's uniform seam
    for moving time in a test. Uniform, and today exercised in exactly one router —
    ``monkeypatch.setattr(assets_router, "utc_now", ...)`` in
    ``tests/test_admin/test_asset_stream.py:205`` is the only such patch in the suite, and it
    reaches ``assets`` alone. So this adapter is kept for consistency of the seam rather than
    because deleting it would fail a test today; that is the honest reason, and a docstring
    promising a red test somebody could not find was worth less than none.
    :func:`~hbd.admin.window.resolve_window` owns every judgement — awareness, which bound is
    missing, and delegating "``to`` before ``from``" to ``time_window`` — and used to be
    copied verbatim into five routers.
    """
    return resolve_window(since, until, now=utc_now())


def build_query(
    state: Annotated[list[OrderState] | None, Query()] = None,
    is_paid: Annotated[bool | None, Query(alias="isPaid")] = None,
    telegram_user_id: Annotated[int | None, Query(alias="telegramUserId")] = None,
    correlation_id: Annotated[
        str | None, Query(alias="correlationId", max_length=CORRELATION_ID_LENGTH)
    ] = None,
    has_assets: Annotated[bool | None, Query(alias="hasAssets")] = None,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
    search: Annotated[str | None, Query(alias="q", max_length=MAX_SEARCH_CHARS)] = None,
) -> OrderFilters:
    """§6.5's filter set, as a dependency so the handler stays a straight line.

    Repeated ``state`` parameters are OR within the field and AND across fields (§6.1), and
    ``state`` is typed as the enum so an unknown value is a 422 from FastAPI rather than a
    filter that quietly matches nothing.

    ``q`` declares ``max_length`` even though :func:`~hbd.db.admin.sql.search_clause`
    truncates: the query layer's cap is a backstop for callers that did not arrive over HTTP,
    and one that fires silently *widens* the pattern. Declaring it here means an operator who
    pastes a wall of text gets a 422 naming ``q`` instead of a page of rows they did not ask
    for — the same shape ``provider`` and ``errorCode`` take on ``/generations``.

    ``correlationId`` and ``q`` are both still here and both still mean what they meant.
    ``q`` does not subsume the exact filter: one answers "this id", the other "something with
    this in it", and collapsing them would change what every existing caller's page contains.
    """
    return OrderFilters(
        states=tuple(state or ()),
        is_paid=is_paid,
        telegram_user_id=telegram_user_id,
        correlation_id=correlation_id,
        window=_window(since, until),
        has_assets=has_assets,
        search=search,
    )


Filters = Annotated[OrderFilters, Depends(build_query)]
WithTotal = Annotated[bool, Query(alias="withTotal")]


def build_orders_router() -> APIRouter:
    """The orders surface. One permission, declared once, on the router."""
    router = APIRouter(
        tags=["orders"],
        dependencies=[Depends(require_permission(Permission.RECORDS_READ))],
    )

    @router.get(ORDERS_PATH)
    async def list_order_page(
        db: Db, filters: Filters, paging: Paging, with_total: WithTotal = False
    ) -> OrdersPage:
        """One keyset page of orders, newest first, masked, and total over every purge state."""
        page = await list_orders(db, filters=filters, request=paging)
        total = await count_orders(db, filters=filters) if with_total else None
        return OrdersPage(
            items=[to_order_view(item) for item in page.items], meta=page_meta(page, total)
        )

    @router.get(ORDER_STATE_COUNTS_PATH)
    async def order_state_counts(db: Db, filters: Filters) -> OrderStateCountsView:
        """Per-state totals for the CURRENT FILTER SET — the distribution bar's real numbers.

        **A sibling route rather than a field on the list's ``meta``, and the reason is the
        cost.** The counts are one ``GROUP BY`` over every row the filters match, which
        cannot be keyset-bounded the way a page is; on ``meta`` that aggregate would run
        again on every ``?cursor=`` an operator turns to, so scrolling a filtered list to row
        four hundred would pay for the same eight numbers eight times. Behind a
        ``?withStateCounts=true`` flag it would be no better in practice — a client sets a
        flag once and then sends it on every request, which is exactly how ``withTotal``
        already behaves in this SPA. As its own URL the aggregate is fetched when the filter
        set changes and at no other moment, it is separately cacheable, and the bar can paint
        before or after the page it labels without either request blocking the other.

        **It takes the identical filter dependency**, so it answers for exactly the rows
        ``GET /api/orders`` with the same query string would return — window, ``isPaid``,
        ``q`` and all. That includes ``?state=`` itself: filtering to ``FAILED`` makes every
        other segment ``0``, which is correct rather than useless, and it is what lets the
        SPA choose which distribution it wants by choosing which parameters it sends. A
        server that silently dropped one filter to make a prettier bar would be describing a
        set the operator is not looking at.

        No ``?withTotal=``: the total is the sum of the segments and is already exact.
        """
        return to_order_state_counts_view(await count_orders_by_state(db, filters=filters))

    @router.get(ORDER_PATH)
    async def order_detail(db: Db, order_id: UUID) -> OrderDetailView:
        """The order, its brief, its assets, its attempts, the inferred plan and the timeline."""
        detail = await get_order_detail(db, order_id)
        if detail is None:
            raise _not_found()
        return to_order_detail_view(detail)

    @router.get(ORDER_ATTEMPTS_PATH)
    async def order_attempts(
        db: Db,
        order_id: UUID,
        paging: Paging,
        kind: Annotated[list[GenerationKind] | None, Query()] = None,
        is_success: Annotated[bool | None, Query(alias="isSuccess")] = None,
        with_total: WithTotal = False,
    ) -> AttemptsPage:
        """This order's render ledger, paged. Orphaned attempts are not this order's rows."""
        filters = AttemptFilters(order_id=order_id, kinds=tuple(kind or ()), is_success=is_success)
        page = await list_attempts(db, filters=filters, request=paging)
        total = await count_attempts(db, filters=filters) if with_total else None
        return AttemptsPage(
            items=[to_attempt_view(item) for item in page.items], meta=page_meta(page, total)
        )

    @router.get(ORDER_ASSETS_PATH)
    async def order_assets(
        db: Db, order_id: UUID, paging: Paging, with_total: WithTotal = False
    ) -> AssetsPage:
        """This order's delivered files, as metadata. The clock is read once for both queries.

        ``now`` is taken here rather than inside the query layer so the page and its count
        cannot straddle a tick of the ``expiring_within_days`` boundary and disagree about how
        many rows there are.
        """
        filters = AssetFilters(order_id=order_id)
        now = utc_now()
        page = await list_assets(db, filters=filters, request=paging, now=now)
        total = await count_assets(db, filters=filters, now=now) if with_total else None
        return AssetsPage(
            items=[to_asset_view(item) for item in page.items], meta=page_meta(page, total)
        )

    @router.get(ORDER_TIMELINE_PATH)
    async def order_timeline(db: Db, order_id: UUID) -> TimelineView:
        """The merged timeline on its own, for a panel that renders it without the detail."""
        detail = await get_order_detail(db, order_id)
        if detail is None:
            raise _not_found()
        return to_timeline_view(detail.timeline)

    return router
