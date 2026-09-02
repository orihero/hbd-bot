"""``GET /api/assets`` and ``GET /api/assets/{asset_id}`` — the file explorer, as metadata.

**Nothing here reads a byte, and there is no ``isFilePresent``.** That is a constraint rather
than a phase-1 shortcut: the admin process mounts the data volume read-only and has no
``Storage`` seam until Phase 2 (§12.7), which is the same phase the range-capable stream
arrives in. So §6.7's presence flag is absent from this response instead of being derived
from a column — a flag computed without stat-ing anything is a claim about a file nobody
looked at, and an operator reads a green tick as evidence the bytes are still there.

What the row *does* know is whether a ``storage_key`` was ever recorded, and its absence is
operationally load-bearing rather than cosmetic: ``purge._purge_assets`` filters ``if key``
(``purge.py:194``), so an asset with no key is a file that outlives its row and is never
swept. ``isStorageKeyRecorded`` surfaces exactly that, and exactly nothing more.

**``payload`` never crosses.** It holds the lyric sheet — the whole song, in the customer's
own words when they pasted their own lyric — and §6.7 routes free text through
``POST /reveal`` alone. The projection is :func:`hbd.admin.schemas.orders.to_asset_view`,
shared with the order detail, so there is one ``AssetRow``-to-wire mapping in the codebase
and no room for a second, laxer copy to grow beside it.

**The guard is ``require_permission`` at the router**, which resolves to ``check_role``:
with no subject there is no scope to weigh a step-up against, so ``check_access`` would log
an ERROR on every request to a route that asks for no step-up at all. §12.2 gives
RECORDS_READ as **M** to all four roles, so there is no unmasked variant to choose between —
and an asset row carries no personal data anyway, because the projection drops
``name_candidate_text`` and keeps only which strategy and rank produced the take.

``expiringWithinDays`` is the retention screen's filter and its window has no lower bound
(``db/admin/assets.py``): a row already past ``expires_at`` has not been swept yet and is the
most urgent line on the page, so excluding it would hide precisely the backlog the filter
exists to show.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from hbd.admin.deps import API_PREFIX, Db, require_permission
from hbd.admin.errors import AdminProblem, ProblemError, unwrap
from hbd.admin.schemas.orders import AssetsPage, AssetWireView, to_asset_view
from hbd.admin.schemas.page import Paging, page_meta
from hbd.admin.security.permissions import Permission
from hbd.contracts import AssetKind
from hbd.db.admin.assets import (
    MAX_EXPIRING_WITHIN_DAYS,
    AssetFilters,
    count_assets,
    get_asset,
    list_assets,
)
from hbd.db.admin.sql import TimeWindow, time_window
from hbd.db.base import utc_now
from hbd.db.retention import RetentionClass
from hbd.errors import ErrorCode

__all__ = ["ASSETS_PATH", "ASSET_PATH", "build_assets_router"]

ASSETS_PATH: Final[str] = f"{API_PREFIX}/assets"
#: One identifier name for this namespace. Declared as a full path because routers are
#: included without a prefix — the forced-rotation gate compares absolute paths.
ASSET_PATH: Final[str] = f"{ASSETS_PATH}/{{asset_id}}"


def _invalid(message: str) -> ProblemError:
    """422 in the pipeline taxonomy — the code the rest of the system already uses for this."""
    return ProblemError(AdminProblem(code=ErrorCode.INVALID_INPUT, message=message))


def _not_found(asset_id: UUID) -> ProblemError:
    """404 comes from ``ErrorCode``: ``AdminErrorCode`` has no member for it, by design."""
    return ProblemError(
        AdminProblem(code=ErrorCode.NOT_FOUND, message=f"no asset with id {asset_id}")
    )


def _aware(name: str, value: datetime | None) -> datetime | None:
    """Refuse a naive instant (§6.1): the column is ``timestamptz`` and would raise anyway."""
    if value is not None and value.tzinfo is None:
        raise _invalid(f"{name} must carry a UTC offset, e.g. 2026-08-30T12:00:00Z")
    return value


def _window(since: datetime | None, until: datetime | None) -> TimeWindow | None:
    """``from``/``to`` as a pair: both bounds, or neither.

    Half a window is not a window. Filling the missing bound would mean inventing a value the
    operator never typed, and the two candidates are both wrong in a way that is invisible on
    the page: an implicit ``to=now`` drops the rows written while the request was in flight,
    and an implicit ``from=epoch`` turns "the last hour" into "everything" for whoever
    mistyped the parameter name.
    """
    start, end = _aware("from", since), _aware("to", until)
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise _invalid("from and to are a pair — supply both bounds of the window, or neither")
    return unwrap(time_window(start, end))


def build_filters(
    kind: Annotated[list[AssetKind] | None, Query()] = None,
    retention_class: Annotated[list[RetentionClass] | None, Query(alias="retentionClass")] = None,
    expiring_within_days: Annotated[
        int | None, Query(alias="expiringWithinDays", ge=1, le=MAX_EXPIRING_WITHIN_DAYS)
    ] = None,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
) -> AssetFilters:
    """§6.7's filter set, as a dependency so both handlers stay a straight line.

    Repeated ``kind`` and ``retentionClass`` are OR within the field and AND across fields
    (§6.1), and both are typed as enums so an unknown value is a 422 from FastAPI rather than
    a filter that quietly matches nothing. ``expiringWithinDays`` is bounded here as well as
    in :data:`~hbd.db.admin.assets.MAX_EXPIRING_WITHIN_DAYS`: past a year the filter selects
    the whole table, which is the one answer an operator would misread as a narrowed one.
    """
    return AssetFilters(
        kinds=tuple(kind or ()),
        retention_classes=tuple(retention_class or ()),
        expiring_within_days=expiring_within_days,
        window=_window(since, until),
    )


Filters = Annotated[AssetFilters, Depends(build_filters)]


def build_assets_router() -> APIRouter:
    """The asset surface. One permission, declared once, on the router."""
    router = APIRouter(
        tags=["assets"],
        dependencies=[Depends(require_permission(Permission.RECORDS_READ))],
    )

    @router.get(ASSETS_PATH)
    async def list_asset_metadata(
        db: Db,
        filters: Filters,
        paging: Paging,
        with_total: Annotated[bool, Query(alias="withTotal")] = False,
    ) -> AssetsPage:
        """One keyset page of asset metadata, newest first.

        The clock is read **once** and handed to both queries. Two ``utc_now()`` calls would
        put the page and its count on either side of an expiry boundary, so a row could be
        listed and not counted — the kind of off-by-one an operator reports as "the total is
        wrong" and nobody can reproduce.
        """
        now = utc_now()
        page = await list_assets(db, filters=filters, request=paging, now=now)
        total = await count_assets(db, filters=filters, now=now) if with_total else None
        return AssetsPage(
            items=[to_asset_view(asset) for asset in page.items], meta=page_meta(page, total)
        )

    @router.get(ASSET_PATH)
    async def get_asset_metadata(db: Db, asset_id: UUID) -> AssetWireView:
        """One asset's metadata. Never its bytes, and never its lyric-sheet payload."""
        asset = await get_asset(db, asset_id)
        if asset is None:
            raise _not_found(asset_id)
        return to_asset_view(asset)

    return router
