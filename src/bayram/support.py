"""What a complaint is worth to the bot: the seam it writes through, and the rules it obeys.

The ⚠️ button under a delivered song, and ``/support`` typed from anywhere, both end in a row
in ``support_tickets``. This module is everything the *bot and the worker* need to know about
that without ever naming ``bayram.db``: one port protocol, the pure functions that mint a
reference and decide which board moves are legal, and the small frozen values those carry.

**This module is a leaf and must stay one.** It imports ``bayram.contracts`` and
``bayram.errors`` and nothing else. The rule is not tidiness — it is the same circular import
``bayram.entitlements`` documents at length: a port that named a ``bayram.db`` type would make
this module import the ``bayram.db`` package, whose ``__init__`` imports modules that import
``bayram.contracts``. It also may never import ``bayram.config``; the quota below reads
``Settings`` defensively through ``getattr`` for exactly that reason, the fourth time this
repo runs the idiom (``entitlements.resolve_entitlement_policy``,
``ratelimit.resolve_inbound_policy``, ``lyric_budget.resolve_lyric_budget_policy``).

**Why a port at all, rather than a repository on the container.** ``bayram.bot.deps.BotDeps``
holds no session factory, no repository and no arq pool: every store a handler can reach is a
narrow ``Protocol`` with an ``Sql*`` implementation under ``bayram.db`` and one wiring line in
``bayram.main``. That is what keeps SQLAlchemy out of the module every handler imports —
``handlers/common.py`` guards its single ``bayram.db`` name behind ``if TYPE_CHECKING:`` with a
paragraph saying why — and it is what lets the whole bot suite run against a fake with a fixed
clock and no database at all.

**WHY ONE PORT AND NOT FOUR.** Every other seam in this codebase is one or two methods, and
:class:`SupportTicketStore` is eleven. The split was tried on paper and rejected: a ticket is a
single row with a single lifecycle, and the four candidate seams ("open", "describe", "post to
the group", "work it") would every one of them need to *find* the same row by one of the same
three keys, so the reads would be duplicated across four protocols and four fakes. Worse, the
group-post latch and the status move are the two operations that must not drift apart — a card
re-rendered from one store while another store owned the status is precisely the "the card
says New and the board says Resolved" bug the latch exists to prevent. The narrowness that
matters here is not the method count: it is that this protocol can express **no read of any
other table and no write to any other table**, which a repository handed to handlers could.

**Every clock is a parameter.** ``UtcDateTime`` raises on a naive datetime at bind time, deep
inside the driver and far from the call that caused it, so nothing below calls ``utc_now()``
for itself. Passing ``now`` in is also what lets a test move a ticket through four days of
board moves without sleeping, the rule ``bayram.db.credits`` and ``bayram.db.lyric_budget``
already keep.

**Nothing here raises.** Every method returns ``Result``, like every other protocol in this
codebase, so a handler that opens a ticket needs no ``try`` and a failed complaint is a
refusal message rather than an unhandled exception in front of an already-annoyed customer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from bayram.contracts import (
    Language,
    Result,
    SupportAuthorKind,
    SupportTicketEventKind,
    SupportTicketSource,
    SupportTicketStatus,
)
from bayram.errors import ConfigError

__all__ = [
    # The reference a human quotes
    "SUPPORT_PUBLIC_REF_CHARS",
    "public_ref_for",
    # The board's rules
    "LEGAL_STATUS_MOVES",
    "legal_moves_from",
    "is_legal_move",
    "REOPEN_STATUS",
    "REOPENING_STATUSES",
    "reopen_target",
    # Quota
    "SupportQuota",
    "DEFAULT_SUPPORT_QUOTA",
    "resolve_support_quota",
    "TicketQuotaVerdict",
    # Values
    "EventAuthor",
    "RelayAddressee",
    "TicketSnapshot",
    # Seam
    "SupportTicketStore",
]


# ---------------------------------------------------------------------------
# The reference a human quotes
# ---------------------------------------------------------------------------
#: How much of the ticket id the customer is given and the staffer reads back.
#:
#: Eight, and it is ``bayram.bot.delivery.ORDER_REFERENCE_CHARS`` deliberately rather than
#: coincidentally: that function's whole argument is that a reference must be **reproducible
#: by READING** — it is the leading characters of the id as printed in every log line, in the
#: ``ticket_id`` context of every error and in the database itself, so support resolves it by
#: looking, never by computing an encoding. A second reference scheme in the same product
#: would be a second thing to get wrong on the phone.
#:
#: **There is deliberately no custom alphabet and no ambiguous-glyph story.** Those are worth
#: inventing when a reference is a random token that must survive being read aloud, and the
#: price is that it no longer matches anything in the database. Hex has its own confusable
#: pair (``0``/``O`` does not arise — there is no ``O`` — but ``b``/``6`` does over a bad
#: line), and the mitigation chosen is the one that costs nothing: the ticket id is the
#: authority, the ref is an index into it, and a ref that was misheard resolves to no ticket
#: at all rather than to the wrong one, because :func:`public_ref_for` is injective on its
#: prefix and the column is UNIQUE.
#:
#: The column is ``VARCHAR(12)``. The four unused characters are headroom the model's own
#: docstring reserves for a longer shape — a deployment prefix, a check character — that can
#: be minted later without a migration.
SUPPORT_PUBLIC_REF_CHARS: Final[int] = 8


def public_ref_for(ticket_id: UUID) -> str:
    """The short reference for ``ticket_id``: the leading characters of the id itself.

    Lowercase, because that is how a UUID prints in this system — in logs, in error context
    and in ``psql`` — and a reference an operator has to case-fold before pasting it into a
    ``WHERE`` clause is a reference that has stopped being reproducible by reading. The card
    and the customer's confirmation both render it inside ``<code>``, which is where the
    shouting gets done.

    Pure and total. The uniqueness of the RESULT is not this function's promise and cannot
    be: two UUIDs sharing eight hex characters are astronomically rare but not impossible,
    which is why ``bayram.db.support_tickets`` mints against the unique index rather than
    trusting the arithmetic — see ``mint_ticket_identity`` there.
    """
    return str(ticket_id)[:SUPPORT_PUBLIC_REF_CHARS]


# ---------------------------------------------------------------------------
# The board's rules
# ---------------------------------------------------------------------------
#: Where a ticket may go from where it is. The whole of the board's grammar, in one table.
#:
#: This is a table and not a chain of ``if`` statements because it is read by three callers
#: that must agree — the panel's status endpoint, the group card's ``✅ Resolve`` button and
#: the automatic move a staff reply performs — and three copies of a lifecycle are three
#: chances for the board and the card to disagree about whether a ticket is finished.
#:
#: **A status may not move to itself.** ``X -> X`` is absent from every set on purpose: it is
#: a no-op that would nevertheless write a ``STATUS_CHANGE`` event recording ``from`` and
#: ``to`` as the same value, which is a timeline row that says nothing and an ``updated_at``
#: bump that makes an untouched ticket look worked. Two operators pressing ``✋ Claim`` on one
#: card is the common case, not the exotic one; the second press must be a refused move, not
#: a second event.
#:
#: **``RESOLVED`` reopens to ``IN_PROGRESS`` and to nothing else.** A ticket that comes back
#: is by definition a ticket somebody is now working, and offering ``RESOLVED -> NEW`` would
#: let a reopened complaint re-enter the unlooked-at column and lose the fact that it was
#: answered once already — the most useful thing to know about a repeat complaint.
#: ``resolved_at`` is not cleared by the reopen for the same reason (see the model).
#:
#: **Nothing returns to ``NEW``.** ``NEW`` means "nobody has looked at this yet", which is a
#: claim about the past that a later move cannot make true again.
LEGAL_STATUS_MOVES: Final[Mapping[SupportTicketStatus, frozenset[SupportTicketStatus]]] = {
    # A brand-new ticket can be claimed, can be answered with a question, or can be closed
    # outright — the last is spam and a duplicate, which are common enough that forcing them
    # through ``IN_PROGRESS`` would only add a click and a meaningless event.
    SupportTicketStatus.NEW: frozenset(
        {
            SupportTicketStatus.IN_PROGRESS,
            SupportTicketStatus.WAITING,
            SupportTicketStatus.RESOLVED,
        }
    ),
    SupportTicketStatus.IN_PROGRESS: frozenset(
        {SupportTicketStatus.WAITING, SupportTicketStatus.RESOLVED}
    ),
    # ``WAITING`` is waiting on the CUSTOMER, so what ends it is the customer answering —
    # which puts the ticket back in somebody's hands, or closes it.
    SupportTicketStatus.WAITING: frozenset(
        {SupportTicketStatus.IN_PROGRESS, SupportTicketStatus.RESOLVED}
    ),
    SupportTicketStatus.RESOLVED: frozenset({SupportTicketStatus.IN_PROGRESS}),
}

#: Where a reopened ticket lands. Named rather than spelled at the two call sites (the panel's
#: reopen, and a customer replying to a ticket somebody had closed) so the two cannot drift.
REOPEN_STATUS: Final[SupportTicketStatus] = SupportTicketStatus.IN_PROGRESS

#: The statuses a CUSTOMER'S OWN MESSAGE moves out of, and the only two of the four.
#:
#: Read this beside :data:`LEGAL_STATUS_MOVES`' two "the customer replies" rows, which are the
#: whole of the grammar this set implements. It is a set rather than a chain of ``if``
#: statements in the handler for the reason the table above is a table: the panel's reopen and
#: the bot's follow-up relay must agree about which tickets a customer can wake up, and two
#: spellings of that are two chances to disagree about whether a complaint came back.
#:
#: **``NEW`` is deliberately absent, and its absence is the interesting half.**
#: ``NEW -> IN_PROGRESS`` is a perfectly legal move — it is what ``✋ Claim`` and a staff reply
#: do — but ``IN_PROGRESS`` means *somebody on our side has picked this up*, and a customer
#: adding a second sentence to a ticket nobody has read yet has not made that true. Moving it
#: would empty the unlooked-at column by pretending the backlog had been worked, which is
#: precisely the fiction §4.1 argues a four-column board exists to prevent. ``IN_PROGRESS`` is
#: absent for the duller reason that it is already the destination: ``X -> X`` is in no row of
#: the table, and a no-op move would still write a ``STATUS_CHANGE`` event saying nothing.
REOPENING_STATUSES: Final[frozenset[SupportTicketStatus]] = frozenset(
    {SupportTicketStatus.WAITING, SupportTicketStatus.RESOLVED}
)


def reopen_target(status: SupportTicketStatus) -> SupportTicketStatus | None:
    """Where a ticket in ``status`` goes when the customer speaks again. ``None`` for "stay".

    The one question a follow-up asks about the board, asked the way the caller asks it, so
    that no caller has to hold both :data:`REOPENING_STATUSES` and :data:`REOPEN_STATUS` in
    its head at once. ``None`` is the ordinary answer — most follow-ups land on a ticket that
    is already ``new`` or already ``in_progress`` — and it means *write the reply event and
    move nothing*, never *drop the reply*.
    """
    return REOPEN_STATUS if status in REOPENING_STATUSES else None


def legal_moves_from(status: SupportTicketStatus) -> frozenset[SupportTicketStatus]:
    """Every column this ticket may be dragged to. Empty for nothing, never ``KeyError``.

    Exists so the panel can render exactly the moves it will not be refused for, rather than
    offering four buttons and discovering which three are 422s. Total over the enum by
    construction: a member added to :class:`~bayram.contracts.SupportTicketStatus` without a
    row in :data:`LEGAL_STATUS_MOVES` is a dead-end column here — visibly, in a test — instead
    of a ``KeyError`` raised at whichever call site reached it first.
    """
    return LEGAL_STATUS_MOVES.get(status, frozenset())


def is_legal_move(from_status: SupportTicketStatus, to_status: SupportTicketStatus) -> bool:
    """May a ticket in ``from_status`` be moved to ``to_status``?

    The one question the whole grammar answers, asked the way callers actually ask it. Note
    that this is a question about the MOVE and not about the caller's authority to make it:
    who is allowed to press the button is ``support.write`` in the admin permission table and
    membership of the support group in the bot, and neither is decidable here.
    """
    return to_status in legal_moves_from(from_status)


# ---------------------------------------------------------------------------
# Quota
# ---------------------------------------------------------------------------
#: A customer may hold this many tickets nobody has described yet.
#:
#: Three. The tap is an unmetered write amplifier — one press writes a row AND sends a
#: message into a group Telegram rate-limits at about twenty a minute — which is exactly the
#: failure ``ratelimit.InboundPolicy.erasure_max_updates`` was added for one domain along. The
#: *undescribed* count is the one that matters because those are the free ones: a ticket with
#: no body cost the customer nothing to create and cost us a row and a card.
#:
#: Three rather than one because a customer with two songs delivered may legitimately have a
#: complaint about each and may open the second before typing the first, and refusing them
#: there is refusing a real complaint to save a row.
_DEFAULT_MAX_UNDESCRIBED: Final[int] = 3

#: How many tickets one account may open in a UTC day, described or not.
#:
#: Five. The ceiling that bounds a script rather than a person: nobody with a real problem
#: opens a sixth ticket in a day, and somebody holding the button down gets a bounded,
#: countable number of group cards instead of an unbounded one. The direction of the error is
#: the same one :mod:`bayram.lyric_budget` argues — too tight refuses a paying customer at the
#: one step support exists for, too loose costs rows — so the order of magnitude is the
#: control and the exact number is not load-bearing.
_DEFAULT_MAX_PER_DAY: Final[int] = 5


@dataclass(frozen=True, slots=True)
class SupportQuota:
    """The two numbers ticket creation is metered against. Immutable, injected, never ambient.

    **Deliberately NOT a row-backed counter of its own**, which is the shape
    :class:`bayram.lyric_budget.LyricBudgetStore` takes and the shape this was expected to
    take. It does not need one: ``support_tickets`` IS the durable record, so "how many has
    this account opened today" and "how many are still undescribed" are two predicates over a
    table that is already indexed by ``telegram_user_id``. A second table counting rows in the
    first one would be a denormalisation with nothing to buy — and, worse, one that a
    ``/forget`` delete would leave stale, because the deleted tickets would stop existing
    while the counter went on remembering them.

    It is also not ``bayram.ratelimit``: that module's counters are an in-process dict, and a
    ceiling a customer can reset by making the bot redeploy is not a ceiling.
    """

    max_undescribed: int = _DEFAULT_MAX_UNDESCRIBED
    max_per_day: int = _DEFAULT_MAX_PER_DAY

    def __post_init__(self) -> None:
        """Refuse a quota that cannot be satisfied, at wiring time rather than mid-complaint.

        Either ceiling below one would refuse every customer their FIRST ticket and therefore
        close support entirely — a configuration mistake and not a policy anyone means. Same
        idiom as :meth:`bayram.lyric_budget.LyricBudgetPolicy.__post_init__` and
        :meth:`bayram.ratelimit.InboundPolicy.__post_init__`, so this codebase has one shape
        for "a policy validates itself" rather than three.
        """
        if self.max_undescribed < 1:
            raise ConfigError(
                "a support quota must allow at least one open ticket",
                context={"max_undescribed": self.max_undescribed},
            )
        if self.max_per_day < 1:
            raise ConfigError(
                "a support quota must allow at least one ticket a day",
                context={"max_per_day": self.max_per_day},
            )


DEFAULT_SUPPORT_QUOTA: Final[SupportQuota] = SupportQuota()


def resolve_support_quota(settings: object | None = None) -> SupportQuota:
    """Build the quota this deployment runs on, reading ``Settings`` defensively.

    ``object`` rather than ``Settings`` and ``getattr`` rather than attribute access, for the
    reason the module docstring gives: importing ``bayram.config`` would give this leaf the
    one edge it has none of. A missing, mistyped or nonsensical value falls back to the
    shipped default rather than raising, because a bad number in the environment must not be
    able to take the support door off its hinges.
    """
    if settings is None:
        return DEFAULT_SUPPORT_QUOTA
    return SupportQuota(
        max_undescribed=_positive_int(
            getattr(settings, "support_max_undescribed_tickets", None), _DEFAULT_MAX_UNDESCRIBED
        ),
        max_per_day=_positive_int(
            getattr(settings, "support_max_tickets_per_day", None), _DEFAULT_MAX_PER_DAY
        ),
    )


def _positive_int(value: object, fallback: int) -> int:
    """``value`` if it is a usable ceiling, else ``fallback``. ``bool`` is not an int here."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return fallback
    return value


