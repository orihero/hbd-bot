"""The campaign write side: creation, the frozen audience, and the claim that cannot double-send.

**THE NEVER-DOUBLE-SEND RULE, which is the reason this module is shaped the way it is.**
ARQ runs with ``retry_jobs=True`` and SIGTERM cancels a running task, so *every* broadcast
job in this system will be replayed — not rarely, but on every single deploy. The record of
who has been messaged therefore cannot live in the job; it lives in ``broadcast_recipients``,
and the ordering of two writes is the whole guarantee:

1. :func:`claim_chunk` moves a row ``PENDING -> SENDING`` and the caller **commits that**
   *before* the Telegram call is made;
2. only after the call returns does :func:`settle_recipient` move it ``SENDING -> SENT`` (or
   to one of the other terminal states).

A job killed between the two leaves the row in ``SENDING``, and **a row in ``SENDING`` is
never claimed again**. Nothing in this module can move it back to ``PENDING`` by itself:
:func:`age_stale_sending` retires it to
:attr:`~bayram.contracts.BroadcastRecipientState.UNKNOWN`, where it counts as neither sent nor
failed and the panel shows it as its own number.

That is a deliberate trade and it is worth stating in the direction it was decided:
**"we do not know whether 3 of 40 000 were delivered" is preferred over "3 people received
it twice."** An unresolved hole is visible, small, and explainable to the three people it
concerns; a duplicate message is a promise broken to a customer who did nothing wrong, at
whatever scale the campaign had. The counter is not smoothed to hide the hole, and the only
route from ``SENDING`` back to ``PENDING`` is :func:`release_recipient`, which a caller may
use **only** when it knows the request never left the process — never after a request whose
outcome is unknown.

**The claim is a conditional UPDATE whose ROWCOUNT is the answer, one row at a time.** The
blueprint's ``UPDATE … WHERE state='pending' AND id IN (…)`` says how *many* rows a caller
won and not *which*, and a chunk that sent to a row it did not win is precisely the
double-send above; there is no claim-token column to disambiguate it afterwards, and
``UPDATE … RETURNING`` is a construct this codebase uses nowhere and cannot portably rely on
across both engines. So each candidate is claimed by its own ``UPDATE … WHERE id = :id AND
state = 'pending'`` and a ``rowcount`` of 1 *is* the claim — the idiom :mod:`bayram.db.churn`
already uses, for the same reason it uses it: ``SELECT … FOR UPDATE`` would serve as well and
SQLite does not have it, so the unit suite could not exercise the production shape. The cost
is one small statement per message in a background job that is about to spend a tenth of a
second per message on the network.

**THE AUDIENCE IS FROZEN AT CREATION.** ``broadcasts.segment`` is a stored document and
``broadcast_recipients`` is materialised from it once, at creation, against
``audience_evaluated_at``. A campaign scheduled for Friday reaches whoever matched on
Tuesday. :func:`expand_chunk` is therefore the only writer of that table on the happy path,
and it is resumable by construction: it walks the ``(users.created_at, users.id)`` keyset —
the account order, never the campaign's display sort — writes through
:func:`~bayram.db.credit_sql.insert_or_ignore` against
``uq_broadcast_recipients_broadcast_id_telegram_user_id``, and persists the cursor it reached.
A replayed chunk re-inserts nothing: the re-run is a database no-op rather than a branch
somebody has to get right.

**There is no consent predicate here, and no opt-out.** The one suppression signal is a
block — the operator's bar (``users.is_blocked``) or Telegram telling us the customer blocked
the bot (``users.blocked_bot_at``). The two are never OR-ed into one stored fact
(``models/user.py``) and both land the recipient row as
:attr:`~bayram.contracts.BroadcastRecipientState.SKIPPED_BLOCKED` at expansion, *inserted rather
than filtered out*, so the funnel from audience to messages is arithmetic in the table
instead of a filter someone has to remember to apply.

Shape follows :mod:`bayram.db.churn` and :mod:`bayram.db.lyric_budget`: the module-level functions
take an ``AsyncSession`` first and positionally, take the clock as a parameter, let
exceptions propagate and **never commit**; :class:`SqlBroadcasts` is the never-throw facade
that owns exactly one ``async with self._sessions.begin()`` per public method.

**The panel does not use the facade.** An admin handler composes the module functions into
the request's own transaction so the campaign and its ``admin_audit_log`` row land together
or not at all; the facade exists for the worker, which has no request transaction to join.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import ColumnElement

from bayram.contracts import (
    BroadcastKind,
    BroadcastRecipientState,
    BroadcastState,
    Language,
    Result,
    is_err,
)
from bayram.db.admin.page import (
    Cursor,
    decode_cursor,
    encode_cursor,
    keyset_order,
    keyset_predicate,
)
from bayram.db.credit_sql import insert_or_ignore, rowcount_of
from bayram.db.enums import AdminRole, AuditReasonCode
from bayram.db.guard import run_guarded
from bayram.db.models.admin_user import AdminUserRow
from bayram.db.models.broadcast import BroadcastRow
from bayram.db.models.broadcast_body import BroadcastBodyRow
from bayram.db.models.broadcast_recipient import BroadcastRecipientRow
from bayram.db.models.user import UserRow

__all__ = [
    "EXPAND_CHUNK_SIZE",
    "SEND_CHUNK_SIZE",
    "DUE_SCAN_LIMIT",
    "STALE_SENDING_ERROR_CODE",
    "TERMINAL_BROADCAST_STATES",
    "TERMINAL_RECIPIENT_STATES",
    "BroadcastActor",
    "BroadcastBody",
    "NewBroadcast",
    "ExpansionChunk",
    "ClaimedRecipient",
    "RecipientTally",
    "BroadcastPlan",
    "ComposedBody",
    "DueBroadcast",
    "load_plan",
    "load_bodies",
    "due_broadcasts",
    "create_broadcast",
    "revise_broadcast",
    "mark_scheduled",
    "mark_sending",
    "pause",
    "resume",
    "cancel",
    "mark_finished",
    "expand_chunk",
    "claim_chunk",
    "settle_recipient",
    "release_recipient",
    "age_stale_sending",
    "roll_up_counters",
    "cache_media_file_id",
    "current_state",
    "decode_expand_cursor",
    "SqlBroadcasts",
]

#: Accounts materialised per expansion job run. Larger than a send chunk because expansion
#: pays only for statements, never for the network — nobody is waiting on it and the whole
#: audience is frozen before the first message leaves.
EXPAND_CHUNK_SIZE: Final[int] = 500

#: Messages claimed per send job run. At the pacer's dozen a second a chunk is under twenty
#: seconds of sending, which keeps one of the worker's slots for far less time than the
#: queue's job timeout and lets a pause take effect within a chunk rather than within a run.
SEND_CHUNK_SIZE: Final[int] = 200

#: Campaigns one pass of the due sweep will look at. Small, because the table gains a few
#: rows a week and the sweep runs twelve times an hour: a limit that could ever be reached
#: is a limit that has hidden a backlog, and the next pass five minutes later is the rest.
DUE_SCAN_LIMIT: Final[int] = 50

#: What :func:`age_stale_sending` writes on a row whose job died mid-send. A symbolic token
#: and not a message, on ``broadcast_recipients.error_code``'s own rule, and it names the
#: *cause* rather than the outcome: the outcome is ``UNKNOWN`` and stays unknown.
STALE_SENDING_ERROR_CODE: Final[str] = "sending_lease_expired"

#: A campaign that has stopped. Nothing moves it again — :func:`mark_finished` and
#: :func:`cancel` both refuse to re-finish one, so a replayed job is a no-op rather than a
#: second ``finished_at``.
TERMINAL_BROADCAST_STATES: Final[frozenset[BroadcastState]] = frozenset(
    {BroadcastState.COMPLETED, BroadcastState.CANCELLED, BroadcastState.FAILED}
)

#: A recipient row that has stopped moving. ``settled_at`` is stamped for every one of them,
#: which is why it is one clock named for settlement rather than a ``sent_at`` that could
#: only stamp the first.
TERMINAL_RECIPIENT_STATES: Final[frozenset[BroadcastRecipientState]] = frozenset(
    {
        BroadcastRecipientState.SENT,
        BroadcastRecipientState.FAILED,
        BroadcastRecipientState.SKIPPED_BLOCKED,
        BroadcastRecipientState.UNDELIVERABLE,
        BroadcastRecipientState.UNKNOWN,
    }
)

#: States a campaign may still be edited from — nothing has left the building yet. A revision
#: after the first message would mean two different texts under one title and one audit row.
_EDITABLE_STATES: Final[tuple[BroadcastState, ...]] = (
    BroadcastState.DRAFT,
    BroadcastState.EXPANDING,
    BroadcastState.READY,
)


@dataclass(frozen=True, slots=True)
class BroadcastActor:
    """Who did this, denormalised exactly as ``admin_audit_log`` denormalises an actor.

    Both halves are optional because a campaign must survive the operator: there is no
    foreign key to ``admin_users``, a deactivated account keeps its campaigns, and the
    tamper-evident record of the action itself is the audit row, not this pair. This is only
    what the list screen renders without a join.
    """

    admin_id: UUID | None = None
    username: str | None = None


@dataclass(frozen=True, slots=True)
class BroadcastBody:
    """One language's message: the text, an optional image and an optional URL button.

    The caption ceiling is **not** checked here. ``ck_broadcast_bodies_caption_length`` caps
    a body carrying media at ``BROADCAST_CAPTION_LENGTH``, and the API schema layer refuses
    an over-long one as a 422 before it reaches a statement — a length an operator can see
    while typing belongs in the validator, and the CHECK is the floor under it rather than
    the thing they meet first.

    :attr:`media_file_id` is absent by design: the cached Telegram id is written by the
    worker after the first successful send (:func:`cache_media_file_id`) and is never
    accepted from a caller, because the admin process is denied a bot token and cannot have
    minted one.
    """

    language: Language
    text: str
    media_storage_key: str | None = None
    button_label: str | None = None
    button_url: str | None = None


@dataclass(frozen=True, slots=True)
class NewBroadcast:
    """Everything a campaign is born with, in one value so no call site can omit half of it.

    :attr:`audience_size` and :attr:`audience_evaluated_at` are the frozen audience's
    evidence and are required rather than defaulted: the first is what
    :func:`~bayram.db.admin.users.count_segment_exactly` returned at creation, the second is the
    ``now`` the segment was compiled against. Without the pair, "why did twelve fewer people
    get this than the preview said" has no answer, and the answer is nearly always "they
    joined after Tuesday".
    """

    title: str
    kind: BroadcastKind
    #: The compiled document, stored verbatim. A copy and not a reference: a re-evaluated
    #: segment answers "who would match now", which on a campaign that has gone out is a
    #: different question wearing the same clothes.
    segment: Mapping[str, Any]
    segment_hash: str
    audience_size: int
    audience_evaluated_at: datetime
    bodies: tuple[BroadcastBody, ...]
    #: ``None`` sends as soon as the audience is materialised; an instant schedules it. There
    #: is no third option — see :func:`mark_scheduled`.
    scheduled_for: datetime | None = None
    created_by: BroadcastActor = BroadcastActor()
    reason_code: AuditReasonCode | None = None
    reason_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ExpansionChunk:
    """What one pass of :func:`expand_chunk` did, and whether the campaign still wanted it.

    :attr:`accepted` is ``False`` when the campaign left ``EXPANDING`` while this chunk was
    being written — a cancel, in practice. The recipient rows this pass inserted are still in
    the caller's transaction: the caller decides whether to commit them (harmless; a
    cancelled campaign sends nothing and ``ON DELETE CASCADE`` clears them with the row) or
    roll them back. What it must not do is enqueue a successor.
    """

    scanned: int
    inserted: int
    suppressed: int
    next_cursor: Cursor | None
    accepted: bool

    @property
    def is_complete(self) -> bool:
        """Whether the audience is now whole and the campaign is ``READY``."""
        return self.accepted and self.next_cursor is None


@dataclass(frozen=True, slots=True)
class ClaimedRecipient:
    """One row this caller — and no other — is entitled to send to.

    :attr:`telegram_user_id` is ``None`` for an account whose ``/forget`` ran between the
    expansion and the send. It is claimed rather than skipped so the campaign can finish:
    the caller settles it :attr:`~bayram.contracts.BroadcastRecipientState.UNDELIVERABLE`
    without calling Telegram, which keeps the funnel arithmetic instead of leaving a row that
    nothing will ever move.
    """

    id: UUID
    telegram_user_id: int | None
    language: Language
    attempts: int


@dataclass(frozen=True, slots=True)
class RecipientTally:
    """The ledger, counted. The rows are truth; the campaign's counters are a copy of this."""

    total: int
    pending: int
    sending: int
    sent: int
    failed: int
    skipped: int
    undeliverable: int
    unknown: int

    @property
    def outstanding(self) -> int:
        """Rows that have not settled. Zero is the only thing that ends a campaign.

        ``SENDING`` is counted here and not among the settled, which is why a campaign with a
        row left behind by a killed job does not finish until :func:`age_stale_sending` has
        retired it. Finishing over the top of it would report a send as complete while a
        message may still have been in flight.
        """
        return self.pending + self.sending


