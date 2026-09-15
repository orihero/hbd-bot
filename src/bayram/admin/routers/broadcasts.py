"""``/broadcasts`` — composing a campaign, and the one button that puts it in front of people.

**This is the only namespace in the panel whose actions reach outside the building.** Every
other mutation here moves a row: a block, a grant, a config commit. A send moves forty
thousand messages into other people's phones, it cannot be undone one record at a time, and
the operator who pressed it is not the person who finds out it was wrong. So the shape of
this module is decided by that asymmetry rather than by REST tidiness.

**Two routers, two cells, and the send is the split.** :func:`build_broadcasts_router` carries
``BROADCAST_READ`` — **M** for all four roles, because a campaign record holds operator copy,
closed enums and counters and no customer data at all. :func:`build_broadcast_actions_router`
carries ``BROADCAST_WRITE``, the ROLE half of ``BROADCAST_SEND``'s ``W+S`` cell, and the two
routes that actually cause a message to leave enforce ``BROADCAST_SEND``'s step-up inside the
handler on ``str(broadcast_id)``. That is the same split ``POST /reveal``, the two media
streams and the block pair already take, and the mechanical reason is unchanged: a router
guard resolves to :func:`~bayram.admin.security.permissions.check_role`, which holds no subject
and therefore no grant, so a router declaring ``BROADCAST_SEND`` would answer
``STEP_UP_REQUIRED`` to a correctly re-authenticated ADMIN for ever.

**The audience is frozen by ``POST /api/broadcasts`` and by nothing else.** The recipient rows
are materialised from the segment at creation, so ``expectedAudienceSize`` — the wizard's
optimistic-concurrency catch — is checked *here*, at the call that decides who is in, and not
at the send. Re-counting at send time would produce a number nobody is going to receive this.
It follows that ``POST /{id}/revise`` takes a title and bodies and refuses a segment: changing
what is said is an edit, and changing who hears it is a different campaign whose audit row
would have to name a different number.

**Nothing here talks to Telegram, and nothing here can.** The admin process is denied a bot
token by ``FORBIDDEN_ENV_VARS`` (D10). Every route below that causes a message writes its rows
and then enqueues an ARQ job through :mod:`bayram.admin.queue` — a Redis write and nothing more.
The enqueue is the **last** statement of each handler, after the campaign row and its audit
row are in the request's transaction, and it is an optimisation rather than the only path: a
crash between the two leaves a ``ready`` campaign the worker's due sweep picks up.

**The test send is an allowlist, not a permission.** ``POST /{id}/test-send`` would otherwise
be "put operator-authored text in front of any Telegram id you can type", which a step-up
authenticates and an audit row records but neither *bounds*. So the recipient must appear in
``admin_broadcast_test_recipients``, which is configuration: whoever may edit ``.env.admin`` is
a smaller population than whoever holds an ADMIN session, and a limit the caller supplies is
not a limit. The list ships empty, so the route is off until somebody turns it on.

**No raw Telegram id is on any wire in this namespace.**
:class:`~bayram.admin.schemas.broadcasts.BroadcastRecipientView` publishes the mask alone —
``/users`` publishes the id beside it because every ``/users/**`` route keys on it, and
nothing here does: a recipient row is addressed by its own UUID. The recipient ledger is the
one list in this API that pages through a membership decision made *about* people, so the id
is absent from the bytes rather than withheld by a renderer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from bayram.admin import audit_sink
from bayram.admin.deps import (
    API_PREFIX,
    Admin,
    Container,
    CurrentAdmin,
    Db,
    enforce_step_up,
    require_permission,
)
from bayram.admin.errors import AdminErrorCode, AdminProblem, ProblemError, problem, unwrap
from bayram.admin.schemas.actions import ReasonedRequest
from bayram.admin.schemas.broadcasts import (
    BroadcastCreateRequest,
    BroadcastDetailView,
    BroadcastRecipientsPage,
    BroadcastReviseRequest,
    BroadcastSendRequest,
    BroadcastsPage,
    BroadcastStatsView,
    BroadcastTestSendRequest,
    BroadcastTestSendResultView,
    to_broadcast_detail_view,
    to_broadcast_stats_view,
    to_broadcast_view,
    to_recipient_view,
)
from bayram.admin.schemas.page import Paging, page_meta
from bayram.admin.schemas.segment import encode_segment, to_segment
from bayram.admin.security.permissions import Permission, StepUpAction
from bayram.admin.security.tokens import sha256_hex
from bayram.admin.serializers.redaction import mask_telegram_user_id
from bayram.admin.window import resolve_window
from bayram.contracts import BroadcastKind, BroadcastRecipientState, BroadcastState, Language
from bayram.db.admin.audit import AuditEntry
from bayram.db.admin.broadcasts import (
    BroadcastFilters,
    RecipientFilters,
    broadcast_stats,
    count_broadcasts,
    count_recipients,
    get_broadcast,
    list_broadcasts,
    list_recipients,
)
from bayram.db.admin.segment import compile_segment, segment_capabilities
from bayram.db.admin.sql import MAX_SEARCH_CHARS, TimeWindow
from bayram.db.admin.users import UserFilters, count_segment_exactly
from bayram.db.admin.views import BroadcastDetail
from bayram.db.base import utc_now
from bayram.db.broadcasts import (
    BroadcastActor,
    BroadcastBody,
    NewBroadcast,
    create_broadcast,
    revise_broadcast,
)
from bayram.db.broadcasts import cancel as cancel_broadcast
from bayram.db.broadcasts import mark_scheduled as schedule_broadcast
from bayram.db.broadcasts import pause as pause_broadcast
from bayram.db.broadcasts import resume as resume_broadcast
from bayram.db.enums import AuditAction, AuditReasonCode
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH, AuditOutcome
from bayram.errors import ErrorCode, StorageError

__all__ = [
    "BROADCASTS_PATH",
    "BROADCAST_STATS_PATH",
    "BROADCAST_RECIPIENTS_PATH",
    "BROADCAST_REVISE_PATH",
    "BROADCAST_SEND_PATH",
    "BROADCAST_PAUSE_PATH",
    "BROADCAST_RESUME_PATH",
    "BROADCAST_CANCEL_PATH",
    "BROADCAST_TEST_SEND_PATH",
    "BROADCAST_PATH",
    "BROADCAST_SUBJECT_TYPE",
    "build_query",
    "build_recipient_query",
    "build_broadcasts_router",
    "build_broadcast_actions_router",
]

BROADCASTS_PATH: Final[str] = f"{API_PREFIX}/broadcasts"
#: The campaign strip's aggregate, and **it must be declared before** ``BROADCAST_PATH`` below
#: or Starlette will never reach it. This is the one path in this namespace where registration
#: order is genuinely load-bearing, unlike the verb paths noted under ``BROADCAST_PATH``:
#: ``stats`` is a SINGLE segment under ``/broadcasts``, exactly like ``{broadcast_id}``, so a
#: parameterised route registered first would match it and the operator would be handed a 422
#: about a malformed UUID instead of their strip. ``ORDER_STATE_COUNTS_PATH`` and
#: ``SUPPORT_BOARD_PATH`` carry this same warning, and it is written out here rather than
#: cross-referenced because the next reader is editing THIS file.
BROADCAST_STATS_PATH: Final[str] = f"{BROADCASTS_PATH}/stats"
#: One identifier name for the whole namespace, typed ``UUID`` on every route below, so a
#: malformed id is FastAPI's 422 rather than a query that runs. The five verb paths and the
#: recipient collection are declared **before** it out of habit rather than necessity: they
#: are two path segments to its one, so ``{broadcast_id}`` — a single segment — cannot match
#: them however they are ordered. ``ORDER_STATE_COUNTS_PATH`` is the case where the ordering
#: really is load-bearing, and stating which of the two this is saves the next reader the
#: experiment.
BROADCAST_PATH: Final[str] = f"{BROADCASTS_PATH}/{{broadcast_id}}"
BROADCAST_RECIPIENTS_PATH: Final[str] = f"{BROADCAST_PATH}/recipients"
BROADCAST_REVISE_PATH: Final[str] = f"{BROADCAST_PATH}/revise"
#: "Send now" and "send at 09:00 on Thursday" are one route because they are one decision —
#: :class:`~bayram.admin.schemas.broadcasts.BroadcastSendRequest` carries the instant or omits it.
#: A separate ``/schedule`` would be a second place to forget the step-up.
BROADCAST_SEND_PATH: Final[str] = f"{BROADCAST_PATH}/send"
BROADCAST_PAUSE_PATH: Final[str] = f"{BROADCAST_PATH}/pause"
BROADCAST_RESUME_PATH: Final[str] = f"{BROADCAST_PATH}/resume"
BROADCAST_CANCEL_PATH: Final[str] = f"{BROADCAST_PATH}/cancel"
BROADCAST_TEST_SEND_PATH: Final[str] = f"{BROADCAST_PATH}/test-send"

#: ``admin_audit_log.subject_type`` for every row this module writes, and for the two the
#: worker writes when a send finishes. Spelled once here and imported by the worker — the
#: ``USER_SUBJECT_TYPE`` precedent — because a second literal is a second way for one action's
#: intent row and its outcome row to end up under different subjects.
BROADCAST_SUBJECT_TYPE: Final[str] = "broadcast"

#: The reason a compose carries when the request had none to give. Creating and revising a
#: campaign are the two actions here that send nobody anything, so
#: :class:`~bayram.admin.schemas.broadcasts.BroadcastCreateRequest` asks for no reason code — but
#: :class:`~bayram.db.admin.audit.AuditEntry` requires one, deliberately, because a row that could
#: omit it would be a row somebody omits it on. ``ROUTINE_OPS`` is the honest answer for a
#: draft: the accountability that matters is on the send, which demands the whole trio.
_COMPOSE_REASON: Final[AuditReasonCode] = AuditReasonCode.ROUTINE_OPS

WithTotal = Annotated[bool, Query(alias="withTotal")]


def _no_such_broadcast() -> ProblemError:
    """404 without echoing the id. An identifier is not a hint worth confirming."""
    return ProblemError(AdminProblem(code=ErrorCode.NOT_FOUND, message="no campaign with that id"))


def _wrong_state(state: BroadcastState) -> ProblemError:
    """409 naming the state the campaign is actually in.

    The state IS published, unlike the id in the 404 above, and the difference is what the
    caller can do with it: an operator whose "pause" lost a race to the campaign finishing
    needs to know it finished, and the value is a closed enum this API already returns in
    every campaign body. What is never published is which write refused — the conditional
    ``UPDATE``s in :mod:`bayram.db.broadcasts` are the authority on that, and this reports the
    state read a moment before them rather than pretending to have raced them.
    """
    return problem(
        AdminErrorCode.CONFLICT,
        "this campaign is not in a state that allows that",
        state=state.value,
    )


def _window(since: datetime | None, until: datetime | None) -> TimeWindow | None:
    """``from``/``to`` as one half-open interval over ``broadcasts.created_at``, or nothing."""
    return resolve_window(since, until, now=utc_now())


def build_query(
    state: Annotated[list[BroadcastState] | None, Query()] = None,
    kind: Annotated[list[BroadcastKind] | None, Query()] = None,
    since: Annotated[datetime | None, Query(alias="from")] = None,
    until: Annotated[datetime | None, Query(alias="to")] = None,
    search: Annotated[str | None, Query(alias="q", max_length=MAX_SEARCH_CHARS)] = None,
) -> BroadcastFilters:
    """The campaign list's filters, as a dependency so the handler stays a straight line.

    Repeated ``state`` and ``kind`` are OR within the field and AND across fields, and both
    are typed as their enums so an unknown value is a 422 from FastAPI rather than a filter
    that silently matches nothing.

    ``q`` matches the campaign TITLE and nothing else. The bodies are deliberately not
    searchable: an ``EXISTS`` over a child table this list cannot render would return
    campaigns with no visible reason for being on the page (see
    :data:`~bayram.db.admin.broadcasts._SEARCHABLE_COLUMNS`).
    """
    return BroadcastFilters(
        states=tuple(state or ()),
        kinds=tuple(kind or ()),
        window=_window(since, until),
        search=search,
    )


def build_recipient_query(
    state: Annotated[list[BroadcastRecipientState] | None, Query()] = None,
    language: Annotated[list[Language] | None, Query()] = None,
    telegram_user_id: Annotated[int | None, Query(alias="telegramUserId")] = None,
) -> RecipientFilters:
    """One campaign's ledger filters. There is no window and no cross-campaign read.

    Every row of one campaign was written by one expansion within minutes of itself, so a date
    range narrows nothing an operator would ask for. What they ask is "show me the failures"
    and "did this person get it", which is ``state`` and ``telegramUserId``.
    """
    return RecipientFilters(
        states=tuple(state or ()),
        languages=tuple(language or ()),
        telegram_user_id=telegram_user_id,
    )


Filters = Annotated[BroadcastFilters, Depends(build_query)]
RecipientQuery = Annotated[RecipientFilters, Depends(build_recipient_query)]


def build_broadcasts_router() -> APIRouter:
    """The campaign surface an operator reads. One permission, declared once, on the router."""
    router = APIRouter(
        tags=["broadcasts"],
        dependencies=[Depends(require_permission(Permission.BROADCAST_READ))],
    )

    @router.get(BROADCASTS_PATH)
    async def list_broadcast_page(
        db: Db, filters: Filters, paging: Paging, with_total: WithTotal = False
    ) -> BroadcastsPage:
        """One keyset page of campaigns, newest composed first.

        The counters on each row are the campaign's own — the worker's rollup — and not a
        recount of the recipient ledger. Recounting per row would be one ``GROUP BY`` over
        tens of thousands of rows per campaign on the page; the recount an operator actually
        watches a send with is on the detail, beside the rollup rather than instead of it.
        """
        page = await list_broadcasts(db, filters=filters, request=paging)
        total = await count_broadcasts(db, filters=filters) if with_total else None
        return BroadcastsPage(
            items=[to_broadcast_view(item) for item in page.items], meta=page_meta(page, total)
        )

    # Declared HERE — before ``BROADCAST_PATH`` — and the position is load-bearing rather than
    # tidy: ``/broadcasts/stats`` and ``/broadcasts/{broadcast_id}`` are both one segment under
    # ``/broadcasts``, Starlette matches in registration order, and the parameterised route
    # would swallow ``stats`` and answer a 422 about a malformed UUID. See
    # :data:`BROADCAST_STATS_PATH`, and ``routers/segments.py`` for the same note made from the
    # other side (nothing under ``/segments`` is parameterised, so nothing there can collide).
    @router.get(BROADCAST_STATS_PATH)
    async def broadcast_strip(db: Db, filters: Filters) -> BroadcastStatsView:
        """The Campaigns strip: campaigns per state, what they reached, and the last send.

        **A sibling route rather than ``meta`` on the list, for ``/orders/state-counts``'
        reason**, and it is worth restating because the cost argument is weaker here and the
        SHAPE argument is not. The aggregate answers for the whole filter set, so on ``meta``
        it would run again on every ``?cursor=`` an operator turns — paying for the same
        numbers once per page of a list whose strip did not change. As its own URL it is
        fetched when the filter set changes and at no other moment, and the strip and the page
        under it can paint independently without either blocking the other.

        **It takes the list's identical filter dependency**, so it describes exactly the
        campaigns ``GET /api/broadcasts`` with the same query string would return — window,
        ``kind``, ``q`` and ``state`` included. Filtering to one state makes every other
        segment ``0``, which is the honest answer to what was asked rather than a strip quietly
        widened to look fuller.

        **Counts, closed enum members and one UTC instant.** No title, no body, no recipient,
        no Telegram id: this is an aggregate surface, and §12.3's rule for one is that nothing
        on it is about a person. That is also why it sits on this router and inherits
        ``BROADCAST_READ`` — the guard is declared once, on the router (§12.1 T3), and a
        handler-level check here would be a second place for the cell to be wrong.

        No ``?withTotal=``: ``total`` is the sum of the segments and is already exact.
        """
        return to_broadcast_stats_view(await broadcast_stats(db, filters=filters))

    @router.get(BROADCAST_RECIPIENTS_PATH)
    async def list_broadcast_recipients(
        db: Db,
        broadcast_id: UUID,
        filters: RecipientQuery,
        paging: Paging,
        with_total: WithTotal = False,
    ) -> BroadcastRecipientsPage:
        """This campaign's ledger, paged and masked. Every row, including the erased ones.

        **No 404 for an unknown campaign**, the same answer ``/orders/{id}/attempts`` gives
        and for the same reason: this is a filtered collection, and an empty page is the right
        response to a filter that matched nothing. The route is reached from a detail screen
        that has already answered 404, so probing for existence would buy a second round trip
        per page to produce an error the SPA never navigates to.

        ``/forget`` nulls ``telegram_user_id`` rather than deleting the row, and the row is
        rendered — ``isErased`` — rather than filtered: it is the evidence that a message went
        to an account this database no longer holds, and dropping it would make the funnel
        stop adding up.
        """
        page = await list_recipients(db, broadcast_id, filters=filters, request=paging)
        total = await count_recipients(db, broadcast_id, filters=filters) if with_total else None
        return BroadcastRecipientsPage(
            items=[to_recipient_view(item) for item in page.items], meta=page_meta(page, total)
        )

    @router.get(BROADCAST_PATH)
    async def broadcast_detail(db: Db, broadcast_id: UUID) -> BroadcastDetailView:
        """One campaign: its bodies rendered as Telegram will see them, and its frozen filter."""
        detail = await get_broadcast(db, broadcast_id)
        if detail is None:
            raise _no_such_broadcast()
        return to_broadcast_detail_view(detail)

    return router


def build_broadcast_actions_router() -> APIRouter:
    """Compose, revise, send, pause, resume, cancel and test — all on ``BROADCAST_WRITE``.

    One factory because one permission: §12.1 T3's rule is that the guard is declared on the
    router, and a second permission would be a second factory. The two routes whose cell is
    ``W+S`` — the send and the test send — layer ``BROADCAST_SEND``'s step-up inside the
    handler, on the campaign id they are about to act on.
    """
    router = APIRouter(
        tags=["broadcasts"],
        dependencies=[Depends(require_permission(Permission.BROADCAST_WRITE))],
    )

    @router.post(BROADCASTS_PATH)
    async def create_campaign(
        body: BroadcastCreateRequest, db: Db, admin: Admin, container: Container
    ) -> BroadcastDetailView:
        """Compose a campaign and FREEZE its audience. This is the call that decides who.

        The order is: compile the filter, count it exactly, refuse on drift, write the
        campaign and its bodies, write the audit row in the same transaction, enqueue the
        expansion last.

        **The count is exact and never bounded.** It is the number a human will authorise a
        send against, and ``10,000+`` is a refusal to answer rather than an approximation —
        :func:`~bayram.db.admin.users.count_segment_exactly` makes that argument at length. It is
        paid once, here, and never per page render.

        **No step-up, and the asymmetry with the send is the point.** This messages nobody: it
        writes rows and spends one count. What needs re-authentication is putting text in
        front of the people it selected, and that is ``POST /{id}/send``.

        ``now`` is read once and threaded through the compile, the count, the row, the audit
        entry and the enqueue, so the instant the segment was evaluated at is the instant
        every chunk of the expansion will compile it against.
        """
        now = utc_now()
        compiled = unwrap(
            compile_segment(to_segment(body.segment), now=now, capabilities=segment_capabilities())
        )
        audience_size = await count_segment_exactly(db, filters=UserFilters(segment=compiled))
        _refuse_on_drift(
            body.expected_audience_size,
            audience_size,
            tolerance=container.settings.admin_broadcast_audience_drift_tolerance,
        )
        broadcast_id = await create_broadcast(
            db,
            draft=NewBroadcast(
                title=body.title,
                kind=body.kind,
                segment=body.segment.model_dump(mode="json", by_alias=True, exclude_none=True),
                segment_hash=sha256_hex(encode_segment(body.segment)),
                audience_size=audience_size,
                audience_evaluated_at=now,
                bodies=tuple(
                    BroadcastBody(
                        language=item.language,
                        text=item.text,
                        media_storage_key=item.media_storage_key,
                        button_label=item.button_label,
                        button_url=item.button_url,
                    )
                    for item in body.bodies
                ),
                created_by=BroadcastActor(
                    admin_id=admin.admin_user_id,
                    username=admin.username[:ACTOR_USERNAME_LENGTH],
                ),
            ),
            at=now,
        )
        await audit_sink.record(
            db,
            container,
            _entry(
                admin,
                action=AuditAction.BROADCAST_CREATE,
                broadcast_id=broadcast_id,
                field_names=("broadcasts.state", "broadcasts.segment", "broadcast_bodies.text"),
                reason_code=_COMPOSE_REASON,
                record_count=audience_size,
            ),
            now=now,
        )
        # Persist, then enqueue — §3.6. The rows and the audit entry are in this request's
        # transaction and this is the last thing that changes anything; the read below it is a
        # read. The worker's due sweep is the backstop if the process dies between the two.
        unwrap(await container.queue.enqueue_expand(broadcast_id, now=now))
        return to_broadcast_detail_view(await _reload(db, broadcast_id))

    @router.post(BROADCAST_REVISE_PATH)
    async def revise_campaign(
        body: BroadcastReviseRequest, db: Db, admin: Admin, container: Container, broadcast_id: UUID
    ) -> BroadcastDetailView:
        """Replace the title and the WHOLE body set of a campaign that has not gone out.

        A whole replacement rather than a patch, because "leave the Russian body alone" and
        "delete the Russian body" are the same JSON document under ``extra="forbid"`` and
        optional fields. The request carries no segment: re-pointing a frozen audience is a
        different campaign, whose audit row would have to name a different number.

        409 once the campaign has left the states :func:`~bayram.db.broadcasts.revise_broadcast`
        accepts — the refusal is that conditional ``UPDATE``'s, not a check here, because the
        send job runs in another process and the gap between a ``SELECT`` and an ``UPDATE`` is
        exactly long enough for the first message to leave under the old text.
        """
        now = utc_now()
        detail = await _found(db, broadcast_id)
        accepted = await revise_broadcast(
            db,
            broadcast_id=broadcast_id,
            title=body.title,
            bodies=[
                BroadcastBody(
                    language=item.language,
                    text=item.text,
                    media_storage_key=item.media_storage_key,
                    button_label=item.button_label,
                    button_url=item.button_url,
                )
                for item in body.bodies
            ],
            at=now,
        )
        if not accepted:
            raise _wrong_state(detail.broadcast.state)
        await audit_sink.record(
            db,
            container,
            _entry(
                admin,
                action=AuditAction.BROADCAST_REVISE,
                broadcast_id=broadcast_id,
                field_names=("broadcasts.title", "broadcast_bodies.text"),
                reason_code=_COMPOSE_REASON,
            ),
            now=now,
        )
        return to_broadcast_detail_view(await _reload(db, broadcast_id))

    @router.post(BROADCAST_SEND_PATH)
    async def send_campaign(
        body: BroadcastSendRequest, db: Db, admin: Admin, container: Container, broadcast_id: UUID
    ) -> BroadcastDetailView:
        """Authorise the send — now, or at a stated instant. **The destructive action.**

        Step-up first, scoped to ``str(broadcast_id)``, because a refusal must cost nothing and
        change nothing; the id must be byte-identical to what the SPA sent ``/auth/step-up``.
        Then the campaign is read, the instant is checked against *this* handler's ``now``, the
        conditional ``UPDATE`` decides whether the campaign was ``READY``, and the audit row
        lands in the same transaction carrying ``recordCount`` — **the audience size** — which
        is what makes a forty-recipient test distinguishable from a forty-thousand-recipient
        send by a query rather than by reading reasons.

        **Only ``READY``.** A campaign whose audience is still being materialised cannot be
        authorised: that would schedule a send against a half-written ledger, which is the
        distinction ``EXPANDING`` and ``READY`` exist to keep. 409, naming the state.

        **The enqueue happens only for an immediate send.** A future instant is the due
        sweep's to pick up, and enqueueing a send job now for a campaign that must not start
        for three days would be a job that either fires early or has to be cancelled.
        """
        now = utc_now()
        await enforce_step_up(
            admin,
            container,
            action=StepUpAction.BROADCAST_SEND,
            subject_id=str(broadcast_id),
            now=now,
        )
        detail = await _found(db, broadcast_id)
        if body.scheduled_for is not None and body.scheduled_for <= now:
            # A schema cannot make this call: no model in this package reads a clock, so
            # "carries a UTC offset" is theirs and "has not already happened" is the
            # handler's, against the same instant it is about to stamp the row with.
            raise ProblemError(
                AdminProblem(
                    code=ErrorCode.INVALID_INPUT,
                    message="scheduledFor is in the past",
                )
            )
        accepted = await schedule_broadcast(
            db,
            broadcast_id=broadcast_id,
            scheduled_for=body.scheduled_for,
            scheduled_by=BroadcastActor(
                admin_id=admin.admin_user_id, username=admin.username[:ACTOR_USERNAME_LENGTH]
            ),
            at=now,
            reason_code=body.reason_code,
            reason_ref=body.reason_ref,
        )
        if not accepted:
            raise _wrong_state(detail.broadcast.state)
        await audit_sink.record(
            db,
            container,
            _entry(
                admin,
                action=AuditAction.BROADCAST_SCHEDULE,
                broadcast_id=broadcast_id,
                field_names=("broadcasts.scheduled_for", "broadcasts.scheduled_by_admin_id"),
                reason_code=body.reason_code,
                reason_ref=body.reason_ref,
                reason_text=body.reason_text,
                record_count=detail.broadcast.audience_size,
            ),
            now=now,
        )
        if body.scheduled_for is None:
            unwrap(await container.queue.enqueue_send(broadcast_id))
        return to_broadcast_detail_view(await _reload(db, broadcast_id))

    @router.post(BROADCAST_PAUSE_PATH)
    async def pause_campaign(
        body: ReasonedRequest, db: Db, admin: Admin, container: Container, broadcast_id: UUID
    ) -> BroadcastDetailView:
        """Stop delivering, from ``SENDING``. Rows already claimed are settled, not abandoned.

        Setting the column is all this does, and it is all it can do: the chunk job reads the
        state at the top of each chunk and again every few messages, so a pause takes effect
        within seconds rather than at the end of a chunk. A row a worker has already claimed
        has either been sent or has an unknown outcome, and neither is undone by pausing.

        No step-up. Pausing is the action that makes fewer messages leave, and putting a
        re-authentication in front of the brake would be a control that costs seconds at
        exactly the moment somebody needs them.
        """
        return await _transition(
            db,
            admin,
            container,
            broadcast_id=broadcast_id,
            body=body,
            action=AuditAction.BROADCAST_PAUSE,
            move=pause_broadcast,
        )

    @router.post(BROADCAST_RESUME_PATH)
    async def resume_campaign(
        body: ReasonedRequest, db: Db, admin: Admin, container: Container, broadcast_id: UUID
    ) -> BroadcastDetailView:
        """``PAUSED -> SENDING``, and re-enqueue the chunk job that stopped.

        ``started_at`` is not re-stamped — a campaign starts once — so the enqueue is the only
        externally visible part of this, and it is the last statement for the same reason the
        create's is.
        """
        detail = await _transition(
            db,
            admin,
            container,
            broadcast_id=broadcast_id,
            body=body,
            action=AuditAction.BROADCAST_RESUME,
            move=resume_broadcast,
        )
        unwrap(await container.queue.enqueue_send(broadcast_id))
        return detail

    @router.post(BROADCAST_CANCEL_PATH)
    async def cancel_campaign(
        body: ReasonedRequest, db: Db, admin: Admin, container: Container, broadcast_id: UUID
    ) -> BroadcastDetailView:
        """Stop the campaign for good, from any non-terminal state — ``EXPANDING`` included.

        Cancelling does not un-send what has gone. A campaign cancelled halfway is a cancelled
        campaign with ``sentCount`` messages already delivered, and the counters keep saying so
        rather than being reset; the recipient rows stay as the evidence of what was about to
        happen. The expansion job learns to stop from its next chunk being refused.
        """
        return await _transition(
            db,
            admin,
            container,
            broadcast_id=broadcast_id,
            body=body,
            action=AuditAction.BROADCAST_CANCEL,
            move=cancel_broadcast,
        )

    @router.post(BROADCAST_TEST_SEND_PATH)
    async def test_send_campaign(
        body: BroadcastTestSendRequest,
        db: Db,
        admin: Admin,
        container: Container,
        broadcast_id: UUID,
    ) -> BroadcastTestSendResultView:
        """Send the composed bodies to ONE allowlisted account, so a human can read them.

        **The allowlist is the control and it is configuration.** Without it this route is
        "put operator-authored text in front of any Telegram id you can type" — the step-up
        proves who asked and the audit row records that they did, and neither bounds who
        receives it. ``admin_broadcast_test_recipients`` ships empty, so the route answers 403
        until a deployment names the operators' own ids.

        The step-up runs **first**, before the 404 and before the allowlist, so an
        unauthenticated probe learns nothing about which campaigns or which ids exist. The
        refusal that follows names neither: the message says the recipient is not permitted
        and the id is not echoed anywhere, masked or otherwise.
        """
        now = utc_now()
        await enforce_step_up(
            admin,
            container,
            action=StepUpAction.BROADCAST_SEND,
            subject_id=str(broadcast_id),
            now=now,
        )
        await _found(db, broadcast_id)
        if body.telegram_user_id not in container.settings.admin_broadcast_test_recipients:
            raise problem(
                AdminErrorCode.FORBIDDEN,
                "that recipient is not on this deployment's test-send allowlist",
            )
        await audit_sink.record(
            db,
            container,
            _entry(
                admin,
                action=AuditAction.BROADCAST_TEST,
                broadcast_id=broadcast_id,
                field_names=("broadcast_bodies.text",),
                reason_code=body.reason_code,
                reason_ref=body.reason_ref,
                reason_text=body.reason_text,
                record_count=1,
            ),
            now=now,
        )
        job_id = unwrap(
            await container.queue.enqueue_test_send(
                broadcast_id, telegram_user_id=body.telegram_user_id
            )
        )
        return BroadcastTestSendResultView(
            broadcast_id=broadcast_id,
            telegram_user_id_masked=mask_telegram_user_id(body.telegram_user_id),
            job_id=job_id,
            requested_at=now,
        )

    return router


# ---------------------------------------------------------------------------
# The shared bodies: one lifecycle move, one audit row, one re-read
# ---------------------------------------------------------------------------
#: A conditional state move in :mod:`bayram.db.broadcasts`. All three take the campaign and the
#: clock and nothing else, and all three answer ``False`` — never raise — when the campaign was
#: not in the state they accept.
type _Move = Callable[..., Awaitable[bool]]


async def _transition(
    db: Db,
    admin: Admin,
    container: Container,
    *,
    broadcast_id: UUID,
    body: ReasonedRequest,
    action: AuditAction,
    move: _Move,
) -> BroadcastDetailView:
    """Pause, resume and cancel are one shape: read, move, refuse or audit, re-read.

    **One transaction, per §9.1's first rule.** The state change and its audit row are in the
    request's own transaction, so an unaudited lifecycle move is impossible rather than
    unlikely — there is nothing external here that could already have happened when the write
    fails, which is why this needs none of the INTENT/OUTCOME pairing the send does.

    The 404 read happens before the move so an unknown id is a 404 and not a 409; the move is
    still the authority on the state, because the campaign can finish under this request and
    the conditional ``UPDATE`` is what races it honestly.

    ``now`` is read once and threaded through the write and the audit row.
    """
    now = utc_now()
    detail = await _found(db, broadcast_id)
    accepted = await move(db, broadcast_id=broadcast_id, at=now)
    if not accepted:
        raise _wrong_state(detail.broadcast.state)
    await audit_sink.record(
        db,
        container,
        _entry(
            admin,
            action=action,
            broadcast_id=broadcast_id,
            field_names=("broadcasts.state",),
            reason_code=body.reason_code,
            reason_ref=body.reason_ref,
            reason_text=body.reason_text,
            record_count=detail.broadcast.audience_size,
        ),
        now=now,
    )
    return to_broadcast_detail_view(await _reload(db, broadcast_id))


async def _found(db: Db, broadcast_id: UUID) -> BroadcastDetail:
    """The campaign, or a 404. Read before every write so an unknown id is never a 409."""
    detail = await get_broadcast(db, broadcast_id)
    if detail is None:
        raise _no_such_broadcast()
    return detail


async def _reload(db: Db, broadcast_id: UUID) -> BroadcastDetail:
    """Read the campaign back from the database rather than from arithmetic.

    Every mutation here answers with the record as it now stands, and it comes from the same
    transaction that just wrote it — a response assembled from what the handler *believes* it
    wrote would be the panel telling an operator about a state nothing confirmed.

    ``None`` is unreachable: the row was read a moment ago in this transaction and nothing
    here deletes it. Raised as a :class:`~bayram.errors.StorageError` so it lands in the shared
    envelope as a 503 rather than as a bare 500.
    """
    detail = await get_broadcast(db, broadcast_id)
    if detail is None:  # pragma: no cover - written in this very transaction
        raise ProblemError(
            StorageError(
                "the campaign this call wrote could not be read back",
                context={"broadcast_id": str(broadcast_id)},
            )
        )
    return detail


def _refuse_on_drift(expected: int | None, actual: int, *, tolerance: float) -> None:
    """Refuse a create whose audience has moved too far from the number the operator saw.

    **The catch is on the CREATE and not on the send**, because creation is what materialises
    the recipient rows: by the time anybody presses send, the audience is a set of rows and
    re-counting the segment would produce a number nobody is going to receive this. The drift
    this guards is between the wizard's preview render and this call.

    A FRACTION rather than a count, and not zero. The same twelve accounts are noise against
    forty thousand and a different campaign against forty, and an exact-match rule would refuse
    a correct request on any live database — people sign up between the preview and the button
    — so the first thing an operator would learn is to stop sending ``expectedAudienceSize`` at
    all, which is the control switching itself off.

    Both numbers are published in the refusal. They are counts of accounts, not accounts, and a
    409 that said only "it moved" would leave the operator with no way to decide whether to
    re-preview or to insist.
    """
    if expected is None:
        return
    if abs(actual - expected) <= expected * tolerance:
        return
    raise ProblemError(
        AdminProblem(
            code=AdminErrorCode.CONFLICT,
            message="the audience has moved since the preview this was composed from",
            # Built as a mapping rather than through ``problem(**details)``'s keywords,
            # because these two keys are camelCase on the wire like every other detail this
            # API publishes (``generations.py``'s ``attemptId``) and a keyword cannot be.
            details={"expectedAudienceSize": expected, "audienceSize": actual},
        )
    )


def _entry(
    admin: CurrentAdmin,
    *,
    action: AuditAction,
    broadcast_id: UUID,
    field_names: tuple[str, ...],
    reason_code: AuditReasonCode,
    reason_ref: str | None = None,
    reason_text: str | None = None,
    record_count: int | None = None,
) -> AuditEntry:
    """One row for one campaign action. Every handler in this module builds its row here.

    ``subjectType`` is :data:`BROADCAST_SUBJECT_TYPE` and ``subjectId`` the campaign's UUID —
    never a recipient's Telegram id. A campaign has exactly one subject, and putting an account
    id here would make ``admin_audit_log`` the place a membership decision about forty thousand
    people accumulates, in the one table the purge deliberately cannot reach.

    ``recordCount`` is **how many people this authorises a message to**: the audience size on a
    send, a pause or a cancel, ``1`` on a test send, and the freshly-counted audience on a
    create. That is the column that makes "which operator sent to how many this month" a ``SUM``
    over an indexed action filter rather than a join, and it is what tells a forty-recipient
    test from a forty-thousand-recipient campaign without reading anybody's prose.

    ``fieldNames`` names columns and never their values — the rule every audit row in this
    package follows. The body text is named as a column for the same reason: what was said is
    on the campaign record, which is not on a 90-day clock, and copying it here would put
    operator copy into the table that cannot be purged.
    """
    return AuditEntry(
        action=action,
        actor_id=admin.admin_user_id,
        actor_username=admin.username[:ACTOR_USERNAME_LENGTH],
        actor_role=admin.role,
        subject_type=BROADCAST_SUBJECT_TYPE,
        subject_id=str(broadcast_id),
        field_names=field_names,
        record_count=record_count,
        reason_code=reason_code,
        reason_ref=reason_ref,
        reason_text=reason_text,
        outcome=AuditOutcome.OK,
        ip=admin.client_ip,
    )