@dataclass(frozen=True, slots=True)
class TicketQuotaVerdict:
    """The meter's answer to "may this account open one more ticket?".

    Both counts travel, not just the boolean, for the reason
    :class:`bayram.ratelimit.ThrottleVerdict` reports its own: a refusal at the line and a
    script hammering the button want different responses from an operator, and the boolean
    cannot tell them apart. The customer-facing copy names the LIMIT rather than the count,
    because a refusal that says "you have 3" invites a fourth attempt.

    **This verdict is advisory and the store does not enforce it.** ``open_ticket`` writes
    whatever it is asked to write; the caller asks this first. The gap between the two is a
    real race, and it is the same one
    :func:`bayram.db.lyric_budget.claim_write`'s docstring closes over: aiogram holds a
    per-chat FSM isolation lock for the whole of an update, so one account's taps are already
    serialised before they reach here, and the worst outcome of the theoretical loser is one
    ticket over the line. The alternative — folding the check into the write — would make
    ``open_ticket`` a function that sometimes does not open a ticket, which is the signature
    every caller then has to remember to check.
    """

    is_allowed: bool
    #: Tickets this account holds with ``described_at IS NULL``. See :class:`SupportQuota`.
    undescribed: int
    #: Tickets this account opened since midnight UTC, described or not.
    opened_today: int
    quota: SupportQuota

    @property
    def is_holding_too_many(self) -> bool:
        """At the undescribed ceiling: they already hold a prompt they have not answered.

        **Split out from :attr:`is_allowed` because the two ceilings deserve opposite
        answers, and collapsing them is how a blocked customer ended up with three empty
        tickets and no way to reach support.** This one is not abuse, it is a customer who
        tapped ⚠️ and did not finish the sentence; §1.4 of the specification says so in as
        many words — *"a customer who taps ⚠️ four times without typing gets the prompt for
        the ticket they already have, not a fourth row"*. So the right response is to hand
        back the ticket they are holding, not to refuse them. Only :attr:`is_over_daily` is a
        refusal.
        """
        return self.undescribed >= self.quota.max_undescribed

    @property
    def is_over_daily(self) -> bool:
        """Past the per-day ceiling: the one that bounds a script rather than a person.

        This is the refusal. A sixth ticket in one UTC day is not a person with six problems,
        and unlike the undescribed ceiling there is nothing useful to hand back — the tickets
        they opened today may all be described and working. See :class:`SupportQuota`.
        """
        return self.opened_today >= self.quota.max_per_day


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class EventAuthor:
    """Who wrote a timeline row, in the three shapes ``support_ticket_events`` stores.

    One value rather than four loose parameters on every append, because the three identity
    columns are only meaningful in combination — an ``author_admin_username`` beside a
    ``CUSTOMER`` kind is a row claiming an audited actor for an act nobody audited, which is
    exactly what :class:`~bayram.contracts.SupportAuthorKind` keeps apart.

    **It validates nothing, and that is deliberate.** The table carries no CHECK constraint
    tying ``author_kind`` to the column it populates — ``support_ticket_events``' docstring
    argues that over-constraining a log loses rows, and a lost row is a hole in the record of
    what a customer was told. A constructor that raised would put that refusal back one layer
    up and lose the row in Python instead of in SQL, which is not an improvement. The four
    classmethods below are how the right shape is made easy; nothing forbids the wrong one.
    """

    kind: SupportAuthorKind
    #: Set for ``OPERATOR``: an actor with an ``admin_users`` row and an audit trail.
    admin_username: str | None = None
    #: Set for ``CUSTOMER`` and ``STAFF_GROUP``: an actor Telegram knows and we do not.
    telegram_user_id: int | None = None
    #: The staffer's ``@handle`` or first name, so the timeline reads as prose. Denormalised
    #: on purpose — a staffer who renames must not rewrite what the timeline says they said.
    display_name: str | None = None

    @classmethod
    def customer(cls, telegram_user_id: int) -> EventAuthor:
        """The person the ticket is about. No display name: this schema does not hold one."""
        return cls(kind=SupportAuthorKind.CUSTOMER, telegram_user_id=telegram_user_id)

    @classmethod
    def operator(cls, admin_username: str) -> EventAuthor:
        """An operator acting in the admin panel, with an ``admin_audit_log`` row beside."""
        return cls(kind=SupportAuthorKind.OPERATOR, admin_username=admin_username)

    @classmethod
    def staff_group(cls, telegram_user_id: int, *, display_name: str | None = None) -> EventAuthor:
        """A staffer replying from the support group — membership of a chat, not a session."""
        return cls(
            kind=SupportAuthorKind.STAFF_GROUP,
            telegram_user_id=telegram_user_id,
            display_name=display_name,
        )

    @classmethod
    def system(cls) -> EventAuthor:
        """Us. The ``OPENED`` row, the ``GROUP_POSTED`` row, an automatic move out of ``NEW``.

        Its own kind so that "nobody has touched this" stays answerable: a machine transition
        attributed to the last human who spoke makes an untouched ticket look worked.
        """
        return cls(kind=SupportAuthorKind.SYSTEM)