@dataclass(frozen=True, slots=True)
class BroadcastPlan:
    """Everything a worker needs about a campaign before it touches a recipient.

    One read rather than an ORM load of :class:`~bayram.db.models.broadcast.BroadcastRow`,
    because a job holds it across ``await`` points on which another process moves the row:
    a detached value cannot be mistaken for the current state, and the state a job acts on
    is re-read through :func:`current_state` at every decision point instead.

    :attr:`actor` and :attr:`actor_role` are for the OUTCOME audit row the send job writes
    when a campaign finishes. The actor is whoever scheduled it, falling back to whoever
    created it — a campaign sent immediately never passes through a separate schedule — and
    the ROLE is read live from ``admin_users``, because the campaign row deliberately does
    not denormalise it and the instant this row describes is the instant the worker finished,
    not the instant the operator pressed the button. ``None`` means the account is gone or
    was never set, and the audit row then records the system as the actor.
    """

    id: UUID
    state: BroadcastState
    kind: BroadcastKind
    #: The document exactly as it was stored: the WIRE shape the panel dumped, which is what
    #: the expansion job hands back to its decoder. Nothing here interprets it.
    segment: Mapping[str, Any]
    audience_evaluated_at: datetime
    expand_cursor: str | None
    scheduled_for: datetime | None
    actor: BroadcastActor
    actor_role: AdminRole | None
    reason_code: AuditReasonCode | None
    reason_ref: str | None


