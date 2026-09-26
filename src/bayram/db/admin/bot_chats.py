"""``/support/groups`` — every chat the bot knows it is in, and which one gets the tickets.

**This module READS. It never selects, never clears and never verifies.** All three are
structural rather than tidy. The two writes belong in the request transaction that carries the
``admin_audit_log`` row, so they are :func:`bayram.db.bot_chats.select_support_group` and
:func:`bayram.db.bot_chats.clear_support_group` composed by the router; and verification has to
talk to Telegram, which ``bayram.admin.*`` may not do at all — that import would drag in
``aiogram.Bot``, and ``test_admin/test_queue.py``'s
``test_the_seam_can_reach_nothing_that_sends_a_message`` reads ``admin/queue.py``'s import
statements to prove it cannot happen. So a selection is an ``AdminQueue`` job plus a write, and
this file is the other half: what the screen shows.

**THE LIST IS NOT PAGED, AND THAT IS A JUDGEMENT ABOUT THE DATA RATHER THAN AN OMISSION.**
Every other list in this package takes a :class:`~bayram.db.admin.page.PageRequest`, carries a
keyset cursor and offers a bounded total. This one returns every row, because of the constraint
the whole feature is built around: **Telegram has no "list my groups" API**, so this table fills
one row at a time from ``my_chat_member`` updates and from ids an operator typed by hand. Its
population is "groups somebody deliberately added this bot to" — a handful, ever, counted on one
hand in every deployment this product will have. A cursor over four rows would be four rows of
machinery, an empty-state the operator can reach by scrolling, and a screen whose one job —
"which of these is the inbox?" — is answered on page two. ``support_ticket_events`` is paged
nowhere either, for the same kind of reason stated about a different number.

If that assumption ever breaks, it breaks visibly: the panel renders every row it is given, so a
directory that grew to hundreds would be an obviously silly screen rather than a silently
truncated one. That is the failure mode worth having.

**SELECTED FIRST, THEN MOST RECENTLY SEEN.** The ordering is the answer to the question the
screen exists for. A list ordered only by ``last_seen_at`` would push the selected group down
the moment the bot is added to anything else — which is precisely when an operator is looking,
and precisely the row they came to check.

No relationship is ever traversed: ``bot_chats`` declares none at all, and the standing rule
holds anyway — every model in this schema is ``lazy="raise"``, so an accidental traversal
surfaces as a greenlet error at an unrelated await.

**Nothing here is a person.** This is the one read in ``bayram.db.admin`` that names no customer
whatsoever — not even a masked Telegram id — because every column of the table is about a group.
``my_chat_member`` hands us ``from_user``, the human who added the bot, and the table does not
store it; the one name that crosses is ``selected_by_username``, an operator's own login, which
``admin_audit_log.actor_username`` already publishes on every screen in the panel.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from bayram.db.admin.views import BotChatListItem
from bayram.db.models.bot_chat import BotChatRow

__all__ = ["list_bot_chats", "selected_bot_chat", "bot_chat_list_item"]


async def list_bot_chats(session: AsyncSession) -> tuple[BotChatListItem, ...]:
    """Every chat in the directory, the selected one first. Unpaged; see the module docstring.

    ``chat_id`` is the last ordering term and is not decoration. ``last_seen_at`` ties exactly
    whenever two chats were recorded by the same act — an operator pasting two ids in a row, or
    the first sighting of a group and its own upgrade to a supergroup arriving in one update —
    and a list whose order is undefined inside a tie group reorders itself between two reads of
    an unchanged table. The primary key makes the order total.

    The selected row is returned in this tuple and is not held back for a separate field. The
    screen highlights it by its own :attr:`~bayram.db.admin.views.BotChatListItem.is_support_group`
    flag, which is the same fact the database enforces to be true of at most one row — a second
    copy of it beside the list would be a second answer to "which one is it?", and the two would
    eventually disagree about a directory that changed between two statements.
    """
    rows = (
        (
            await session.execute(
                sa.select(BotChatRow).order_by(
                    BotChatRow.is_support_group.desc(),
                    BotChatRow.last_seen_at.desc(),
                    BotChatRow.chat_id.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return tuple(bot_chat_list_item(row) for row in rows)


async def selected_bot_chat(session: AsyncSession) -> BotChatListItem | None:
    """The chat tickets are posted into, with its verification state, or ``None``.

    Not a filter over :func:`list_bot_chats`' result, and not sugar for one either: this is the
    read a screen that only has to say "tickets go here, last verified then" performs, and it is
    a single row off ``ix_bot_chats_selected_support_group`` rather than a table scan the caller
    then walks.

    ``None`` is an ordinary answer. A fresh deployment has never selected anything, and an
    operator may clear the selection on purpose; tickets keep working either way, and only the
    group post stops. It is a state to render, never an error to raise.

    ``LIMIT 1`` even though the partial unique index makes a second row impossible: a directory
    that somehow acquired two — an index dropped by hand, a migration run half-way — answers
    with one of them instead of raising ``MultipleResultsFound`` at an operator who is trying to
    find out what is wrong.
    """
    row = await session.scalar(
        sa.select(BotChatRow).where(BotChatRow.is_support_group.is_(True)).limit(1)
    )
    return None if row is None else bot_chat_list_item(row)


# ---------------------------------------------------------------------------
# Row -> view model. Pure.
# ---------------------------------------------------------------------------
def bot_chat_list_item(row: BotChatRow) -> BotChatListItem:
    """Build one row of the Support group screen. Every column crosses; the view says why.

    There is no ``keyword-only extra`` here of the kind ``ticket_list_item`` takes, because
    there is nothing to correlate: this table has no children, no counts and no second
    statement. One row in, one row out.
    """
    return BotChatListItem(
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
