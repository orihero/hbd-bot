"""The statements behind the chat directory: one upsert, one selection, two verdicts.

The shape is the one :mod:`bayram.db.support_tickets`, :mod:`bayram.db.churn` and
:mod:`bayram.db.broadcasts` already keep, and it is a split rather than a style:

* the module-level functions take an ``AsyncSession`` first and positionally, take the clock as
  a parameter, let exceptions propagate and **never commit** — so the admin panel can compose
  :func:`select_support_group` into the request transaction its ``admin_audit_log`` row is
  already in, and a selection that failed to audit leaves the inbox where it was;
* :class:`SqlBotChats` is the never-throw facade in the ``SqlKitRepository`` idiom — one
  ``run_guarded`` delegation owning exactly one ``async with self._sessions.begin()`` — for the
  bot and the worker, which have no request transaction to join.

**THE SELECTION CLEARS BEFORE IT SETS, AND BOTH HALVES ARE IN ONE TRANSACTION.** That ordering
is not a preference. ``ix_bot_chats_selected_support_group`` is a PARTIAL UNIQUE index over
``is_support_group``, so the moment a second row holds ``true`` the write fails — and setting
the new row first trips it against a row this same transaction was about to clear. Clear, then
set, then commit. The index is still needed and is not redundant with the ordering: under
Postgres' READ COMMITTED two operators pressing Select at the same instant each read one
selected row, each clear the row they read, each set their own, and both commit. The
transaction is what makes the ordinary path not depend on a failure; the index is what closes
the path the transaction cannot. ``admin_users``' active-OWNER pair makes the identical
argument, and there it was measured rather than theorised.

**THE MEMBERSHIP UPSERT NAMES ITS COLUMNS, AND THE OTHER SIX ARE THE POINT.** ``ON CONFLICT DO
UPDATE`` here sets ``chat_type``, ``title``, ``username``, ``bot_status``, ``source``,
``last_seen_at`` and ``updated_at`` — and touches ``is_support_group``, ``thread_id``,
``selected_by_username``, ``selected_at``, ``verified_at`` and ``verification_error`` never.
An update that reset any of those would mean the bot being promoted to administrator in the
selected group, or re-added after a restart, silently unselected the support inbox: tickets
stop arriving, no request failed, nothing is in any log.
:class:`~bayram.bot_chats.MembershipSighting` carries only the writable six, so the rule
survives somebody adding a column later.

**NOTHING HERE HAS A ``server_default``, INCLUDING ``is_support_group``.** The table is created
empty and has no backfill (revision 0024's rule), so the mapper default covers ORM inserts and
every Core ``INSERT`` in this module supplies ``is_support_group``, ``first_seen_at`` and
``last_seen_at`` by hand. Omitting one is a NOT NULL violation at runtime rather than at import,
which is why they are written out in one place — :func:`_new_chat_values` — rather than at each
call site.

**There is no ``UPDATE … RETURNING`` anywhere below**, and the previous selection is therefore
read with its own ``SELECT`` before the clear. ``db/broadcasts.py`` states the rule this
follows: ``RETURNING`` is a construct this codebase uses nowhere and cannot portably rely on
across both engines. Every conditional write here is claimed by rowcount instead, one row at a
time, the way ``claim_chunk`` and ``claim_group_post`` are.

**``verified_at`` and ``verification_error`` are kept mutually exclusive by the writers** and
not by a ``CheckConstraint`` — :func:`mark_verified` clears the error and
:func:`mark_verification_failed` clears the clock. The direction that matters is the second:
a chat whose last check failed must not keep a green badge it earned yesterday, because that
badge is what an operator reads to decide the inbox is fine.

**THERE IS A THIRD WRITER OF THAT PAIR, AND IT IS THE SELECTION.**
:func:`select_support_group` NULLS both columns, because the pair does not mean "what we once
learned about this chat" — it means "the verdict on the selection as it now stands", and the
selection is the thing that just changed. The invariant every one of these five statements
maintains, and the one to check an edit against: **both null means a verdict is on its way;
either one set is a verdict about the current selection.** :func:`clear_support_group` and
:func:`record_membership` therefore do NOT touch the pair — neither of them enqueues anything,
so nulling from either would park a row in "checking…" for ever with nothing coming. The full
argument, including the kicked-bot case that cuts against it, is at
:func:`select_support_group`, which is where a reader tempted to "simplify" the statement will
be standing.

**Nothing in this module talks to Telegram and nothing decides policy.** Whether a chat is
worth verifying, what a failure should say, and whether the operator was allowed to press the
button are decisions for the caller; :mod:`bayram.bot_chats` holds the values and this module
holds the statements.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.bot_chats import (
    BotChatSnapshot,
    MembershipSighting,
    SelectionChange,
    SupportGroupTarget,
    chat_type_for_pasted_id,
)
from bayram.contracts import BotChatSource, BotChatStatus, BotChatType, Result
from bayram.db.credit_sql import rowcount_of, upsert_statement
from bayram.db.guard import run_guarded
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH
from bayram.db.models.bot_chat import (
    BOT_CHAT_TITLE_LENGTH,
    BOT_CHAT_USERNAME_LENGTH,
    VERIFICATION_ERROR_LENGTH,
    BotChatRow,
)
from bayram.errors import ValidationError

__all__ = [
    "record_membership",
    "selected_support_group",
    "selected_chat_id",
    "select_support_group",
    "clear_support_group",
    "mark_verified",
    "mark_verification_failed",
    "load_chat",
    "snapshot_of",
    "SqlBotChats",
]

#: One unit of work inside a transaction the facade owns. Named so
#: :meth:`SqlBotChats._in_session` has one signature rather than five inferred ones.
type _Work[T] = Callable[[AsyncSession], Coroutine[Any, Any, T]]

#: What an over-long string is cut down to end with, so a trimmed value is visibly trimmed.
#:
#: One character, which matters: the trim has to fit INSIDE the column's own bound, so the
#: marker is subtracted from the budget rather than added to it.
_ELLIPSIS: Final[str] = "…"


def _fit(value: str | None, limit: int) -> str | None:
    """Cut a string down to a column's declared width. ``None`` passes through untouched.

    **Trimming rather than raising is a decision, and it is not the usual one.** Everywhere
    else in this repo an over-long value is a ``ValidationError`` the caller has to fix, and the
    admin panel restates every bound as a pydantic validator so an operator gets a 422 naming
    the field rather than an ``IntegrityError`` out of a half-written transaction. The values
    trimmed here are different in kind: a chat title and a ``@handle`` come from TELEGRAM, so
    refusing them refuses a row about a group that really exists because a vendor changed a cap
    we do not control; and a verification error is prose about a failure, so refusing it means
    the one record of why an operator's inbox does not work is the record we threw away.

    In-memory SQLite enforces no length at all, which is the other half of the reason this
    exists: without it an over-long value would pass every unit test in the suite and raise a
    ``DataError`` the first time it met Postgres.
    """
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[: limit - len(_ELLIPSIS)] + _ELLIPSIS


# ---------------------------------------------------------------------------
# What the bot sees: one membership update
# ---------------------------------------------------------------------------
async def record_membership(
    session: AsyncSession, sighting: MembershipSighting, *, now: datetime
) -> bool:
    """Upsert the chat this ``my_chat_member`` update is about. ``True`` if it is new to us.

    The ``SELECT`` before the upsert exists only to answer that boolean, and it is an index
    probe on the primary key. It is not a check-then-act and nothing depends on it being
    race-free: two simultaneous first sightings of one chat would both report ``True`` and both
    write the same row, which costs one duplicated log line and no correctness at all. The
    upsert below is what actually decides.

    ``INSERT`` carries the columns a first sighting establishes; ``ON CONFLICT DO UPDATE``
    carries only what a later sighting may change. The six columns absent from the update
    clause are absent on purpose — see the module docstring, which is the one place that rule
    is argued, because it is the one way to break this table from outside it.

    **``verified_at`` stays put even when this sighting says the bot was KICKED**, which is the
    one absence a reader is likely to try to fix. :func:`select_support_group` argues it at
    length; the short form is that this process never tried to post, so it has no verdict to
    write, and nulling the pair from here would leave the row reading "checking…" with no job
    enqueued behind it. ``bot_status`` is what carries this news, and the panel tones ``kicked``
    and ``left`` as failures for exactly that reason.

    ``source`` IS in the update clause, and it moves in exactly one direction in practice: the
    only caller is the membership recorder, which always passes ``membership_event``, so a row
    an operator pasted by hand is promoted to Telegram's own word the first time Telegram says
    anything about it. That promotion is the point — a ``manual`` row is an unverified claim,
    and a membership update is evidence that supersedes it.
    """
    known = await session.scalar(
        sa.select(sa.literal(1))
        .select_from(BotChatRow)
        .where(BotChatRow.chat_id == sighting.chat_id)
    )
    await session.execute(
        upsert_statement(
            session,
            BotChatRow,
            _new_chat_values(
                chat_id=sighting.chat_id,
                chat_type=sighting.chat_type,
                title=sighting.title,
                username=sighting.username,
                bot_status=sighting.bot_status,
                source=BotChatSource.MEMBERSHIP_EVENT,
                seen_at=sighting.at,
                now=now,
            ),
            index_elements=["chat_id"],
            set_={
                "chat_type": sighting.chat_type,
                "title": _fit(sighting.title, BOT_CHAT_TITLE_LENGTH),
                "username": _fit(sighting.username, BOT_CHAT_USERNAME_LENGTH),
                "bot_status": sighting.bot_status,
                "source": BotChatSource.MEMBERSHIP_EVENT,
                # TELEGRAM's clock for the sighting, OURS for the row. Never the other way
                # round; :class:`MembershipSighting.at` argues why at length.
                "last_seen_at": sighting.at,
                "updated_at": now,
            },
        )
    )
    return known is None


# ---------------------------------------------------------------------------
# The selection
# ---------------------------------------------------------------------------
async def selected_support_group(session: AsyncSession) -> SupportGroupTarget | None:
    """Where ticket cards go, or ``None``. One row off the partial unique index.

    Two columns rather than the whole row, deliberately: this is the hot read on the posting
    path and the caller has no business holding ``bot_status`` while it decides whether to
    send. :func:`load_chat` is there for the reader that genuinely needs the rest.

    ``LIMIT 1`` even though the index makes a second row impossible. The limit costs nothing and
    means that a directory which somehow acquired two selected rows — an index dropped by hand,
    a migration run half-way — answers with one of them and keeps posting, rather than raising
    ``MultipleResultsFound`` in the middle of a customer's complaint.
    """
    row = (
        await session.execute(
            sa.select(BotChatRow.chat_id, BotChatRow.thread_id)
            .where(BotChatRow.is_support_group.is_(True))
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return SupportGroupTarget(chat_id=row.chat_id, thread_id=row.thread_id)


async def selected_chat_id(session: AsyncSession) -> int | None:
    """Just the id of the selected chat, for the writers that have to report what they moved.

    Public rather than private because the admin router needs it twice over: once to refuse a
    clear that would do nothing, and once to build the ``before`` half of an audit row. Reading
    it and then writing is not a check-then-act — the write below is unconditional and the index
    is what decides — the value is only ever used to describe what happened.
    """
    selected: int | None = await session.scalar(
        sa.select(BotChatRow.chat_id).where(BotChatRow.is_support_group.is_(True)).limit(1)
    )
    return selected


async def select_support_group(
    session: AsyncSession,
    chat_id: int,
    *,
    thread_id: int | None = None,
    selected_by_username: str,
    now: datetime,
) -> SelectionChange:
    """Point the support inbox at this chat, recording a ``manual`` row if it is unknown.

    **Clear, then set, then let the caller commit.** Both statements are in the caller's
    transaction, and the order is load-bearing: setting first trips
    ``ix_bot_chats_selected_support_group`` against the row this transaction was about to clear,
    which is an ``IntegrityError`` on the happy path. The module docstring argues why the index
    is nonetheless not redundant with the ordering.

    **An id the table has never heard of is INSERTED as ``source=manual``**, which is what makes
    this one endpoint rather than two. There is no separate "add a chat" call: Telegram has no
    "list my groups" API, so a group the bot was already in when this feature shipped can never
    be discovered and a pasted id is the only route that exists for it. The row is born with
    ``bot_status=unknown`` — nobody has told us anything about the bot's standing there, and
    ``unknown`` is in the enum for exactly this — and with a ``chat_type`` inferred from the id's
    shape (:func:`~bayram.bot_chats.chat_type_for_pasted_id`), which the verification job
    overwrites with ``getChat``'s answer. What the operator gets back is a selection that is
    honest about being unverified, not a claim that anything works.

    **THE CLAIM UPDATE NULLS ``verified_at`` AND ``verification_error``, AND THAT IS THE POINT
    OF THE STATEMENT RATHER THAN HOUSEKEEPING ATTACHED TO IT.** Three places already promise it
    — :attr:`SupportGroupView.verified_at` ("``None`` means nobody has checked since this row
    last changed"), ``api/support.ts``'s ``checking`` state ("**both null.** Nobody has checked
    since this row last changed") and ``SupportGroupDialog.tsx`` ("a row moves to *checking…*
    and stays there until ``verifiedAt`` or ``verificationError`` says otherwise") — and for the
    first cut of this feature the promise held only by accident, because every chat anybody
    selected in a test had never been verified.

    The invariant the reset establishes, stated so it can be checked rather than inferred:
    **a null pair means a verdict is on its way, and a non-null pair is a verdict about the
    selection as it now stands.** Without the reset both halves fail at once. Group A was the
    inbox in August and verified then; it was replaced by B, and somebody removed the bot from A
    meanwhile. An operator selects A today, and the 200 — and the refetch right behind it, which
    is all there is, because the panel deliberately does not poll — carry
    ``verified_at = 2026-08-01``. The row and the "Ticket cards go to" header both draw the
    accent "Posting works" badge for a room the bot was thrown out of, a second before the job
    writes the real 403 that nothing on screen will ever ask for. The mirror case is as bad: a
    chat whose last verdict was "the bot cannot post here" keeps the red sentence through a
    re-select, so an operator who has just fixed the permission in Telegram and pressed "Check
    again" is shown the identical red sentence and cannot tell whether the check ran.

    The three writes this covers are one write, which is why it is one statement and not three:
    a first selection, a re-select of the already-selected chat to move its topic, and the
    "Check again" button — which is this same endpoint pressed on the selected row, and has no
    other route to a fresh verdict. It deliberately does NOT cover the two neighbours:

    * :func:`clear_support_group` leaves the pair standing. Clearing enqueues nothing (there is
      no room to verify), so nulling here would park the row in "checking…" for ever with
      nothing coming — manufacturing exactly the lie this reset removes, in the other direction.
      An unselected row claims nothing about where tickets go, so its last verdict is history
      and reads as history.
    * :func:`record_membership` leaves it standing too, and the temptation is real: a chat the
      bot was just KICKED from arguably should not keep a green tick. It is refused on three
      grounds. The upsert's column list is the one way to break this table from outside it — the
      rule is written on the model, in this module's docstring and in the schema stream's
      hand-over — and a list that grows by one "obviously safe" column is how it grows by two.
      The bot process has no business writing verification verdicts at all; nothing it knows is
      the result of trying to post. And nulling from there would enqueue nothing either, so a
      bot re-added after a deploy would leave a verified inbox reading "checking…" with no job
      behind it. What the screen does instead is render ``bot_status`` beside the badge, where
      ``left`` and ``kicked`` are the two tones ``BOT_STATUS_TONE`` deliberately marks
      ``danger`` — a negative reading of that column is trustworthy in a way a positive one is
      not. Whether a removal should also *unselect* is spec §9's Q8 and is still open.

    **A chat the bot has been kicked from can still be selected**, and that is deliberate. The
    obvious guard — refuse unless ``bot_status`` is ``member`` or ``administrator`` — would
    block the ordinary recovery path, because ``delete_webhook(drop_pending_updates=True)`` on
    every start throws away the membership updates that arrived while the bot was down: a group
    the bot was re-added to during a deploy still reads ``kicked`` here and would be
    unselectable forever. ``bot_status`` is evidence and not permission; the verification job is
    what says whether the selection works.

    Returns what changed, because the caller cannot see it afterwards: by the time the audit row
    is composed the previous selection has already been cleared inside this transaction.
    """
    if not selected_by_username.strip():
        raise ValidationError(
            "a support group selection must name the operator who made it",
            context={"chat_id": chat_id},
        )
    # Refuses a non-negative id (a private chat — a person) before anything is written, and
    # supplies the type for the INSERT below if one is needed.
    inferred_type = chat_type_for_pasted_id(chat_id)
    previous = await selected_chat_id(session)
    await session.execute(
        sa.update(BotChatRow)
        .where(BotChatRow.is_support_group.is_(True))
        .values(is_support_group=False, updated_at=now)
    )
    actor = _fit(selected_by_username, ACTOR_USERNAME_LENGTH)
    claimed = await session.execute(
        sa.update(BotChatRow)
        .where(BotChatRow.chat_id == chat_id)
        .values(
            is_support_group=True,
            thread_id=thread_id,
            selected_by_username=actor,
            selected_at=now,
            # THE VERDICT IS RETIRED BY THE SELECTION. Not a tidy-up — see the docstring.
            verified_at=None,
            verification_error=None,
            updated_at=now,
        )
    )
    created = rowcount_of(claimed) == 0
    if created:
        await session.execute(
            sa.insert(BotChatRow).values(
                _new_chat_values(
                    chat_id=chat_id,
                    chat_type=inferred_type,
                    title=None,
                    username=None,
                    # Nobody has told us anything about the bot's standing in a chat somebody
                    # typed the number of. This is the member the enum carries for this case.
                    bot_status=BotChatStatus.UNKNOWN,
                    source=BotChatSource.MANUAL,
                    # OUR clock, and the only instant this row has: a manual chat has no
                    # Telegram transition behind it to borrow a stamp from.
                    seen_at=now,
                    now=now,
                    is_support_group=True,
                    thread_id=thread_id,
                    selected_by_username=actor,
                    selected_at=now,
                )
            )
        )
    return SelectionChange(
        chat_id=chat_id, previous_chat_id=previous, thread_id=thread_id, created=created
    )


async def clear_support_group(session: AsyncSession, *, now: datetime) -> int | None:
    """Unselect whatever is selected. Returns the chat that was, or ``None`` if none was.

    Tickets keep working with nothing selected — only the group post stops — so this is a
    supported state rather than a broken one, and the ``None`` return is an ordinary answer that
    lets the caller answer "there was nothing to clear" without a second read.

    **``selected_at``, ``selected_by_username`` and ``thread_id`` are deliberately left
    standing.** Only the boolean moves. "This was once the support group, chosen by this person,
    on that day, in that topic" is the most useful thing to know about a chat an operator is
    looking at while wondering where last month's tickets went — and re-selecting the same group
    later keeps the topic it always had instead of quietly reverting to the whole group.

    **``verified_at`` and ``verification_error`` are left standing too, and that is the opposite
    of what the select does.** :func:`select_support_group` nulls the pair because a selection
    enqueues a verification and the null pair is what the panel renders as "checking…". This
    write enqueues nothing — there is no room to verify and a verdict about a chat nobody is
    posting to is a red badge on a row that claims nothing — so nulling here would leave the row
    saying "checking…" for ever with no job behind it. That is the same lie the select's reset
    exists to remove, told the other way round. The last verdict on a chat that WAS the inbox is
    history, and it reads as history beside ``selected_at`` and ``selected_by_username``, which
    stay for the same reason.
    """
    previous = await selected_chat_id(session)
    if previous is None:
        return None
    await session.execute(
        sa.update(BotChatRow)
        .where(BotChatRow.is_support_group.is_(True))
        .values(is_support_group=False, updated_at=now)
    )
    return previous


# ---------------------------------------------------------------------------
# What the verification job found
# ---------------------------------------------------------------------------
async def mark_verified(
    session: AsyncSession,
    chat_id: int,
    *,
    at: datetime,
    title: str | None = None,
    username: str | None = None,
    chat_type: BotChatType | None = None,
) -> bool:
    """Stamp the proof that the bot can post here, and clear any stored failure.

    ``False`` when no such row exists, and **no row is created**. A verification result about a
    chat that is no longer in the directory is a job running against something an operator
    deleted; re-creating it would resurrect a chat somebody removed on purpose, and — worse —
    would do it with whatever partial information the job happened to hold.

    ``title``, ``username`` and ``chat_type`` are written only when supplied, because the caller
    has usually just learned them from ``getChat`` and a ``manual`` row pasted as a bare number
    has no title until exactly that moment. ``None`` leaves the stored value alone rather than
    blanking it: a verification that could erase a title would make the row an operator is least
    able to recognise harder still.

    ``chat_type`` is the one of the three that corrects a value rather than filling an empty
    one. A pasted id's type is INFERRED from its ``-100`` prefix
    (:func:`~bayram.bot_chats.chat_type_for_pasted_id`), which cannot distinguish a supergroup
    from a channel; that inference is acceptable only because ``getChat`` answers the question
    properly and this statement writes the answer down. It is never NULLed by a caller that did
    not ask, because the column is NOT NULL and a row must always spell some type.

    ``last_seen_at`` is NOT touched here, deliberately. That column is the MEMBERSHIP clock —
    the answer to "is this group still live?" for a bot that cannot ask Telegram that question —
    and a sweep that stamped it would make a chat the bot was thrown out of last week look
    recently seen because a job looked at it this morning. The stronger statement, that we
    actually posted, is ``verified_at``, and it is the column this function is for.
    """
    values: dict[str, Any] = {"verified_at": at, "verification_error": None, "updated_at": at}
    if title is not None:
        values["title"] = _fit(title, BOT_CHAT_TITLE_LENGTH)
    if username is not None:
        values["username"] = _fit(username, BOT_CHAT_USERNAME_LENGTH)
    if chat_type is not None:
        values["chat_type"] = chat_type
    result = await session.execute(
        sa.update(BotChatRow).where(BotChatRow.chat_id == chat_id).values(**values)
    )
    return rowcount_of(result) == 1


async def mark_verification_failed(
    session: AsyncSession, chat_id: int, *, message: str, at: datetime
) -> bool:
    """Record why the bot could not post here, and drop the stale proof that it could.

    ``False`` when no such row exists; nothing is created, for :func:`mark_verified`'s reason.

    **The message is trimmed to fit and a blank one is refused**, and the asymmetry is the
    point. Trimming: a failure that could not be stored because the caller pasted a traceback is
    a failure nobody ever sees, and the column exists to be read by an operator in a list row.
    Refusing a blank: a ``verification_error`` of ``""`` would render as a red row with nothing
    to act on, which is worse than either a real message or no error at all — so the caller is
    made to say something, and the four things worth saying (the chat was not found, the bot is
    not a member, the bot cannot post, the group migrated to a NEW id which must be named) are
    listed on :meth:`~bayram.bot_chats.BotChatDirectory.record_verification_failed`.

    **``verified_at`` is cleared.** The two columns are mutually exclusive by the writers rather
    than by a ``CheckConstraint`` — ``vendor_usage``'s call, restated on the model — and this is
    the direction that matters: a green badge earned yesterday, sitting beside today's failure,
    is exactly what an operator reads to conclude the inbox is fine.
    """
    trimmed = _fit(message.strip(), VERIFICATION_ERROR_LENGTH)
    if not trimmed:
        raise ValidationError(
            "a verification failure must say something an operator can act on",
            context={"chat_id": chat_id},
        )
    result = await session.execute(
        sa.update(BotChatRow)
        .where(BotChatRow.chat_id == chat_id)
        .values(verified_at=None, verification_error=trimmed, updated_at=at)
    )
    return rowcount_of(result) == 1


# ---------------------------------------------------------------------------
# Reading one back
# ---------------------------------------------------------------------------
async def load_chat(session: AsyncSession, chat_id: int) -> BotChatSnapshot | None:
    """One chat by id as a frozen value, or ``None`` when the directory has never heard of it.

    ``session.get`` would be the shorter spelling and is avoided on the same footing
    ``db/support_tickets.py`` takes: a Core ``UPDATE`` does not touch the session's identity
    map, so a ``get`` issued after one of the writes above can answer with the object as it was
    BEFORE the statement. A ``SELECT`` always asks the database.
    """
    row = await session.scalar(sa.select(BotChatRow).where(BotChatRow.chat_id == chat_id))
    return None if row is None else snapshot_of(row)


def snapshot_of(row: BotChatRow) -> BotChatSnapshot:
    """Mapped row to frozen value. Pure, and the only place the two shapes meet.

    Every column crosses. Unlike a ticket there is nothing here to withhold — no customer
    appears on this row at all, which is the property ``test_privacy_constraints.py`` records
    for this table and which holds only because ``my_chat_member.from_user`` is never stored.
    """
    return BotChatSnapshot(
        chat_id=row.chat_id,
        chat_type=row.chat_type,
        title=row.title,
        username=row.username,
        bot_status=row.bot_status,
        source=row.source,
        is_support_group=row.is_support_group,
        thread_id=row.thread_id,
        verified_at=row.verified_at,
        verification_error=row.verification_error,
        selected_by_username=row.selected_by_username,
        selected_at=row.selected_at,
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# The facade the bot and the worker hold
# ---------------------------------------------------------------------------
class SqlBotChats:
    """:class:`bayram.bot_chats.BotChatDirectory` over ``bot_chats``. Never raises.

    Owns its transaction — one per public method, no exceptions — and is held by the bot (which
    records sightings and asks where cards go) and by the worker (which asks the same question
    and writes the verification verdict). The admin process builds it too through
    ``build_container`` and never calls it: the panel's reads go through
    ``bayram.db.admin.bot_chats`` and its two writes are the module-level functions above,
    composed into the request transaction that carries the audit row.

    **It exposes no way to select or clear**, which is the protocol's decision and is restated
    here because this class is what a wiring line actually hands to a handler. A bot process
    holding a method that repoints the support inbox is a bot process one bug away from
    repointing it with no ``admin_audit_log`` row behind the move.
    """

    __slots__ = ("_sessions",)

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def record_membership(
        self, sighting: MembershipSighting, *, now: datetime
    ) -> Result[bool]:
        """Upsert one sighting. ``True`` means this chat was new to the directory."""
        return await run_guarded(
            "bot_chats.record_membership",
            lambda: self._in_session(lambda session: record_membership(session, sighting, now=now)),
            chat_id=sighting.chat_id,
            bot_status=sighting.bot_status.value,
        )

    async def selected_support_group(self) -> Result[SupportGroupTarget | None]:
        """Where ticket cards go. ``None`` is an ordinary answer — nothing is selected."""
        return await run_guarded(
            "bot_chats.selected_support_group",
            lambda: self._in_session(selected_support_group),
        )

    async def load_chat(self, chat_id: int) -> Result[BotChatSnapshot | None]:
        """One chat by id, for the job that was handed an id and must check it."""
        return await run_guarded(
            "bot_chats.load_chat",
            lambda: self._in_session(lambda session: load_chat(session, chat_id)),
            chat_id=chat_id,
        )

    async def record_verified(
        self,
        chat_id: int,
        *,
        at: datetime,
        title: str | None = None,
        username: str | None = None,
        chat_type: BotChatType | None = None,
    ) -> Result[bool]:
        """The bot posted here. ``False`` when the row is gone; none is created."""
        return await run_guarded(
            "bot_chats.record_verified",
            lambda: self._in_session(
                lambda session: mark_verified(
                    session, chat_id, at=at, title=title, username=username, chat_type=chat_type
                )
            ),
            chat_id=chat_id,
        )

    async def record_verification_failed(
        self, chat_id: int, *, message: str, at: datetime
    ) -> Result[bool]:
        """The bot could not post here, and this is why, in an operator's language."""
        return await run_guarded(
            "bot_chats.record_verification_failed",
            lambda: self._in_session(
                lambda session: mark_verification_failed(session, chat_id, message=message, at=at)
            ),
            chat_id=chat_id,
        )

    # -- internals -----------------------------------------------------------
    async def _in_session[T](self, work: _Work[T]) -> T:
        """One transaction, one delegation. Every public method above is this plus a name.

        Written once rather than five times because the thing that must not drift is the
        transaction boundary — the same reason ``SqlSupportTickets`` has one of these.
        """
        async with self._sessions.begin() as session:
            return await work(session)


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _new_chat_values(
    *,
    chat_id: int,
    chat_type: BotChatType,
    title: str | None,
    username: str | None,
    bot_status: BotChatStatus,
    source: BotChatSource,
    seen_at: datetime,
    now: datetime,
    is_support_group: bool = False,
    thread_id: int | None = None,
    selected_by_username: str | None = None,
    selected_at: datetime | None = None,
) -> dict[str, Any]:
    """The INSERT half of every write in this module, in one place.

    It exists because ``bot_chats`` carries NO ``server_default`` on any column — revision
    0024's no-backfill rule, restated on the model — so a Core ``INSERT`` that forgets
    ``is_support_group``, ``first_seen_at`` or ``last_seen_at`` is a NOT NULL violation at
    runtime and not at import. Two call sites spelling that out separately is one call site away
    from forgetting one; ``churn._new_user_values`` exists for the identical reason.

    ``created_at`` and ``updated_at`` are set explicitly rather than left to
    ``TimestampMixin``'s Python-side default. The default reads the ambient clock, and the whole
    point of taking ``now`` as a parameter is that a test can walk a chat through a week of
    membership changes without sleeping — leaving the hook to fire would make these the two
    columns that ignored the injected clock. On the ``ON CONFLICT DO UPDATE`` path it matters
    more than that: ``onupdate`` does not fire for an upsert at all, so ``updated_at`` would
    simply go stale.

    ``first_seen_at`` and ``last_seen_at`` are equal on a row that has been seen once, which is
    every row at the moment it is created.
    """
    return {
        "chat_id": chat_id,
        "chat_type": chat_type,
        "title": _fit(title, BOT_CHAT_TITLE_LENGTH),
        "username": _fit(username, BOT_CHAT_USERNAME_LENGTH),
        "bot_status": bot_status,
        "source": source,
        "is_support_group": is_support_group,
        "thread_id": thread_id,
        "selected_by_username": selected_by_username,
        "selected_at": selected_at,
        "first_seen_at": seen_at,
        "last_seen_at": seen_at,
        "created_at": now,
        "updated_at": now,
    }