@dataclass(frozen=True, slots=True)
class ComposedBody:
    """One language's message as the worker sends it — the read counterpart of
    :class:`BroadcastBody`.

    It carries :attr:`media_file_id`, which the write side deliberately cannot: the id is
    minted by Telegram on the first send and cached by :func:`cache_media_file_id`, so it
    exists only in this direction. Everything else is the operator's text, sent verbatim —
    the body is HTML the compose step validated, never a catalogue key, and it is not passed
    through ``translate`` or escaped again at send time.
    """

    language: Language
    text: str
    media_storage_key: str | None
    media_file_id: str | None
    button_label: str | None
    button_url: str | None


@dataclass(frozen=True, slots=True)
class DueBroadcast:
    """A campaign the sweep found waiting, and why it is waiting.

    :attr:`state` is the whole decision: ``READY`` is the scheduled-send path (its instant
    has arrived, or it never had one), while ``EXPANDING`` and ``SENDING`` are the
    crash-recovery path — a campaign whose job died mid-chunk and whose row has not moved
    since. One query answers both because the answer is the same shape: enqueue the job that
    state is waiting for.
    """

    id: UUID
    state: BroadcastState
    scheduled_for: datetime | None
    audience_evaluated_at: datetime


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------
async def create_broadcast(session: AsyncSession, *, draft: NewBroadcast, at: datetime) -> UUID:
    """Write the campaign and its bodies. Returns the new id.

    Born ``EXPANDING`` and never ``DRAFT``: the audience is frozen at creation, so there is
    no state in which a campaign exists and its recipients have not begun to be materialised.
    ``BroadcastState.DRAFT`` stays in the enum for the panel's benefit and has no writer here
    — a campaign nobody has pointed at an audience is a form, not a row.

    Core inserts rather than ``session.add`` for :mod:`bayram.db.churn`'s reason: the caller
    composes this into a transaction it owns, and an ORM flush at a moment the caller did not
    choose would reorder it against the audit row that has to land beside it.
    """
    broadcast_id = uuid4()
    await session.execute(
        sa.insert(BroadcastRow).values(
            id=broadcast_id,
            title=draft.title,
            kind=draft.kind,
            state=BroadcastState.EXPANDING,
            segment=dict(draft.segment),
            segment_hash=draft.segment_hash,
            audience_size=draft.audience_size,
            audience_evaluated_at=draft.audience_evaluated_at,
            expand_cursor=None,
            scheduled_for=draft.scheduled_for,
            recipient_count=0,
            sent_count=0,
            failed_count=0,
            skipped_count=0,
            undeliverable_count=0,
            unknown_count=0,
            created_by_admin_id=draft.created_by.admin_id,
            created_by_username=draft.created_by.username,
            reason_code=draft.reason_code,
            reason_ref=draft.reason_ref,
            created_at=at,
            updated_at=at,
        )
    )
    await _insert_bodies(session, broadcast_id=broadcast_id, bodies=draft.bodies, at=at)
    return broadcast_id


async def revise_broadcast(
    session: AsyncSession,
    *,
    broadcast_id: UUID,
    title: str,
    bodies: Sequence[BroadcastBody],
    at: datetime,
) -> bool:
    """Replace the title and the whole body set. ``True`` when the campaign accepted it.

    ``False`` means the campaign has left :data:`_EDITABLE_STATES` — it is sending, paused or
    over — and nothing was written. That is a conditional ``UPDATE`` and not a read-then-write
    for the reason every guard in this module is: the send job runs in another process and
    the window between a ``SELECT`` and an ``UPDATE`` is exactly long enough for the first
    message to go out under the old text.

    **The audience is untouched.** A revision changes what is said, never who hears it: the
    segment, the frozen count and the materialised rows all stay. Re-pointing a campaign at a
    different audience is a new campaign, because the audit row that authorised this one
    named a number.

    The bodies are deleted and re-inserted rather than upserted per language, so a language
    dropped from the set actually disappears; an upsert would leave last week's Russian body
    attached to a campaign whose author removed it.
    """
    result = await session.execute(
        sa.update(BroadcastRow)
        .where(BroadcastRow.id == broadcast_id, BroadcastRow.state.in_(_EDITABLE_STATES))
        .values(title=title, updated_at=at)
    )
    if rowcount_of(result) != 1:
        return False
    await session.execute(
        sa.delete(BroadcastBodyRow).where(BroadcastBodyRow.broadcast_id == broadcast_id)
    )
    await _insert_bodies(session, broadcast_id=broadcast_id, bodies=bodies, at=at)
    return True


async def mark_scheduled(
    session: AsyncSession,
    *,
    broadcast_id: UUID,
    scheduled_for: datetime | None,
    scheduled_by: BroadcastActor,
    at: datetime,
    reason_code: AuditReasonCode | None = None,
    reason_ref: str | None = None,
) -> bool:
    """Authorise the send. ``True`` when the campaign was ``READY`` and took it.

    ``scheduled_for=None`` means *now* — the due sweep picks a ``READY`` campaign with no
    instant on the next pass, and the handler enqueues the first chunk directly. A future
    instant means the sweep waits for it. There is deliberately no third shape: a campaign is
    either sent immediately or scheduled for one moment, and "send it sometime this week" is
    a decision nobody could later show they made.

    Only from ``READY``. Authorising a campaign whose audience is still being materialised
    would schedule a send against a half-written ledger, which is the distinction
    ``EXPANDING`` and ``READY`` exist to keep.

    The free text of the reason is **not** copied here. ``admin_audit_log.reason_text`` owns
    it, along with the 90-day clock that sweeps it; a second copy on this row would be
    operator prose that nothing expires. Only the code and the reference land, and the
    handler writes the audit row in the same transaction.
    """
    result = await session.execute(
        sa.update(BroadcastRow)
        .where(BroadcastRow.id == broadcast_id, BroadcastRow.state == BroadcastState.READY)
        .values(
            scheduled_for=scheduled_for,
            scheduled_by_admin_id=scheduled_by.admin_id,
            scheduled_by_username=scheduled_by.username,
            reason_code=reason_code,
            reason_ref=reason_ref,
            updated_at=at,
        )
    )
    return rowcount_of(result) == 1


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
async def mark_sending(session: AsyncSession, *, broadcast_id: UUID, at: datetime) -> bool:
    """``READY -> SENDING``, stamping ``started_at``. ``True`` when this call was the start.

    ``False`` on a replay: the second send job to run for one campaign finds it already
    ``SENDING`` and proceeds to claim a chunk, which is correct — the guard exists so that
    ``started_at`` records the first message and not the last restart.
    """
    result = await session.execute(
        sa.update(BroadcastRow)
        .where(BroadcastRow.id == broadcast_id, BroadcastRow.state == BroadcastState.READY)
        .values(state=BroadcastState.SENDING, started_at=at, updated_at=at)
    )
    return rowcount_of(result) == 1


