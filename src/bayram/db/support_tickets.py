"""Writing a complaint down: the ticket row, its timeline, and the latch on its group card.

The shape is the one :mod:`bayram.db.broadcasts`, :mod:`bayram.db.churn` and
:mod:`bayram.db.lyric_budget` already keep, and it is a split rather than a style:

* the module-level functions take an ``AsyncSession`` first and positionally, take the clock
  as a parameter, let exceptions propagate and **never commit** — so the admin panel can
  compose them into the request transaction its ``admin_audit_log`` row is already in, and a
  status change that failed to audit leaves the ticket unmoved;
* :class:`SqlSupportTickets` is the never-throw facade in the ``SqlKitRepository`` idiom —
  one ``run_guarded`` delegation owning exactly one ``async with self._sessions.begin()`` —
  for the bot and the worker, which have no request transaction to join.

**THE GROUP-POST LATCH IS A CONDITIONAL UPDATE AND ITS ROWCOUNT IS THE LOCK.** ARQ runs with
``retry_jobs=True`` and SIGTERM cancels running jobs, so every job in this system is replayed
on every deploy: a record of "the card was posted" that lives in the job posts the card twice,
and two cards for one ticket means a staffer answering on the one the relay is not listening
to. So :func:`claim_group_post` writes ``group_chat_id``/``group_message_id`` under
``WHERE group_message_id IS NULL``, a rowcount of 1 *is* the claim, and the caller commits
that **before** the Telegram call. ``UPDATE … RETURNING`` would say the same thing in one
statement and is not available: it is a construct this codebase uses nowhere and cannot
portably rely on across both engines (``db/broadcasts.py`` states this in full), so every
conditional write below is claimed one row at a time by rowcount the way ``claim_chunk`` does.

The unique index behind that latch is over the PAIR — ``(group_chat_id, group_message_id)`` —
and never over ``group_message_id`` alone, because a Telegram ``message_id`` is a counter
*within one chat* and a global unique index would assert something Telegram never promised.
Move the support group (a new group, or Telegram auto-upgrading a basic group to a supergroup,
which changes the chat id) and the next card numbered 5 in the new chat collides with a card
numbered 5 in the old one: the post succeeded, the latch raises ``IntegrityError``, and the
ticket is left permanently un-latched behind a card nothing can edit or relay from. The model
argues that at length; the statements below simply key on both columns everywhere, and a
lookup or a claim written against the message id alone is the thing that is wrong.

Even so the index is a **backstop and deliberately not the latch**. An ``IntegrityError`` would
also stop a second post, but only by aborting the transaction it arrived in — which on the
panel's path is the transaction carrying the audit row — and it would arrive as a failure
rather than as the ordinary "somebody else already did this" that a replayed job actually is.

**Every status move names the status it expects.** ``support_tickets.status`` has a Python-side
default of ``NEW`` and that default is the ONLY unconditional write of the column; every later
move is ``WHERE id = :id AND status = :expected``. Two staffers pressing ``✅ Resolve`` on one
card therefore produce one move, one ``STATUS_CHANGE`` event and one loser who is told to
re-read, rather than two events claiming the ticket was resolved twice.

**``updated_at`` is set by hand in every ``UPDATE`` below**, overriding
``TimestampMixin``'s ``onupdate=utc_now``. The mixin's hook reads the ambient clock, and the
whole point of taking ``now`` as a parameter is that a test can move a ticket through four
days of board moves without sleeping; leaving the hook to fire would make ``updated_at`` the
one column on the row that ignored the injected clock.

**Reads after a write use ``populate_existing``.** A Core ``UPDATE`` does not touch the
session's identity map, so a plain ``session.get`` afterwards answers with the object as it was
BEFORE the statement — the same trap ``db/lyric_budget.py`` avoids by selecting columns. Here
the refresh is explicit instead, because a snapshot is thirteen columns and naming them twice
is two places for a field to go missing.

**Nothing in this module talks to Telegram and nothing decides policy.** Whether a card may be
posted at all (is the group configured?), what it says, and whether the customer is over their
quota are decisions for the caller; :mod:`bayram.support` holds the rules and this module holds
the statements.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bayram.contracts import (
    Language,
    Result,
    SupportTicketEventKind,
    SupportTicketSource,
    SupportTicketStatus,
)
from bayram.db.credit_sql import rowcount_of
from bayram.db.guard import run_guarded
from bayram.db.models.support_ticket import SupportTicketRow
from bayram.db.models.support_ticket_event import SupportTicketEventRow
from bayram.errors import StorageError, ValidationError
from bayram.support import (
    DEFAULT_SUPPORT_QUOTA,
    SUPPORT_PUBLIC_REF_CHARS,
    EventAuthor,
    SupportQuota,
    TicketQuotaVerdict,
    TicketSnapshot,
    is_legal_move,
    public_ref_for,
)

__all__ = [
    "MINT_ATTEMPTS",
    "mint_ticket_identity",
    "quota_verdict",
    "open_ticket",
    "attach_prompt",
    "listen_on",
    "find_latest_undescribed",
    "find_by_prompt",
    "describe",
    "claim_group_post",
    "settle_group_post",
    "release_group_post",
    "find_by_group_message",
    "move_status",
    "assign",
    "append_event",
    "mark_relayed",
    "load_ticket",
    "snapshot_of",
    "SqlSupportTickets",
]

#: One unit of work inside a transaction the facade owns. Named so
#: :meth:`SqlSupportTickets._in_session` has one signature rather than fifteen lambdas'
#: worth of inferred ones.
type _Work[T] = Callable[[AsyncSession], Coroutine[Any, Any, T]]

#: How many candidate references :func:`mint_ticket_identity` will try before giving up.
#:
#: Five, and the loop exists because ``public_ref`` is eight hex characters of a UUID and the
#: column is UNIQUE — the birthday bound, not the address space, is what bites. At a hundred
#: thousand tickets the chance that any two share a prefix is a fraction of a percent, so in
#: practice the first candidate always wins and the loop costs one indexed probe; what it buys
#: is that the improbable case is a second ``uuid4`` rather than an ``IntegrityError`` raised
#: in front of a customer who is already annoyed.
#:
#: Five rather than "until it works", because an unbounded retry against a genuinely full
#: keyspace is a hot loop holding a transaction open, and the honest answer at that point is a
#: retryable failure somebody can see.
MINT_ATTEMPTS: Final[int] = 5


# ---------------------------------------------------------------------------
# Opening
# ---------------------------------------------------------------------------
async def mint_ticket_identity(
    session: AsyncSession, *, attempts: int = MINT_ATTEMPTS
) -> tuple[UUID, str]:
    """A fresh ticket id and the public reference derived from it, known to be free.

    The id is minted HERE rather than left to the model's ``default=uuid4`` because the
    reference is a function of the id (:func:`bayram.support.public_ref_for`) and the two must
    be the same id — a row whose ref came from one UUID and whose primary key came from
    another would look correct in every test and resolve to nothing when support typed it in.

    The ``SELECT`` before the ``INSERT`` is a probe and not a guarantee, and the race it leaves
    is the one worth leaving: two customers would have to mint colliding eight-character
    prefixes within the same instant, which is the negligible case squared, and the unique
    index is still there to refuse it. What the probe removes is the *ordinary* collision —
    the one that happens because the table has grown — and it removes it without a ``SAVEPOINT``
    around every insert.
    """
    for _ in range(attempts):
        candidate = uuid4()
        reference = public_ref_for(candidate)
        taken = await session.scalar(
            sa.select(sa.literal(1))
            .select_from(SupportTicketRow)
            .where(SupportTicketRow.public_ref == reference)
            .limit(1)
        )
        if taken is None:
            return candidate, reference
    raise StorageError(
        "could not mint an unused support reference",
        context={"attempts": attempts, "reference_chars": SUPPORT_PUBLIC_REF_CHARS},
    )


async def quota_verdict(
    session: AsyncSession,
    telegram_user_id: int,
    *,
    now: datetime,
    quota: SupportQuota = DEFAULT_SUPPORT_QUOTA,
) -> TicketQuotaVerdict:
    """Two counts over ``support_tickets``, and the verdict they imply. Reads nothing else.

    **An undescribed ticket that an operator has RESOLVED does not count against the
    customer.** That is the only remedy available when somebody has genuinely filled their
    three slots with taps they never followed up: closing them gives the slots back. Counting
    resolved rows too would make the quota permanent, which turns an abuse rail into a ban.

    The daily count is over every ticket regardless of status, because that ceiling is about
    what the group was asked to absorb and a card posted is a card posted.

    Both statements are served by ``ix_support_tickets_telegram_user_id``; neither is bounded
    the way :func:`bayram.db.admin.page.bounded_total` bounds a list count, because the numbers
    here are single digits by construction and a ceiling on the count of a ceiling would be
    absurd.
    """
    undescribed = await session.scalar(
        sa.select(sa.func.count())
        .select_from(SupportTicketRow)
        .where(
            SupportTicketRow.telegram_user_id == telegram_user_id,
            SupportTicketRow.described_at.is_(None),
            SupportTicketRow.status != SupportTicketStatus.RESOLVED,
        )
    )
    opened_today = await session.scalar(
        sa.select(sa.func.count())
        .select_from(SupportTicketRow)
        .where(
            SupportTicketRow.telegram_user_id == telegram_user_id,
            SupportTicketRow.created_at >= _day_start(now),
        )
    )
    held = int(undescribed or 0)
    today = int(opened_today or 0)
    return TicketQuotaVerdict(
        is_allowed=held < quota.max_undescribed and today < quota.max_per_day,
        undescribed=held,
        opened_today=today,
        quota=quota,
    )


async def open_ticket(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    language: Language,
    source: SupportTicketSource,
    order_id: UUID | None,
    now: datetime,
) -> TicketSnapshot:
    """Write the row a tap creates — no body, no ``described_at`` — and its ``OPENED`` event.

    ``body`` and ``described_at`` are left NULL deliberately and are not a half-written row:
    a customer who taps ⚠️ and never types is the state a large minority of tickets stay in,
    and it is the only measure of how many people started to complain and gave up. See the
    model's docstring.

    The ``OPENED`` event is written in the same statement batch as the row, so a ticket can
    never exist with an empty timeline — the panel's detail read would otherwise show a
    complaint that apparently happened to nobody.

    ``status`` is not passed. The mapper's ``default=SupportTicketStatus.NEW`` is the one
    unconditional write of that column in this module; every later move names the status it
    expects.
    """
    ticket_id, reference = await mint_ticket_identity(session)
    session.add(
        SupportTicketRow(
            id=ticket_id,
            public_ref=reference,
            telegram_user_id=telegram_user_id,
            language=language,
            source=source,
            order_id=order_id,
            created_at=now,
            updated_at=now,
        )
    )
    await append_event(
        session,
        ticket_id,
        kind=SupportTicketEventKind.OPENED,
        author=EventAuthor.customer(telegram_user_id),
        now=now,
    )
    await session.flush()
    return _require(await load_ticket(session, ticket_id), ticket_id)


async def attach_prompt(
    session: AsyncSession, ticket_id: UUID, *, prompt_message_id: int, now: datetime
) -> bool:
    """Record the ForceReply message this ticket is waiting on. ``True`` when a row moved.

    Conditional on the ticket having no prompt yet, which is what makes a replayed handler
    harmless: a second ForceReply for the same ticket would orphan the first, and the first is
    the one the customer can still see scrolled up their chat. ``False`` therefore means
    "already prompted" or "unknown id", and the caller should not send a second prompt.
    """
    result = await session.execute(
        sa.update(SupportTicketRow)
        .where(
            SupportTicketRow.id == ticket_id,
            SupportTicketRow.prompt_message_id.is_(None),
        )
        .values(prompt_message_id=prompt_message_id, updated_at=now)
    )
    return rowcount_of(result) == 1


async def listen_on(
    session: AsyncSession, ticket_id: UUID, *, prompt_message_id: int, now: datetime
) -> bool:
    """Point a ticket at the message it should now hear replies to. ``True`` when it moved.

    **Unconditional on the current value, and that is the whole difference from
    :func:`attach_prompt`.** That one is conditional on ``prompt_message_id IS NULL`` so a
    replayed open cannot orphan a ForceReply the customer can still see scrolled up their
    chat. This one is called when a NEWER message has taken over the conversation — the relay
    of a staff answer, which ends by inviting the customer to reply to it — and a conditional
    write there would leave the ticket listening on a prompt from three weeks ago while the
    customer answers the paragraph in front of them. That is the routing hole ``REPLY`` events
    from customers did not exist to fill: the follow-up matched no ticket, fell past the
    support router, and was taken as wizard input.

    Do not "simplify" the two into one unconditional write. ``attach_prompt``'s condition is
    what makes the open path idempotent, and this function's absence of one is what makes the
    conversation follow the customer's screen. They are the same column and two different
    questions.
    """
    result = await session.execute(
        sa.update(SupportTicketRow)
        .where(SupportTicketRow.id == ticket_id)
        .values(prompt_message_id=prompt_message_id, updated_at=now)
    )
    return rowcount_of(result) == 1


async def find_latest_undescribed(
    session: AsyncSession, telegram_user_id: int
) -> TicketSnapshot | None:
    """This account's newest ticket that was opened and never described, or ``None``.

    The row handed back when a customer is at the undescribed ceiling, so the ⚠️ button's
    fourth tap re-prompts the ticket they are already holding instead of refusing them —
    §1.4's rule, which the first build implemented as a refusal and which a BLOCKED customer
    turned into a closed loop: three empty tickets, a quota that would not let them open a
    fourth, and no way to describe any of them.

    ``status != RESOLVED`` matches :func:`quota_verdict`'s own predicate exactly, and the two
    must keep matching: a ticket the counter has stopped charging for is a ticket this must
    not hand back, or the customer is re-prompted about a complaint an operator has closed.

    Newest first, because that is the prompt still on their screen. Limited to one — there is
    no list of a customer's tickets anywhere in this bot, by design.
    """
    row = (
        await session.execute(
            sa.select(SupportTicketRow)
            .where(
                SupportTicketRow.telegram_user_id == telegram_user_id,
                SupportTicketRow.described_at.is_(None),
                SupportTicketRow.status != SupportTicketStatus.RESOLVED,
            )
            .order_by(SupportTicketRow.created_at.desc(), SupportTicketRow.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return None if row is None else snapshot_of(row)


# ---------------------------------------------------------------------------
# The customer's words
# ---------------------------------------------------------------------------
async def find_by_prompt(
    session: AsyncSession, telegram_user_id: int, *, prompt_message_id: int
) -> TicketSnapshot | None:
    """The ticket this customer's reply belongs to — described or not — or ``None``.

    **Both keys are required and the account one is not decoration.**
    ``prompt_message_id`` is a per-chat counter, so two customers hold the same value as a
    matter of routine; a lookup on the message id alone would attach one person's complaint to
    another person's ticket and then relay a stranger's answer back.

    **``described_at IS NULL`` used to be in this predicate and its removal is the fix for a
    critical routing hole, not a loosening.** With it, the only private message this feature
    could ever claim was the answer to a fresh ForceReply. A customer replying to a relayed
    staff answer — which ``support.ticket.reply`` ends by inviting them to do — matched
    nothing, fell past the support router, and was claimed by whichever wizard step they were
    parked in: at ``Wizard.name`` "thanks, it is fine now" became the RECIPIENT'S NAME and the
    pipeline sang it. The narrowing that protects the FIRST complaint from being overwritten
    is not here at all — it is :func:`describe`'s own ``WHERE described_at IS NULL``, which is
    the right place for it, because that is the statement that would do the overwriting.

    Ordered newest-first and limited to one: a customer who somehow holds two tickets on one
    prompt id (a prompt resent after an ``attach_prompt`` that lost its race) gets the one they
    most recently saw, which is the one they are replying to.
    """
    row = (
        await session.execute(
            sa.select(SupportTicketRow)
            .where(
                SupportTicketRow.telegram_user_id == telegram_user_id,
                SupportTicketRow.prompt_message_id == prompt_message_id,
            )
            .order_by(SupportTicketRow.created_at.desc(), SupportTicketRow.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return None if row is None else snapshot_of(row)


async def describe(
    session: AsyncSession, ticket_id: UUID, *, body: str, now: datetime
) -> TicketSnapshot | None:
    """Fill the body, stamp ``described_at``, write the ``DESCRIBED`` event. ``None`` if lost.

    Conditional on ``described_at IS NULL``, so the FIRST message a customer sends is the
    complaint and a second one cannot silently replace it. That direction is chosen rather
    than last-write-wins because a customer's follow-up ("sorry, I meant Dilnora") is an
    addition to the record, not a correction of it — and the record is what an operator
    pastes from months later.

    The event is written only when the row actually moved, so a replayed handler does not add
    a second ``DESCRIBED`` row to a timeline that already has one.

    ``body`` is stored exactly as the customer typed it. It is NOT escaped here: escaping is a
    property of the surface something is rendered on (``bayram.bot.i18n.escape_html`` at the
    card, the JSON encoder at the panel), and a database holding pre-escaped text is a database
    whose contents depend on where they were going.
    """
    result = await session.execute(
        sa.update(SupportTicketRow)
        .where(SupportTicketRow.id == ticket_id, SupportTicketRow.described_at.is_(None))
        .values(body=body, described_at=now, updated_at=now)
    )
    if rowcount_of(result) != 1:
        return None
    ticket = _require(await load_ticket(session, ticket_id, fresh=True), ticket_id)
    await append_event(
        session,
        ticket_id,
        kind=SupportTicketEventKind.DESCRIBED,
        author=EventAuthor.customer(ticket.telegram_user_id),
        now=now,
        body=body,
    )
    return ticket


# ---------------------------------------------------------------------------
# The group card — a once-only latch, never a cache
# ---------------------------------------------------------------------------
async def claim_group_post(
    session: AsyncSession, ticket_id: UUID, *, group_chat_id: int, group_message_id: int
) -> bool:
    """Take the once-only right to have posted this card. ``True`` means this caller won it.

    **The caller must commit before the Telegram call.** A claim sitting in an uncommitted
    transaction is not a claim; the entire guarantee is that the row names the message id in
    the database before a second worker can read it. ``db/broadcasts.py``'s ``claim_chunk``
    states the same rule for the same reason, one table along.

    ``False`` is an ordinary answer and not an error: it means another replay of the same ARQ
    job already posted this ticket's card, which happens on every deploy.

    The awkward part, said out loud: Telegram hands out the ``message_id`` only in the
    *response* to ``sendMessage``, so a claim made beforehand cannot know it. The caller
    therefore claims with the id it is about to use — which for the card is impossible — or,
    as the shipped flow does, sends first and claims second, accepting that a crash between
    the two leaves a card in the group with no row pointing at it. That is the direction the
    ticket is allowed to fail in: an orphaned card is a message a staffer replies to and gets
    no relay from (visible, and repairable by :func:`release_group_post` plus a repost),
    whereas an un-latched ticket that is posted twice is two cards racing each other. What
    this function guarantees is that only ONE of the racing senders' message ids is ever
    recorded, so the relay has exactly one card to listen to.
    """
    result = await session.execute(
        sa.update(SupportTicketRow)
        .where(
            SupportTicketRow.id == ticket_id,
            SupportTicketRow.group_message_id.is_(None),
        )
        .values(group_chat_id=group_chat_id, group_message_id=group_message_id)
    )
    return rowcount_of(result) == 1


async def settle_group_post(session: AsyncSession, ticket_id: UUID, *, now: datetime) -> bool:
    """Stamp ``group_posted_at`` and write the ``GROUP_POSTED`` event. ``True`` when it moved.

    Separate from the claim, and stamped afterwards, so that a row with a message id and no
    clock is legible as exactly what it is: a send that crashed between Telegram accepting the
    card and us writing it down. Conditional on the clock being unset, so a replay does not add
    a second ``GROUP_POSTED`` row to the timeline.
    """
    result = await session.execute(
        sa.update(SupportTicketRow)
        .where(
            SupportTicketRow.id == ticket_id,
            SupportTicketRow.group_message_id.is_not(None),
            SupportTicketRow.group_posted_at.is_(None),
        )
        .values(group_posted_at=now, updated_at=now)
    )
    if rowcount_of(result) != 1:
        return False
    await append_event(
        session,
        ticket_id,
        kind=SupportTicketEventKind.GROUP_POSTED,
        author=EventAuthor.system(),
        now=now,
    )
    return True


async def release_group_post(session: AsyncSession, ticket_id: UUID) -> bool:
    """Give an unsettled claim back, so the card can be posted again. ``True`` when released.

    **Only legal when the send provably never left this process** — the request was refused
    before it was made, or the client raised before writing a byte. A caller that released a
    claim after a request whose outcome is UNKNOWN would post a second card into the group,
    and two cards for one ticket means a staffer answering on the one the relay is not
    listening to. ``db/broadcasts.py``'s ``release_recipient`` carries the identical warning,
    and this is the identical trade: a ticket that is visibly un-posted is better than a
    ticket that is posted twice.

    ``group_posted_at IS NULL`` is in the predicate so a SETTLED post can never be released,
    whatever a caller believes. No event is written: nothing happened that a timeline should
    claim did.
    """
    result = await session.execute(
        sa.update(SupportTicketRow)
        .where(
            SupportTicketRow.id == ticket_id,
            SupportTicketRow.group_posted_at.is_(None),
        )
        .values(group_chat_id=None, group_message_id=None)
    )
    return rowcount_of(result) == 1


async def find_by_group_message(
    session: AsyncSession, *, group_chat_id: int, group_message_id: int
) -> TicketSnapshot | None:
    """The ticket a staffer's reply belongs to, or ``None`` when it replies to something else.

    **Both columns are the key, because the uniqueness is over both.** A Telegram
    ``message_id`` is a per-chat counter, so ``group_message_id`` is not unique on its own and
    the index that once claimed it was does not exist — ``(group_chat_id, group_message_id)``
    is what ``ix_support_tickets_group_chat_id_group_message_id`` covers, and this lookup is
    the exact query that shape was chosen for. Dropping the chat id here would not merely be
    "one redundant predicate fewer": it would make the lookup ambiguous by construction, so a
    deployment moved to a second support group would resolve a reply in the NEW group to a card
    posted in the old one and relay a stranger's sentence to a customer. Two rows can legally
    hold message id 5.

    Most messages in a support group are not replies to a card at all, so ``None`` is the
    common answer and is not a failure.
    """
    row = (
        await session.execute(
            sa.select(SupportTicketRow).where(
                SupportTicketRow.group_chat_id == group_chat_id,
                SupportTicketRow.group_message_id == group_message_id,
            )
        )
    ).scalar_one_or_none()
    return None if row is None else snapshot_of(row)


# ---------------------------------------------------------------------------
# Working it
# ---------------------------------------------------------------------------
async def move_status(
    session: AsyncSession,
    ticket_id: UUID,
    *,
    expected: SupportTicketStatus,
    to_status: SupportTicketStatus,
    author: EventAuthor,
    now: datetime,
) -> TicketSnapshot | None:
    """Move a ticket between columns and write the ``STATUS_CHANGE`` event carrying both ends.

    ``expected`` is required and has no default. The ``UPDATE`` names it, so the rowcount is
    the lock: two staffers pressing ``✅ Resolve`` on one card produce one move and one event,
    and the loser gets ``None`` — "somebody got there first", which is ordinary and means
    re-read and re-render, never retry.

    An illegal move raises instead, and the asymmetry is the point:
    :func:`bayram.support.is_legal_move` is a question about the board's grammar that the
    caller could have asked before offering the button, so a ``NEW -> NEW`` or a
    ``RESOLVED -> WAITING`` is a bug in the caller and deserves a typed refusal the panel
    renders as a 422. Returning ``None`` for it would make a programming error indistinguishable
    from a lost race.

    ``resolved_at`` is stamped on the way into ``RESOLVED`` and is deliberately **never
    cleared** on the way out: it records that this ticket was once considered finished, which
    is the single most useful thing to know about a ticket that came back.
    """
    if not is_legal_move(expected, to_status):
        raise ValidationError(
            "that support status move is not allowed",
            context={
                "ticket_id": str(ticket_id),
                "from_status": expected.value,
                "to_status": to_status.value,
            },
        )
    values: dict[str, Any] = {"status": to_status, "updated_at": now}
    if to_status is SupportTicketStatus.RESOLVED:
        values["resolved_at"] = now
    result = await session.execute(
        sa.update(SupportTicketRow)
        .where(SupportTicketRow.id == ticket_id, SupportTicketRow.status == expected)
        .values(**values)
    )
    if rowcount_of(result) != 1:
        return None
    await _add_event(
        session,
        ticket_id,
        kind=SupportTicketEventKind.STATUS_CHANGE,
        author=author,
        now=now,
        from_status=expected,
        to_status=to_status,
    )
    return _require(await load_ticket(session, ticket_id, fresh=True), ticket_id)


async def assign(
    session: AsyncSession,
    ticket_id: UUID,
    *,
    admin_username: str,
    author: EventAuthor,
    now: datetime,
) -> TicketSnapshot | None:
    """Record who has this ticket and write the ``ASSIGNED`` event. ``None`` for an unknown id.

    Unconditional on the current assignee, unlike every other write here, and that is a
    product decision rather than an oversight: handing a ticket over is a normal act, so a
    reassignment must not be refused because somebody else claimed it first. The append-only
    event is what keeps the history — ``assigned_admin_username`` is who has it *now*, and the
    timeline is who has had it.

    Separate from :func:`move_status` because a ticket can be claimed without being moved and
    moved without being claimed. ``✋ Claim`` on the group card is both, as two statements.
    """
    result = await session.execute(
        sa.update(SupportTicketRow)
        .where(SupportTicketRow.id == ticket_id)
        .values(assigned_admin_username=admin_username, assigned_at=now, updated_at=now)
    )
    if rowcount_of(result) != 1:
        return None
    await _add_event(
        session,
        ticket_id,
        kind=SupportTicketEventKind.ASSIGNED,
        author=author,
        now=now,
        body=None,
    )
    return _require(await load_ticket(session, ticket_id, fresh=True), ticket_id)


async def append_event(
    session: AsyncSession,
    ticket_id: UUID,
    *,
    kind: SupportTicketEventKind,
    author: EventAuthor,
    now: datetime,
    body: str | None = None,
) -> UUID:
    """Append one timeline row and return its id. The id is needed by a reply, later.

    A ``REPLY`` is composed in one transaction and DELIVERED by a network call in another, so
    the caller keeps this id and stamps :func:`mark_relayed` when the message really reached
    the customer. Every other kind ignores the return value, which is why it is an id and not
    a snapshot: loading the event back would be a second statement nobody reads.

    Nothing is validated. The table carries no CHECK constraint tying ``author_kind`` to the
    column it populates, on the argument its own docstring makes — over-constraining a log
    loses rows, and a lost row is a hole in the record of what a customer was told — and a
    writer that refused in Python would lose exactly the same row one layer up.
    """
    return await _add_event(session, ticket_id, kind=kind, author=author, now=now, body=body)


async def mark_relayed(session: AsyncSession, event_id: UUID, *, now: datetime) -> bool:
    """Stamp ``relayed_at`` on a reply that actually reached the customer's private chat.

    The one clock written after insert on an append-only table, and it is not an amendment:
    the row records that a reply was COMPOSED, this records that it was DELIVERED, and the two
    are separated by a network call that fails often enough to be worth telling apart — a
    customer who blocked the bot, a chat Telegram will not open.

    Conditional on the clock being unset, so a replayed relay job does not move the instant a
    reply is recorded as having landed. ``False`` means unknown, or already stamped.
    """
    result = await session.execute(
        sa.update(SupportTicketEventRow)
        .where(
            SupportTicketEventRow.id == event_id,
            SupportTicketEventRow.relayed_at.is_(None),
        )
        .values(relayed_at=now)
    )
    return rowcount_of(result) == 1


# ---------------------------------------------------------------------------
# Reading it back
# ---------------------------------------------------------------------------
async def load_ticket(
    session: AsyncSession, ticket_id: UUID, *, fresh: bool = False
) -> TicketSnapshot | None:
    """One ticket by id, as a frozen snapshot. ``None`` for an unknown id.

    ``fresh=True`` forces a re-``SELECT`` through ``populate_existing`` and is required after
    any Core ``UPDATE`` in this module: a Core statement does not touch the session's identity
    map, so the default read would hand back the object as it was BEFORE the move — the same
    trap ``db/lyric_budget.py`` sidesteps by selecting columns. It is off by default because
    the read paths have not written anything and an unconditional refresh would make every
    lookup pay for a write nobody did.
    """
    row = await session.get(SupportTicketRow, ticket_id, populate_existing=fresh)
    return None if row is None else snapshot_of(row)


def snapshot_of(row: SupportTicketRow) -> TicketSnapshot:
    """Row to frozen value. Pure, and the ONE place the mapping is spelled.

    Only mapped scalar columns are read. There is no relationship on this model to traverse
    by accident — ``support_tickets`` declares none, on the rule every model in this package
    keeps — so a snapshot can be built outside the session that produced it without the
    greenlet error a lazy load would raise at an unrelated ``await``.
    """
    return TicketSnapshot(
        id=row.id,
        public_ref=row.public_ref,
        telegram_user_id=row.telegram_user_id,
        language=row.language,
        source=row.source,
        order_id=row.order_id,
        status=row.status,
        body=row.body,
        prompt_message_id=row.prompt_message_id,
        described_at=row.described_at,
        assigned_admin_username=row.assigned_admin_username,
        group_chat_id=row.group_chat_id,
        group_message_id=row.group_message_id,
        group_posted_at=row.group_posted_at,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# The never-throw facade
# ---------------------------------------------------------------------------
class SqlSupportTickets:
    """:class:`bayram.support.SupportTicketStore` over the two support tables.

    One transaction per method, never raises, and it is what ``bayram.main`` wires into
    ``BotDeps.support``. The panel does NOT use this facade: an admin handler composes the
    module functions above into the request's own transaction so the ticket move and its
    ``admin_audit_log`` row land together or not at all — the split
    :mod:`bayram.db.broadcasts` already makes, and for the identical reason.

    ``__slots__`` because this object is built once at the composition root and held for the
    life of the process; a per-instance ``__dict__`` for one attribute is noise.
    """

    __slots__ = ("_quota", "_sessions")

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        quota: SupportQuota = DEFAULT_SUPPORT_QUOTA,
    ) -> None:
        self._sessions = sessions
        self._quota = quota

    @property
    def quota(self) -> SupportQuota:
        """The numbers this store was built with. Read by the wiring test, nothing else."""
        return self._quota

    async def check_open_quota(
        self,
        telegram_user_id: int,
        *,
        now: datetime,
        quota: SupportQuota | None = None,
    ) -> Result[TicketQuotaVerdict]:
        """Two counts and a verdict. ``quota`` overrides the store's own, for a caller that
        meters a command and the ⚠️ button differently."""
        return await run_guarded(
            "support_check_open_quota",
            lambda: self._quota_verdict(telegram_user_id, now, quota or self._quota),
            telegram_user_id=telegram_user_id,
        )

    async def open_ticket(
        self,
        *,
        telegram_user_id: int,
        language: Language,
        source: SupportTicketSource,
        order_id: UUID | None,
        now: datetime,
    ) -> Result[TicketSnapshot]:
        """Write the ticket and its ``OPENED`` event in one transaction."""
        return await run_guarded(
            "support_open_ticket",
            lambda: self._open(telegram_user_id, language, source, order_id, now),
            telegram_user_id=telegram_user_id,
        )

    async def attach_prompt(
        self, ticket_id: UUID, *, prompt_message_id: int, now: datetime
    ) -> Result[bool]:
        """Record the ForceReply this ticket waits on."""
        return await run_guarded(
            "support_attach_prompt",
            lambda: self._in_session(
                lambda session: attach_prompt(
                    session, ticket_id, prompt_message_id=prompt_message_id, now=now
                )
            ),
            ticket_id=str(ticket_id),
        )

    async def listen_on(
        self, ticket_id: UUID, *, prompt_message_id: int, now: datetime
    ) -> Result[bool]:
        """Re-point the ticket at the message the conversation has moved to."""
        return await run_guarded(
            "support_listen_on",
            lambda: self._in_session(
                lambda session: listen_on(
                    session, ticket_id, prompt_message_id=prompt_message_id, now=now
                )
            ),
            ticket_id=str(ticket_id),
        )

    async def latest_undescribed_ticket(
        self, telegram_user_id: int
    ) -> Result[TicketSnapshot | None]:
        """The newest ticket this account opened and never described."""
        return await run_guarded(
            "support_latest_undescribed_ticket",
            lambda: self._in_session(
                lambda session: find_latest_undescribed(session, telegram_user_id)
            ),
            telegram_user_id=telegram_user_id,
        )

    async def ticket_listening_on(
        self, telegram_user_id: int, *, prompt_message_id: int
    ) -> Result[TicketSnapshot | None]:
        """The ticket listening on that message, for that account. Described or not."""
        return await run_guarded(
            "support_ticket_listening_on",
            lambda: self._in_session(
                lambda session: find_by_prompt(
                    session, telegram_user_id, prompt_message_id=prompt_message_id
                )
            ),
            telegram_user_id=telegram_user_id,
        )

    async def describe_ticket(
        self, ticket_id: UUID, *, body: str, now: datetime
    ) -> Result[TicketSnapshot | None]:
        """Fill the body and stamp the clock, once."""
        return await run_guarded(
            "support_describe_ticket",
            lambda: self._in_session(
                lambda session: describe(session, ticket_id, body=body, now=now)
            ),
            ticket_id=str(ticket_id),
        )

    async def claim_group_post(
        self, ticket_id: UUID, *, group_chat_id: int, group_message_id: int
    ) -> Result[bool]:
        """Latch the card. The transaction this owns is committed on the way out, which is
        what makes the claim visible to another worker before the next Telegram call."""
        return await run_guarded(
            "support_claim_group_post",
            lambda: self._in_session(
                lambda session: claim_group_post(
                    session,
                    ticket_id,
                    group_chat_id=group_chat_id,
                    group_message_id=group_message_id,
                )
            ),
            ticket_id=str(ticket_id),
        )

    async def settle_group_post(self, ticket_id: UUID, *, now: datetime) -> Result[bool]:
        """Stamp the post clock and write the ``GROUP_POSTED`` event."""
        return await run_guarded(
            "support_settle_group_post",
            lambda: self._in_session(
                lambda session: settle_group_post(session, ticket_id, now=now)
            ),
            ticket_id=str(ticket_id),
        )

    async def release_group_post(self, ticket_id: UUID) -> Result[bool]:
        """Give an unsettled claim back. See :func:`release_group_post` for when this is legal."""
        return await run_guarded(
            "support_release_group_post",
            lambda: self._in_session(lambda session: release_group_post(session, ticket_id)),
            ticket_id=str(ticket_id),
        )

    async def ticket_for_group_message(
        self, *, group_chat_id: int, group_message_id: int
    ) -> Result[TicketSnapshot | None]:
        """The ticket a staffer replied to, or ``None`` — the common answer in a busy group."""
        return await run_guarded(
            "support_ticket_for_group_message",
            lambda: self._in_session(
                lambda session: find_by_group_message(
                    session, group_chat_id=group_chat_id, group_message_id=group_message_id
                )
            ),
            group_chat_id=group_chat_id,
        )

    async def move_status(
        self,
        ticket_id: UUID,
        *,
        expected: SupportTicketStatus,
        to_status: SupportTicketStatus,
        author: EventAuthor,
        now: datetime,
    ) -> Result[TicketSnapshot | None]:
        """Move columns, conditionally. An illegal move is an ``Err``; a lost race is ``None``."""
        return await run_guarded(
            "support_move_status",
            lambda: self._in_session(
                lambda session: move_status(
                    session,
                    ticket_id,
                    expected=expected,
                    to_status=to_status,
                    author=author,
                    now=now,
                )
            ),
            ticket_id=str(ticket_id),
        )

    async def assign_ticket(
        self, ticket_id: UUID, *, admin_username: str, author: EventAuthor, now: datetime
    ) -> Result[TicketSnapshot | None]:
        """Record who has it now; the timeline keeps who has had it."""
        return await run_guarded(
            "support_assign_ticket",
            lambda: self._in_session(
                lambda session: assign(
                    session, ticket_id, admin_username=admin_username, author=author, now=now
                )
            ),
            ticket_id=str(ticket_id),
        )

    async def append_event(
        self,
        ticket_id: UUID,
        *,
        kind: SupportTicketEventKind,
        author: EventAuthor,
        now: datetime,
        body: str | None = None,
    ) -> Result[UUID]:
        """Append one timeline row and hand back its id."""
        return await run_guarded(
            "support_append_event",
            lambda: self._in_session(
                lambda session: append_event(
                    session, ticket_id, kind=kind, author=author, now=now, body=body
                )
            ),
            ticket_id=str(ticket_id),
        )

    async def mark_relayed(self, event_id: UUID, *, now: datetime) -> Result[bool]:
        """Stamp a reply that landed."""
        return await run_guarded(
            "support_mark_relayed",
            lambda: self._in_session(lambda session: mark_relayed(session, event_id, now=now)),
            event_id=str(event_id),
        )

    async def load_ticket(self, ticket_id: UUID) -> Result[TicketSnapshot | None]:
        """One ticket by id, for a job that was handed an id and must re-render its card."""
        return await run_guarded(
            "support_load_ticket",
            lambda: self._in_session(lambda session: load_ticket(session, ticket_id)),
            ticket_id=str(ticket_id),
        )

    # -- internals -----------------------------------------------------------
    async def _in_session[T](self, work: _Work[T]) -> T:
        """One transaction, one delegation. Every public method above is this plus a name.

        Written once rather than fifteen times because the thing that must not drift is the
        transaction boundary: a method that opened two would be a status move whose event
        landed in a transaction the move could no longer roll back.
        """
        async with self._sessions.begin() as session:
            return await work(session)

    async def _quota_verdict(
        self, telegram_user_id: int, now: datetime, quota: SupportQuota
    ) -> TicketQuotaVerdict:
        return await self._in_session(
            lambda session: quota_verdict(session, telegram_user_id, now=now, quota=quota)
        )

    async def _open(
        self,
        telegram_user_id: int,
        language: Language,
        source: SupportTicketSource,
        order_id: UUID | None,
        now: datetime,
    ) -> TicketSnapshot:
        return await self._in_session(
            lambda session: open_ticket(
                session,
                telegram_user_id=telegram_user_id,
                language=language,
                source=source,
                order_id=order_id,
                now=now,
            )
        )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------
def _day_start(now: datetime) -> datetime:
    """Midnight UTC of the day ``now`` falls in. The daily quota's window, and nothing else.

    A naive ``now`` is refused rather than assumed to be UTC: guessing the zone would move the
    boundary by up to a day and hand a customer a second day's tickets. ``UtcDateTime`` makes
    the same refusal at bind time; this one is here because the arithmetic happens before the
    bind, and an error naming the day boundary is more useful than one naming a driver.
    """
    if now.tzinfo is None:
        raise ValidationError(
            "a support quota window needs an aware datetime",
            context={"now": repr(now)},
        )
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


async def _add_event(
    session: AsyncSession,
    ticket_id: UUID,
    *,
    kind: SupportTicketEventKind,
    author: EventAuthor,
    now: datetime,
    body: str | None = None,
    from_status: SupportTicketStatus | None = None,
    to_status: SupportTicketStatus | None = None,
) -> UUID:
    """Insert one timeline row. The one place :class:`EventAuthor` is unpacked into columns.

    Private, and wider than :func:`append_event`, because ``from_status``/``to_status`` are
    set only by :func:`move_status` — offering them on the public function would invite a
    caller to write a ``NOTE`` that claims a status change nobody made.
    """
    event_id = uuid4()
    session.add(
        SupportTicketEventRow(
            id=event_id,
            ticket_id=ticket_id,
            kind=kind,
            author_kind=author.kind,
            author_admin_username=author.admin_username,
            author_telegram_user_id=author.telegram_user_id,
            author_display_name=author.display_name,
            from_status=from_status,
            to_status=to_status,
            body=body,
            created_at=now,
        )
    )
    await session.flush()
    return event_id


def _require(ticket: TicketSnapshot | None, ticket_id: UUID) -> TicketSnapshot:
    """Unwrap a read that has just been proven to exist by a rowcount of 1.

    Not defensive programming: every call site has already written or moved this exact row in
    this exact transaction, so ``None`` here means the row vanished mid-transaction, which is
    a storage fault and not a missing ticket. Raising rather than returning ``None`` keeps the
    signatures honest — a caller told "the move succeeded" always gets the moved ticket.
    """
    if ticket is None:
        raise StorageError(
            "a support ticket disappeared inside its own transaction",
            context={"ticket_id": str(ticket_id)},
        )
    return ticket
