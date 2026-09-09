"""``payme_transactions`` — what the RAIL thinks happened, stored verbatim beside our own.

An intent is our record of an offer. This is the rail's record of a CHARGE, mirrored into
our database because the rail resends every one of its calls until it gets an answer it
likes, and "did we already answer this, and with what?" is a question no amount of care in
the handler can answer without a row.

**THIS TABLE IS THE ENTIRE RETRY STORY, and the unique index on ``payme_transaction_id`` is
the whole of it.** The rail's protocol guarantees that create, perform and cancel are each
resent on a lost response, and its certification suite asserts that the SECOND answer
matches the first — byte for byte, including the timestamps. That is only possible if the
first answer was written down. So ``create_time``, ``perform_time`` and ``cancel_time`` are
three persisted columns rather than one derived from ``created_at``/``updated_at``: a replay
must return the ORIGINAL instant, and a handler that answered ``now()`` on the second call
would fail certification while looking, in every log, exactly like a handler that worked.

**WHY THE RAIL'S ID IS A ``String(24)`` AND IS NEVER PARSED AS A NUMBER.** It is a Mongo
ObjectId: 24 hexadecimal characters, which reads as a number often enough to tempt somebody
and overflows every integer type this schema has. It is stored as text, compared as text and
echoed as text. Our OWN ``id`` is the UUID primary key, and the two are deliberately not
interchangeable — on the wire the field named ``transaction`` is OURS and the field named
``id`` is THEIRS, except in a statement row where the two swap, which is precisely the kind
of trap that a single conflated column turns into silent data corruption.

**WHY ``intent_id`` IS INDEXED, HAS NO FOREIGN KEY, AND IS DELIBERATELY NOT UNIQUE.** Not
unique because the protocol allows an intent to accumulate transactions: a customer's card
declines, the rail cancels that transaction, the hold is released, the customer pays with a
second card and a SECOND transaction is created against the same intent. A unique index here
would refuse the retry — turning a declined card into a dead payment page — which is the
opposite of the design the ``awaiting`` hold exists to enable. Exclusivity is enforced where
it belongs instead: on the intent's own state, by a conditional ``UPDATE`` whose ``rowcount``
is the lock, so only ONE transaction may hold an intent at a time while any number may have
tried. No foreign key, following every other table in this area: the two rows are written in
one commit, so a constraint would add a second and weaker opinion about an ordering the
commit already guarantees, while making the retention sweeps care about delete order.

**WHY ``payme_time`` IS A COLUMN AT ALL, GIVEN WE HAVE ``created_at``.** The twelve-hour
transaction timeout is measured, by the rail's own specification, from the moment the
transaction was created IN THE RAIL — not from when our request handler got round to writing
a row. The two differ by network time, by retries, and by however long our process was
restarting. Running the timeout off our clock would cancel transactions the rail still
considers live, which is the single worst failure available on this path: a customer whose
money moved against a payment we had already refused. So the rail's own instant is stored,
and it is the one the expiry predicate reads. It is indexed because the statement endpoint
filters on it INCLUSIVELY and sorts ascending by it.

**WHY ``cancel_reason`` IS A BARE INTEGER — a deliberate exception to this package's own
rule, argued rather than assumed.** Every other coded value in this schema is a
``StrEnum`` through ``enum_type``, for reasons ``CreditReason`` states well: a closed
vocabulary a query can group by, and no free text about a person. This column breaks that,
and it should. The reason codes are the RAIL's vocabulary, defined by them, echoed back to
them numerically on the wire, and extendable by them without asking us. A ``VARCHAR`` mirror
would be a translation table with two failure modes and no upside: an unknown incoming code
would either be rejected (losing a cancellation the rail has already applied) or mapped to
``UNKNOWN`` (destroying the only evidence of what actually happened), and on the way out a
mistranslation would emit a value the rail does not recognise. Storing their integer
verbatim cannot be wrong. It is also honest about ownership — a reader who wants to know
what ``4`` means looks it up in the rail's documentation, which is where the answer lives
and where it stays correct. The mapping we DO need in code is a Python ``IntEnum`` at the
wire boundary in ``hbd.payme.protocol``, not a column type.

**WHY THE AMOUNT IS STORED AGAIN, WHEN THE INTENT ALREADY HAS ONE.** This is what THEY said,
not what we quoted. The two must agree — a mismatch is a refusal, never a re-price — and
keeping both is what makes a dispute answerable from our own database instead of from a
screenshot of somebody else's dashboard. The duplication is the point.

**PRIVACY — in NEITHER of ``tests/test_db/test_privacy_constraints.py``'s two sets, and this
table's claim is stronger than the intent's beside it: IT HOLDS NO TELEGRAM ID AT ALL.**
Every column is a UUID, a rail-side machine id, an integer, a closed enum or a clock. It is
reachable to a person only by joining through ``payment_intents``, which is exactly the join
``/forget`` breaks by nulling that table's ``telegram_user_id`` — so erasure over there is
what erases the person from here, with nothing to null on this row.

**RETENTION — this table is on NO bound at all, and the absence is the decision.** It is an
audit fact about MONEY, on ``topup_purchases``' footing: it answers "the rail says it charged
this customer; did we ever grant them anything for it?" long after the recipient's name, the
customer's note and the rendered audio are lawfully gone. The rail can also ask us about any
transaction it has ever created, through a statement call with an arbitrary period, and a
row we deleted on a schedule is a transaction we would have to answer "never existed" about.
Growth is one row per payment actually attempted, which is bounded by the business rather
than by a sweep. The ``payme_rpc_log`` beside it — the chatter, not the money — is the table
that carries the cutoff.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.db.base import Base, TimestampMixin, UtcDateTime, enum_type
from hbd.db.enums import PaymeState

__all__ = ["PaymeTransactionRow", "PAYME_TRANSACTION_ID_LENGTH"]

#: A Mongo ObjectId rendered as hex: exactly 24 characters, always. Sized to the fact rather
#: than padded, because this width is the one thing on the row that is not ours to change —
#: a rail that started issuing 25-character ids would be a protocol change we must notice as
#: a failed INSERT rather than absorb as a silent truncation.
PAYME_TRANSACTION_ID_LENGTH: Final[int] = 24


class PaymeTransactionRow(Base, TimestampMixin):
    """One rail-side transaction, and the three instants a replay has to be able to repeat.

    ``TimestampMixin`` IS used, for ``plan_purchases``' reason and not ``topup_purchases``':
    this row is genuinely UPDATEd — created, then performed or cancelled, each by a
    conditional statement — so ``updated_at`` is a column that can be true. It is also the
    only clock that records when WE moved the row, as distinct from the three below, which
    record when the RAIL says the corresponding event happened. Keeping both is what lets an
    operator see a settlement that our side applied hours after the rail believed it had.
    """

    __tablename__ = "payme_transactions"
    __table_args__ = (
        # Zero is legal for the same reason it is on the intent — a promo priced at nothing
        # is a real charge — but a negative amount from a payment rail is a refund arriving
        # dressed as a charge, and this deployment builds no refunds.
        sa.CheckConstraint("amount_minor >= 0", name="amount_not_negative"),
        # Hand-named, and spelled identically in revision 0023 because
        # ``test_the_migrated_indexes_match_the_model_metadata`` compares index NAMES. It
        # serves the sweep for transactions stuck in ``created`` past the timeout — the one
        # read that filters on both columns — while the single-column index on
        # ``payme_time`` below stays for the statement endpoint, whose period filter has no
        # state term to offer as a leading column.
        sa.Index("ix_payme_transactions_state_payme_time", "state", "payme_time"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: THEIR id for this transaction: 24 hex characters, stored and compared as text, never
    #: parsed as a number. Unique, and that index is the entire retry story — see the module
    #: docstring. Indexed because every inbound call arrives carrying this value and nothing
    #: else we could look the row up by.
    payme_transaction_id: Mapped[str] = mapped_column(
        sa.String(PAYME_TRANSACTION_ID_LENGTH), nullable=False, unique=True, index=True
    )
    #: Which of our intents this charge is against. Indexed, no foreign key, and deliberately
    #: NOT unique — see the module docstring on why a declined card must be allowed to leave
    #: a cancelled transaction behind and try again.
    intent_id: Mapped[UUID] = mapped_column(sa.Uuid, nullable=False, index=True)
    #: The instant the RAIL created the transaction, from its own request. The clock the
    #: twelve-hour timeout runs off, and the one the statement endpoint filters and sorts on
    #: — never ``created_at``, which is ours. Indexed for that endpoint.
    payme_time: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    #: What the rail said the charge was for, in minor units, stored verbatim. Compared
    #: against the intent's amount; a mismatch is a refusal. See the module docstring.
    amount_minor: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: Where the charge got to, in OUR words rather than their integers — see
    #: :class:`hbd.db.enums.PaymeState`. Moved only by conditional ``UPDATE``s that name the
    #: state they expect, so an illegal transition writes nothing rather than being caught
    #: by a check somebody has to remember.
    state: Mapped[PaymeState] = mapped_column(enum_type(PaymeState), nullable=False)
    #: THEIR reason code, verbatim, as an integer. NULL until the transaction is cancelled,
    #: and it is the null-never-zero rule that makes it NULL rather than 0: zero is not a
    #: reason code, and a default of it would say "cancelled for reason zero" about every
    #: transaction that was never cancelled at all. The deliberate departure from this
    #: package's closed-enum rule is argued at length in the module docstring.
    cancel_reason: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: When the transaction was created, as we answered it. Persisted, not derived, because a
    #: replayed create must return THIS value and not a fresh one.
    create_time: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    #: When the charge was performed, as we answered it. NULL until it was — see above.
    perform_time: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: When the transaction was cancelled, as we answered it. NULL until it was — see above.
    cancel_time: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