async def pause(session: AsyncSession, *, broadcast_id: UUID, at: datetime) -> bool:
    """``SENDING -> PAUSED``. ``True`` when this call paused it.

    The flag is all this does. The chunk job reads :func:`current_state` at the top of each
    chunk and again every few messages, so a pause takes effect within seconds of the
    operator pressing it rather than at the end of a chunk — and rows already claimed are
    settled rather than abandoned, because a claimed row has either been sent or is unknown
    and neither is undone by pausing.
    """
    result = await session.execute(
        sa.update(BroadcastRow)
        .where(BroadcastRow.id == broadcast_id, BroadcastRow.state == BroadcastState.SENDING)
        .values(state=BroadcastState.PAUSED, updated_at=at)
    )
    return rowcount_of(result) == 1


async def resume(session: AsyncSession, *, broadcast_id: UUID, at: datetime) -> bool:
    """``PAUSED -> SENDING``. ``True`` when this call resumed it.

    ``started_at`` is not re-stamped: a campaign starts once, and a resumed one that reported
    a new start would make its own duration unreadable.
    """
    result = await session.execute(
        sa.update(BroadcastRow)
        .where(BroadcastRow.id == broadcast_id, BroadcastRow.state == BroadcastState.PAUSED)
        .values(state=BroadcastState.SENDING, updated_at=at)
    )
    return rowcount_of(result) == 1


async def cancel(session: AsyncSession, *, broadcast_id: UUID, at: datetime) -> bool:
    """Stop the campaign for good. ``True`` when this call stopped it.

    Legal from every non-terminal state, including ``EXPANDING``: an operator who realises
    mid-expansion that the audience is wrong must not have to wait for it to finish. Rows
    already materialised stay — they are the evidence of what was about to happen — and
    :func:`expand_chunk` reports ``accepted=False`` on its next pass, which is how the
    expansion job learns to stop.

    Cancelling does **not** un-send what has gone. A campaign cancelled halfway is a
    cancelled campaign with ``sent_count`` messages already delivered, and the counters say
    so rather than being reset.
    """
    return await mark_finished(
        session, broadcast_id=broadcast_id, state=BroadcastState.CANCELLED, at=at
    )


async def mark_finished(
    session: AsyncSession,
    *,
    broadcast_id: UUID,
    state: BroadcastState,
    at: datetime,
    error_code: str | None = None,
) -> bool:
    """Move the campaign to a terminal state and stamp ``finished_at``.

    ``True`` when this call finished it; ``False`` when it was already terminal, which is
    what a replayed final chunk looks like and is not an error.

    ``FAILED`` grades the **run**, never the recipients: a campaign in which twelve of forty
    thousand messages were refused is ``COMPLETED``, and the per-account outcome lives on the
    recipient row. Rolling the two together is how "did it go out?" stops having an answer.

    Raises :class:`ValueError` for a non-terminal target. That is a caller bug rather than
    bad input — every state in this module is a literal at the call site — so it raises where
    everything else here returns a boolean.
    """
    if state not in TERMINAL_BROADCAST_STATES:
        raise ValueError(f"{state!r} is not a terminal broadcast state")
    result = await session.execute(
        sa.update(BroadcastRow)
        .where(
            BroadcastRow.id == broadcast_id,
            BroadcastRow.state.not_in(tuple(TERMINAL_BROADCAST_STATES)),
        )
        .values(state=state, finished_at=at, error_code=error_code, updated_at=at)
    )
    return rowcount_of(result) == 1


async def current_state(session: AsyncSession, *, broadcast_id: UUID) -> BroadcastState | None:
    """The campaign's state right now, or ``None`` if there is no such campaign.

    A column read rather than an ORM load, and it is read repeatedly: the chunk job checks it
    between messages so a pause or a cancel is honoured mid-chunk. The ORM row would come
    back from the identity map after this session's own writes, which is exactly the value a
    pause check must not see.
    """
    state: BroadcastState | None = await session.scalar(
        sa.select(BroadcastRow.state).where(BroadcastRow.id == broadcast_id)
    )
    return state


# ---------------------------------------------------------------------------
# What the worker reads before it acts
# ---------------------------------------------------------------------------
async def load_plan(session: AsyncSession, *, broadcast_id: UUID) -> BroadcastPlan | None:
    """One campaign, as the jobs need it. ``None`` when there is no such campaign.

    A ``None`` is an ordinary answer here and not a failure: a campaign deleted between the
    enqueue and the run leaves a job pointing at nothing, and the job's correct response is
    to log it and stop rather than to raise into the queue's retry ladder.

    The ``LEFT OUTER JOIN`` to ``admin_users`` exists for one column — the role the OUTCOME
    audit row records — and is an outer join because the campaign must survive the operator:
    there is no foreign key from ``broadcasts`` to ``admin_users``, a deactivated account
    keeps its campaigns, and a join that dropped the row would make a finished campaign
    unreportable because of who scheduled it.
    """
    scheduler = sa.orm.aliased(AdminUserRow)
    row = (
        await session.execute(
            sa.select(
                BroadcastRow.id,
                BroadcastRow.state,
                BroadcastRow.kind,
                BroadcastRow.segment,
                BroadcastRow.audience_evaluated_at,
                BroadcastRow.expand_cursor,
                BroadcastRow.scheduled_for,
                BroadcastRow.scheduled_by_admin_id,
                BroadcastRow.scheduled_by_username,
                BroadcastRow.created_by_admin_id,
                BroadcastRow.created_by_username,
                BroadcastRow.reason_code,
                BroadcastRow.reason_ref,
                scheduler.role.label("actor_role"),
            )
            .join(
                scheduler,
                scheduler.id
                == sa.func.coalesce(
                    BroadcastRow.scheduled_by_admin_id, BroadcastRow.created_by_admin_id
                ),
                isouter=True,
            )
            .where(BroadcastRow.id == broadcast_id)
        )
    ).first()
    if row is None:
        return None
    # Scheduled by, falling back to created by: a campaign sent immediately never passes
    # through a separate schedule, and the operator who composed it is the one who
    # authorised the send.
    actor = BroadcastActor(
        admin_id=row.scheduled_by_admin_id or row.created_by_admin_id,
        username=row.scheduled_by_username or row.created_by_username,
    )
    return BroadcastPlan(
        id=row.id,
        state=row.state,
        kind=row.kind,
        segment=row.segment,
        audience_evaluated_at=row.audience_evaluated_at,
        expand_cursor=row.expand_cursor,
        scheduled_for=row.scheduled_for,
        actor=actor,
        actor_role=row.actor_role,
        reason_code=row.reason_code,
        reason_ref=row.reason_ref,
    )


