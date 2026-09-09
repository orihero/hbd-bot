"""Recording a customer's block as a TRANSITION, in one statement that cannot lose a race.

Two facts are written here and they are deliberately different shapes. ``users.blocked_bot_at``
is the CURRENT state — what the Churn card's gauge counts, and the only thing that can answer
"can we message this person right now?". ``bot_membership_events`` is the HISTORY — one
append-only row per observed passage, which is what a period count and a sparkline need and
what a column can never provide, because an account that blocks on Monday and comes back on
Wednesday clears the column and takes Monday's bucket down with it. The split is
``credit_accounts.balance`` beside ``credit_ledger``, for the same reason and with the same
division of labour; :mod:`hbd.db.models.bot_membership_event` argues it in full.

**The conditional UPDATE, and why it is not a read-then-write.** Two writers really can
fire for one account at overlapping times: the ``my_chat_member`` handler in the bot process,
which runs inside aiogram's per-chat FSM isolation lock, and the delivery arm in the ARQ
worker, which holds no such lock and is a different process entirely. A ``SELECT`` followed
by an ``UPDATE`` has a window between them in which both writers see ``blocked_bot_at IS
NULL``, both write, and both append an event — a lost update and a duplicate passage, neither
of which is visible in a unit suite. ``UPDATE … WHERE blocked_bot_at IS NULL`` decides in one
statement, and its ROWCOUNT *is* the transition test: exactly one writer is told it won.
``SELECT … FOR UPDATE`` would do the same job and SQLite does not have it, so the unit suite
could not exercise the production shape.

**The guard is also the abuse rail.** The ``my_chat_member`` observer carries no throttle —
``InboundGateMiddleware`` is registered on ``message`` and ``callback_query`` only — so a
customer hammering block/unblock is bounded by nothing else. Because the event row is written
only when the guard says a state actually changed, that customer can produce at most one row
per REAL transition, which is a tighter bound than a rate limiter and cannot drop the one
transition we most want to keep.

**Why an UPSERT of the ``users`` row first.** :func:`hbd.db.credits.set_blocked` states the
argument and it is the same one: an account that has not spoken since the last deploy has no
``users`` row, and that is *precisely* the account whose block we need to record. A
rowcount-checked ``UPDATE`` alone would silently do nothing for exactly the population this
module exists to serve. The insert half uses ``ON CONFLICT DO NOTHING`` and never DO UPDATE:
a touch-style upsert that reset the churn column on ordinary traffic would be the identical
defect ``credits.touch`` records for ``is_blocked`` — "a touch that reset the flag would
unblock an abuser the moment they sent their next message".

**Why one code path serves both sources** rather than a cheaper UPDATE-only path for the
worker. One writer means one guarantee: the delivery arm fires on a kit that could not be
sent, which is often the *first* thing the system learns about an account whose
``my_chat_member`` update was dropped by ``delete_webhook(drop_pending_updates=True)`` on the
last restart — so it needs the row-creating half at least as much as the handler does. The
``source`` column is what keeps the two distinguishable afterwards.

**The block and unblock paths are asymmetric, and that asymmetry is load-bearing.** A block
that had to CREATE the ``users`` row is a transition and writes its event. An unblock that
had to create the row is NOT: Telegram sends a ``my_chat_member`` update the first time
anybody presses Start (``left`` → ``member``), and a fresh row has ``blocked_bot_at`` already
``NULL``, so treating that as a passage would fill the win-back series with people who had
never left. See :func:`mark_bot_unblocked`.

Shape follows :mod:`hbd.db.credits` and :mod:`hbd.db.lyric_budget`: the module-level
functions take an ``AsyncSession`` first and positionally, take ``at`` as a parameter, let
exceptions propagate and **never commit**; :class:`SqlBotBlocks` is the never-throw facade
that owns exactly one ``async with self._sessions.begin()`` per public method.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hbd.contracts import BotBlockSource, BotMembershipEvent, Result
from hbd.db.credit_sql import insert_or_ignore, rowcount_of
from hbd.db.guard import run_guarded
from hbd.db.models.bot_membership_event import BotMembershipEventRow
from hbd.db.models.user import UserRow
from hbd.db.users_sql import DEFAULT_UI_LANGUAGE

__all__ = [
    "SqlBotBlocks",
    "mark_bot_blocked",
    "mark_bot_unblocked",
    "anonymise_bot_membership_events",
]


async def mark_bot_blocked(
    session: AsyncSession, *, telegram_user_id: int, at: datetime, source: BotBlockSource
) -> bool:
    """Record that this customer blocked the bot. ``True`` when this call was the passage.

    Three statements, and the ordering subtlety is worth stating because the obvious reading
    is wrong. When the UPSERT actually INSERTS the row it inserts it with ``blocked_bot_at``
    already set, so the conditional UPDATE that follows matches NOTHING — and an
    implementation that trusted the UPDATE's rowcount alone would create the row, set the
    column and then write no event at all, which is silent and exactly the population the
    upsert exists for. The event is therefore written when the row was INSERTED **or** the
    UPDATE matched, and :func:`hbd.db.credit_sql.insert_or_ignore` is used precisely because
    it reports which.

    ``is_blocked`` is written only on the INSERT, and only as ``False``. It is the OPERATOR's
    bar and this is the CUSTOMER's block; the two are separate cards on the dashboard, they
    are never OR-ed, and neither is ever derived from the other. Nothing on this path may
    move it, in either direction.
    """
    inserted = await insert_or_ignore(
        session,
        UserRow,
        _new_user_values(telegram_user_id=telegram_user_id, at=at, blocked_bot_at=at),
        index_elements=["telegram_user_id"],
    )
    updated = 0
    if not inserted:
        result = await session.execute(
            sa.update(UserRow)
            .where(
                UserRow.telegram_user_id == telegram_user_id,
                UserRow.blocked_bot_at.is_(None),
            )
            .values(blocked_bot_at=at, updated_at=at)
        )
        updated = rowcount_of(result)
    if not (inserted or updated == 1):
        return False
    await _append_event(
        session,
        telegram_user_id=telegram_user_id,
        event=BotMembershipEvent.BLOCKED,
        source=source,
        at=at,
    )
    return True


async def mark_bot_unblocked(
    session: AsyncSession, *, telegram_user_id: int, at: datetime, source: BotBlockSource
) -> bool:
    """Record that this customer unblocked the bot. ``True`` when this call was the passage.

    The mirror of :func:`mark_bot_blocked` with ONE deliberate difference: an INSERT here is
    never a transition, so the event is written only when the conditional UPDATE matched.
    Telegram sends a ``my_chat_member`` update the first time anyone presses Start — the
    membership goes ``left`` → ``member`` — and that update reaches this function for an
    account that may well have no ``users`` row yet. A fresh row is born with
    ``blocked_bot_at`` ``NULL``, i.e. not blocked, so nothing changed and nothing is
    recorded. Counting it would put a win-back on the dashboard for a customer who had never
    left, and win-backs are the number the events table exists to make trustworthy.

    The row is still upserted rather than skipped, because "we have now seen this account"
    is worth a row on the same reasoning ``credits.touch`` writes one, and because it keeps
    both halves of this module reaching the database the same way.
    """
    await insert_or_ignore(
        session,
        UserRow,
        _new_user_values(telegram_user_id=telegram_user_id, at=at, blocked_bot_at=None),
        index_elements=["telegram_user_id"],
    )
    result = await session.execute(
        sa.update(UserRow)
        .where(
            UserRow.telegram_user_id == telegram_user_id,
            UserRow.blocked_bot_at.is_not(None),
        )
        .values(blocked_bot_at=None, updated_at=at)
    )
    if rowcount_of(result) != 1:
        return False
    await _append_event(
        session,
        telegram_user_id=telegram_user_id,
        event=BotMembershipEvent.UNBLOCKED,
        source=source,
        at=at,
    )
    return True


async def anonymise_bot_membership_events(session: AsyncSession, *, telegram_user_id: int) -> int:
    """Strip the owner off this account's transitions, keeping every row. Rows touched.

    The ``credit_ledger`` treatment, not the ``credit_accounts`` one, and here the argument
    is sharper than it is for a receipt: DELETING these rows would make the churn series
    shrink retroactively by the number of people who asked to be forgotten, which is the
    exact defect — a historical count that changes after the fact — the events table was
    created to avoid. An anonymous transition record says nothing about anybody and keeps
    the day counts true.

    Mirrors :func:`hbd.db.plan_sql.anonymise_plans` exactly, including that it does not
    commit: the caller (:func:`hbd.db.credit_erasure.forget_account`) owns the transaction so
    a ``/forget`` either lands whole or not at all.

    ``users.blocked_bot_at`` is deliberately NOT cleared by this, on the same footing as
    ``is_blocked`` and ``last_seen_at``: a forgotten customer who still has the bot blocked
    is still unreachable, and clearing it would make the gauge count them as reachable.
    """
    result = await session.execute(
        sa.update(BotMembershipEventRow)
        .where(BotMembershipEventRow.telegram_user_id == telegram_user_id)
        .values(telegram_user_id=None)
    )
    return rowcount_of(result)


def _new_user_values(
    *, telegram_user_id: int, at: datetime, blocked_bot_at: datetime | None
) -> dict[str, object]:
    """The INSERT half of both upserts. Discarded entirely when the row already exists.

    ``ui_language`` is supplied because the column is ``nullable=False``: an INSERT that
    omitted it would violate the constraint, ``run_guarded`` would turn that into an ``Err``,
    and no ``users`` row would ever be created for a pre-onboarding account — the same trap
    ``users_sql.DEFAULT_UI_LANGUAGE`` is named for. Learning that somebody blocked us must
    never change the language they read in, so it appears here and in no update clause.
    """
    return {
        # Discarded on conflict; a row that already exists keeps its own id.
        "id": uuid4(),
        "telegram_user_id": telegram_user_id,
        "ui_language": DEFAULT_UI_LANGUAGE,
        # The OPERATOR's bar, and this path is the CUSTOMER's block. A row born here is not
        # barred by anybody; nothing on this path may ever write ``True`` into it.
        "is_blocked": False,
        "last_seen_at": at,
        "created_at": at,
        "updated_at": at,
        "blocked_bot_at": blocked_bot_at,
    }


async def _append_event(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    event: BotMembershipEvent,
    source: BotBlockSource,
    at: datetime,
) -> None:
    """Write the passage. A Core INSERT rather than ``session.add``.

    Core because the two statements above are Core: an ORM ``add`` would flush at some point
    the caller does not control, and the whole guarantee of this module is that the decision
    and the record land in one transaction in a known order.
    """
    await session.execute(
        sa.insert(BotMembershipEventRow).values(
            id=uuid4(),
            telegram_user_id=telegram_user_id,
            event=event,
            source=source,
            at=at,
        )
    )


class SqlBotBlocks:
    """:class:`hbd.churn.BotBlockRecorder` over ``users`` and ``bot_membership_events``.

    Owns its transaction, never raises, and is held by BOTH the bot and the worker — unlike
    ``profiles`` (bot only) and the render gate (worker only). That is not an oversight: a
    block is learned in two places, from the ``my_chat_member`` update the bot receives and
    from the ``sendAudio`` the worker is refused, and the two are not redundant while
    ``run_polling`` calls ``delete_webhook(drop_pending_updates=True)`` on every start.

    The admin process builds this object too, through ``build_container``, and never calls
    it: no admin route writes churn. The panel READS ``bot_membership_events`` through
    ``hbd.db.admin`` and the only writers are the two above.
    """

    __slots__ = ("_sessions",)

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def record_bot_blocked(
        self, telegram_user_id: int, *, at: datetime, source: BotBlockSource
    ) -> Result[bool]:
        """Record a block. A failure comes back as an ``Err``; no caller has to catch."""
        return await run_guarded(
            "churn.record_bot_blocked",
            lambda: self._blocked(telegram_user_id, at, source),
            telegram_user_id=telegram_user_id,
            source=source.value,
        )

    async def record_bot_unblocked(
        self, telegram_user_id: int, *, at: datetime, source: BotBlockSource
    ) -> Result[bool]:
        """Record an unblock. Same never-throw contract as above."""
        return await run_guarded(
            "churn.record_bot_unblocked",
            lambda: self._unblocked(telegram_user_id, at, source),
            telegram_user_id=telegram_user_id,
            source=source.value,
        )

    async def _blocked(self, telegram_user_id: int, at: datetime, source: BotBlockSource) -> bool:
        async with self._sessions.begin() as session:
            return await mark_bot_blocked(
                session, telegram_user_id=telegram_user_id, at=at, source=source
            )

    async def _unblocked(self, telegram_user_id: int, at: datetime, source: BotBlockSource) -> bool:
        async with self._sessions.begin() as session:
            return await mark_bot_unblocked(
                session, telegram_user_id=telegram_user_id, at=at, source=source
            )
