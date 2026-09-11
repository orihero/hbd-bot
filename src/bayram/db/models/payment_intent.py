"""``payment_intents`` — one payment started here and finished somewhere else.

Every sale this schema has recorded until now was settled INSIDE the request that started
it: ``StubCheckoutProvider`` stamps ``is_paid=True`` and the same coroutine writes the
receipt and the credit grant microseconds later. A redirect rail breaks that in half. The
customer is handed a URL, leaves for a bank's own page, and the answer arrives minutes
later on an inbound HTTPS request to a DIFFERENT PROCESS which has never heard of the
Telegram update that started it. This table is the only thing the two halves share.

**WHY THIS IS NOT A COLUMN ON ``topup_purchases``.** That table is a RECEIPT: append-only
by explicit design (its own class docstring pre-empts the reviewer who would "restore
symmetry" by adding ``TimestampMixin``), written once, at the moment a completed sale is
recorded. An intent is the opposite of all three. It MUTATES — pending, held, paid — it is
written before any money exists, and **most intents never become sales at all**: people
open a payment page and close it. Writing a pre-emptive receipt for each one would make
every windowed revenue rollup in the panel count money nobody paid, and the only repair
would be a ``WHERE paid_at IS NOT NULL`` that every future reader has to remember. Worse,
the two tables would then disagree about what a row MEANS — ``topup_purchases`` says "this
sale happened", and half its rows would say "this sale was offered" — which is exactly the
"one table meaning two things" objection revision 0020 rejected money-on-``credit_ledger``
for.

**WHY IT IS NOT A ``plan_purchases`` ROW EITHER.** Revision 0020 already argued this and
the objection is unchanged, only sharper: ``plan_sql.current_plan`` and ``live_plan`` would
SEE the row. An unpaid intent for a starter plan would block the sale of a real plan for the
life of an invented end date, while ``claim_plan_song`` minted songs out of a purchase
nobody has paid for. An unpaid intent that mints entitlement is not a schema-reuse
inconvenience; it is free songs.

**WHY ``public_ref`` EXISTS AT ALL, GIVEN ``idempotency_key`` IS ALREADY UNIQUE.** The
obvious design hands the rail the idempotency key as its account number and saves a column.
That key is ``topup:{telegram_user_id}:{scope}:{seq}`` — it CONTAINS the customer's Telegram
id — and the account number is rendered in the customer's browser address bar, logged by the
rail, printed on the rail's own receipt and visible to anyone the customer forwards the link
to. ``public_ref`` is 24 lowercase hex characters from ``secrets.token_hex(12)``: it is
opaque by construction, it identifies nothing on its own, and it contains neither a ``;``
(which the checkout link's own parser treats as a field separator and would silently
truncate the value at) nor an ``=`` (which it treats as the key/value split). The two
identifiers are therefore split by AUDIENCE — one is ours and never leaves, one is theirs
and says nothing — and the column that looks redundant is the one keeping a Telegram id out
of a third party's logs.

**WHY ``merchant_id`` AND ``is_sandbox`` ARE STORED RATHER THAN READ FROM SETTINGS.** A link
is built now and settled minutes or hours later, and settings can change in between — a
deployment repointed at a sandbox cashbox, or a second cashbox opened for a second product.
Re-deriving the merchant account at settlement time would answer with the value that is true
NOW rather than the one that was true when the link was BUILT, which is how a customer gets
charged by an account nobody is reconciling. Stored on the row, the mismatch is a refusal.

**WHY ``language`` IS STAMPED HERE.** The process that tells the customer their money landed
is not the process that took the money and is not the process that showed them the price. It
has no Telegram update to read a locale off. Without this column the notification would be
written in whatever the account's stored language happens to be at delivery time, which is
not necessarily the one the customer was buying in.

**WHY ``valid_until`` IS NOT NAMED ``*_expires_at``, AND THIS IS NOT A STYLE CHOICE.**
``tests/test_db/test_audit_retention.py::_clocks_in_the_schema`` collects EVERY column in
``Base.metadata`` whose name ends in ``expires_at`` and demands that
``bayram.db.purge.rows_past_expiry_statements`` reads it. That suffix is this codebase's word
for a RETENTION clock: a published legal commitment, stamped per row by its writer from
``RetentionPolicy``, which a purge sweep must honour. This is a BUSINESS clock — how long a
payment page stays payable — and naming it with that suffix would enlist it in the retention
inventory and claim a schedule this column does not have. ``plan_purchases.plan_ends_at``
and ``bayram.checkout.PlanState.ends_at`` are named for the identical reason.

**THE TWO NULLABLE CLOCKS ARE TWO EVENTS, NOT ONE.** ``settled_at`` is when the money
landed; ``notified_at`` is when the customer was told. They are minutes apart when a
Telegram delivery fails and can be days apart when it keeps failing, and a single column
could not express "paid, but nobody has said so yet" — which is precisely the population an
operator has to be able to list, because it is the one where somebody has paid and thinks
they got nothing.

**THERE IS NO FOREIGN KEY ANYWHERE ON THIS TABLE**, following ``credit_ledger`` (0006),
``plan_purchases`` (0015) and ``topup_purchases`` (0020). ``telegram_user_id`` points at no
``users`` row because a customer can pay before any ``users`` row exists and the payment
must outlive the account. ``active_transaction_id`` points at no ``payme_transactions`` row
for a sharper reason: the two rows are written in the same transaction by a conditional
``UPDATE`` whose ``rowcount`` is the lock, and a foreign key would add a second, weaker
opinion about an ordering the commit already guarantees — while making the erasure and the
retention sweeps care about delete order for no benefit.

**PRIVACY — in NEITHER of ``tests/test_db/test_privacy_constraints.py``'s two sets, by the
third route ``credit_ledger``, ``plan_purchases`` and ``topup_purchases`` already take, and
the reason is written down there rather than left silent.** Not personal data: every column
is a Telegram id, an integer, a three-letter ISO currency, a closed enum, a machine-built
key, a hex token, a merchant account id, a boolean or a clock — no name, no note, no lyric,
no free text of any kind, so nothing here is text ABOUT a person. Not erased-on-request
either, because that set's semantics are "the absence of a row IS the erasure record" and
this table is erased by ANONYMISATION: ``/forget`` nulls ``telegram_user_id`` and leaves
``public_ref``, the amount, the rail reference and every clock intact. **Deleting the row
would be worse than useless.** The rail can still see its own transaction and can still ask
us about it months later through GetStatement, and answering "that payment never existed"
about money somebody really paid is a worse outcome for that person than holding an
anonymous row — it is the answer that loses them a dispute.

**RETENTION.** Terminal UNPAID intents (``cancelled``, ``expired``) are deleted on a 400-day
cutoff by ``bayram.db.purge`` — bounded growth over a table that gets a row every time anybody
opens a payment page, on ``vendor_usage``'s footing rather than on a legal clock. **A
``paid`` intent is never purged**: it is the join between a rail-side transaction and a
receipt, and the statement endpoint may still be asked about it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.db.base import Base, TimestampMixin, UtcDateTime, enum_type
from bayram.db.enums import IntentProduct, PaymentIntentState

__all__ = [
    "PaymentIntentRow",
    "PUBLIC_REF_LENGTH",
    "INTENT_IDEMPOTENCY_KEY_LENGTH",
    "INTENT_PROVIDER_LENGTH",
    "MERCHANT_ID_LENGTH",
    "INTENT_LANGUAGE_LENGTH",
    "SETTLE_NOTE_LENGTH",
]

#: ``secrets.token_hex(12)`` is 24 characters. The column is 32, and the eight spare
#: characters are deliberate rather than lazy: widening a Postgres ``VARCHAR`` later is a
#: migration, and a rail that one day requires a prefix (``bayram-``) or a checksum suffix must
#: not cost one. Not narrower than 24 for the obvious reason, and not wider than 32 because
#: this value is rendered inside a base64-encoded URL a human occasionally has to read out.
PUBLIC_REF_LENGTH: Final[int] = 32
#: Matches ``TOPUP_IDEMPOTENCY_KEY_LENGTH``, ``PLAN_IDEMPOTENCY_KEY_LENGTH`` and
#: ``credit_ledger.IDEMPOTENCY_KEY_LENGTH`` exactly, and the match is load-bearing rather
#: than tidy: the settlement writes THIS row's key into those tables, so a narrower ceiling
#: here would truncate a key that the receipt then stores in full, and the two would stop
#: deduplicating against each other on the one string that makes exactly-once fulfilment work.
INTENT_IDEMPOTENCY_KEY_LENGTH: Final[int] = 128
#: Mirrors ``Purchase.provider``'s ``max_length`` and ``TOPUP_PROVIDER_LENGTH``, so an intent
#: whose provider validated in ``bayram.checkout`` cannot fail its INSERT here or its copy into
#: the receipt.
INTENT_PROVIDER_LENGTH: Final[int] = 32
#: A Payme cashbox id is a 24-character Mongo ObjectId today. Sized at 64 because this column
#: is the merchant account of WHATEVER redirect rail issued the link — a second rail with a
#: longer account id must not need a migration to be reconciled against.
MERCHANT_ID_LENGTH: Final[int] = 64
#: ``Language`` values are short (``uz_latn`` is the longest at 7). Sized at 16 rather than
#: stored as ``enum_type(Language)`` on purpose: this is the language the CUSTOMER was
#: buying in, recorded for a message written later, and a value that has since been retired
#: from the enum must still round-trip out of an old row rather than raise on read.
INTENT_LANGUAGE_LENGTH: Final[int] = 16
#: ``'payme'`` for a settlement the rail performed, ``'operator:<ref>'`` for one an operator
#: forced through the CLI after a lost callback. Bounded, not free text — see the column.
SETTLE_NOTE_LENGTH: Final[int] = 64


class PaymentIntentRow(Base, TimestampMixin):
    """One started payment: what was offered, to whom, for how much, and how it ended.

    ``TimestampMixin`` IS used here, and a reviewer arriving from ``topup_purchases`` — which
    refuses the mixin, in a docstring that pre-empts exactly this comparison — should read
    the difference rather than "restore symmetry" in either direction. That table is a
    receipt of a completed sale and is never amended, so an ``updated_at`` there could never
    be true. **This row is a state machine.** It moves pending -> awaiting -> paid, or
    awaiting -> pending on a declined card, or pending -> expired, and every one of those
    moves is a conditional ``UPDATE``. ``updated_at`` is therefore a column that is not only
    true but is the cheapest evidence an operator has of when a stuck payment last moved —
    the first thing anyone looks at when a customer says the money left their card and
    nothing arrived.
    """

    __tablename__ = "payment_intents"
    __table_args__ = (
        # Zero is legal — a promo priced at nothing is a real offer, and
        # ``Settings.single_song_price_minor`` ships ``ge=0`` — but a negative amount is a
        # refund wearing an offer's shape, and this rail builds no refunds.
        sa.CheckConstraint("amount_minor >= 0", name="amount_not_negative"),
        # A plan is a song count that runs out on a date. An intent for one that reached
        # settlement without both numbers would write a ``plan_purchases`` row with a NULL
        # ``songs_included`` (NOT NULL there, so an IntegrityError inside the money
        # transaction) or, worse, be "repaired" by a future reader looking the package up
        # from settings at settle time — which is the retroactive shrink revision 0015
        # stores ``songs_included`` on the row to prevent. The pair is required here, at the
        # only moment the customer's actual purchase is known.
        #
        # Spelled against the literal ``'starter'`` rather than against IntentProduct, and
        # the migration spells it the same way: a CHECK is DDL, it outlives the Python enum,
        # and a member renamed in code must never silently change what the database enforces.
        sa.CheckConstraint(
            "product <> 'starter' OR (plan_songs IS NOT NULL AND plan_days IS NOT NULL)",
            name="plan_fields_present",
        ),
        # ``awaiting`` means "a live rail-side transaction holds this intent", and the whole
        # value of that state is that it names WHICH one — that is what makes the release and
        # the claim conditional on the holder rather than on the state alone, and therefore
        # what stops a second transaction settling an intent the first one is holding. An
        # ``awaiting`` row with a NULL holder would be a hold nobody can release: every
        # conditional UPDATE that names a transaction id would miss it forever, and the
        # expiry predicate (which reads ``pending`` only) cannot see it either. It would be
        # stuck, silently, for the life of the row. The database refuses it instead.
        sa.CheckConstraint(
            "state <> 'awaiting' OR active_transaction_id IS NOT NULL",
            name="holder_present",
        ),
        # Hand-named, and spelled identically in revision 0023 because
        # ``test_the_migrated_indexes_match_the_model_metadata`` compares index NAMES. It
        # serves the expiry sweep — ``WHERE state = 'pending' AND valid_until <= :now`` —
        # which runs on a schedule against the fastest-growing table on the payment path.
        # The leading column alone would not do: ``state`` has five values and ``pending``
        # is the commonest of them, so a scan of every intent ever opened is precisely what
        # the second term exists to avoid.
        sa.Index("ix_payment_intents_state_valid_until", "state", "valid_until"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: The ONLY identifier that ever crosses to a third party: 24 lowercase hex characters
    #: from ``secrets.token_hex(12)``, opaque by construction. Unique because the rail's
    #: account number must resolve to exactly one intent — two rows sharing it would make
    #: "which payment is this?" unanswerable at the moment money is moving. See the module
    #: docstring on why this is not ``idempotency_key``.
    public_ref: Mapped[str] = mapped_column(
        sa.String(PUBLIC_REF_LENGTH), nullable=False, unique=True, index=True
    )
    #: The string the BOT minted, and the one identifier that crosses the process boundary
    #: intact. The settlement writes the receipt and the credit grant under it, landing on
    #: exactly the unique indexes a double tap in the bot would have landed on — which is
    #: what makes an operator's forced settlement and a late genuine one collapse into ONE
    #: grant instead of two. Unique here for the ordinary reason as well: a replayed open
    #: must return the SAME intent and therefore the SAME URL, or one purchase puts two live
    #: payment pages in one chat and the customer cannot tell which took their money.
    idempotency_key: Mapped[str] = mapped_column(
        sa.String(INTENT_IDEMPOTENCY_KEY_LENGTH), nullable=False, unique=True, index=True
    )
    #: Who is buying. **NULLABLE ONLY SO THAT ERASURE HAS SOMEWHERE TO GO** — every writer
    #: supplies it, and a ``NULL`` means one thing only: ``/forget`` ran. Indexed for that
    #: same anonymising ``UPDATE``, which runs inside the transaction the customer is
    #: waiting on. No foreign key; see the module docstring.
    telegram_user_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, index=True)
    #: Which product. Decides which receipt table the settlement writes, so it is a closed
    #: enum rather than a string and a second product is a member with no DDL.
    product: Mapped[IntentProduct] = mapped_column(enum_type(IntentProduct), nullable=False)
    #: What the customer was quoted, in minor units (UZS tiyin) — already the number the rail
    #: is sent, so nothing on this path multiplies by 100 and nothing re-quotes from
    #: ``Settings`` at settlement. The rail's stated amount is compared against THIS value
    #: and a mismatch is a refusal, never a re-price.
    amount_minor: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: ISO-4217, three letters. Travels with the amount always.
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)
    #: The plan snapshot, for a plan product only, frozen at the moment of the offer so a
    #: package change between the tap and the payment cannot shrink what somebody paid for —
    #: ``plan_purchases.songs_included``'s argument, one step earlier in the flow. NULL for a
    #: one-off product, which has neither a duration nor a song count; the pair is required
    #: for a plan by ``ck_payment_intents_plan_fields_present`` above.
    plan_songs: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    plan_days: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    #: Which rail was asked. Carried at the finest grain, exactly as on both receipt tables,
    #: so no aggregate may collapse a stub row and a real one into one settled figure.
    provider: Mapped[str] = mapped_column(sa.String(INTENT_PROVIDER_LENGTH), nullable=False)
    #: The merchant account this link was issued for. The single column that turns a
    #: sandbox/production or second-cashbox split-brain into a refusal instead of a customer
    #: charged by an account nobody is reconciling. No default: a writer that does not know
    #: which cashbox it is selling through must not be able to guess.
    merchant_id: Mapped[str] = mapped_column(sa.String(MERCHANT_ID_LENGTH), nullable=False)
    #: Whether the link points at the rail's TEST environment. Stored beside ``merchant_id``
    #: rather than derived at read time for the same reason it is: the answer must be the one
    #: that was true when the link was built. Also the column that keeps a certification run
    #: countable — sandbox money is not revenue and must never be summed with the real kind.
    is_sandbox: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    #: The language the customer was buying in, stamped so a notification written minutes
    #: later by a different process is written in it. See the module docstring.
    language: Mapped[str] = mapped_column(sa.String(INTENT_LANGUAGE_LENGTH), nullable=False)
    #: Where this payment has got to. Deliberately NOT defaulted to ``pending``: every state
    #: change on this row is an explicit conditional ``UPDATE`` naming both the state it
    #: expects and the state it writes, and a Python-side default would be the one place a
    #: state was set by omission.
    state: Mapped[PaymentIntentState] = mapped_column(enum_type(PaymentIntentState), nullable=False)
    #: WHICH rail-side transaction holds this intent, while one does. NULL in every other
    #: state, and required in ``awaiting`` by ``ck_payment_intents_holder_present``. It is
    #: what makes the release and the claim conditional on the HOLDER and not merely on the
    #: state, so a second transaction racing for the same intent settles nothing. No foreign
    #: key; see the module docstring.
    active_transaction_id: Mapped[UUID | None] = mapped_column(sa.Uuid, nullable=True)
    #: When an unpaid intent stops being payable. A BUSINESS clock — read the module
    #: docstring before renaming it to anything ending in ``expires_at``.
    valid_until: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    #: When the money landed. NULL until it did; set in the same transaction that wrote the
    #: receipt and the credit grant, so a non-NULL value here with no receipt behind it is a
    #: bug that cannot occur rather than one to be reconciled.
    #:
    #: **Indexed by revision 0025**, and not by 0023, because 0023 had no reader for it. It is
    #: now the filter column of ``payme_sql.settlement_counts`` (the three-way invariant the
    #: five-minute sweep logs) and of the operator-settlement count beside it — both of which
    #: the admin panel recomputes on every load of a screen that polls. Unindexed, each of
    #: those is a full scan of the fastest-growing table on the payment path; the column is
    #: also highly selective, since it is NULL for every intent that was never paid, which on
    #: this product is most of them. The name is spelled identically in the migration because
    #: ``test_the_migrated_indexes_match_the_model_metadata`` compares index NAMES.
    settled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True, index=True)
    #: When the customer was TOLD. NULL while they have not been — see the module docstring
    #: on why this is a second clock and not a flag on the first.
    notified_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: HOW it settled: ``'payme'`` when the rail performed it, ``'operator:<ref>'`` when a
    #: human forced it through the CLI after a callback was lost. Bounded and machine-built,
    #: never a free-text note — a column an operator can type into is a column a customer's
    #: name ends up in, which is the whole argument ``CreditReason`` is a closed enum for.
    #: It is kept forever rather than derived from a log, because "was this money moved by
    #: the rail or by one of us?" is the first question of any reconciliation, and a manually
    #: settled row must stay distinguishable from an automatic one for the life of the row.
    settle_note: Mapped[str | None] = mapped_column(sa.String(SETTLE_NOTE_LENGTH), nullable=True)