async def load_bodies(session: AsyncSession, *, broadcast_id: UUID) -> tuple[ComposedBody, ...]:
    """Every language's message, read once per chunk rather than once per recipient.

    A campaign has at most one body per language and four languages exist, so this is a
    handful of rows the send loop resolves in memory — the alternative, a lookup per
    recipient, is two hundred index probes per chunk to answer the same four questions.
    """
    rows = (
        await session.execute(
            sa.select(
                BroadcastBodyRow.language,
                BroadcastBodyRow.text,
                BroadcastBodyRow.media_storage_key,
                BroadcastBodyRow.media_file_id,
                BroadcastBodyRow.button_label,
                BroadcastBodyRow.button_url,
            )
            .where(BroadcastBodyRow.broadcast_id == broadcast_id)
            .order_by(BroadcastBodyRow.language)
        )
    ).all()
    return tuple(
        ComposedBody(
            language=row.language,
            text=row.text,
            media_storage_key=row.media_storage_key,
            media_file_id=row.media_file_id,
            button_label=row.button_label,
            button_url=row.button_url,
        )
        for row in rows
    )


async def due_broadcasts(
    session: AsyncSession,
    *,
    now: datetime,
    stalled_before: datetime,
    limit: int = DUE_SCAN_LIMIT,
) -> tuple[DueBroadcast, ...]:
    """Campaigns whose moment has come, and campaigns whose job did not come back.

    **Two predicates, one query, because the sweep's job is one sentence: enqueue what is
    waiting.** A ``READY`` campaign is waiting for its instant — ``NULL`` means "as soon as
    possible", which is what a send-now campaign carries — and an ``EXPANDING`` or
    ``SENDING`` one whose row has not been touched since ``stalled_before`` is waiting for a
    worker that died. Both are answered by enqueueing the job that state expects, and a
    duplicate enqueue costs nothing: expansion is idempotent by unique constraint and the
    send claims row by row.

    ``stalled_before`` is an instant the caller computes from its own clock and the lease,
    for :func:`age_stale_sending`'s reason: the lease is a deployment's setting and this
    stays a function of its arguments. It is compared against ``broadcasts.updated_at``,
    which every chunk's roll-up re-stamps — so a campaign being actively worked on is never
    picked up here and the sweep cannot fan out one live campaign into twelve chains an hour.

    ``PAUSED`` is deliberately absent. A pause is an operator decision and a sweep that
    resumed it would be a machine overruling a person.
    """
    is_due = sa.and_(
        BroadcastRow.state == BroadcastState.READY,
        sa.or_(BroadcastRow.scheduled_for.is_(None), BroadcastRow.scheduled_for <= now),
    )
    is_stalled = sa.and_(
        BroadcastRow.state.in_((BroadcastState.EXPANDING, BroadcastState.SENDING)),
        BroadcastRow.updated_at <= stalled_before,
    )
    rows = (
        await session.execute(
            sa.select(
                BroadcastRow.id,
                BroadcastRow.state,
                BroadcastRow.scheduled_for,
                BroadcastRow.audience_evaluated_at,
            )
            .where(sa.or_(is_due, is_stalled))
            # Oldest campaign first: a backlog is worked off in the order it was authorised,
            # never in the order the index happened to return.
            .order_by(BroadcastRow.created_at, BroadcastRow.id)
            .limit(limit)
        )
    ).all()
    return tuple(
        DueBroadcast(
            id=row.id,
            state=row.state,
            scheduled_for=row.scheduled_for,
            audience_evaluated_at=row.audience_evaluated_at,
        )
        for row in rows
    )


# ---------------------------------------------------------------------------
# Expansion — the frozen audience, materialised
# ---------------------------------------------------------------------------
def decode_expand_cursor(raw: str | None) -> Cursor | None:
    """Read ``broadcasts.expand_cursor`` back. ``None`` means "start from the beginning".

    Raises rather than returning an ``Err``: this token was minted by
    :func:`expand_chunk` and written by us, so a token that will not parse is a corrupted row
    or a changed encoding, not a caller mistake — the same line :func:`sort_expression` draws
    between validated input and a broken invariant.
    """
    if raw is None:
        return None
    decoded = decode_cursor(raw)
    if is_err(decoded):
        raise decoded.error
    return decoded.value


async def expand_chunk(
    session: AsyncSession,
    *,
    broadcast_id: UUID,
    predicate: ColumnElement[bool] | None,
    cursor: Cursor | None,
    at: datetime,
    limit: int = EXPAND_CHUNK_SIZE,
) -> ExpansionChunk:
    """Materialise one keyset page of the frozen audience. Re-running a page writes nothing.

    ``predicate`` is :func:`~bayram.db.admin.segment.compile_segment`'s output for the stored
    document, compiled against ``audience_evaluated_at`` and **not** against ``at``: the
    audience is the one the operator approved, and a chunk that re-read the clock would let
    the second half of an expansion match a different population from the first.

    **The walk is the account order, never the campaign's display sort.** ``(users.created_at
    DESC, users.id DESC)`` is a total order over an indexed pair; the segment's sort is a
    presentation of the preview, and resuming a cursor over an aggregate subquery for fifty
    thousand rows would make every chunk pay for the whole sort again.

    Every scanned account gets a row, including the ones that cannot be messaged: a blocked
    account — the operator's bar or the customer's own — is inserted ``SKIPPED_BLOCKED`` and
    already settled, so "audience minus skips equals messages" is arithmetic a reader can do
    on the table rather than a filter they have to remember. There is no consent predicate;
    a block is the only suppression signal this system has.

    The insert goes through :func:`~bayram.db.credit_sql.insert_or_ignore` against
    ``uq_broadcast_recipients_broadcast_id_telegram_user_id``, so a replayed job inserts
    nothing and :attr:`ExpansionChunk.inserted` comes back zero — the ``user_activity_
    snapshots`` idempotency shape, where a re-run is a database no-op instead of a branch.
    One statement per account rather than one multi-row ``VALUES`` clause, because the
    per-row boolean is what makes that no-op observable rather than assumed.

    The cursor and the running count are persisted by a conditional ``UPDATE`` that also
    flips the campaign to ``READY`` on the last page; ``accepted=False`` means the campaign
    stopped wanting this (see :class:`ExpansionChunk`).
    """
    statement = sa.select(
        UserRow.id,
        UserRow.telegram_user_id,
        UserRow.ui_language,
        UserRow.is_blocked,
        UserRow.blocked_bot_at,
        UserRow.created_at,
    )
    if predicate is not None:
        statement = statement.where(predicate)
    resume_at = keyset_predicate(UserRow.created_at, UserRow.id, cursor)
    if resume_at is not None:
        statement = statement.where(resume_at)
    scanned = (
        await session.execute(
            statement.order_by(*keyset_order(UserRow.created_at, UserRow.id)).limit(limit + 1)
        )
    ).all()
    # The probe row detects a next page and is not itself written — ``build_page``'s trick,
    # spelled out here because this walk yields rows to INSERT rather than a page to render.
    kept = scanned[:limit]
    next_cursor = (
        Cursor(at=kept[-1].created_at, id=kept[-1].id) if len(scanned) > limit and kept else None
    )
    inserted = 0
    suppressed = 0
    for row in kept:
        blocked = row.is_blocked or row.blocked_bot_at is not None
        if blocked:
            suppressed += 1
        state = (
            BroadcastRecipientState.SKIPPED_BLOCKED if blocked else BroadcastRecipientState.PENDING
        )
        written = await insert_or_ignore(
            session,
            BroadcastRecipientRow,
            {
                # Discarded on conflict; the row that is already there keeps its own id.
                "id": uuid4(),
                "broadcast_id": broadcast_id,
                "telegram_user_id": row.telegram_user_id,
                "language": row.ui_language,
                "state": state,
                "attempts": 0,
                "error_code": None,
                # A skipped row is settled the moment it is written: it has already reached
                # its final state and nothing will move it again.
                "settled_at": at if blocked else None,
                "created_at": at,
                "updated_at": at,
            },
            index_elements=["broadcast_id", "telegram_user_id"],
        )
        if written:
            inserted += 1
    progressed = await session.execute(
        sa.update(BroadcastRow)
        .where(BroadcastRow.id == broadcast_id, BroadcastRow.state == BroadcastState.EXPANDING)
        .values(
            expand_cursor=None if next_cursor is None else encode_cursor(next_cursor),
            recipient_count=BroadcastRow.recipient_count + inserted,
            state=BroadcastState.EXPANDING if next_cursor is not None else BroadcastState.READY,
            updated_at=at,
        )
    )
    return ExpansionChunk(
        scanned=len(kept),
        inserted=inserted,
        suppressed=suppressed,
        next_cursor=next_cursor,
        accepted=rowcount_of(progressed) == 1,
    )


