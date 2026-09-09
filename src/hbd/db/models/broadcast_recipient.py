"""``broadcast_recipients`` — the frozen audience, the send log and the retry ledger, in one table.

Those three are deliberately not three tables, because they are three readings of the same
row and splitting them would make the arithmetic of a campaign a join. A row is written when
the audience is materialised (the audience), it carries the outcome of the one message aimed
at that account (the log), and it carries the attempt count and the error that decide whether
another attempt is owed (the ledger).

**PERSISTED STATE, NOT JOB STATE, AND THIS IS NOT A NICETY.** ARQ ships with
``retry_jobs=True`` and SIGTERM cancels a running job so it runs again on the next boot, so
"which of these forty thousand people have already been messaged?" is a question the queue
cannot answer and this table must. ``SENDING`` is written and COMMITTED before the message
leaves; that commit is what makes the claim exclusive, and it is why a killed job leaves rows
that are ``SENDING`` rather than rows that are lost.

**THE UNIQUE CONSTRAINT IS THE IDEMPOTENCY AUTHORITY.** ``UNIQUE (broadcast_id,
telegram_user_id)`` makes a second row for the same account in the same campaign impossible at
the database, so a replayed expansion chunk is an ``insert_or_ignore`` no-op — the
``user_activity_snapshots`` pattern — rather than a branch some future writer forgets. Note
what it does and does not buy: the constraint makes a duplicate ROW structurally impossible,
and the ``PENDING -> SENDING`` claim above makes a duplicate SEND impossible. Both halves are
needed and neither substitutes for the other.

The constraint is deliberately hostile to erasure, in the correct direction.
:attr:`BroadcastRecipientRow.telegram_user_id` becomes NULL when ``/forget`` runs, and both
engines permit any number of NULLs in a unique index — so anonymised rows stop participating
in uniqueness and keep their counts. That is exactly right: the campaign's arithmetic
survives, and the person does not.

**THE ONLY SUPPRESSION SIGNAL IS A BLOCK.** ``SKIPPED_BLOCKED`` covers both directions of it —
``users.is_blocked`` (our bar) and ``users.blocked_bot_at`` / a ``TelegramForbiddenError`` at
send time (theirs) — because neither is a delivery attempt. There is no consent column and no
opt-out column on this table, and a future one belongs on a table of its own keyed to the
account, never here: this row is about one message, and a standing preference that outlives
the campaign cannot be stored on a row that is swept with it.

**A skipped account is INSERTED, never filtered out.** The funnel from audience to messages is
then arithmetic in this table — ``recipient_count`` = sent + failed + skipped + undeliverable +
unknown + still-pending — instead of a ``WHERE`` clause every future reader has to remember.
An audience that shrinks silently between the preview and the send is the single defect this
whole design is arranged against.

**Not personal data, and in NEITHER of ``tests/test_db/test_privacy_constraints.py``'s two
sets** — recorded there rather than left silent, and it may NOT borrow ``vendor_usage``'s
argument, because this table carries a ``telegram_user_id`` and is therefore about an
identified person. Its route is ``bot_membership_events``', ``credit_ledger``'s and
``plan_purchases``': erasure by ANONYMISATION, nulling the id in place and keeping the row so
the campaign's counts survive. It is NOT in ``tables_erased_on_request``, whose stated
semantics are "the absence of a row IS the erasure record; ``/forget`` DELETEs it outright" —
deleting these rows would silently rewrite the delivery record of a campaign that has already
gone out. It is NOT in ``tables_with_personal_data`` either, because that set demands a
``*_expires_at`` clock, and that suffix obliges a sweep BY NAME in
``tests/test_db/test_audit_retention.py`` and would claim a legal schedule this table does not
have. Its growth — by far the fastest in this schema, one row per account per campaign — is
bounded instead by a CUTOFF on ``created_at``, counted by
``purge_runs.broadcast_recipients_deleted``, which is defence in depth beside the erasure arm
and never a substitute for it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.contracts import BroadcastRecipientState, Language
from hbd.db.base import Base, TimestampMixin, UtcDateTime, enum_type

__all__ = ["BroadcastRecipientRow", "ERROR_CODE_LENGTH"]

#: A symbolic ``hbd.errors`` member or a Telegram error CLASS token — never a response body.
#: Matches ``chat_messages`` and ``admin_audit_log``, because the same taxonomy fills all
#: three.
ERROR_CODE_LENGTH: Final[int] = 48


class BroadcastRecipientRow(TimestampMixin, Base):
    """One account's place in one campaign, and how the one message aimed at it ended.

    ``TimestampMixin`` IS used, and both clocks earn their place. ``created_at`` is when the
    audience was materialised — indexed by the mixin, which is exactly the predicate the
    retention cutoff sweeps on. ``updated_at`` is when the row last moved, which is how a
    ``SENDING`` row left behind by a killed job is aged into ``UNKNOWN`` without a fourth
    clock: the sweep reads "in ``SENDING`` and not touched for N minutes".
    """

    __tablename__ = "broadcast_recipients"
    __table_args__ = (
        # THE IDEMPOTENCY AUTHORITY — see the module docstring. Unnamed so
        # ``NAMING_CONVENTION``'s ``uq`` template renders
        # ``uq_broadcast_recipients_broadcast_id_telegram_user_id``, which is what the
        # migration must spell through ``batch_op.f``.
        sa.UniqueConstraint("broadcast_id", "telegram_user_id"),
        # THE TWO HOT QUERIES, and they are the same shape. Claiming a chunk is
        # ``WHERE broadcast_id = :id AND state = 'pending' LIMIT :n``; the progress rollup is
        # ``SELECT state, count(*) … WHERE broadcast_id = :id GROUP BY state``. Both run
        # repeatedly against the largest table in the schema while an operator watches a
        # progress bar, and ``broadcast_id`` alone does not narrow them: on a completed
        # campaign every row shares it and the pending scan would read all forty thousand to
        # find none. Hand-named to the shape ``NAMING_CONVENTION`` would render, so the
        # migration and the model agree under
        # ``test_the_migrated_indexes_match_the_model_metadata``.
        sa.Index("ix_broadcast_recipients_broadcast_id_state", "broadcast_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: ``CASCADE``: a deleted campaign takes its ledger with it. There is no route by which a
    #: campaign is deleted while it is running — terminal states are reached, not removed —
    #: and the audit trail of the send lives on ``admin_audit_log``, which nothing here
    #: cascades to.
    broadcast_id: Mapped[UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("broadcasts.id", ondelete="CASCADE"), nullable=False
    )
    #: Who. **NULLABLE ONLY SO THAT ERASURE HAS SOMEWHERE TO GO** — the expansion always knows
    #: the account, so a NULL means one thing only: ``/forget`` ran. Indexed for that
    #: anonymising ``UPDATE`` first, which runs inside the transaction a customer's erasure is
    #: waiting on and must not scan the largest table in the schema; and for "was this person
    #: sent that campaign?" second, which is the first question of any complaint. No foreign
    #: key to ``users``, following every other table that holds this column: the delivery
    #: record must outlive the account row.
    telegram_user_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, index=True)
    #: The account's language AT EXPANSION, snapshotted rather than joined. The body is chosen
    #: from this column, so a campaign counted as 3 000 Russian readers sends 3 000 Russian
    #: messages even if some of them switch language while it runs — and a body that exists
    #: for every language on the frozen audience cannot become a body that is missing for one.
    language: Mapped[Language] = mapped_column(enum_type(Language), nullable=False)
    #: Where this one message got to. No Python-side default, on ``broadcasts.state``'s
    #: argument: the expansion writes ``PENDING`` explicitly and every move after it is a
    #: conditional ``UPDATE`` naming the state it expects, so there is no path on which a
    #: state is set by omission.
    state: Mapped[BroadcastRecipientState] = mapped_column(
        enum_type(BroadcastRecipientState), nullable=False
    )
    #: How many times a send has been ATTEMPTED for this row — incremented in the same
    #: statement that claims it, so a row that is retried forever is visible as a number
    #: rather than inferred from a log. ``SmallInteger`` because the retry budget is single
    #: digits and a column that could hold 2 000 000 000 attempts invites one.
    attempts: Mapped[int] = mapped_column(sa.SmallInteger, nullable=False, default=0)
    #: Why it failed, as a symbolic token. **Never an excerpt of a vendor response**, on
    #: ``vendor_usage``'s argument: a third party's error body can quote what we sent it, and
    #: a column that can hold a message is a column a message ends up in.
    error_code: Mapped[str | None] = mapped_column(sa.String(ERROR_CODE_LENGTH), nullable=True)
    #: When this row stopped moving — the instant it reached ``SENT``, ``FAILED``,
    #: ``SKIPPED_BLOCKED``, ``UNDELIVERABLE`` or ``UNKNOWN``. NULL while it is ``PENDING`` or
    #: ``SENDING``.
    #:
    #: Deliberately ONE clock named for settlement rather than a ``sent_at`` named for one
    #: outcome. A ``sent_at`` could not stamp a skip or a refusal, so every non-sent row would
    #: carry a NULL that means "never settled" and "settled, not by a send" at the same time —
    #: and the pair an operator actually reads is "what happened" beside "when did it stop",
    #: which is this column beside :attr:`state`. The send instant is recoverable exactly when
    #: it exists: ``state = 'sent'`` narrows it, and nothing else does.
    settled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
