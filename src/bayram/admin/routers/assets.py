"""The asset surface: metadata on one router, the two audited media reveals on another.

**The metadata routes read no byte, and there is still no ``isFilePresent``.** §6.7's
presence flag is absent from that response rather than derived from a column — a flag
computed without stat-ing anything is a claim about a file nobody looked at, and an operator
reads a green tick as evidence the bytes are still there. The ``Storage`` seam now exists
(§12.7) and the media routes below use it, but they use it on a request an operator has
stepped up for; making the list page stat one file per row would put the volume behind every
page load and would answer a question nobody asked.

**Why there are two routers, and why that is not a stylistic choice.** §12.2 puts "stream
audio or read lyric text" on an ``A+S`` cell — the reveal cell — while the metadata around
it is ``RECORDS_READ``, an ``M`` for all four roles. A router-level guard resolves to
``check_role``, which holds no subject and therefore no grant, so it answers
``STEP_UP_REQUIRED`` to any cell carrying a step-up and never consults one: guarding these
two routes with ``REVEAL_MEDIA`` at the router would 403 an operator holding a live,
correctly-scoped grant, for ever. §12.2 worked this out once already for the admin roster
and split that row in two. The same split is applied here: ``REVEAL_MEDIA_READ`` is the role
half (SUPPORT and above, no step-up) and lives on the router; ``REVEAL_MEDIA``'s ``A+S``
cell is enforced by the handler, on the asset id it has just read, through
``services.assets.authorise_media_reveal``. Both run on every request.

The order inside each handler is deliberate too: **the row first, then the mime, then the
step-up**. An asset id that names nothing is a 404 before a grant is asked for, because
existence is already public at ``RECORDS_READ`` and 403-ing an operator into a
re-authentication prompt for a row that does not exist is a loop they cannot win.

What the row *does* know is whether a ``storage_key`` was ever recorded, and its absence is
operationally load-bearing rather than cosmetic: ``purge._purge_assets`` filters ``if key``
(``purge.py:194``), so an asset with no key is a file that outlives its row and is never
swept. ``isStorageKeyRecorded`` surfaces exactly that, and exactly nothing more.

**``payload`` never crosses.** It holds the lyric sheet — the whole song, in the customer's
own words when they pasted their own lyric — and §6.7 routes free text through
``POST /reveal`` alone. The projection is :func:`bayram.admin.schemas.orders.to_asset_view`,
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

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import Response, StreamingResponse

from bayram.admin.deps import API_PREFIX, Admin, Container, Db, require_permission
from bayram.admin.errors import AdminErrorCode, AdminProblem, ProblemError, problem, unwrap
from bayram.admin.schemas.assets import AssetTextView
from bayram.admin.schemas.orders import AssetsPage, AssetWireView, to_asset_view
from bayram.admin.schemas.page import Paging, page_meta
from bayram.admin.security.permissions import Permission
from bayram.admin.services.assets import (
    ASSET_STREAM_WINDOW_S,
    LYRIC_TEXT_MIME,
    STREAM_FIELD_NAME,
    STREAMABLE_MIMES,
    TEXT_FIELD_NAME,
    AssetMedia,
    RangeOutcome,
    authorise_media_reveal,
    load_media,
    lyric_text,
    object_key,
    parse_range,
)
from bayram.admin.window import resolve_window
from bayram.contracts import AssetKind
from bayram.db.admin.assets import (
    MAX_EXPIRING_WITHIN_DAYS,
    AssetFilters,
    count_assets,
    get_asset,
    list_assets,
)
from bayram.db.admin.sql import TimeWindow
from bayram.db.base import utc_now
from bayram.db.enums import AuditAction
from bayram.db.retention import RetentionClass
from bayram.errors import ErrorCode

__all__ = [
    "ASSETS_PATH",
    "ASSET_PATH",
    "ASSET_STREAM_PATH",
    "ASSET_TEXT_PATH",
    "build_assets_router",
    "build_asset_media_router",
]

ASSETS_PATH: Final[str] = f"{API_PREFIX}/assets"
#: One identifier name for this namespace. Declared as a full path because routers are
#: included without a prefix — the forced-rotation gate compares absolute paths.
ASSET_PATH: Final[str] = f"{ASSETS_PATH}/{{asset_id}}"
#: Under ``/api``, not under ``/assets`` — ``security_headers.IMMUTABLE_PATH_PREFIX`` is the
#: literal string ``"/assets/"`` and is matched on the raw request path, so a stream mounted
#: outside ``/api`` would inherit the SPA bundle's one-year immutable cache. It does not
#: match this, and both constants must stay exactly as they are.
ASSET_STREAM_PATH: Final[str] = f"{ASSET_PATH}/stream"
ASSET_TEXT_PATH: Final[str] = f"{ASSET_PATH}/text"


def _not_found(asset_id: UUID) -> ProblemError:
    """404 comes from ``ErrorCode``: ``AdminErrorCode`` has no member for it, by design."""
    return ProblemError(
        AdminProblem(code=ErrorCode.NOT_FOUND, message=f"no asset with id {asset_id}")
    )


def _window(since: datetime | None, until: datetime | None) -> TimeWindow | None:
    """``from``/``to`` as a half-open interval, either end open.

    ``to`` is the bound this route's callers omit: "what has been created since the sweep ran"
    is the question, and it has no upper end an operator would type. It is answered with the
    request's own ``now``, taken from this module's ``utc_now`` so the shifted-clock fixture
    reaches it like it reaches every other clock on this surface
    (``tests/test_admin/test_asset_stream.py:205``). Everything else — awareness, ordering,
    the open lower bound for a bare ``?to=`` — is
    :func:`~bayram.admin.window.resolve_window`'s, which four other routers had also copied.
    """
    return resolve_window(since, until, now=utc_now())


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
    in :data:`~bayram.db.admin.assets.MAX_EXPIRING_WITHIN_DAYS`: past a year the filter selects
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


def _unsupported(media: AssetMedia, expected: str) -> ProblemError:
    """415, carrying the row's mime so the SPA can say *why* rather than "cannot play".

    The distinction matters operationally: a song rendered in a format nobody configured the
    panel to play is un-playable for a reason that has nothing to do with the file being
    missing, and an operator told "not found" would go looking for a retention bug.
    """
    return problem(
        AdminErrorCode.UNSUPPORTED_MEDIA_TYPE,
        f"this asset is {media.mime}; this route serves {expected}",
        mime=media.mime,
    )


def build_asset_media_router() -> APIRouter:
    """The two audited media reveals. One permission on the router; the step-up in the handler.

    ``REVEAL_MEDIA_READ`` and not ``REVEAL_MEDIA``: see the module docstring. The router
    decides the role (SUPPORT and above), the handler decides the scope.
    """
    router = APIRouter(
        tags=["assets"],
        dependencies=[Depends(require_permission(Permission.REVEAL_MEDIA_READ))],
    )

    @router.get(ASSET_STREAM_PATH)
    async def stream_asset(
        request: Request, admin: Admin, container: Container, db: Db, asset_id: UUID
    ) -> Response:
        """A range-capable audio stream, audited once per ten-minute window (§12.3).

        Every failure this can produce is decided before a byte moves, and each one is a
        different answer on purpose: 404 for a row or an object that is not there, 415 for an
        asset whose format this route does not serve, 403 without a scoped step-up, 429 with
        the reveal budget spent, 416 for a range past the end, and 503 when the volume itself
        refuses. None of them names a filesystem path — the storage layer's operator messages
        are constants, its ``context`` is dropped by ``errors._details_of``, and nothing here
        interpolates a key into a message.
        """
        now = utc_now()
        media = await load_media(db, asset_id)
        if media is None:
            raise _not_found(asset_id)
        if media.mime not in STREAMABLE_MIMES:
            raise _unsupported(media, "audio only")
        key = object_key(media)
        if key is None:
            # The row names a filename this route will not resolve. 404, not 422: nothing the
            # caller sent is malformed, and the refusal must not describe the stored value.
            raise _not_found(asset_id)
        await authorise_media_reveal(
            admin,
            container,
            action=AuditAction.ASSET_STREAM,
            asset_id=asset_id,
            field_name=STREAM_FIELD_NAME,
            now=now,
            window_s=ASSET_STREAM_WINDOW_S,
        )
        # ``Storage.size`` and never ``AssetView.size_bytes``: that column is
        # ``BigInteger NOT NULL DEFAULT 0`` and no writer in this repository has ever set it,
        # so a ``Content-Range`` built from it would read ``bytes 0-99/0``.
        total = unwrap(await container.storage.size(key))
        wanted = parse_range(request.headers.get("range"), total=total)
        if wanted.outcome is RangeOutcome.UNSATISFIABLE:
            raise problem(
                AdminErrorCode.RANGE_NOT_SATISFIABLE,
                "that byte range is past the end of this object",
                # RFC 9110 §15.5.17: a 416 says how long the object actually is, which is
                # what lets a client re-ask for a range that exists.
                headers={"Content-Range": f"bytes */{total}", "Accept-Ranges": "bytes"},
            )
        if wanted.outcome is RangeOutcome.ABSENT and total == 0:
            # An empty object with no range asked for: a 200 with nothing in it. Not routed
            # through ``open_range``, which refuses every range of an empty object.
            return Response(
                content=b"",
                media_type=media.mime,
                headers={"Accept-Ranges": "bytes", "Content-Length": "0"},
            )
        served = (
            wanted
            if wanted.outcome is RangeOutcome.SATISFIABLE
            else parse_range(f"bytes=0-{total - 1}", total=total)
        )
        chunks = unwrap(
            await container.storage.open_range(key, start=served.start, end=served.last)
        )
        headers = {"Accept-Ranges": "bytes", "Content-Length": str(served.length)}
        if wanted.outcome is RangeOutcome.SATISFIABLE:
            headers["Content-Range"] = served.content_range(total=total)
        return StreamingResponse(
            chunks,
            status_code=206 if wanted.outcome is RangeOutcome.SATISFIABLE else 200,
            media_type=media.mime,
            headers=headers,
        )

    @router.get(ASSET_TEXT_PATH)
    async def read_asset_text(
        admin: Admin, container: Container, db: Db, asset_id: UUID
    ) -> AssetTextView:
        """The lyric sheet as ``application/json`` — §12.1 T7's whole point.

        It reads ``assets.payload`` and never the filesystem: the column already holds the
        lyric, so this route has no object key, no byte range and no traversal surface at all.
        Every request is its own reveal — one request returns the whole sheet, so there is
        nothing to deduplicate and a second read is a second disclosure.
        """
        now = utc_now()
        media = await load_media(db, asset_id)
        if media is None:
            raise _not_found(asset_id)
        if media.mime != LYRIC_TEXT_MIME:
            raise _unsupported(media, "the lyric sheet only")
        await authorise_media_reveal(
            admin,
            container,
            action=AuditAction.REVEAL_PERSONAL,
            asset_id=asset_id,
            field_name=TEXT_FIELD_NAME,
            now=now,
            window_s=0,
        )
        text = lyric_text(media)
        if text is None:
            raise _not_found(asset_id)
        return AssetTextView(asset_id=asset_id, text=text)

    return router
