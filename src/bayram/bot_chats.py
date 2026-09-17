"""Which groups the bot is in, and which one of them the support tickets go to.

The support group used to be ``BAYRAM_SUPPORT_GROUP_CHAT_ID`` — an integer read out of the
environment by anything that needed it, changed by editing a unit file and redeploying. It is
now a row in ``bot_chats``, and a row is not something a bot handler may read for itself: this
module is the seam it reads through, holding the port protocol, the frozen values that cross
it, and the one pure function that has to give the same answer on both sides of it.

**WHY THIS IS A NEW TOP-LEVEL MODULE AND NOT THREE MORE METHODS ON ``bayram.support``.** That
was the other candidate and it is the obvious one: the only thing anybody wants from this
table today is "where do the ticket cards go?", every caller of that question already imports
``bayram.support``, and a second module means a second copy of the leaf rules below. It was
still refused, on two grounds.

First, ``bot_chats`` is not a support table. It records **every** chat the bot is added to —
a marketing group, a developer group, a channel somebody made it an administrator of — and the
writer is a ``my_chat_member`` registration that has no idea what support is and must not
acquire one. A handler recording that the bot joined a group would then be importing the
module whose docstring opens "what a complaint is worth to the bot", and the next person to
read it would reasonably conclude the bot only tracks support groups. The selection is one
boolean column on a directory; the directory is not a feature of the selection.

Second, the shapes do not overlap by a single field. ``bayram.support`` is eleven methods over
two tables about one customer's complaint, and its own docstring argues at length why those
eleven belong together — "a ticket is a ticket". Nothing here is a ticket. The two modules
share a domain in the panel's sidebar and nowhere in the code.

So this follows :mod:`bayram.lyric_budget`, which is the precedent this repo already set for
exactly this size of thing: one table, one narrow port, one ``Sql*`` implementation under
``bayram.db``, one container field and one wiring line in ``bayram.main``. The parallel is
deliberate down to the module names — ``bayram.lyric_budget`` beside ``bayram.db.lyric_budget``,
``bayram.support`` beside ``bayram.db.support_tickets``, and now this beside
:mod:`bayram.db.bot_chats`.

**THIS MODULE IS A LEAF AND MUST STAY ONE.** It imports ``bayram.contracts`` and
``bayram.errors`` and nothing else — in particular never ``bayram.db`` and never
``bayram.config``. The rule is not tidiness; it is the circular import ``bayram.entitlements``
documents: a port naming a ``bayram.db`` type would make the module every bot handler imports
pull in the ``bayram.db`` package, whose ``__init__`` imports modules that import
``bayram.contracts``. It is also what lets the whole bot suite run this seam against a fake
with a fixed clock and no database at all.

**TELEGRAM HAS NO "LIST MY GROUPS" API, AND EVERY SHAPE BELOW IS BENT AROUND THAT.** A bot
cannot enumerate its own chats. The only way it ever learns a group exists is a
``my_chat_member`` update — delivered when its OWN membership changes — so a group the bot was
already sitting in when this feature shipped produces no event and can never be discovered.
That is why :class:`MembershipSighting` exists at all (the one authoritative route, and it
arrives as a push nobody asked for), why a pasted chat id is a first-class route rather than a
debugging convenience (:func:`chat_type_for_pasted_id`), and why "the bot says it is a member"
and "the bot has been proved able to post" are two different fields on
:class:`BotChatSnapshot` rather than one.

**STATUS IS EVIDENCE; ``verified_at`` IS PERMISSION.** :attr:`BotChatSnapshot.bot_status` is
what Telegram last told us, at the instant it told us. It is not a capability: an administrator
can have ``can_post_messages`` taken away with no membership transition sent at all, a group can
be deleted under us in silence, and a ``manual`` row has never had a transition in the first
place. The only field that answers "can the bot post here" is :attr:`BotChatSnapshot.verified_at`,
written by the job that actually tried. A caller — or a panel row — that renders a green badge
off ``bot_status`` is the one misuse of this seam worth naming twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, runtime_checkable

from bayram.contracts import BotChatSource, BotChatStatus, BotChatType, Result
from bayram.errors import ValidationError

__all__ = [
    # Values
    "MembershipSighting",
    "SupportGroupTarget",
    "BotChatSnapshot",
    "SelectionChange",
    # Pure
    "SUPERGROUP_ID_PREFIX",
    "chat_type_for_pasted_id",
    # Seam
    "BotChatDirectory",
]

#: Every supergroup and channel id Telegram issues begins with these four characters; an
#: ordinary basic group's does not. See :func:`chat_type_for_pasted_id` for what is and is not
#: inferred from that, and for why the inference is allowed to be wrong.
SUPERGROUP_ID_PREFIX: Final[str] = "-100"


def chat_type_for_pasted_id(chat_id: int) -> BotChatType:
    """The best guess at what kind of chat a bare pasted id names.

    **This exists because ``bot_chats.chat_type`` is NOT NULL and a pasted id carries no type
    with it.** The alternatives were both worse. Making the column nullable would put "we do
    not know" into the schema for the one row shape that is *already* the untrusted one, and
    every reader would then need a third branch. Asking the operator to pick the type in the
    panel would be asking them to answer a question Telegram's own id format answers, and to
    get it wrong in a way nothing would ever correct.

    **The guess is deliberately allowed to be wrong, because something else fixes it.** An id
    beginning ``-100`` is a supergroup *or a channel* and this function says supergroup, which
    is right almost always and unverifiable here either way. That is acceptable only because
    the ``support:verify_group`` job calls ``getChat`` on every selection and overwrites this
    column with Telegram's own word — so the guess survives for as long as it takes one job to
    run, and the row an operator is shown afterwards is not a guess at all. If that job is ever
    removed, this function becomes a lie the panel repeats forever; they ship together.

    **A non-negative id is refused rather than guessed at**, and this is the half that is not a
    convenience. A positive Telegram id is a PRIVATE chat — a person — and
    :class:`~bayram.contracts.BotChatType` has no ``private`` member precisely so that a person
    cannot be recorded in this table (the churn recorder's ``my_chat_member`` registration owns
    private chats, and the two registrations stay structurally disjoint). An operator who
    pastes their own user id must be told they pasted a person, not have the support inbox
    quietly pointed at a direct message thread where every ticket card would be visible to
    exactly one human being and to no one else.

    Raises :class:`~bayram.errors.ValidationError`, which the admin router renders as a 422
    naming the field. The router validates the same bound in its request schema as well, for
    the reason ``_checked_bodies`` gives — ``tests/test_admin`` runs on in-memory SQLite, which
    enforces neither a length nor a check constraint, so a bound stated only in the database is
    a bound that unit tests cannot see.
    """
    if chat_id >= 0:
        raise ValidationError(
            "a group chat id is negative; a non-negative id names a private chat",
            context={"chat_id": chat_id},
        )
    if str(chat_id).startswith(SUPERGROUP_ID_PREFIX):
        return BotChatType.SUPERGROUP
    return BotChatType.GROUP


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MembershipSighting:
    """One ``my_chat_member`` update about a group, reduced to what may be stored.

    **THIS TYPE IS THE ENFORCEMENT OF A RULE THAT IS OTHERWISE ONLY A COMMENT.** The upsert
    behind :meth:`BotChatDirectory.record_membership` may write six columns and must not touch
    the other six: ``is_support_group``, ``thread_id``, ``selected_by_username``,
    ``selected_at``, ``verified_at`` and ``verification_error`` belong to the operator and to
    the verification job, and a membership update that reset any of them would mean the bot
    being promoted to administrator in the selected group — or simply re-added after a
    restart — silently unselected the support inbox, tickets stopped arriving, and nothing
    anywhere said why. ``BotChatRow``'s class docstring states that rule. This dataclass is
    what makes it structural: the recorder cannot pass a field it has no slot for, so the rule
    survives somebody adding a column to the table without reading the comment above it.

    It deliberately does NOT carry ``from_user``, which Telegram supplies on every one of these
    updates and which is the person who added the bot. Storing it would make ``bot_chats`` a
    table about a human being — with an erasure route to write, a place to claim in
    ``tests/test_db/test_privacy_constraints.py``, and an answer owed about what ``/forget``
    does to a group other people still use. The model argues that at length; this value object
    is where the field is dropped, before any of it reaches persistence.

    :attr:`at` is **Telegram's clock** and never ours. See the attribute.
    """

    #: Negative for a group, ``-100…`` for a supergroup or channel. Never a private chat: the
    #: router's type filter is what guarantees that, exactly as ``membership.py``'s
    #: ``ChatType.PRIVATE`` filter guarantees the opposite for the churn recorder.
    chat_id: int
    chat_type: BotChatType
    #: What the group calls itself right now. Refreshed on every sighting, so a renamed group
    #: is renamed in the panel rather than listed under a name nobody uses any more.
    title: str | None
    #: The public ``@handle``. ``None`` for every private group, which is most of them.
    username: str | None
    #: What Telegram says the bot's standing is **as of this update**. Evidence, not
    #: permission — see the module docstring.
    bot_status: BotChatStatus
    #: ``ChatMemberUpdated.date``: the instant TELEGRAM stamped the transition, tz-aware, and
    #: never ``deps.clock()``. ``bayram.bot.handlers.membership`` refuses the same substitution
    #: on the same update for the same reason, and the gap between the two clocks is real —
    #: ``delete_webhook(drop_pending_updates=True)`` on every start throws away the updates
    #: that arrived while the bot was down, so a row can be written long after the event it
    #: describes, or never. Our own clock lands in ``created_at``/``updated_at``, which is why
    #: :meth:`BotChatDirectory.record_membership` takes both.
    at: datetime


@dataclass(frozen=True, slots=True)
class SupportGroupTarget:
    """Where a ticket card goes: a chat, and optionally a topic inside it.

    **Two fields and not a whole :class:`BotChatSnapshot`**, because this is what the posting
    path is allowed to know. A caller handed the full row would have ``bot_status`` in scope at
    the exact moment it is deciding whether to send, and the module docstring names reading that
    column as a capability as the one misuse of this seam that matters. There is nothing to
    decide here: the selection is the operator's answer to "where", the verification job is the
    answer to "can we", and the sender's job is to send.

    The two travel together because a topic id is meaningless apart from the chat it is a topic
    OF. As two environment variables they could be — and eventually would be — edited apart,
    which is a card posted into a thread that does not exist in the group it was sent to.
    """

    chat_id: int
    #: The forum topic to post into, or ``None`` for the group itself. ``None`` is the ordinary
    #: case and not a missing value: most groups are not forums.
    thread_id: int | None


@dataclass(frozen=True, slots=True)
class BotChatSnapshot:
    """One ``bot_chats`` row as everything outside persistence sees it.

    A frozen value and NOT the ORM row, which is this repo's standing rule for every seam: a
    ``BotChatRow`` handed to a handler is a detached instance whose attributes are read after
    its session closed, and inside async SQLAlchemy that surfaces as a greenlet error at a
    random later ``await`` rather than as an error where the mistake was made.

    Every column crosses, including the two clocks, because unlike a ticket there is nothing
    here to withhold: a chat id, a chat title, a public ``@handle``, three closed enums, a
    boolean, an operator's own login and a bounded error string. No customer appears on this
    row at all — the one field that would have been a person, ``my_chat_member.from_user``, is
    the field this table deliberately does not store.
    """

    chat_id: int
    chat_type: BotChatType
    title: str | None
    username: str | None
    #: Telegram's last word on the bot's standing. Never a capability; see :attr:`verified_at`.
    bot_status: BotChatStatus
    #: Telegram's own word that the bot is here (``membership_event``), or an operator's claim
    #: that it is (``manual``). A reader that renders the two identically presents a typo with
    #: the same confidence as a fact.
    source: BotChatSource
    is_support_group: bool
    thread_id: int | None
    #: The last time the verification job PROVED it can post here. ``None`` means nobody has
    #: checked since this row was last written — which is the state every freshly pasted id is
    #: in, and the reason a selection is never reported to an operator as a success.
    verified_at: datetime | None
    #: Why the last check failed, in words an operator can act on. Mutually exclusive with
    #: :attr:`verified_at`: the writer clears each when it sets the other, so a row never shows
    #: a green proof beside a red reason.
    verification_error: str | None
    selected_by_username: str | None
    #: When the selection was last made — and NOT cleared when a chat is unselected. "This was
    #: once the support group" is the most useful thing to know about a chat somebody is
    #: looking at while wondering where last month's tickets went.
    selected_at: datetime | None
    #: Telegram's clocks, not ours. See :attr:`MembershipSighting.at`.
    first_seen_at: datetime
    last_seen_at: datetime
    #: Ours: when this process wrote the row, and when it last changed it.
    created_at: datetime
    updated_at: datetime

    @property
    def is_verified(self) -> bool:
        """The bot has been proved able to post here at least once since the last change.

        The property exists so that no caller writes ``snapshot.bot_status == MEMBER`` and
        believes it has asked this question. They are different questions and the second one
        has a wrong answer available.
        """
        return self.verified_at is not None

    @property
    def target(self) -> SupportGroupTarget:
        """Where a card would go if this chat were the selected one. Pure projection."""
        return SupportGroupTarget(chat_id=self.chat_id, thread_id=self.thread_id)


@dataclass(frozen=True, slots=True)
class SelectionChange:
    """What one press of Select actually did, reported back for the audit row.

    The selection write is a clear and a set inside one transaction, so the caller cannot
    observe the old value by reading before and after — by the time the request's audit row is
    composed the previous selection is already gone. That is what this type carries out:
    :attr:`previous_chat_id` is the ``before`` an ``admin_audit_log`` entry needs, and without
    it the log would record that somebody selected a group and lose which group they took the
    tickets away from — the single most useful fact in the entry.

    :attr:`created` is the other half the panel cannot infer. An id the table had never heard
    of is recorded as ``source=manual`` by the same call, and an operator who has just invented
    a row from a number they typed should be told so — it is the difference between "you
    repointed the inbox at a group we know the bot is in" and "you repointed it at a claim that
    nothing has checked yet".
    """

    chat_id: int
    #: The chat that was the support group until a moment ago, or ``None`` when nothing was
    #: selected. May equal :attr:`chat_id`: re-selecting the same group to change its topic is
    #: an ordinary act, not a no-op, and it is not reported as a move.
    previous_chat_id: int | None
    thread_id: int | None
    #: ``True`` when this call inserted a ``manual`` row for an id the directory did not hold.
    created: bool

    @property
    def moved(self) -> bool:
        """The tickets will now arrive somewhere they were not arriving before."""
        return self.previous_chat_id is not None and self.previous_chat_id != self.chat_id


# ---------------------------------------------------------------------------
# Seam
# ---------------------------------------------------------------------------
@runtime_checkable
class BotChatDirectory(Protocol):
    """The seam between "the bot is in some groups" and the table that remembers which.

    Implemented by ``bayram.db.bot_chats.SqlBotChats``, which owns exactly one transaction per
    method and never raises. Held by ``BotDeps`` and by the worker's container as an optional,
    trailing field: ``None`` means this deployment has no chat directory, which is a supported
    configuration and not a degraded one — the bot then records nothing and posts no cards,
    exactly as it behaved before the support feature existed.

    ``runtime_checkable`` verifies member PRESENCE only and never signatures. ``mypy --strict``
    over ``tests`` is what actually catches a fake that has drifted from this protocol, which is
    why the fakes live under ``tests`` and are type-checked there.

    **SELECTING AND CLEARING ARE DELIBERATELY NOT ON THIS PROTOCOL.** They are the only two
    writes that move the selection, they happen exactly once each, in the admin panel, and they
    have to land in the same transaction as the ``admin_audit_log`` row that records who did it
    — so they are module-level functions in :mod:`bayram.db.bot_chats` taking the request's own
    ``AsyncSession``, the shape ``bayram.db.support_tickets`` already uses for the same reason.
    Putting them here would hand the bot process a method that can repoint the support inbox
    with no audit row behind it, and there is no caller that wants one.

    **There is no ``list_chats`` here either.** The only reader of the whole directory is the
    panel, which reads through ``bayram.db.admin.bot_chats`` like every other screen; a bot
    handler that could enumerate every group the bot is in would be one loop away from posting
    into all of them.
    """

    async def record_membership(
        self, sighting: MembershipSighting, *, now: datetime
    ) -> Result[bool]:
        """Record that Telegram just said something about the bot's membership of a group.

        Upsert: a chat nobody has seen before becomes a row, a chat already known has its
        title, ``@handle``, type, status and ``last_seen_at`` refreshed. ``True`` means this
        call was the first sighting of that chat — a fact worth an INFO line, and nothing else:
        no caller branches on it, and a race between two simultaneous first sightings would at
        worst log it twice.

        **Two clocks, and the split is not incidental.** ``sighting.at`` is Telegram's stamp on
        the transition and lands in ``first_seen_at``/``last_seen_at``; ``now`` is ours and
        lands in ``created_at``/``updated_at``. Passing one for the other would either downgrade
        Telegram's own stamp to "whenever our worker happened to be running" or claim we wrote a
        row at an instant we did not.

        Never raises, and the handler behind it must be structurally incapable of raising for
        the reason ``membership.py`` documents: the ``my_chat_member`` observer carries neither
        ``InboundGateMiddleware`` nor ``ErrorGuardMiddleware``, so an escaping exception is
        logged by aiogram and lost — and here it would be lost silently, because nobody is
        waiting on this update.
        """
        ...

    async def selected_support_group(self) -> Result[SupportGroupTarget | None]:
        """Where ticket cards go, or ``None`` when no group is selected.

        ``None`` is an ordinary answer and not a failure: a fresh deployment has never selected
        anything, and an operator may clear the selection deliberately. Tickets keep working
        when it is ``None`` — only the group post stops — so every caller treats it as "do not
        post" rather than as an error to surface to a customer.

        **This is also how the group router decides whether an incoming message is from the
        support group**, by comparing the chat it arrived in against this answer. There is no
        ``is_selected(chat_id)`` method beside it on purpose: it would be a second statement
        answering the same question, and the caller that asks it almost always needs the
        ``thread_id`` in the next line anyway.

        **Deliberately uncached.** Group traffic is a handful of messages a day and this is a
        single-row lookup on a partial index the database goes straight to. A cache would buy
        nothing measurable and would cost the one thing this feature was built for: an operator
        who repoints the inbox and finds tickets still arriving in the old group for another
        five minutes has no way to tell whether the change worked. If a cache is ever added,
        the TTL has to be short enough that an operator does not notice it, which is roughly the
        point at which it stops being a cache.
        """
        ...

    async def load_chat(self, chat_id: int) -> Result[BotChatSnapshot | None]:
        """One chat by id, or ``None`` when the directory has never heard of it.

        The verification job's read: it is handed a chat id, and it needs the topic to post its
        confirmation into and the ``source`` to know whether it is checking Telegram's word or
        an operator's claim.
        """
        ...

    async def record_verified(
        self,
        chat_id: int,
        *,
        at: datetime,
        title: str | None = None,
        username: str | None = None,
        chat_type: BotChatType | None = None,
    ) -> Result[bool]:
        """Record that the bot really can post in this chat, right now. ``False`` if unknown.

        Called only after a send actually succeeded — not after ``getChat`` returned, which
        proves the chat exists and nothing about whether we may write into it. ``at`` is OUR
        clock: this is a fact about when we tried, not about anything Telegram stamped.

        ``title``, ``username`` and ``chat_type`` are optional because the caller may have just
        learned them from ``getChat``, and a ``manual`` row pasted as a bare number has no title
        until exactly that moment. Passing ``None`` leaves the stored value alone rather than
        erasing it — a verification that could blank a title would make the one row an operator
        is least able to recognise even harder to recognise.

        **``chat_type`` is the half that redeems a guess, and it is why this parameter exists at
        all.** :func:`chat_type_for_pasted_id` infers ``supergroup`` from a ``-100`` prefix and
        cannot tell a supergroup from a CHANNEL, which it is allowed to do only because this
        call overwrites the column with Telegram's own word the first time the job runs. Without
        it the inference is not a guess that gets corrected, it is a guess the panel repeats for
        the life of the row — and the two ship together or neither is honest.

        Writing this **clears any stored verification error**; see
        :meth:`record_verification_failed` for why the two columns are kept exclusive.

        ``False`` means no such row, and no row is created: a verification result about a chat
        nobody selected is a job running against a deleted row, and inventing the row back
        would resurrect a chat an operator removed on purpose.
        """
        ...

    async def record_verification_failed(
        self, chat_id: int, *, message: str, at: datetime
    ) -> Result[bool]:
        """Record why the bot could not post here, in words an operator can act on.

        **The message is prose for a human being and the whole point of the feature.** Four
        failures need four different things done about them: the chat was not found (the id is
        wrong), the bot is not a member (add it), the bot cannot post (give it permission), and
        — the one that is invisible without this — the group was upgraded to a supergroup and
        has a NEW id, which must be named in the message so the operator can select it. A
        generic "verification failed" defeats the entire design, because a selected group that
        migrated is a dead inbox that looks exactly like a healthy one.

        Never a vendor exception's ``repr``. The column is bounded at 200 characters and the
        writer trims to fit rather than failing, on the grounds that a failure that could not be
        recorded because it was too long is a failure nobody will ever see; an empty message is
        refused outright, for the same reason from the other end.

        Writing this **clears ``verified_at``**. The two columns are kept mutually exclusive by
        the writers rather than by a ``CheckConstraint``, and this direction is the one that
        matters: a chat that failed its last check must not keep a green badge earned yesterday,
        because the badge is what an operator uses to decide the inbox is fine. What that costs
        is the instant of the last successful check, which is recoverable from the audit trail
        and from ``updated_at``, and which nobody has ever needed to know.

        ``False`` means no such row, and none is created — see :meth:`record_verified`.
        """
        ...