# ---------------------------------------------------------------------------
# The send ledger
# ---------------------------------------------------------------------------
async def claim_chunk(
    session: AsyncSession, *, broadcast_id: UUID, at: datetime, limit: int = SEND_CHUNK_SIZE
) -> tuple[ClaimedRecipient, ...]:
    """Take exclusive ownership of up to ``limit`` pending rows. Only the winner gets a row.

    **This is the statement that makes concurrent workers safe, and the shape is the point.**
    Candidates are read first — the ``(broadcast_id, state)`` index narrows straight to them
    — and then each is claimed by its own ``UPDATE … WHERE id = :id AND state = 'pending'``
    whose ``rowcount`` of 1 *is* the claim. A row another worker took between the read and
    the update updates nothing and is simply absent from what comes back, so two callers
    racing over one row produce one sender and one silence. There is no ``IN`` list here on
    purpose: its rowcount says how many rows were won and not which, and sending to a row
    this caller did not win is the double-send the module docstring refuses.

    The caller **must commit before the first Telegram call.** A claim that is still in an
    uncommitted transaction is not a claim; the whole guarantee is that the row says
    ``SENDING`` in the database before the message can possibly leave.

    ``attempts`` is incremented in the same statement, so a row that has been claimed twice
    says so as a number rather than as an inference from a log.
    """
    candidates = (
        await session.execute(
            sa.select(
                BroadcastRecipientRow.id,
                BroadcastRecipientRow.telegram_user_id,
                BroadcastRecipientRow.language,
                BroadcastRecipientRow.attempts,
            )
            .where(
                BroadcastRecipientRow.broadcast_id == broadcast_id,
                BroadcastRecipientRow.state == BroadcastRecipientState.PENDING,
            )
            # Oldest first, so a campaign drains in the order it was materialised. The sort
            # is over the pending remainder only, which shrinks by a chunk on every pass.
            .order_by(BroadcastRecipientRow.created_at, BroadcastRecipientRow.id)
            .limit(limit)
        )
    ).all()
    claimed: list[ClaimedRecipient] = []
    for candidate in candidates:
        won = await session.execute(
            sa.update(BroadcastRecipientRow)
            .where(
                BroadcastRecipientRow.id == candidate.id,
                BroadcastRecipientRow.state == BroadcastRecipientState.PENDING,
            )
            .values(
                state=BroadcastRecipientState.SENDING,
                attempts=BroadcastRecipientRow.attempts + 1,
                updated_at=at,
            )
        )
        if rowcount_of(won) == 1:
            claimed.append(
                ClaimedRecipient(
                    id=candidate.id,
                    telegram_user_id=candidate.telegram_user_id,
                    language=candidate.language,
                    attempts=candidate.attempts + 1,
                )
            )
    return tuple(claimed)


async def settle_recipient(
    session: AsyncSession,
    *,
    recipient_id: UUID,
    state: BroadcastRecipientState,
    at: datetime,
    error_code: str | None = None,
) -> bool:
    """Close one claimed row. ``True`` when this call settled it.

    Guarded on ``SENDING`` so only the claimant can settle, and so a replayed job cannot
    overwrite the outcome of a row that has already been closed — ``False`` means somebody
    else got there, which on a replay is the correct and expected answer.

    ``error_code`` is a symbolic token: an :mod:`bayram.errors` member or a Telegram error
    class. **Never an excerpt of a response body**, on ``vendor_usage``'s argument that a
    third party's error text can quote what we sent it.

    Raises :class:`ValueError` for a non-terminal target, for :func:`mark_finished`'s reason.
    """
    if state not in TERMINAL_RECIPIENT_STATES:
        raise ValueError(f"{state!r} is not a terminal recipient state")
    result = await session.execute(
        sa.update(BroadcastRecipientRow)
        .where(
            BroadcastRecipientRow.id == recipient_id,
            BroadcastRecipientRow.state == BroadcastRecipientState.SENDING,
        )
        .values(state=state, settled_at=at, error_code=error_code, updated_at=at)
    )
    return rowcount_of(result) == 1


async def release_recipient(session: AsyncSession, *, recipient_id: UUID, at: datetime) -> bool:
    """Hand a claimed row back to the queue. ``True`` when this call released it.

    **The one route from ``SENDING`` back to ``PENDING``, and it is narrow on purpose.** A
    caller may use it only when it knows the request never left the process — Telegram
    answered ``retry_after`` before the send, or a pause was noticed between the claim and
    the call. After a request whose outcome is unknown this function is the double-send:
    settle the row :attr:`~bayram.contracts.BroadcastRecipientState.UNKNOWN` instead, or leave
    it in ``SENDING`` for :func:`age_stale_sending` to retire.

    ``attempts`` is deliberately not decremented. It counts claims, not deliveries, and a row
    that keeps being claimed and released is a row an operator should be able to see.
    """
    result = await session.execute(
        sa.update(BroadcastRecipientRow)
        .where(
            BroadcastRecipientRow.id == recipient_id,
            BroadcastRecipientRow.state == BroadcastRecipientState.SENDING,
        )
        .values(state=BroadcastRecipientState.PENDING, updated_at=at)
    )
    return rowcount_of(result) == 1


async def age_stale_sending(
    session: AsyncSession, *, broadcast_id: UUID, older_than: datetime, at: datetime
) -> int:
    """Retire rows abandoned in ``SENDING`` to ``UNKNOWN``. Rows touched.

    **This is where the never-double-send rule is paid for.** A job killed mid-send leaves
    its claimed row behind, and nothing retries it: after the lease expires it becomes
    ``UNKNOWN``, which counts as neither sent nor failed and which the panel renders as its
    own number. The alternative — returning it to ``PENDING`` — would message some customers
    twice, every deploy, forever.

    ``older_than`` is an instant the caller computes from its own clock and the lease, rather
    than a duration computed here, so the lease is a setting the deployment owns and this
    function stays a function of its arguments. It compares against ``updated_at``, which the
    claim stamped, so the lease runs from the claim and not from the campaign.

    A bulk ``UPDATE``: the rowcount is a report, not a decision, and no row's outcome depends
    on which of them it covered.
    """
    result = await session.execute(
        sa.update(BroadcastRecipientRow)
        .where(
            BroadcastRecipientRow.broadcast_id == broadcast_id,
            BroadcastRecipientRow.state == BroadcastRecipientState.SENDING,
            BroadcastRecipientRow.updated_at < older_than,
        )
        .values(
            state=BroadcastRecipientState.UNKNOWN,
            settled_at=at,
            error_code=STALE_SENDING_ERROR_CODE,
            updated_at=at,
        )
    )
    return rowcount_of(result)