@runtime_checkable
class RelayAddressee(Protocol):
    """The two things you must know to write a customer a sentence about their ticket.

    **This exists because ONE relay template is rendered from TWO different ticket types, and
    the bound on its finished length may only be computed once.** A staffer's answer is
    relayed by the bot process, which holds a :class:`TicketSnapshot`; an operator's answer is
    relayed by the worker's ``relay_support_reply``, which holds a
    ``bayram.db.admin.views.SupportTicketListItem`` because it reads the ticket through the
    PANEL's own query (so the worker and the panel cannot disagree about what the reply says).
    The two types share no base class and never will — one is the bot's leaf-module value, the
    other is the admin read layer's — and ``bayram.support`` may not import either direction
    without the circular import this module's header forbids.

    So the seam is STRUCTURAL: ``bayram.bot.handlers.support.relay_text_for`` takes this
    protocol, both callers satisfy it by having the fields, and ``mypy --strict`` proves it at
    each call site. The two alternatives were both refused. Widening the parameter to ``Any``
    would turn a rename of either field into a runtime ``AttributeError`` in the one job that
    answers an unhappy customer. Copying the fitting logic into the worker would put two
    implementations of "does this message fit in 4096 characters" in a feature whose whole
    supersession note (``SUPPORT_TICKETS_SPEC §3.5``) is about the first one having been wrong.

    **Read-only properties and not bare attributes**, so a frozen value and a mutable one both
    conform and neither renderer can write back through the seam. Nothing here is a method: a
    protocol this small exists to name two fields, and anything that grows a verb belongs on
    :class:`SupportTicketStore` instead.
    """

    @property
    def public_ref(self) -> str:
        """The reference the customer already holds, quoted back so a follow-up ties to it."""
        ...

    @property
    def language(self) -> Language:
        """The locale the TICKET was opened in — never the account's language today."""
        ...


