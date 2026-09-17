"""Wire models for ``/api/support/groups`` — the chats the bot is in, and which one is the inbox.

**A module of its own rather than more models in ``schemas/tickets.py``, and the two reasons
point in opposite directions — which is why both are written down.**

The first is subject matter. ``schemas/tickets.py`` is about one customer's complaint: its
models carry a Telegram id, a masked twin of it, a language, a body the customer typed and a
timeline of what was said back. Nothing here is any of that. A ``bot_chats`` row is a ROOM —
an id, a title, a public ``@handle``, three closed enums and an operator's own login — and the
table it comes from records every chat the bot is added to, including the marketing group and
the developer group that have nothing to do with support. ``bayram.bot_chats`` refused the same
merge one layer down, for the same reason and at greater length; this module is the wire half of
that decision and would be incoherent filed against the other one.

The second is mechanical and cuts the other way. ``schemas/tickets.py`` imports
:class:`~bayram.admin.schemas.page.PageMeta`, and ``page.py`` imports FastAPI — which is why
that module carries a standing prohibition on being re-exported from
``bayram.admin.schemas.__init__`` — ``test_the_worker_decodes_a_stored_segment_without_``
``importing_a_web_framework`` runs in a subprocess and fails the moment a web framework appears
in the worker's import graph.
**This module imports no web framework at all**, because the list it describes is deliberately
unpaged — ``bayram.db.admin.bot_chats`` argues why at length: Telegram has no "list my groups"
API, so the population is a handful of rows in every deployment this product will have, and a
keyset cursor over four rows answers the screen's one question on page two. Folding these models
into ``tickets.py`` would tie a framework-free shape to a framework-importing module for ever,
for no gain.

**It is still not re-exported from ``schemas/__init__.py``.** That package re-exports what the
WORKER needs, and the worker needs none of this: it reads ``bot_chats`` through
:mod:`bayram.db.bot_chats`, which is where the values it actually passes around live. A
re-export would be a line nobody reads added to a file whose whole discipline is that every line
in it was argued for.

**Every column bound is restated here as a pydantic constraint, and the reason is where the
tests run.** ``tests/test_admin`` is on in-memory SQLite, which enforces neither CHECK
constraints nor ``VARCHAR`` lengths and will happily store a 900-character verification error in
a ``String(200)`` column — so a bound that lives only in the model is a bound this suite cannot
see and Postgres discovers in production, inside a transaction that has already cleared the
previous selection. Restated here it is a 422 naming the field, before a session opens.
``_checked_bodies`` in ``schemas/broadcasts.py`` is the precedent and makes the case in full.

**The one bound that is NOT a length is the one that matters most.** ``chatId`` must be
NEGATIVE. A non-negative Telegram id is a PRIVATE chat — a person — and
:class:`~bayram.contracts.BotChatType` has no ``private`` member precisely so that a person
cannot be recorded in this table. An operator who pastes their own user id must be told they
pasted a person, not have the support inbox quietly pointed at a direct-message thread where
every ticket card would be visible to exactly one human being and to nobody else.
:func:`~bayram.bot_chats.chat_type_for_pasted_id` refuses the same value in the data layer and
the two cannot disagree, because the rule is "negative" in both places and there is nothing to
drift; what this copy buys is *when* — a 422 naming ``chatId``, rather than a
:class:`~bayram.errors.ValidationError` surfacing from two statements deeper.

**Neither request carries a ``reasonCode``, and that is this namespace's second departure from
§12.4.** ``schemas/tickets.py`` argues the first at length and the argument is not quite the
same here, so it is made again rather than borrowed. §12.4 requires a reason for a DESTRUCTIVE
action — one that deletes a record, discloses a customer's name, bars an account or mints
spendable credit. Repointing the support inbox destroys nothing and discloses nothing: it
changes where the NEXT card is posted, every ticket already in the queue is untouched, and the
act is undone by selecting the previous group again. What carries the accountability is the
``admin_audit_log`` row, which names the actor, their role, their IP, the chat selected AND the
chat the tickets were taken away from — plus ``bot_chats.selected_by_username`` and
``selected_at``, which stay standing on the row afterwards. A mandatory code picked from a list
would be answered with the same member every time, which is an accountability control switching
itself off while continuing to look enabled.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final

from pydantic import Field

from bayram.admin.schemas.common import ApiModel
from bayram.contracts import BotChatSource, BotChatStatus, BotChatType
from bayram.db.admin.views import BotChatListItem
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH
from bayram.db.models.bot_chat import (
    BOT_CHAT_TITLE_LENGTH,
    BOT_CHAT_USERNAME_LENGTH,
    VERIFICATION_ERROR_LENGTH,
)

__all__ = [
    "MIN_CHAT_ID",
    "MAX_THREAD_ID",
    "SupportGroupView",
    "SupportGroupsResponse",
    "SupportGroupSelectRequest",
    "SupportGroupSelectionView",
    "SupportGroupSelectResponse",
    "SupportGroupClearResponse",
    "to_support_group_view",
    "to_groups_response",
]

#: ``bot_chats.chat_id`` is ``BIGINT``, so this is the floor of a signed 64-bit integer and not
#: a number chosen here. Stated because JSON has no integer width: a body carrying
#: ``-99999999999999999999`` is syntactically fine, passes every other check on this model, and
#: becomes a ``DataError`` from inside the transaction that has already cleared the previous
#: selection — on Postgres. On the SQLite this suite runs against it is simply stored, so the
#: bound would never be tested at all. There is no matching ceiling: :attr:`chatId` is bounded
#: above by ``lt=0``, which is the stronger rule and the one the module docstring argues.
MIN_CHAT_ID: Final[int] = -(2**63)

#: A forum topic id is a Telegram MESSAGE id — the id of the message that opened the topic — so
#: it is positive and fits the same column width. ``0`` is refused rather than accepted as "no
#: topic": ``null`` is how this API says the group itself, and a zero stored in ``thread_id``
#: would be a topic id Telegram has never issued, posted into by a worker that has no way to
#: tell it apart from a real one.
MAX_THREAD_ID: Final[int] = 2**63 - 1


# ---------------------------------------------------------------------------
# requests
# ---------------------------------------------------------------------------
class SupportGroupSelectRequest(ApiModel):
    """Point the support inbox at this chat, and optionally at one topic inside it.

    **One endpoint takes this body whether or not the chat is already known**, which is the
    whole shape of the feature rather than a convenience. Telegram has no "list my groups" API,
    so a group the bot was already sitting in when this shipped can never be discovered; a
    pasted id is the only route to it, and a separate "add a chat" call would invent a state —
    added, unselected, unverified, unowned — that means nothing here. An id the directory has
    never heard of is recorded as ``source=manual`` by the same call that selects it, and the
    verification job is what tells the truth about the claim. ``routers/support_groups.py``
    states that where an operator's client would look for it.

    There is no ``reasonCode`` — see the module docstring, which argues the departure rather
    than borrowing ``schemas/tickets.py``'s.
    """

    #: NEGATIVE, always. The module docstring argues why a non-negative id is refused here
    #: rather than guessed at, and :func:`~bayram.bot_chats.chat_type_for_pasted_id` refuses it
    #: again in the data layer. ``lt=0`` and not ``le=-1``: the same set, said the way the rule
    #: reads ("a group chat id is negative"), so a future reader does not have to work out
    #: whether the off-by-one was deliberate.
    chat_id: Annotated[int, Field(lt=0, ge=MIN_CHAT_ID)]
    #: The forum topic to post cards into, or absent for the group itself. Absent is the
    #: ordinary case: most groups are not forums.
    #:
    #: **Sending it is how it is kept.** ``select_support_group`` sets ``thread_id`` from this
    #: field on every call, so re-selecting the same group without it clears the topic — by
    #: design, because the topic travels with the selection and "the group, no topic" has to be
    #: expressible. A panel form that omits the field on an edit meaning "leave it alone" moves
    #: the inbox out of the topic it was in, which is a real failure and is why this note is
    #: here rather than in the SPA alone.
    thread_id: Annotated[int | None, Field(default=None, gt=0, le=MAX_THREAD_ID)] = None


# ---------------------------------------------------------------------------
# responses
# ---------------------------------------------------------------------------
class SupportGroupView(ApiModel):
    """One chat the bot knows it is in, as the Support group screen draws it.

    **Every column of the table crosses, and this is the only view on this wire that can say
    that.** It is not an exception to the redaction rule: it is a record the rule has nothing to
    say about. There is no customer anywhere on this row — the one field that would have been a
    person, ``my_chat_member.from_user``, is the field ``bot_chats`` deliberately does not store
    — so there is no id to mask and no ``*Chars`` count to substitute for anything.
    :class:`~bayram.db.admin.views.BotChatListItem` argues each column; this model is that
    record on the wire and adds nothing to it.

    **There is no ``isVerified`` boolean, on purpose.** It would be a second answer to the
    question :attr:`verified_at` and :attr:`verification_error` already answer between them, and
    the panel needs THREE states, not two: proved (a clock), refused (a reason to render in
    words), and never checked (both null — which is where every freshly pasted id sits, and
    where a selection whose verification job was refused by a worker-less deployment stays). A
    boolean collapses the last two into "not verified" and loses the only one an operator can
    act on.

    The maximum lengths below are the columns' own, restated for the module docstring's reason.
    None of them has a validator, because nothing on this surface accepts one on the way IN:
    every string here is written by Telegram, by the verification job or by the session that
    made the selection.
    """

    #: Telegram's own id and the table's primary key. NEGATIVE for every row — a group's id is
    #: negative and a supergroup's begins ``-100`` — and 64 bits wide the whole way to the wire.
    #: A client that parses it into a 32-bit integer is naming a chat that does not exist.
    chat_id: int
    chat_type: BotChatType
    #: What the group calls itself, or ``None`` until something learns it — which for a pasted
    #: id means until the verification job's ``getChat`` runs. The title is the only way an
    #: operator tells four negative numbers apart, so a missing one is a fact to render rather
    #: than a hole to fill with the id again.
    title: Annotated[str | None, Field(default=None, max_length=BOT_CHAT_TITLE_LENGTH)] = None
    #: The public ``@handle``. ``None`` for every private group, which is most of them.
    username: Annotated[str | None, Field(default=None, max_length=BOT_CHAT_USERNAME_LENGTH)] = None
    #: **Evidence, never permission.** What Telegram last said about the bot's standing, at the
    #: instant it said it — an administrator can have ``can_post_messages`` taken away with no
    #: membership transition sent at all, and a ``manual`` row has never had a transition in the
    #: first place. A green badge drawn from this field is a chat the panel claims works and the
    #: bot cannot write a word into. The badge comes from :attr:`verified_at`.
    bot_status: BotChatStatus
    #: Telegram's own word that the bot is in this room (``membership_event``) or an operator's
    #: claim that it is (``manual``). **The screen must render it.** The two exist as separate
    #: values only because Telegram has no "list my groups" API, and drawing them identically
    #: presents a typed-in guess with the same confidence as a fact.
    source: BotChatSource
    #: The selection. At most one row in this response holds ``True``, enforced by a partial
    #: unique index rather than by whoever wrote the last endpoint.
    is_support_group: bool
    #: The forum topic cards are posted into, or ``None`` for the group itself. 64 bits wide,
    #: like :attr:`chat_id`, and travels beside it because a topic id means nothing apart from
    #: the chat it is a topic OF.
    thread_id: int | None = None
    #: When the bot was last PROVED able to post here, by a job that actually tried. ``None``
    #: means nobody has checked since this row last changed — which is the state every freshly
    #: pasted id is in, and the reason a selection is never reported to an operator as a success.
    #:
    #: **"Since this row last changed" is enforced and not merely hoped for.** ``/select`` nulls
    #: this column and :attr:`verification_error` together in the statement that claims the row,
    #: so a chat verified in August and re-selected today comes back here as ``None`` rather
    #: than with a clock that describes a check of a selection nobody has made since. Reading
    #: this field as "the last time we ever managed to post there" is the mistake that draws a
    #: green badge over a room the bot was thrown out of;
    #: :func:`~bayram.db.bot_chats.select_support_group` argues it where the statement is.
    verified_at: datetime | None = None
    #: Why the last check failed, in words an operator can act on: the chat was not found, the
    #: bot is not a member, the bot cannot post there, or the group was upgraded to a supergroup
    #: and has a NEW id — which the message names, because a migrated group is a dead inbox that
    #: looks exactly like a healthy one. Mutually exclusive with :attr:`verified_at`.
    verification_error: Annotated[
        str | None, Field(default=None, max_length=VERIFICATION_ERROR_LENGTH)
    ] = None
    #: The operator's login, denormalised with no foreign key: a rename must not rewrite who
    #: repointed the support inbox. The only human name on this row, and it is a colleague's.
    selected_by_username: Annotated[
        str | None, Field(default=None, max_length=ACTOR_USERNAME_LENGTH)
    ] = None
    #: NOT cleared when a chat is unselected. "This was once the support group, chosen by this
    #: person, on that day" is the most useful thing to know about a chat somebody is looking at
    #: while wondering where last month's tickets went.
    selected_at: datetime | None = None
    #: TELEGRAM's clocks — ``ChatMemberUpdated.date`` from the first and most recent membership
    #: updates — and never this system's. For a ``manual`` row both are the instant the id was
    #: pasted, which is the only instant such a row has.
    first_seen_at: datetime
    last_seen_at: datetime
    #: OURS: when this process wrote the row and when it last changed it. Published beside the
    #: two above rather than instead of them, because the gap between the pairs is real —
    #: ``delete_webhook(drop_pending_updates=True)`` throws away the updates that arrived while
    #: the bot was down, so a row can be written long after the event it describes.
    created_at: datetime
    updated_at: datetime


class SupportGroupsResponse(ApiModel):
    """Every chat in the directory, the selected one first. **Unpaged, and it always will be.**

    A wrapper object rather than a bare JSON array, for :class:`SupportBoardView`'s reason one
    namespace along: a top-level array is a shape nothing can be added to later without breaking
    every client that indexed it. There is no ``meta`` and there must never be one —
    :func:`~bayram.db.admin.bot_chats.list_bot_chats` returns the whole table by construction
    and argues at length why a cursor over a handful of rows would be four rows of machinery and
    a screen whose one question is answered on page two.

    **The selected chat is in this list and is not lifted out beside it.** A ``selected`` field
    next to ``groups`` would be a second answer to "which one is it?", assembled from a second
    statement, and the two would eventually disagree about a directory that changed between
    them. The flag on the row is the same fact the database enforces to be true of at most one
    row; a client finds it by looking, and it is first.
    """

    groups: list[SupportGroupView]


class SupportGroupSelectionView(ApiModel):
    """What one press of Select actually did — the half the panel cannot work out for itself.

    :attr:`previous_chat_id` is the chat the tickets were taken away from. By the time this
    response is built the selection has already been cleared and set inside one transaction, so
    it is unreadable from the directory and is carried out of the writer instead; it is also the
    ``before`` half of the ``admin_audit_log`` row, which is the single most useful fact in that
    entry.

    :attr:`created` is the other half. An id the table had never heard of is recorded as
    ``source=manual`` by the same call, and an operator who has just conjured a row out of a
    number they typed should be told so — it is the difference between "you repointed the inbox
    at a group we know the bot is in" and "you repointed it at a claim nothing has checked".

    **Nothing here says the selection WORKS**, and that is the shape of the whole feature: this
    process cannot talk to Telegram, so it reports what it recorded and enqueues the job that
    will find out. The panel is expected to render the row as "checking…" until
    :attr:`SupportGroupView.verified_at` or :attr:`SupportGroupView.verification_error` says
    otherwise, rather than claiming success the moment this response arrives.
    """

    chat_id: int
    #: ``None`` when nothing was selected before. May EQUAL :attr:`chat_id` — re-selecting the
    #: same group to change its topic is an ordinary act, not a no-op — which is why
    #: :attr:`moved` is published rather than left to be inferred by comparing the two.
    previous_chat_id: int | None = None
    thread_id: int | None = None
    #: ``True`` when this call inserted a ``manual`` row for an id the directory did not hold.
    created: bool
    #: ``True`` when future cards will arrive somewhere they were not arriving before. Derived
    #: server-side from the pair above so the panel's sentence and the audit row's cannot
    #: disagree about whether the inbox actually moved.
    moved: bool


class SupportGroupSelectResponse(ApiModel):
    """The directory as it now stands, plus what the press did to it.

    The list is re-read inside the request's transaction after the write, exactly as every
    ticket action answers with the record as it now stands: a response assembled from what the
    handler *believes* it wrote would be the panel telling an operator about a state nothing
    confirmed. It also saves the SPA a round trip it would otherwise make immediately.
    """

    groups: list[SupportGroupView]
    selection: SupportGroupSelectionView


class SupportGroupClearResponse(ApiModel):
    """The directory with nothing selected, and which chat that used to be.

    :attr:`cleared_chat_id` is ``None`` when there was nothing to clear, and that case is a
    **200 rather than a 404**: "no group is selected" is the state the caller asked for, it is a
    supported state rather than a broken one — tickets keep working, only the group post stops —
    and answering a second press with an error would make the panel report a failure for having
    arrived at exactly the outcome it wanted. Idempotent, and said out loud because the obvious
    alternative is a 404 that looks tidy and reads as a bug.
    """

    groups: list[SupportGroupView]
    cleared_chat_id: int | None = None


# ---------------------------------------------------------------------------
# record -> wire. Pure, and the only place a chat becomes bytes.
# ---------------------------------------------------------------------------
def to_support_group_view(item: BotChatListItem) -> SupportGroupView:
    """One directory row on the wire. A straight copy, and it is meant to stay one.

    There is nothing to compute here — no mask, no derived boolean, no count standing in for a
    string — which is unusual on this wire and is the point:
    :class:`~bayram.db.admin.views.BotChatListItem` is already the shape the screen needs, and a
    projection that started deriving fields would be the place the "green badge from
    ``bot_status``" mistake got made.
    """
    return SupportGroupView(
        chat_id=item.chat_id,
        chat_type=item.chat_type,
        title=item.title,
        username=item.username,
        bot_status=item.bot_status,
        source=item.source,
        is_support_group=item.is_support_group,
        thread_id=item.thread_id,
        verified_at=item.verified_at,
        verification_error=item.verification_error,
        selected_by_username=item.selected_by_username,
        selected_at=item.selected_at,
        first_seen_at=item.first_seen_at,
        last_seen_at=item.last_seen_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def to_groups_response(items: tuple[BotChatListItem, ...]) -> SupportGroupsResponse:
    """The whole directory on the wire, in the order the read layer returned it.

    Not re-sorted here. ``list_bot_chats`` orders selected-first, then by ``last_seen_at``, then
    by ``chat_id`` for a total order, and argues each term; re-doing it here would be a second
    implementation of a promise that already has one, and the two would eventually disagree
    about a tie.
    """
    return SupportGroupsResponse(groups=[to_support_group_view(item) for item in items])