async def roll_up_counters(
    session: AsyncSession, *, broadcast_id: UUID, at: datetime
) -> RecipientTally:
    """Recount the ledger and copy it onto the campaign. Two statements, never one per row.

    One grouped ``SELECT`` over ``(broadcast_id, state)`` and one ``UPDATE``, so the cost of
    a progress bar is constant in the size of the audience rather than linear in it.

    **The rows are truth and the counters are a cache**, which is why every number is
    recomputed here rather than incremented at each settlement: an increment lost to a
    rollback or doubled by a replay would drift silently, and the number an operator reads
    while deciding whether to pause is the one that must not.

    ``recipient_count`` is recomputed too. During expansion it is the running total
    :func:`expand_chunk` maintains; once the ledger exists this is the count that is actually
    in it, which is the number ``audience_size`` beside it is meant to be compared against.
    """
    grouped = (
        await session.execute(
            sa.select(BroadcastRecipientRow.state, sa.func.count())
            .where(BroadcastRecipientRow.broadcast_id == broadcast_id)
            .group_by(BroadcastRecipientRow.state)
        )
    ).all()
    counts = {state: int(count) for state, count in grouped}
    tally = RecipientTally(
        total=sum(counts.values()),
        pending=counts.get(BroadcastRecipientState.PENDING, 0),
        sending=counts.get(BroadcastRecipientState.SENDING, 0),
        sent=counts.get(BroadcastRecipientState.SENT, 0),
        failed=counts.get(BroadcastRecipientState.FAILED, 0),
        skipped=counts.get(BroadcastRecipientState.SKIPPED_BLOCKED, 0),
        undeliverable=counts.get(BroadcastRecipientState.UNDELIVERABLE, 0),
        unknown=counts.get(BroadcastRecipientState.UNKNOWN, 0),
    )
    await session.execute(
        sa.update(BroadcastRow)
        .where(BroadcastRow.id == broadcast_id)
        .values(
            recipient_count=tally.total,
            sent_count=tally.sent,
            failed_count=tally.failed,
            skipped_count=tally.skipped,
            undeliverable_count=tally.undeliverable,
            unknown_count=tally.unknown,
            updated_at=at,
        )
    )
    return tally


async def cache_media_file_id(
    session: AsyncSession,
    *,
    broadcast_id: UUID,
    language: Language,
    file_id: str,
    at: datetime,
) -> bool:
    """Remember the ``file_id`` Telegram minted for this body's image. ``True`` when stored.

    The panel uploads an image to our object store because the admin process is denied a bot
    token and cannot mint a ``file_id`` at all; the worker uploads it once, on the first send,
    and every message after that references the id instead of the bytes. Same cost control as
    ``assets.tg_file_id``, and the same reason it is written from exactly one place.

    Guarded on ``media_storage_key IS NOT NULL AND media_file_id IS NULL``, which mirrors
    ``ck_broadcast_bodies_media_pair`` and makes the write once-only: a second worker that
    also uploaded gets ``False`` and keeps the first id, so the two do not fight over which
    upload the rest of the campaign quotes.

    ``at`` is threaded like every other clock here rather than left to the mapper's
    ``onupdate``: this module reads no clock of its own, so a job replayed an hour later
    stamps the row with the instant the send belonged to rather than the instant the retry
    happened to land.
    """
    result = await session.execute(
        sa.update(BroadcastBodyRow)
        .where(
            BroadcastBodyRow.broadcast_id == broadcast_id,
            BroadcastBodyRow.language == language,
            BroadcastBodyRow.media_storage_key.is_not(None),
            BroadcastBodyRow.media_file_id.is_(None),
        )
        .values(media_file_id=file_id, updated_at=at)
    )
    return rowcount_of(result) == 1


async def _insert_bodies(
    session: AsyncSession, *, broadcast_id: UUID, bodies: Sequence[BroadcastBody], at: datetime
) -> None:
    """Write one row per language. Core, for :func:`create_broadcast`'s reason.

    ``media_file_id`` is never written here: it is the worker's, and a create path that could
    set it would be a create path that could quote a ``file_id`` nobody minted.
    """
    for body in bodies:
        await session.execute(
            sa.insert(BroadcastBodyRow).values(
                id=uuid4(),
                broadcast_id=broadcast_id,
                language=body.language,
                text=body.text,
                media_storage_key=body.media_storage_key,
                media_file_id=None,
                button_label=body.button_label,
                button_url=body.button_url,
                created_at=at,
                updated_at=at,
            )
        )


