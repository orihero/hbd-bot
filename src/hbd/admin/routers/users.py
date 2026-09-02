"""``/users`` — the list, one person's record, their orders, and their live wizard session.

**Two routers, not one, and the split is the permission.** §12.2 gives RECORDS_READ and
WIZARD_STATE_READ as separate rows, and the guard in this codebase is declared on the router
so that a route added next quarter inherits it instead of needing somebody to remember a
decorator (§12.1 T3). One router carrying two permissions cannot do that — it would have to
put the second guard on a handler, which is exactly the shape the convention forbids, or
guard the wizard state with RECORDS_READ, which grants the reveal-adjacent screen to
everyone holding the ordinary one. So :func:`build_users_router` owns the three
database routes and :func:`build_wizard_state_router` owns the Redis one, and **the
application must include both**: mounting only the first silently drops
``/users/{id}/wizard-state`` from the surface with no error anywhere.

**``lastOrderAt`` is not "last seen".** ``users.last_seen_at`` is written by
``repository._ensure_user``, which is called only from ``_create_order``, so it advances
when an order is *created* and at no other moment; a person who walks the whole wizard and
never confirms has no ``users`` row at all. The list therefore reports ``lastOrderAt``,
derived from ``MAX(orders.created_at)``. Phase 3's inbound middleware gives the column a
real writer; until then a column headed "last seen" would be a claim about presence read off
a measurement of purchases.

**The wizard-state route deliberately does not 404 on an unknown user.** It reads Redis and
not the database, and the person it is most often opened for — somebody stuck mid-wizard who
has never confirmed an order — has no ``users`` row by construction. Refusing them would
make the screen useless in precisely the case it exists for, so an absent session comes back
as ``isStatePresent: false`` and an absent row is not consulted at all.

Everything here is masked and there is no unmasked variant at any role, OWNER included
(§12.3): RECORDS_READ is **M** in all four cells, and the wizard draft's plaintext — the
recipient's display name, the note, the whole approved lyric — is reachable only through
``POST /reveal`` in Phase 2. For an abandoned session that draft is the only copy that
exists anywhere, which is why the projection reads an allowlist rather than the dict.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query

from hbd.admin.deps import API_PREFIX, Container, Db, require_permission
from hbd.admin.errors import AdminProblem, ProblemError, unwrap
from hbd.admin.schemas.orders import OrdersPage, to_order_view
from hbd.admin.schemas.page import Paging, page_meta
from hbd.admin.schemas.users import (
    UserDetailView,
    UsersPage,
    WizardStateView,
    to_user_detail_view,
    to_user_view,
    to_wizard_state_view,
)
from hbd.admin.security.permissions import Permission
from hbd.admin.wizard_state import read_wizard_state
from hbd.contracts import Language
from hbd.db.admin.orders import OrderFilters, count_orders, list_orders
from hbd.db.admin.sql import TimeWindow, time_window
from hbd.db.admin.users import UserFilters, count_users, get_user_detail, list_users
from hbd.errors import ErrorCode

__all__ = [
    "USERS_PATH",
    "USER_PATH",
    "USER_ORDERS_PATH",
    "WIZARD_STATE_PATH",
    "build_users_router",
    "build_wizard_state_router",
]

USERS_PATH: Final[str] = f"{API_PREFIX}/users"
#: One identifier name for the whole namespace. Every ``/users/**`` route keys on the
#: Telegram id — the value an operator has in front of them in a support ticket — and never
#: on ``users.id``, so no route in this file can be reached with the wrong kind of id.
USER_PATH: Final[str] = f"{USERS_PATH}/{{telegram_user_id}}"
USER_ORDERS_PATH: Final[str] = f"{USER_PATH}/orders"
WIZARD_STATE_PATH: Final[str] = f"{USER_PATH}/wizard-state"

WithTotal = Annotated[bool, Query(alias="withTotal")]


def _invalid(message: str) -> ProblemError:
    """422 in the pipeline taxonomy — the code the rest of the system already uses for this."""
    return ProblemError(AdminProblem(code=ErrorCode.INVALID_INPUT, message=message))


def _no_such_user() -> ProblemError:
    """404 without echoing the id back.

    The id the caller supplied is a Telegram user id, and §12.3 says an unmasked one is
    never in a JSON payload the operator did not explicitly request — an error body is a
    JSON payload. The operator already knows what they typed; repeating it here would put
    the one value this whole slice masks into the one response nobody thought to mask.
    """
    return ProblemError(
        AdminProblem(
            code=ErrorCode.NOT_FOUND,
            message="no user with that Telegram id has ever confirmed an order",
        )
    )


def _aware(name: str, value: datetime | None) -> datetime | None:
    """Refuse a naive instant (§6.1): the column is ``timestamptz`` and would raise anyway."""
    if value is not None and value.tzinfo is None:
        raise _invalid(f"{name} must carry a UTC offset, e.g. 2026-08-30T12:00:00Z")
    return value


def _window(since: datetime | None, until: datetime | None) -> TimeWindow | None:
    """``from``/``to`` as a half-open window, or ``None`` when neither was given.

    Half a window is a 422 rather than an invented bound. Defaulting the missing end to
    "now" or the missing start to the epoch would answer a different question than the one
    asked, and the operator would have no way to tell from the response which one.
    """
    start, end = _aware("from", since), _aware("to", until)
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise _invalid("from and to are one window; give both or neither")
    return unwrap(time_window(start, end))


def build_filters(
    telegram_user_id: Annotated[int | None, Query(alias="telegramUserId")] = None,
    is_blocked: Annotated[bool | None, Query(alias="isBlocked")] = None,
    ui_language: Annotated[list[Language] | None, Query(alias="uiLanguage")] = None,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
) -> UserFilters:
    """§6.6's filter set, as a dependency so the handler stays a straight line.

    Repeated ``uiLanguage`` values are OR within the field and AND across fields (§6.1).
    ``Language`` is an enum here, so an unknown value is a 422 naming the parameter rather
    than a filter that quietly matches nothing.
    """
    return UserFilters(
        telegram_user_id=telegram_user_id,
        is_blocked=is_blocked,
        ui_languages=tuple(ui_language or ()),
        window=_window(since, until),
    )


Filters = Annotated[UserFilters, Depends(build_filters)]


def build_users_router() -> APIRouter:
    """The three database routes. One permission, declared once, on the router."""
    router = APIRouter(
        tags=["users"],
        dependencies=[Depends(require_permission(Permission.RECORDS_READ))],
    )

    @router.get(USERS_PATH)
    async def list_user_records(
        db: Db, filters: Filters, paging: Paging, with_total: WithTotal = False
    ) -> UsersPage:
        """One keyset page of users, newest account first."""
        page = await list_users(db, filters=filters, request=paging)
        total = await count_users(db, filters=filters) if with_total else None
        return UsersPage(
            items=[to_user_view(item) for item in page.items], meta=page_meta(page, total)
        )

    @router.get(USER_PATH)
    async def get_user_record(db: Db, telegram_user_id: int) -> UserDetailView:
        """One person's record plus their per-state order breakdown."""
        detail = await get_user_detail(db, telegram_user_id)
        if detail is None:
            raise _no_such_user()
        return to_user_detail_view(detail)

    @router.get(USER_ORDERS_PATH)
    async def list_user_orders(
        db: Db, telegram_user_id: int, paging: Paging, with_total: WithTotal = False
    ) -> OrdersPage:
        """This person's orders, newest first.

        The existence check is not ceremony: without it an unknown id answers with an empty
        page, which reads as "this customer has never ordered" when the truth is "we hold
        nothing about this id at all". One bounded count buys the difference.
        """
        existing = await count_users(db, filters=UserFilters(telegram_user_id=telegram_user_id))
        if existing.total == 0:
            raise _no_such_user()
        filters = OrderFilters(telegram_user_id=telegram_user_id)
        page = await list_orders(db, filters=filters, request=paging)
        total = await count_orders(db, filters=filters) if with_total else None
        return OrdersPage(
            items=[to_order_view(item) for item in page.items], meta=page_meta(page, total)
        )

    return router


def build_wizard_state_router() -> APIRouter:
    """The Redis route, alone behind its own permission. See the module docstring."""
    router = APIRouter(
        tags=["users"],
        dependencies=[Depends(require_permission(Permission.WIZARD_STATE_READ))],
    )

    @router.get(WIZARD_STATE_PATH)
    async def get_wizard_state(container: Container, telegram_user_id: int) -> WizardStateView:
        """The live FSM session, projected. No database, no plaintext, no 404.

        The client comes off the container rather than through ``deps.RedisClient``. That
        alias is ``Annotated["Redis[str]", ...]`` and FastAPI resolves a handler's
        annotations at import: ``redis.asyncio.Redis`` is generic only in the type stubs, so
        evaluating the string raises ``TypeError: Redis is not a generic class`` and the
        route never gets registered. Same object, one hop, no import-time landmine.
        """
        snapshot = await read_wizard_state(container.redis, telegram_user_id=telegram_user_id)
        return to_wizard_state_view(telegram_user_id, state=snapshot.state, draft=snapshot.draft)

    return router
