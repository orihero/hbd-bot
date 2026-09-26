"""``broadcasts`` — one campaign, with the audience it was pointed at frozen onto the row.

**The segment document is stored, not referenced.** A campaign is composed against a filter
the operator built on the records screen, and that filter is a *document* (``bayram.db.admin.
segment``), not a saved object with an id. Keeping a copy here is what lets the panel answer
"who was this sent to?" a year later, after the fields have been re-labelled and the operator
who built it has left — and it is the only form of that answer that cannot drift, because a
re-evaluated segment answers "who would match NOW", which is a different question and, on a
campaign that has already gone out, a misleading one. :attr:`BroadcastRow.segment_hash`
beside it is what lets the wizard say "this campaign used the segment you are looking at"
without comparing two JSON blobs field by field.

**THE AUDIENCE IS FROZEN AT CREATION, AND THIS TABLE IS WHERE THAT PROMISE IS KEPT.** The
recipient rows are materialised when the campaign is created; the send delivers to exactly
those rows and re-compiles nothing. A campaign scheduled for Friday therefore reaches whoever
matched on Tuesday. That is a product decision and not an implementation detail, so both of
its consequences are stored rather than inferred: :attr:`audience_evaluated_at` is the ``now``
the segment was compiled against, and :attr:`audience_size` is the exact count it returned.
Without the pair, "why did twelve fewer people get this than the preview said" has no answer
at all — and the answer is nearly always "they joined after Tuesday", which is correct
behaviour that looks like a bug until the row can prove it.

**:attr:`audience_size` and :attr:`recipient_count` are two numbers on purpose.** The first is
what ``count_segment_exactly`` returned at creation; the second is how many
``broadcast_recipients`` rows the expansion actually wrote. They are equal on every healthy
campaign and they are the *evidence* that a campaign is healthy —  ``purge_runs``'
``storage_keys_returned``/``storage_keys_deleted`` split, in a different domain and for the
identical reason. Smoothing them into one "audience" column would hide a half-written
expansion behind a number that looks right.

**The counters are denormalised and the rows are truth.** ``broadcast_recipients`` is the
ledger; the five counters here are a rollup recomputed per chunk so the list screen can draw a
progress bar without an aggregate over forty thousand rows per campaign per poll. A counter
that disagrees with its rows is a rollup bug, and the repair is to recompute it from the rows
— never the other way round.

``UNKNOWN`` gets its own counter for the reason ``BroadcastRecipientState`` states: a row left
in ``SENDING`` by a killed job may or may not have reached Telegram, it is never retried, and
folding it into ``failed_count`` would report a message that possibly *was* delivered as one
that certainly was not. It is small, it is real, and the operator sees it as its own number.

**No free-text reason column, deliberately, and this is a departure worth stating.** The
schedule request carries ``ReasonedRequest``'s ``reason_text``, and it is written to
``admin_audit_log`` — which owns the 90-day clock that nulls it (``reason_expires_at``) and
the sweep that reads that clock. A copy here would be the same operator prose ("Dilnoza asked
us to…") on a row with no clock and no sweep behind it, which is precisely the retention leak
``admin_audit_log.reason_text`` was given two columns to avoid. The closed
:class:`~bayram.db.enums.AuditReasonCode` and the bounded ticket reference carry the
accountability and hold no prose, so they are stored; the prose stays where it is swept.

**Not personal data, and in NEITHER of ``tests/test_db/test_privacy_constraints.py``'s two
sets** — recorded in a comment there rather than left silent, on the footing
``user_activity_snapshots`` uses. Every column here is a UUID, an operator's username, a
closed enum, an integer count, a clock, a hex digest, or the segment document — and the
segment document is a list of registry KEYS and their bounded values (``plan_status in
[lapsed]``), never a name, a number or free text about anybody. It narrows to a population,
never to a person; the per-account rows are on ``broadcast_recipients``, which carries its own
argument.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.contracts import BroadcastKind, BroadcastState
from bayram.db.base import SHA256_LENGTH, Base, TimestampMixin, UtcDateTime, enum_type
from bayram.db.enums import AuditReasonCode
from bayram.db.models.admin_audit import ACTOR_USERNAME_LENGTH, REASON_REF_LENGTH

__all__ = [
    "BroadcastRow",
    "BROADCAST_TITLE_LENGTH",
    "EXPAND_CURSOR_LENGTH",
    "ERROR_CODE_LENGTH",
]

#: Operator-facing only — this string is never sent to anybody. Sized like every other short
#: human label in the panel, and bounded rather than free because a title is rendered in a
#: list row.
BROADCAST_TITLE_LENGTH: Final[int] = 120
#: A base64url keyset cursor from ``bayram.db.admin.page``. 256 is comfortably above the encoded
#: ``SortedCursor`` (a key name, a direction, an ISO-8601 instant and a UUID) and leaves room
#: for a sort key added later without a migration.
EXPAND_CURSOR_LENGTH: Final[int] = 256
#: ``BayramError.error_code`` is a short symbolic name, never a message. Matches
#: ``chat_messages`` and ``admin_audit_log`` exactly, because the same taxonomy fills all
#: three.
ERROR_CODE_LENGTH: Final[int] = 48


class BroadcastRow(TimestampMixin, Base):
    """One campaign: what was composed, who it was aimed at, and how far it has got.

    ``TimestampMixin`` IS used, unlike on the append-only tables in this package. This row is
    a state machine — ``draft`` -> ``expanding`` -> ``ready`` -> ``sending`` -> ``completed``,
    with ``paused`` the one state that goes back — and every move is a conditional ``UPDATE``.
    ``updated_at`` is therefore true, and it is the cheapest evidence an operator has of when
    a stuck campaign last moved.

    **No foreign key to ``admin_users``**, following ``admin_audit_log``'s reasoning one step
    further: that table takes ``ON DELETE RESTRICT`` so history cannot be orphaned, and a
    campaign is history of the same kind. A deactivated operator's campaign must survive them,
    and the username is denormalised beside the id for the identical reason the audit row
    denormalises its actor — a rename must not silently rewrite who sent forty thousand
    messages.
    """

    __tablename__ = "broadcasts"
    __table_args__ = (
        # THE ONE SCAN A SCHEDULER RUNS: ``WHERE state = 'ready' AND scheduled_for <= :now``.
        # Hand-named, and the migration must spell it identically, because
        # ``test_the_migrated_indexes_match_the_model_metadata`` compares index NAMES.
        #
        # It is also the ONLY declared index on this table, and the omissions are deliberate.
        # A single-column index on ``state`` would be redundant with this one's leading
        # column, which is exactly the "three unused indexes shipped" mistake ``orders``
        # records; a single-column index on ``scheduled_for`` serves no query the composite
        # does not; and the list screen's ``ORDER BY created_at DESC, id DESC`` runs against
        # a table that gains a handful of rows a week, where ``ix_broadcasts_created_at``
        # from the mixin is already more index than the row count earns.
        sa.Index("ix_broadcasts_state_scheduled_for", "state", "scheduled_for"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: What an operator calls this campaign in the list. NEVER sent to a customer — the
    #: message is entirely in ``broadcast_bodies``, so a working title cannot leak into a
    #: chat.
    title: Mapped[str] = mapped_column(sa.String(BROADCAST_TITLE_LENGTH), nullable=False)
    #: ``service`` or ``marketing``. One column, never one predicate: see
    #: :class:`bayram.contracts.BroadcastKind` for why collapsing the two would make widening
    #: the first quietly widen the second.
    kind: Mapped[BroadcastKind] = mapped_column(enum_type(BroadcastKind), nullable=False)
    #: Where the run has got to. No Python-side default: every transition is an explicit
    #: conditional ``UPDATE`` naming the state it expects and the state it writes, and a
    #: default would be the one place a campaign's state was set by omission —
    #: ``payment_intents.state``'s argument, and the stake here is a send.
    state: Mapped[BroadcastState] = mapped_column(enum_type(BroadcastState), nullable=False)

    # -- the frozen audience -------------------------------------------------
    #: The segment document, exactly as it was compiled. ``none_as_null=True`` for the reason
    #: ``briefs.approved_lyrics`` carries it: without it, ``None`` persists as the JSON scalar
    #: ``null`` rather than SQL ``NULL``, and ``segment IS NOT NULL`` stops meaning what a
    #: reader assumes. The column is NOT NULL regardless — a campaign aimed at nothing in
    #: particular is spelled as the empty root group, which is "everyone" said out loud.
    segment: Mapped[dict[str, Any]] = mapped_column(sa.JSON(none_as_null=True), nullable=False)
    #: ``sha256`` of the canonical JSON above. Not a security property — it is how the panel
    #: recognises "this campaign used the segment you are looking at" in one comparison
    #: instead of a structural diff of two documents.
    segment_hash: Mapped[str] = mapped_column(sa.String(SHA256_LENGTH), nullable=False)
    #: The exact ``SELECT count(*)`` over the segment at creation — never ``bounded_total``,
    #: which saturates at 10 000 and would make this read "10,000+" on precisely the campaign
    #: nobody could then approve. NOT NULL with no default: the count is taken before the row
    #: is written, so a writer that does not know the audience must not be able to guess it.
    audience_size: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: The ``now`` the segment was compiled against — the instant the audience was frozen.
    #: NOT NULL for the same reason as above, and load-bearing: every relative operator in the
    #: DSL (``within_last_days`` and friends) is a function of one instant, so without this
    #: column the stored document cannot be re-read to mean what it meant.
    audience_evaluated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    #: The keyset cursor the materialisation resumes from, NULL before it starts and after it
    #: finishes. Expansion is chunked and every ARQ job is replayed on deploy, so the position
    #: has to survive the process — a cursor held only in a job argument is a cursor a SIGTERM
    #: restarts from the beginning, which is how an audience gets written twice. (It cannot
    #: actually be sent twice; ``broadcast_recipients``' unique constraint sees to that. This
    #: column is what stops it being *rewritten* for an hour on every deploy.)
    expand_cursor: Mapped[str | None] = mapped_column(
        sa.String(EXPAND_CURSOR_LENGTH), nullable=True
    )

    # -- the clocks ----------------------------------------------------------
    #: When the send is due. NULL means "as soon as the audience is ready". Indexed through
    #: ``ix_broadcasts_state_scheduled_for`` above, never on its own.
    scheduled_for: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: When the first message of the run left. NULL until it did.
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: When the run reached a terminal state — completed, cancelled or failed. NULL while it
    #: is still moving, and never cleared by a resume, because a campaign that finished twice
    #: is not a thing this schema should be able to express.
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # -- the rollup: denormalised counters, recomputed FROM the recipient rows -
    #: How many ``broadcast_recipients`` rows exist. Compare with :attr:`audience_size`; see
    #: the module docstring on why these are two numbers.
    recipient_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    sent_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    #: Rows skipped without an attempt because the account was unreachable — the operator's
    #: bar or the customer's own block. A skip is inserted rather than filtered out, so the
    #: funnel from audience to messages is arithmetic in the table instead of a filter
    #: somebody has to remember.
    skipped_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    #: Telegram said the chat is gone. Distinct from a skip (we knew beforehand) and from a
    #: failure (we may retry).
    undeliverable_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    #: Rows a killed job left in ``SENDING`` and the sweep aged out. Neither sent nor failed,
    #: and never retried: messaging a customer twice is worse than an unresolved three in
    #: forty thousand. Its own counter because a number folded into ``failed_count`` would
    #: report a possibly-delivered message as certainly undelivered.
    unknown_count: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    # -- who -----------------------------------------------------------------
    #: The operator who composed it, and the one who authorised the send. Two pairs because
    #: they are two different acts by possibly two different people, and the second is the one
    #: that steps up. No foreign key; see the class docstring.
    created_by_admin_id: Mapped[UUID | None] = mapped_column(sa.Uuid, nullable=True)
    created_by_username: Mapped[str | None] = mapped_column(
        sa.String(ACTOR_USERNAME_LENGTH), nullable=True
    )
    scheduled_by_admin_id: Mapped[UUID | None] = mapped_column(sa.Uuid, nullable=True)
    scheduled_by_username: Mapped[str | None] = mapped_column(
        sa.String(ACTOR_USERNAME_LENGTH), nullable=True
    )

    # -- why -----------------------------------------------------------------
    #: Why this campaign exists, captured at schedule. A closed enum and a bounded ticket
    #: reference only — the free-text half of ``ReasonedRequest`` is deliberately NOT stored
    #: here; see the module docstring.
    reason_code: Mapped[AuditReasonCode | None] = mapped_column(
        enum_type(AuditReasonCode), nullable=True
    )
    reason_ref: Mapped[str | None] = mapped_column(sa.String(REASON_REF_LENGTH), nullable=True)

    #: Terminal failure of the RUN, not of a recipient — a symbolic ``bayram.errors`` name, never
    #: a vendor message. A campaign in which twelve of forty thousand messages were refused is
    #: ``completed`` with twelve failed rows, and this column stays NULL.
    error_code: Mapped[str | None] = mapped_column(sa.String(ERROR_CODE_LENGTH), nullable=True)