@dataclass(frozen=True, slots=True)
class TicketSnapshot:
    """One ticket as the bot and the worker see it — everything needed to render its card.

    A frozen value and NOT the ORM row, which is the rule this whole seam exists to keep: a
    ``SupportTicketRow`` handed to a handler is a detached instance whose every unloaded
    attribute is a greenlet error waiting for an ``await``, and whose relationships are
    ``lazy="raise"`` precisely so that mistake is loud rather than slow. Every field below is
    a plain scalar read inside the transaction that produced it.

    The field set is exactly what ``bot/support_card.py`` renders plus the three keys a
    lookup happens by. It deliberately does NOT carry the event timeline: the card shows the
    current state, the panel shows the history, and a snapshot that dragged every event along
    would make the group-post path pay for a second query it never reads.
    """

    id: UUID
    public_ref: str
    telegram_user_id: int
    #: The locale the ticket was OPENED in. The relay answers in this, not in the account's
    #: language today — see the model: an account that switched language in between would
    #: otherwise get the one message where being understood is the entire point in a language
    #: it no longer reads.
    language: Language
    source: SupportTicketSource
    order_id: UUID | None
    status: SupportTicketStatus
    #: The customer's own words, or ``None`` while they have not answered the prompt yet.
    body: str | None
    prompt_message_id: int | None
    described_at: datetime | None
    assigned_admin_username: str | None
    group_chat_id: int | None
    group_message_id: int | None
    group_posted_at: datetime | None
    created_at: datetime

    @property
    def is_described(self) -> bool:
        """The customer actually typed something. ``False`` is a real row, not a missing one."""
        return self.described_at is not None

    @property
    def is_posted(self) -> bool:
        """The card reached the group. ``False`` means the post is still owed — never lost."""
        return self.group_message_id is not None


