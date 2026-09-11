"""``/users`` — the list, one person's record, their orders, and their live wizard session.

**Three routers, not one, and every split is a permission.** §12.2 gives RECORDS_READ,
WIZARD_STATE_READ and the block/unblock cell as separate rows, and the guard in this codebase
is declared on the router so that a route added next quarter inherits it instead of needing
somebody to remember a decorator (§12.1 T3). One router carrying three permissions cannot do
that — it would have to put the other two on handlers, which is exactly the shape the
convention forbids, or guard the wizard state with RECORDS_READ, which grants the
reveal-adjacent screen to everyone holding the ordinary one. So :func:`build_users_router`
owns the four database reads, :func:`build_wizard_state_router` owns the Redis one and
:func:`build_user_block_router` owns the two writes — and **the application must include all
three**: mounting only the first silently drops ``/users/{id}/wizard-state`` and both
operational actions from the surface with no error anywhere.

**The block pair is the first mutation in this file, and it is shaped by two rules.** §9.1:
an action that is a single database transaction writes its audit row *inside* that
transaction, so an unaudited state change is impossible. And §12.2's cell is ``W+S``, which a
router guard cannot enforce — see :func:`build_user_block_router`, and the matrix note beside
``USER_BLOCK_WRITE``.

**``lastOrderAt`` is not "last seen", and the reason changed while the conclusion did not.**
This paragraph used to say that ``users.last_seen_at`` had no real writer yet — that
``repository._ensure_user`` was called only from ``_create_order``, so the column advanced
when an order was created and at no other moment, and that somebody who walked the whole
wizard without confirming had no ``users`` row at all. All of that is false in the shipped
code: ``credits.touch`` (``db/credits.py``) UPSERTs the row and moves
``last_seen_at`` on **every inbound update**, driven by ``gate.TouchDrain``, and
``SqlUserProfiles.record_language`` writes a row the moment somebody answers the first
question the bot asks. The column has three writers and a person who never bought anything
has a row. The list still reports ``lastOrderAt``, derived from ``MAX(orders.created_at)``,
for the reason that survives: a per-update presence stamp on a *records* screen is activity
surveillance — an operator watching a customer minute by minute — and this screen exists to
show what was ordered, not who was awake. ``db/admin/users.py``'s module docstring carries
the same correction, and the two must not drift apart.

**``?segment=`` and ``?sort=`` are additions to the list, not a second list.** The segment
document (``BROADCAST_SPEC §1.1``) is ANDed with the six chip parameters rather than replacing
them, so every bookmarked chip URL keeps working, and it is compiled by
:func:`~bayram.admin.routers.segments.compiled_segment` — the same pipeline
``GET /api/segments/preview`` runs, which is what makes the wizard's audience count and this
screen the same population by construction rather than by agreement. Neither parameter widens
the guard and neither widens the projection: the registry is an allowlist that cannot name a
masked column, and sorting on a field is not publishing it — ``last_activity_at`` stays
filterable while the column and the ordering both stay refused. :func:`build_query` owns the
one thing they do change, which is which of the two cursors a page is walked with.

**The avatar is on this router, at ``RECORDS_READ``, and it is not a reveal surface.** The
product owner chose the branch where an operator opening ``/users`` sees faces: a real
thumbnail in the list and the photo on the detail screen, with no step-up, no reveal budget
unit and no per-view audit row. That decision is what makes it an ordinary records route,
and an ordinary records route belongs on the router that already declares ``RECORDS_READ`` —
a second router would exist only to carry a guard this route does not have. The masked half
of the record and the picture of the person it describes are now the same permission, which
is the trade, stated plainly: a face is a stronger identifier than a masked handle, and it is
visible to every role that can already list the account.

**It streams; it does not ``get``.** ``Storage.size`` then ``Storage.open_range``, exactly as
``routers.assets.stream_asset`` does, so confinement stays inside ``LocalFileStorage._resolve``
and this package touches no private storage member. It does **not** implement ``Range``: an
``<img>`` never sends one, RFC 9110 §14.2 permits ignoring a range specification, and lifting
``parse_range``, the 416 and the empty-object 200 would be four screens of scrubbing machinery
for an element that cannot scrub.

**The object key is rebuilt server-side and there is no filename anywhere.**
``avatar_key(user_id)`` is ``users/{user_id}/avatar.jpg`` — a fixed filename under a UUID this
handler read from the database. The path parameter is an ``int``, so nothing a caller sends
reaches a key, and there is no stored filename to re-validate the way
``services.assets.object_key`` must.

**No cache headers, and that is a verified fact rather than a preference.**
``SecurityHeadersMiddleware`` stamps ``Cache-Control: no-store`` outside
``IMMUTABLE_PATH_PREFIX = "/assets/"`` and REPLACES the header rather than appending
(``security_headers.py:125-159``), so a handler-set ``Cache-Control`` is discarded on its way
out. Setting an ``ETag`` under ``no-store`` is dead weight, and any positive freshness would
leave a customer's face in a shared proxy after their session was revoked. The cost of fifty
thumbnails on a page is bounded at the SPA instead, by rendering the ``<img>`` only when
``hasAvatar`` and lazily. **This route must stay under ``/api``**: ``IMMUTABLE_PATH_PREFIX``
is matched against the raw request path, so a route mounted outside would inherit the SPA
bundle's one-year immutable cache on a photograph.

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

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query
from starlette.responses import Response, StreamingResponse

from bayram.admin import audit_sink
from bayram.admin.deps import (
    API_PREFIX,
    Admin,
    Container,
    CurrentAdmin,
    Db,
    Settings,
    enforce_step_up,
    require_permission,
)
from bayram.admin.errors import AdminErrorCode, AdminProblem, ProblemError, problem, unwrap
from bayram.admin.routers.segments import SegmentToken, compiled_segment
from bayram.admin.schemas.actions import UserBlockRequest, UserBlockResultView
from bayram.admin.schemas.orders import OrdersPage, to_order_view
from bayram.admin.schemas.page import Paging, page_meta
from bayram.admin.schemas.segment import MAX_SEGMENT_KEY_CHARS
from bayram.admin.schemas.users import (
    UserDetailView,
    UsersPage,
    WizardStateView,
    to_user_detail_view,
    to_user_view,
    to_wizard_state_view,
)
from bayram.admin.security.permissions import Permission, StepUpAction
from bayram.admin.serializers.redaction import mask_telegram_user_id
from bayram.admin.settings import AdminSettings
from bayram.admin.window import resolve_window
from bayram.admin.wizard_state import read_wizard_state
from bayram.contracts import Language
from bayram.db.admin.audit import AuditEntry
from bayram.db.admin.orders import OrderFilters, count_orders, list_orders
from bayram.db.admin.page import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    MIN_PAGE_LIMIT,
    PageRequest,
    SortedCursor,
    decode_sorted_cursor,
    page_request,
)
from bayram.db.admin.segment import (
    DEFAULT_SORT,
    SORT_KEYS,
    SegmentError,
    SortDirection,
)
from bayram.db.admin.segment import SortSpec as SegmentSortSpec
from bayram.db.admin.sql import MAX_SEARCH_CHARS, TimeWindow
from bayram.db.admin.users import (
    UserFilters,
    count_users,
    get_user_detail,
    list_users,
    load_avatar,
    page_sort,
)
from bayram.db.admin.views import UserListItem
from bayram.db.base import utc_now
from bayram.db.credits import set_blocked
from bayram.db.enums import AuditAction
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH, AuditOutcome
from bayram.entitlements import EntitlementPolicy
from bayram.errors import ErrorCode
from bayram.user_profiles import AVATAR_MIME, avatar_key

__all__ = [
    "USERS_PATH",
    "USER_PATH",
    "USER_ORDERS_PATH",
    "USER_AVATAR_PATH",
    "USER_BLOCK_PATH",
    "USER_UNBLOCK_PATH",
    "WIZARD_STATE_PATH",
    "AVATAR_MIMES",
    "USER_SUBJECT_TYPE",
    "no_such_user",
    "build_users_router",
    "build_wizard_state_router",
    "build_user_block_router",
]

USERS_PATH: Final[str] = f"{API_PREFIX}/users"
#: One identifier name for the whole namespace. Every ``/users/**`` route keys on the
#: Telegram id — the value an operator has in front of them in a support ticket — and never
#: on ``users.id``, so no route in this file can be reached with the wrong kind of id.
USER_PATH: Final[str] = f"{USERS_PATH}/{{telegram_user_id}}"
USER_ORDERS_PATH: Final[str] = f"{USER_PATH}/orders"
#: The avatar's own path. Declared HERE and nowhere else: the literal ``/avatar`` appears
#: exactly once, so ``avatar_url`` on the wire and the route that answers it cannot drift
#: into two spellings and make every ``avatarUrl`` a 404. It is deliberately NOT in
#: ``schemas/users.py``: ``USER_PATH`` is built from ``API_PREFIX``, which lives in
#: ``bayram.admin.deps`` and drags ``AdminContainer``, the session factory and the permission
#: machinery with it — a schema module importing that would be an import cycle waiting for
#: the next route.
USER_AVATAR_PATH: Final[str] = f"{USER_PATH}/avatar"
#: Two paths and not one with a body flag: the state being set is the ROUTE, so a step-up
#: scope, an audit action and a URL in a request log all say which of the two happened. A
#: single ``/block`` taking ``{"isBlocked": false}`` would audit an unblock as a block the
#: first time somebody sent the wrong body.
USER_BLOCK_PATH: Final[str] = f"{USER_PATH}/block"
USER_UNBLOCK_PATH: Final[str] = f"{USER_PATH}/unblock"
WIZARD_STATE_PATH: Final[str] = f"{USER_PATH}/wizard-state"

#: ``admin_audit_log.subject_type`` for everything keyed on a Telegram id. One of
#: ``db.admin.audit.SUBJECT_TYPES``' closed set, spelled once here because ``routers/credits.py``
#: writes rows about the same subject and a second spelling would be an
#: ``AuditValueRejectedError`` raised inside ``append`` — which ``audit_sink`` swallows, retries
#: without the subject, and returns 200 for.
USER_SUBJECT_TYPE: Final[str] = "user"

#: What this route will serve, matched WHOLE. Never ``mime.split(";")[0]``: the idiom is two
#: files away in ``pipeline.assets`` and it happens to give the right answer today while
#: quietly widening the allowlist to any ``image/jpeg; something=nobody-reviewed`` variant.
#: The bot writes ``image/jpeg`` and only ``image/jpeg`` (it downscales Telegram's smallest
#: ``PhotoSize``); anything else on the row is a 415 rather than a byte stream the browser
#: gets to sniff at.
#:
#: Built from :data:`bayram.user_profiles.AVATAR_MIME` rather than from a literal of our own,
#: and that is not tidiness. ``record_avatar`` discards a MIME it does not recognise and
#: answers ``ok(None)``; this route answers 415 for one outside this set. Two independent
#: spellings therefore drift silently in both directions AT ONCE, and the observable result
#: is "no avatars anywhere" with a fully green suite. Importing from ``bayram.user_profiles`` is
#: legal: ``tests/test_admin/test_asset_stream.py:712`` caps only what this package imports
#: from ``bayram.storage``, and ``avatar_key`` already arrives the same way.
AVATAR_MIMES: Final[frozenset[str]] = frozenset({AVATAR_MIME})

WithTotal = Annotated[bool, Query(alias="withTotal")]


def no_such_user() -> ProblemError:
    """404 without echoing the id back. Public, because ``routers/credits.py`` answers it too.

    Shared rather than copied: the two 404 arms of the avatar route are asserted to be
    **indistinguishable** (``test_users_router.py``), and a second module spelling this
    message its own way is how a caller learns to tell one absence from another.

    The id the caller supplied is a Telegram user id, and §12.3 says an unmasked one is
    never in a JSON payload the operator did not explicitly request — an error body is a
    JSON payload. The operator already knows what they typed; repeating it here would put
    the one value this whole slice masks into the one response nobody thought to mask.

    The message no longer says "has never confirmed an order". That sentence was true of a
    world with one ``users`` writer and it is not true of this one: ``credits.touch`` and
    ``SqlUserProfiles.record_language`` both create rows for people who have bought nothing,
    so a 404 here means only that nothing at all is held under that id. It also has to cover
    the avatar route, where the absence being reported may be a profile row or a photo rather
    than an account. "Known here" is the weakest true claim that covers all three, which is
    the most an error body should ever make.
    """
    return ProblemError(
        AdminProblem(
            code=ErrorCode.NOT_FOUND,
            message="no user with that Telegram id is known here",
        )
    )


def _unsupported_avatar(mime: str | None) -> ProblemError:
    """415, carrying the row's own content type so the SPA can say *why*.

    Deliberately not ``routers.assets._unsupported``, which takes an ``AssetMedia`` this
    route never builds — the avatar handler holds a bare ``str | None``, so calling it is a
    type error rather than reuse; and deliberately not a widening of that function, because
    it sits beside a step-up scope compared byte-exact and a refactor there buys nothing
    here.

    Echoing the mime is safe and useful: it is a content type this system stored, not
    anything the customer wrote, and an operator told "not found" for a format nobody
    configured the panel to serve goes looking for a retention bug.
    """
    return problem(
        AdminErrorCode.UNSUPPORTED_MEDIA_TYPE,
        f"this avatar is {mime}; this route serves {AVATAR_MIME}",
        mime=mime,
    )


def _avatar_url(item: UserListItem) -> str | None:
    """The route's own path for this row, or ``None`` when there is nothing to fetch.

    Formatted here rather than in the schema so the SPA never builds a path — a prefix change
    would then be a TypeScript edit nobody remembers — and so the literal ``/avatar`` stays in
    one place. ``None`` when ``has_avatar`` is false, so the panel can skip the request
    entirely rather than issue fifty that 404.
    """
    if not item.has_avatar:
        return None
    return USER_AVATAR_PATH.format(telegram_user_id=item.telegram_user_id)


def _window(since: datetime | None, until: datetime | None) -> TimeWindow | None:
    """``from``/``to`` as a half-open window, or ``None`` when neither was given.

    "Accounts created since the campaign started" is the question this filter is asked, and
    it has no upper bound the operator would type — so a missing ``to`` becomes the request's
    ``now`` and a missing ``from`` leaves the window open below.
    :func:`~bayram.admin.window.resolve_window` makes both calls for all five routers; the
    ``utc_now()`` stays here so the clock is patchable per module, as it is everywhere else in
    this package.
    """
    return resolve_window(since, until, now=utc_now())


def build_filters(
    telegram_user_id: Annotated[int | None, Query(alias="telegramUserId")] = None,
    search: Annotated[str | None, Query(alias="q", max_length=MAX_SEARCH_CHARS)] = None,
    is_blocked: Annotated[bool | None, Query(alias="isBlocked")] = None,
    has_balance: Annotated[bool | None, Query(alias="hasBalance")] = None,
    ui_language: Annotated[list[Language] | None, Query(alias="uiLanguage")] = None,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
) -> UserFilters:
    """§6.6's filter set, as a dependency so the handler stays a straight line.

    Repeated ``uiLanguage`` values are OR within the field and AND across fields (§6.1).
    ``Language`` is an enum here, so an unknown value is a 422 naming the parameter rather
    than a filter that quietly matches nothing.

    ``q`` carries ``max_length`` for the reason :func:`bayram.db.admin.sql.search_clause` gives:
    that function truncates as a backstop, and a silently widened match is a page an operator
    cannot explain. Declared here, an over-long ``q`` is a 422 naming the parameter — the same
    shape ``provider`` and ``errorCode`` take on ``/generations``.

    **What ``q`` searches is a privacy decision, and it is made in
    :class:`~bayram.db.admin.users.UserFilters`, not here.** It matches the Telegram id and
    nothing else: every other text column this list can reach lives on ``user_profiles``, is
    masked at all four roles, and a substring filter over it would let an operator with no
    reveal cell confirm a customer's name three characters at a time, with no step-up, no
    budget unit and no audit row.

    ``hasBalance`` is the panel's "Has balance > 0" chip and it is a tri-state, not a flag:
    absent means "do not filter", ``true`` means a strictly positive stored balance, and
    ``false`` means no positive balance — which deliberately includes the customer with no
    ``credit_accounts`` row at all. :class:`~bayram.db.admin.users.UserFilters` argues why the
    never-metered account is excluded from ``true`` rather than counted as owed-an-allowance,
    and why the predicate is the stored column rather than the projection the detail publishes
    as ``creditsProjected``.
    """
    return UserFilters(
        telegram_user_id=telegram_user_id,
        search=search,
        is_blocked=is_blocked,
        has_balance=has_balance,
        ui_languages=tuple(ui_language or ()),
        window=_window(since, until),
    )


Filters = Annotated[UserFilters, Depends(build_filters)]


@dataclass(frozen=True, slots=True)
class UserQuery:
    """One resolved list request: what to narrow by, how many rows, and where to resume from.

    Three values rather than the two every other list endpoint needs, because a sorted walk
    and the default one take **different cursors** — :class:`~bayram.db.admin.page.Cursor` on
    :attr:`request` for ``(created_at, id)``, :class:`~bayram.db.admin.page.SortedCursor` on
    :attr:`cursor` for everything else — and :func:`~bayram.db.admin.users.list_users` raises
    ``ValueError`` for a caller that hands it both. Resolving which one a request is *once*,
    here, is what keeps that from being a decision the handler could get wrong.
    """

    filters: UserFilters
    request: PageRequest
    cursor: SortedCursor | None


def build_query(
    filters: Filters,
    segment: SegmentToken = None,
    sort: Annotated[str | None, Query(max_length=MAX_SEGMENT_KEY_CHARS)] = None,
    sort_dir: Annotated[SortDirection, Query(alias="sortDir")] = DEFAULT_SORT.direction,
    limit: Annotated[int, Query(ge=MIN_PAGE_LIMIT, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> UserQuery:
    """``?segment=&sort=&sortDir=&limit=&cursor=``, resolved into one coherent request.

    **The segment is a document and the sort is a key**, and both name things the registry
    owns rather than anything this module does: ``?segment=`` is the base64url JSON
    ``BROADCAST_SPEC §1.2`` specifies, bounded by :data:`MAX_SEGMENT_CHARS` here and again
    inside the codec, and ``?sort=`` is a
    :data:`~bayram.db.admin.segment.SORT_KEYS` member — a **name**, resolved to an expression
    object by :func:`~bayram.db.admin.segment.sort_expression`, so no caller string ever reaches
    ``ORDER BY``. ``?sortDir=`` is typed as the two-member ``Literal`` the db layer declares,
    which is what makes anything else a 422 from FastAPI rather than a guess.

    **``?sort=`` overrides the document's own ordering rather than sitting beside it** — see
    :func:`~bayram.admin.routers.segments.compiled_segment`, which is the single pipeline both
    routers run. One ordering, one source; :class:`~bayram.db.admin.users.UserFilters` refuses
    the alternative outright.

    **The default sort keeps the cheap cursor, and that is not an optimisation.**
    ``joined_at`` **is** ``users.created_at`` under the registry's own name, so a segment
    ordered the default way is the walk this list has always done: it keeps
    :class:`~bayram.db.admin.page.Cursor`, and every bookmarked "next page" link an operator
    already holds keeps working. Only a genuinely different key mints the larger sorted token.

    **``limit`` and ``cursor`` are declared here rather than taken from
    :data:`~bayram.admin.schemas.page.Paging`**, and the duplication is forced: that dependency
    decodes the cursor as an unsorted one, so a sorted token would be refused as "not one of
    ours" before this function ever saw the sort it belongs to. The bounds are the same
    constants, and :func:`~bayram.db.admin.page.page_request` still validates the limit a second
    time for callers that reach the db layer without going through HTTP.
    """
    compiled = compiled_segment(
        segment,
        now=utc_now(),
        sort=None if sort is None else SegmentSortSpec(key=sort, direction=sort_dir),
    )
    if compiled is None or compiled.sort == DEFAULT_SORT:
        narrowed = filters if compiled is None else replace(filters, segment=compiled)
        return UserQuery(
            filters=narrowed, request=unwrap(page_request(limit=limit, cursor=cursor)), cursor=None
        )
    # Unreachable for an unsortable key: ``compile_segment`` resolved it against ``SORT_KEYS``
    # already, which is the boundary that turns an unknown one into a 422.
    spec, kind = page_sort(compiled.sort)
    return UserQuery(
        filters=replace(filters, segment=compiled, sort=spec),
        request=unwrap(page_request(limit=limit)),
        cursor=(
            None if cursor is None else unwrap(decode_sorted_cursor(cursor, sort=spec, kind=kind))
        ),
    )


Listing = Annotated[UserQuery, Depends(build_query)]


def _refuse_a_total_beside_an_aggregate_sort(filters: UserFilters, *, with_total: bool) -> None:
    """422 for ``?withTotal=true`` on an aggregate sort — ``BROADCAST_SPEC §1.6``.

    Ordering by ``delivered_order_count`` makes the planner evaluate a correlated subquery
    over the whole filtered set before it can sort, and a bounded count pays for the same
    scan a second time. One request never buys both: the operator drops the total or drops
    the sort, and the refusal says which parameter to change. The count itself is still
    available — sorted the default way, or as the exact
    :func:`~bayram.db.admin.users.count_segment_exactly` behind ``/segments/preview``.

    ``SORT_KEYS`` is indexed rather than ``.get``-ed: a sort that reached
    :class:`UserQuery` was resolved against that same mapping by
    :func:`~bayram.db.admin.users.page_sort`, so a miss here would be a bug in this module and
    not a request worth rendering an error for.
    """
    if not with_total or filters.sort is None or not SORT_KEYS[filters.sort.key].is_aggregate:
        return
    raise ProblemError(
        SegmentError(
            "withTotal cannot be combined with a sort on an aggregate field",
            context={"parameter": "withTotal", "sort": filters.sort.key},
        )
    )


def _entitlement_policy(settings: AdminSettings) -> EntitlementPolicy:
    """The policy ``creditsProjected`` and ``inFlightRenderCount`` are computed with.

    TWO numbers move, and this paragraph used to say one did. It read "the allowance numbers
    are constants on both sides", which was true until the paywall shipped:
    :func:`bayram.entitlements.resolve_entitlement_policy` now reads
    ``Settings.free_allowance_credits`` into every policy it returns, and that setting went to
    0. Leaving ``allowance_credits`` at the dataclass default of 3 therefore stopped being a
    harmless shorthand and became a standing lie about every customer's balance:
    :func:`bayram.db.credit_sql.read_balance` adds ``policy.allowance_credits`` whenever an
    allowance is due, and with the worker's 0 nothing ever stamps ``allowance_period_index``,
    so "due" is permanently true. The panel showed 4 songs to a customer who had bought
    exactly 1. Both numbers are now mirrored — see ``admin_free_allowance_credits`` and
    ``admin_settlement_grace_s`` in :mod:`bayram.admin.settings` — and neither may be defaulted
    here again.

    The remaining policy field that resolver touches is ``is_balance_enforced``, which this
    read never consults, so the mirror is still two integers rather than a call into
    :mod:`bayram.config` — which this process deliberately cannot read (``settings.py``'s module
    docstring: that separation is what keeps a vendor key out of the panel's reach).

    An unpublished grace — ``None`` — falls back to the shipped
    ``DEFAULT_ENTITLEMENT_POLICY`` value rather than to a guess derived from queue settings
    this process also cannot see. The allowance has no such ``None``: a projection is
    arithmetic, so the mirror's default is the number the bot itself ships (0) and an
    operator who configures nothing gets agreement. The grace fallback can still disagree
    with the gate, which is why the value it was computed with is published on
    ``GET /api/config``: an operator holding a refusal the panel does not explain can see
    whether the two clocks are the same one.
    """
    allowance = settings.admin_free_allowance_credits
    grace = settings.admin_settlement_grace_s
    if grace is None:
        return EntitlementPolicy(allowance_credits=allowance)
    return EntitlementPolicy(allowance_credits=allowance, settlement_grace_s=grace)


def build_users_router() -> APIRouter:
    """The four database routes. One permission, declared once, on the router."""
    router = APIRouter(
        tags=["users"],
        dependencies=[Depends(require_permission(Permission.RECORDS_READ))],
    )

    @router.get(USERS_PATH)
    async def list_user_records(
        db: Db, listing: Listing, with_total: WithTotal = False
    ) -> UsersPage:
        """One keyset page of users — newest account first, unless ``?sort=`` asked otherwise.

        The three parts of the request were resolved by :func:`build_query`, which is also
        where the walk was chosen: this handler hands both cursors on and never decides
        between them. The projection is unchanged by any of it — a segment narrows the page
        and a sort orders it, and neither puts a column on the wire that
        :func:`~bayram.admin.schemas.users.to_user_view` did not already publish. Sorting on a
        field is not publishing it, which is what lets ``last_activity_at`` stay filterable
        while both the column and the ordering stay refused.
        """
        _refuse_a_total_beside_an_aggregate_sort(listing.filters, with_total=with_total)
        page = await list_users(
            db, filters=listing.filters, request=listing.request, cursor=listing.cursor
        )
        total = await count_users(db, filters=listing.filters) if with_total else None
        return UsersPage(
            items=[to_user_view(item, avatar_url=_avatar_url(item)) for item in page.items],
            meta=page_meta(page, total),
        )

    @router.get(USER_PATH)
    async def get_user_record(db: Db, settings: Settings, telegram_user_id: int) -> UserDetailView:
        """One person's record plus their per-state order breakdown.

        ``settings`` is here for two numbers, and it used to be one. ``inFlightRenderCount``
        is counted against the settlement grace and ``creditsProjected`` adds the free
        allowance; both belong to the worker rather than to this process, and both are
        mirrored into :class:`~bayram.admin.settings.AdminSettings`. :func:`_entitlement_policy`
        says what each one does when the deployment has not published it, and why defaulting
        the allowance instead of mirroring it overstated every balance by three.
        """
        detail = await get_user_detail(
            db, telegram_user_id, now=utc_now(), policy=_entitlement_policy(settings)
        )
        if detail is None:
            raise no_such_user()
        return to_user_detail_view(detail, avatar_url=_avatar_url(detail.user))

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
            raise no_such_user()
        filters = OrderFilters(telegram_user_id=telegram_user_id)
        page = await list_orders(db, filters=filters, request=paging)
        total = await count_orders(db, filters=filters) if with_total else None
        return OrdersPage(
            items=[to_order_view(item) for item in page.items], meta=page_meta(page, total)
        )

    @router.get(USER_AVATAR_PATH)
    async def get_user_avatar(container: Container, db: Db, telegram_user_id: int) -> Response:
        """The customer's profile photo, streamed. ``RECORDS_READ``, like the row it belongs to.

        The order of the refusals is ``stream_asset``'s and it is the control, not a style:
        the ROW first, then the MIME, then the bytes. Every absence this handler can SEE — no
        ``users`` row, no profile row, a profile that never captured a photo — answers the
        same :func:`no_such_user` 404, and it does not echo the id back, because an error
        body is a JSON payload and repeating a Telegram id would put the one value this slice
        masks into the one response nobody thought to mask. It is never a 204 and never a
        generated placeholder: an invented picture is one the panel made up, and an operator
        will read it as the customer's. The SPA draws the monogram off the ``<img onError>``.

        An object the volume no longer holds is ALSO a 404, but not this one: it comes out of
        ``unwrap(await container.storage.size(key))``, where ``LocalFileStorage._measure``
        returns ``_absent(key)`` — a ``NotFoundError`` carrying ``_ABSENT_MESSAGE``. Same
        status, different body. Say it that way rather than claiming one unified 404: the
        status is what the ``<img onError>`` reacts to, the body is what an operator reads in
        the network tab, and a docstring that promised they were identical would be the thing
        they trusted while debugging.

        A storage failure is a 503 and must not collapse into the 404. :func:`unwrap` already
        keeps them apart — ``Err(NotFoundError)`` carries ``ErrorCode.NOT_FOUND`` (404) and
        ``Err(StorageError)`` carries ``ErrorCode.STORAGE_FAILED`` (503) — and the difference
        is whether an operator goes looking for a retention bug or for a mount that did not
        come up.

        ``media_type=mime`` is safe only because the :data:`AVATAR_MIMES` membership test is
        above it: it is the test, and never the column, that decides the ``Content-Type`` a
        browser is handed. Moving that check below the storage read would let any string a
        writer put on the row become the type of a body the browser then sniffs. There is no
        ``Accept-Ranges`` header either — this route does not implement ``Range``, and
        advertising support would invite a request it answers with a whole-body 200: legal,
        and confusing.
        """
        loaded = await load_avatar(db, telegram_user_id)
        if loaded is None:
            raise no_such_user()
        user_id, mime, stored_at = loaded
        if stored_at is None:
            raise no_such_user()
        if mime not in AVATAR_MIMES:
            raise _unsupported_avatar(mime)
        key = avatar_key(user_id)
        total = unwrap(await container.storage.size(key))
        if total == 0:
            # A zero-byte object is not a photograph. ``open_range`` refuses every range of
            # an empty object with a ValidationError, which ``unwrap`` would render as a 422
            # about a request the caller made correctly.
            raise no_such_user()
        chunks = unwrap(await container.storage.open_range(key, start=0, end=total - 1))
        return StreamingResponse(
            chunks,
            media_type=mime,
            headers={"Content-Length": str(total)},
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


def build_user_block_router() -> APIRouter:
    """Block and unblock, behind the ROLE half of §12.2's ``W+S`` cell.

    ``USER_BLOCK_WRITE`` on the router and ``USER_BLOCK``'s step-up in each handler — the
    split the RBAC matrix argues beside the two rows, and the same shape the media routes and
    ``POST /reveal`` already take. A router guarded by ``USER_BLOCK`` itself would call
    :func:`~bayram.admin.security.permissions.check_role`, which holds no subject and therefore
    no grant, and would answer ``STEP_UP_REQUIRED`` to a correctly re-authenticated ADMIN for
    ever.

    A third router rather than two more routes on :func:`build_users_router`, for that file's
    own stated reason: the guard is declared on the router so a route added next quarter
    inherits it, and one router cannot carry two permissions without putting the second on a
    handler (§12.1 T3).
    """
    router = APIRouter(
        tags=["users"],
        dependencies=[Depends(require_permission(Permission.USER_BLOCK_WRITE))],
    )

    @router.post(USER_BLOCK_PATH)
    async def block_user(
        body: UserBlockRequest, db: Db, admin: Admin, container: Container, telegram_user_id: int
    ) -> UserBlockResultView:
        """Bar this Telegram account from the bot. Step-up scoped to this id, then audited."""
        return await _set_blocked(
            db, admin, container, telegram_user_id=telegram_user_id, body=body, is_blocked=True
        )

    @router.post(USER_UNBLOCK_PATH)
    async def unblock_user(
        body: UserBlockRequest, db: Db, admin: Admin, container: Container, telegram_user_id: int
    ) -> UserBlockResultView:
        """Lift the bar. A separate route, and a separate audit action — see below."""
        return await _set_blocked(
            db, admin, container, telegram_user_id=telegram_user_id, body=body, is_blocked=False
        )

    return router


async def _set_blocked(
    db: Db,
    admin: Admin,
    container: Container,
    *,
    telegram_user_id: int,
    body: UserBlockRequest,
    is_blocked: bool,
) -> UserBlockResultView:
    """The body both routes share: step up, write, audit — in that order, in one transaction.

    **There is no 404 here, and its absence is the whole design of the writer.**
    ``db.credits.set_blocked`` is an UPSERT precisely because the account an operator reaches
    for this button is often one with no ``users`` row at all: somebody who has not spoken to
    the bot since the onboarding deploy, which is exactly the population a rowcount-checked
    ``UPDATE`` would silently fail for (§5.11, ``db.credits.set_blocked``). Refusing an unknown
    id would therefore refuse the case the action exists for, and it would also make the route
    an existence oracle for any Telegram id anybody can guess.

    **One transaction, per §9.1's first rule.** Block/unblock is "a single database
    transaction", so the audit row goes *inside* it through :func:`audit_sink.record` — an
    unaudited state change is then impossible, including under deliberate database pressure.
    That is why this does not use the INTENT/OUTCOME pair the enqueueing actions need: there
    is nothing external here that could already have happened when the row fails to write.

    **The step-up is enforced before the write and audited by ``enforce_step_up`` if it
    fails**, in its own committed transaction, because this one is about to roll back.

    ``now`` is read once and threaded through the write, the audit row and the response, so
    the three cannot land on either side of a boundary.
    """
    now = utc_now()
    await enforce_step_up(
        admin,
        container,
        action=StepUpAction.USER_BLOCK,
        subject_id=str(telegram_user_id),
        now=now,
    )
    await set_blocked(db, telegram_user_id=telegram_user_id, is_blocked=is_blocked, now=now)
    await audit_sink.record(
        db,
        container,
        _block_entry(admin, telegram_user_id=telegram_user_id, body=body, is_blocked=is_blocked),
        now=now,
    )
    return UserBlockResultView(
        telegram_user_id=telegram_user_id,
        telegram_user_id_masked=mask_telegram_user_id(telegram_user_id),
        is_blocked=is_blocked,
        changed_at=now,
    )


def _block_entry(
    admin: CurrentAdmin, *, telegram_user_id: int, body: UserBlockRequest, is_blocked: bool
) -> AuditEntry:
    """One ``USER_BLOCK`` / ``USER_UNBLOCK`` row.

    Two actions rather than one carrying a boolean, because the audit log is queried by an
    equality filter on ``action`` (§12.4) and "show me every block this week" must not mean
    "read every row and look at a field". ``AuditAction.USER_BLOCK`` and ``USER_UNBLOCK`` have
    existed unused since the enum was written (``db/enums.py:192-193``) for exactly this.

    ``field_names`` names the column that moved and never its value — the same rule a reveal
    row follows. The value is not a secret, but a log that records values is a log that
    eventually records one that is.
    """
    return AuditEntry(
        action=AuditAction.USER_BLOCK if is_blocked else AuditAction.USER_UNBLOCK,
        actor_id=admin.admin_user_id,
        actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
        actor_role=admin.role,
        subject_type=USER_SUBJECT_TYPE,
        subject_id=str(telegram_user_id),
        field_names=("users.is_blocked",),
        reason_code=body.reason_code,
        reason_ref=body.reason_ref,
        reason_text=body.reason_text,
        outcome=AuditOutcome.OK,
        ip=admin.client_ip,
    )