class SqlBroadcasts:
    """The worker's never-throw handle on a campaign. One transaction per method.

    The same division of labour :class:`~bayram.db.churn.SqlBotBlocks` keeps: the module
    functions above are composable and let exceptions out; this class owns exactly one
    ``async with self._sessions.begin()`` per call and turns every failure into a typed
    ``Err`` through :func:`~bayram.db.guard.run_guarded`, so no job body carries a ``try``.

    **One transaction per method is the contract the send pipeline depends on, not an
    implementation detail.** :meth:`claim` must commit before the caller touches Telegram —
    that commit is what makes the claim visible to every other replica — and :meth:`settle`
    must commit on its own so a crash in the next message cannot roll back the outcome of
    this one. Batching them would reintroduce exactly the window the state machine exists to
    close.

    The two ``raise``-instead-of-``Err`` cases upstream (a non-terminal state handed to
    :func:`mark_finished` or :func:`settle_recipient`) are caller bugs and stay exceptions:
    ``run_guarded`` translates database and schema failures, not literals somebody mistyped.
    """

    __slots__ = ("_sessions",)

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def state_of(self, broadcast_id: UUID) -> Result[BroadcastState | None]:
        """The campaign's state, for the pause check the chunk job runs between messages."""
        return await run_guarded(
            "broadcasts.state_of",
            lambda: self._state_of(broadcast_id),
            broadcast_id=str(broadcast_id),
        )

    async def plan(self, broadcast_id: UUID) -> Result[BroadcastPlan | None]:
        """The campaign as a job needs it. ``Ok(None)`` when it no longer exists."""
        return await run_guarded(
            "broadcasts.plan",
            lambda: self._plan(broadcast_id),
            broadcast_id=str(broadcast_id),
        )

    async def bodies(self, broadcast_id: UUID) -> Result[tuple[ComposedBody, ...]]:
        """Every language's message, read once per chunk."""
        return await run_guarded(
            "broadcasts.bodies",
            lambda: self._bodies(broadcast_id),
            broadcast_id=str(broadcast_id),
        )

    async def due(
        self, *, now: datetime, stalled_before: datetime, limit: int = DUE_SCAN_LIMIT
    ) -> Result[tuple[DueBroadcast, ...]]:
        """What the sweep must enqueue: campaigns due, and campaigns whose job died."""
        return await run_guarded(
            "broadcasts.due",
            lambda: self._due(now, stalled_before, limit),
            now=now.isoformat(),
        )

    async def expand(
        self,
        broadcast_id: UUID,
        *,
        predicate: ColumnElement[bool] | None,
        cursor: Cursor | None,
        at: datetime,
        limit: int = EXPAND_CHUNK_SIZE,
    ) -> Result[ExpansionChunk]:
        """Materialise one page of the frozen audience."""
        return await run_guarded(
            "broadcasts.expand",
            lambda: self._expand(broadcast_id, predicate, cursor, at, limit),
            broadcast_id=str(broadcast_id),
        )

    async def start(self, broadcast_id: UUID, *, at: datetime) -> Result[bool]:
        """``READY -> SENDING``. ``False`` on a replay, which is not a failure."""
        return await run_guarded(
            "broadcasts.start",
            lambda: self._start(broadcast_id, at),
            broadcast_id=str(broadcast_id),
        )

    async def claim(
        self, broadcast_id: UUID, *, at: datetime, limit: int = SEND_CHUNK_SIZE
    ) -> Result[tuple[ClaimedRecipient, ...]]:
        """Claim a chunk. The commit this method performs is what makes the claim exclusive."""
        return await run_guarded(
            "broadcasts.claim",
            lambda: self._claim(broadcast_id, at, limit),
            broadcast_id=str(broadcast_id),
        )

    async def settle(
        self,
        recipient_id: UUID,
        *,
        state: BroadcastRecipientState,
        at: datetime,
        error_code: str | None = None,
    ) -> Result[bool]:
        """Close one claimed row, in its own transaction."""
        return await run_guarded(
            "broadcasts.settle",
            lambda: self._settle(recipient_id, state, at, error_code),
            recipient_id=str(recipient_id),
            state=state.value,
        )

    async def release(self, recipient_id: UUID, *, at: datetime) -> Result[bool]:
        """Return a claimed row to the queue. See :func:`release_recipient` for when."""
        return await run_guarded(
            "broadcasts.release",
            lambda: self._release(recipient_id, at),
            recipient_id=str(recipient_id),
        )

    async def age_stale(
        self, broadcast_id: UUID, *, older_than: datetime, at: datetime
    ) -> Result[int]:
        """Retire rows abandoned in ``SENDING``. Rows touched."""
        return await run_guarded(
            "broadcasts.age_stale",
            lambda: self._age_stale(broadcast_id, older_than, at),
            broadcast_id=str(broadcast_id),
        )

    async def roll_up(self, broadcast_id: UUID, *, at: datetime) -> Result[RecipientTally]:
        """Recount the ledger onto the campaign's counters."""
        return await run_guarded(
            "broadcasts.roll_up",
            lambda: self._roll_up(broadcast_id, at),
            broadcast_id=str(broadcast_id),
        )

    async def finish(
        self,
        broadcast_id: UUID,
        *,
        state: BroadcastState,
        at: datetime,
        error_code: str | None = None,
    ) -> Result[bool]:
        """Move the campaign to a terminal state."""
        return await run_guarded(
            "broadcasts.finish",
            lambda: self._finish(broadcast_id, state, at, error_code),
            broadcast_id=str(broadcast_id),
            state=state.value,
        )

    async def remember_media_file_id(
        self, broadcast_id: UUID, *, language: Language, file_id: str, at: datetime
    ) -> Result[bool]:
        """Cache the ``file_id`` of this body's image after the first successful send."""
        return await run_guarded(
            "broadcasts.remember_media_file_id",
            lambda: self._remember_media_file_id(broadcast_id, language, file_id, at),
            broadcast_id=str(broadcast_id),
            language=language.value,
        )

    async def _state_of(self, broadcast_id: UUID) -> BroadcastState | None:
        async with self._sessions.begin() as session:
            return await current_state(session, broadcast_id=broadcast_id)

    async def _plan(self, broadcast_id: UUID) -> BroadcastPlan | None:
        async with self._sessions.begin() as session:
            return await load_plan(session, broadcast_id=broadcast_id)

    async def _bodies(self, broadcast_id: UUID) -> tuple[ComposedBody, ...]:
        async with self._sessions.begin() as session:
            return await load_bodies(session, broadcast_id=broadcast_id)

    async def _due(
        self, now: datetime, stalled_before: datetime, limit: int
    ) -> tuple[DueBroadcast, ...]:
        async with self._sessions.begin() as session:
            return await due_broadcasts(
                session, now=now, stalled_before=stalled_before, limit=limit
            )

    async def _expand(
        self,
        broadcast_id: UUID,
        predicate: ColumnElement[bool] | None,
        cursor: Cursor | None,
        at: datetime,
        limit: int,
    ) -> ExpansionChunk:
        async with self._sessions.begin() as session:
            return await expand_chunk(
                session,
                broadcast_id=broadcast_id,
                predicate=predicate,
                cursor=cursor,
                at=at,
                limit=limit,
            )

    async def _start(self, broadcast_id: UUID, at: datetime) -> bool:
        async with self._sessions.begin() as session:
            return await mark_sending(session, broadcast_id=broadcast_id, at=at)

    async def _claim(
        self, broadcast_id: UUID, at: datetime, limit: int
    ) -> tuple[ClaimedRecipient, ...]:
        async with self._sessions.begin() as session:
            return await claim_chunk(session, broadcast_id=broadcast_id, at=at, limit=limit)

    async def _settle(
        self,
        recipient_id: UUID,
        state: BroadcastRecipientState,
        at: datetime,
        error_code: str | None,
    ) -> bool:
        async with self._sessions.begin() as session:
            return await settle_recipient(
                session, recipient_id=recipient_id, state=state, at=at, error_code=error_code
            )

    async def _release(self, recipient_id: UUID, at: datetime) -> bool:
        async with self._sessions.begin() as session:
            return await release_recipient(session, recipient_id=recipient_id, at=at)

    async def _age_stale(self, broadcast_id: UUID, older_than: datetime, at: datetime) -> int:
        async with self._sessions.begin() as session:
            return await age_stale_sending(
                session, broadcast_id=broadcast_id, older_than=older_than, at=at
            )

    async def _roll_up(self, broadcast_id: UUID, at: datetime) -> RecipientTally:
        async with self._sessions.begin() as session:
            return await roll_up_counters(session, broadcast_id=broadcast_id, at=at)

    async def _finish(
        self, broadcast_id: UUID, state: BroadcastState, at: datetime, error_code: str | None
    ) -> bool:
        async with self._sessions.begin() as session:
            return await mark_finished(
                session, broadcast_id=broadcast_id, state=state, at=at, error_code=error_code
            )

    async def _remember_media_file_id(
        self, broadcast_id: UUID, language: Language, file_id: str, at: datetime
    ) -> bool:
        async with self._sessions.begin() as session:
            return await cache_media_file_id(
                session,
                broadcast_id=broadcast_id,
                language=language,
                file_id=file_id,
                at=at,
            )