# ---------------------------------------------------------------------------
# Seam
# ---------------------------------------------------------------------------
@runtime_checkable
class SupportTicketStore(Protocol):
    """The seam between "a customer has a problem" and the two tables that remember it.

    Implemented by ``bayram.db.support_tickets.SqlSupportTickets``, which owns exactly one
    transaction per method. Held by ``BotDeps`` as an optional, trailing field: ``None`` means
    no persistence at all, which is a supported configuration rather than a degraded one —
    the ⚠️ button falls back to the sentence it rendered before this feature existed.

    ``runtime_checkable`` verifies member PRESENCE only and never signatures. ``mypy --strict``
    over ``tests`` is what actually catches a fake that has drifted from this protocol, which
    is the reason the fakes live under ``tests`` and are type-checked there.

    **Read the four lookups as one design.** A ticket is found by its id (the panel knows
    it), by the message it is currently listening on (the customer replied to something we
    sent), by the card it was posted as (a staffer replied in the group), or — on the open
    path only — as this account's newest undescribed row, so a customer at the undescribed
    ceiling is handed the ticket they already hold instead of a refusal. There is
    deliberately no "find by telegram_user_id" returning a LIST: the bot never shows a
    customer their ticket history, and a method that could would be one screen away from a
    customer reading a row an operator wrote.
    """

    # -- opening -------------------------------------------------------------
    async def check_open_quota(
        self,
        telegram_user_id: int,
        *,
        now: datetime,
        quota: SupportQuota = DEFAULT_SUPPORT_QUOTA,
    ) -> Result[TicketQuotaVerdict]:
        """May this account open another ticket? Advisory — see :class:`TicketQuotaVerdict`.

        Two counts over ``support_tickets`` and no counter table; the reasoning is on
        :class:`SupportQuota`. ``now`` fixes the UTC day the daily count is taken over, so a
        test moves a variable rather than waiting for midnight.
        """
        ...

    async def open_ticket(
        self,
        *,
        telegram_user_id: int,
        language: Language,
        source: SupportTicketSource,
        order_id: UUID | None,
        now: datetime,
    ) -> Result[TicketSnapshot]:
        """Write the row a tap creates, with no body and no description clock, plus its
        ``OPENED`` event.

        Unconditional: the quota is the caller's question and this is the answer to a
        different one. The returned snapshot carries the ``public_ref`` the customer is about
        to be shown, which is why this returns a value rather than an id.
        """
        ...

    async def attach_prompt(
        self, ticket_id: UUID, *, prompt_message_id: int, now: datetime
    ) -> Result[bool]:
        """Record which ForceReply message this ticket is waiting on. ``False`` if unknown.

        A second statement rather than a column on :meth:`open_ticket`, because the row must
        exist BEFORE the prompt is sent: a prompt whose ticket failed to write is a message
        asking a customer to describe a problem into nothing.
        """
        ...

    async def latest_undescribed_ticket(
        self, telegram_user_id: int
    ) -> Result[TicketSnapshot | None]:
        """The newest ticket this account opened and never described, or ``None``.

        **The ticket handed back when the undescribed ceiling is reached**
        (:attr:`TicketQuotaVerdict.is_holding_too_many`), which is the half of §1.4 the first
        build left out: the specification's rule is "a customer who taps ⚠️ four times without
        typing gets the prompt for the ticket they already have, not a fourth row", and a
        refusal is not that. Newest rather than oldest because it is the one whose prompt is
        still on their screen; the older ones are scrolled away and re-pointing at one of them
        would put a ForceReply in front of a customer quoting a reference they never saw.

        This is NOT the "find by telegram_user_id returning a list" the class docstring
        refuses. It answers with at most one row, it is reachable only from the open path, and
        it can show a customer nothing an operator wrote — an undescribed ticket has no body
        and no reply.
        """
        ...

    # -- the customer's words ------------------------------------------------
    async def ticket_listening_on(
        self, telegram_user_id: int, *, prompt_message_id: int
    ) -> Result[TicketSnapshot | None]:
        """The ticket this account's reply belongs to, described or not, or ``None``.

        ``telegram_user_id`` is required and is not decoration: ``prompt_message_id`` is a
        per-chat counter, so two customers hold the same value routinely, and a lookup on the
        message id alone would attach one person's complaint to another person's ticket.

        **It deliberately does NOT narrow to ``described_at IS NULL``, and the rename from
        ``ticket_awaiting_reply_to`` records why.** ``prompt_message_id`` is not "the
        ForceReply we sent once"; it is *the message this ticket is currently listening on*,
        re-pointed at each relay by :meth:`listen_on`. Narrowed to undescribed rows, a
        customer's answer to a staff reply — the thing ``support.ticket.reply`` ends by
        inviting — matched nothing here, fell past the support router, and was claimed by
        whichever wizard step they happened to be parked in: at ``Wizard.name`` their sentence
        became the recipient's name and the product SANG IT. Widening the lookup is what makes
        that invitation true, and the caller branches on
        :attr:`TicketSnapshot.is_described` to decide whether the message is the complaint or
        a follow-up to it.
        """
        ...

    async def listen_on(
        self, ticket_id: UUID, *, prompt_message_id: int, now: datetime
    ) -> Result[bool]:
        """Re-point a ticket at the message it should now hear replies to. ``False`` if gone.

        Deliberately UNCONDITIONAL, which is the one way it differs from
        :meth:`attach_prompt` and the reason both exist. ``attach_prompt`` is conditional on
        ``prompt_message_id IS NULL`` so that a replayed open cannot orphan the ForceReply the
        customer can still see; this is called when a *newer* message has taken over the
        conversation — the relay of a staff answer — and refusing to move because a value is
        already there would leave the ticket listening on a prompt from three weeks ago while
        the customer replies to the paragraph in front of them.

        There is no new column behind this. ``support_tickets.prompt_message_id`` is exactly
        what §2.1 says it is — "the ForceReply prompt this ticket waits on" — read as the
        general case: the ticket waits on whatever we spoke to it with last.
        """
        ...

    async def describe_ticket(
        self, ticket_id: UUID, *, body: str, now: datetime
    ) -> Result[TicketSnapshot | None]:
        """Fill the body, stamp ``described_at`` and write the ``DESCRIBED`` event.

        Conditional on the ticket still being undescribed, so a customer who answers the same
        prompt twice describes it once: the second call returns ``None`` and the caller says
        "we already have that" instead of overwriting the first complaint with a follow-up
        sentence. ``None`` also covers an unknown id.
        """
        ...

    # -- the group card ------------------------------------------------------
    async def claim_group_post(
        self, ticket_id: UUID, *, group_chat_id: int, group_message_id: int
    ) -> Result[bool]:
        """Take the once-only right to have posted this ticket's card. ``True`` means won.

        **Called BEFORE the Telegram send and committed before it**, because ARQ runs with
        ``retry_jobs=True`` and SIGTERM cancels running jobs: every job in this system is
        replayed on every deploy, and a record of "the card was posted" that lives in the job
        is a record that posts the card again. A ``False`` is not an error — it is another
        worker having already posted it.
        """
        ...

    async def settle_group_post(self, ticket_id: UUID, *, now: datetime) -> Result[bool]:
        """Stamp ``group_posted_at`` once Telegram has taken the card. Committed after.

        A row with a message id and no clock is therefore a send that crashed mid-flight,
        which is a state worth being able to see rather than one smoothed away.
        """
        ...

    async def release_group_post(self, ticket_id: UUID) -> Result[bool]:
        """Give the claim back when the send provably never left this process.

        The only route from "claimed" back to "unposted", and it is as narrow as
        ``bayram.db.broadcasts.release_recipient``'s for the same reason: a caller that
        released a claim after a request whose outcome is UNKNOWN would post a second card
        into the group, and two cards for one ticket means a staffer answering on the one the
        relay is not listening to.
        """
        ...

    async def ticket_for_group_message(
        self, *, group_chat_id: int, group_message_id: int
    ) -> Result[TicketSnapshot | None]:
        """The ticket a staffer's reply belongs to, or ``None`` when it replies to something
        that is not one of our cards.

        The chat id is checked as well as the message id even though ``group_message_id`` is
        unique: message ids are per-chat, and a bot moved to a second group would otherwise
        resolve a stranger's reply to a ticket posted in the first one.
        """
        ...

    # -- working it ----------------------------------------------------------
    async def move_status(
        self,
        ticket_id: UUID,
        *,
        expected: SupportTicketStatus,
        to_status: SupportTicketStatus,
        author: EventAuthor,
        now: datetime,
    ) -> Result[TicketSnapshot | None]:
        """Move a ticket between columns, conditionally, writing the ``STATUS_CHANGE`` event.

        ``expected`` is required and has no default: the move is a conditional ``UPDATE``
        whose rowcount is the lock, so two staffers pressing ``✅ Resolve`` on one card
        produce one move and one event. ``None`` means the ticket had already left
        ``expected`` — the caller re-reads and re-renders rather than retrying.

        An illegal move (:func:`is_legal_move`) is an ``Err`` and not a ``None``, because the
        two mean different things: ``None`` is "somebody got there first", which is ordinary,
        and an illegal move is a caller that offered a button it should not have.
        """
        ...

    async def assign_ticket(
        self, ticket_id: UUID, *, admin_username: str, author: EventAuthor, now: datetime
    ) -> Result[TicketSnapshot | None]:
        """Record who has this ticket, and write the ``ASSIGNED`` event. ``None`` if unknown.

        Separate from :meth:`move_status` because a ticket can be claimed without being moved
        and moved without being claimed — ``✋ Claim`` in the group does both, in two
        statements, and the panel's assign does only this one.
        """
        ...

    async def append_event(
        self,
        ticket_id: UUID,
        *,
        kind: SupportTicketEventKind,
        author: EventAuthor,
        now: datetime,
        body: str | None = None,
    ) -> Result[UUID]:
        """Append one row to the timeline and return its id.

        The id comes back because a ``REPLY`` is composed here and delivered later: the
        caller needs it to stamp :meth:`mark_relayed` once the message really reached the
        customer's private chat.
        """
        ...

    async def mark_relayed(self, event_id: UUID, *, now: datetime) -> Result[bool]:
        """Stamp ``relayed_at`` on a reply that actually reached the customer.

        The one clock written after insert on an append-only table, and it is not an
        amendment: the row records that a reply was COMPOSED, this records that it was
        DELIVERED, and a reply that was written but never landed must read differently from
        one that did. ``False`` when the event is unknown or has already been stamped.
        """
        ...

    # -- reading it back -----------------------------------------------------
    async def load_ticket(self, ticket_id: UUID) -> Result[TicketSnapshot | None]:
        """One ticket by id, for a job that was handed an id and must re-render its card."""
        ...
