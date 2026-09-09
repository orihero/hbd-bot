"""``topup_purchases`` — the receipt for a single song somebody bought.

``hbd.db.purchases._fulfil_single`` writes exactly one ``credit_ledger`` GRANT
(``reason=TOPUP_PURCHASE``, ``delta=+1``) and nothing else. That row carries no amount, no
currency and no provider: **the sale price is lost the instant the charge is reported
paid**, and no column anywhere in the schema could have held it. This table is where the
money goes.

**WHY A NEW TABLE RATHER THAN MONEY COLUMNS ON ``credit_ledger``.** Adding
``amount_minor``/``currency``/``provider``/``reference`` there is genuinely attractive — one
statement, one unique key, perfect idempotency for free — and erasure is not the
discriminator either, since ``credit_ledger`` is anonymised rather than deleted, so money on
it would outlive ``/forget`` just as a receipt does. It is rejected on four grounds:

1. **It makes one table mean two things.** That table's own docstring commits it to "one
   movement of one account's credits". A money column would be non-null on ONE
   ``CreditReason`` out of twelve, so the column's meaning would live in a different column
   and every future reader summing it would have to know which reasons may carry it.
2. **It cannot record a sale that grants no credit** — and the schema has already met one: a
   plan grants nothing at purchase and writes ``plan_purchases``. Revenue would be
   permanently split between a receipts table (one row per sale) and a movements table (one
   row per movement) at different grains, and "total revenue" would be a UNION with
   hand-aligned columns forever.
3. **It puts four nullable columns and a both-or-neither CHECK on the hottest table in the
   entitlement schema** — a row per render debit, per settle, per allowance mint.
4. **Refunds.** A REFUND row carries ``delta > 0``; with money on the ledger a refund either
   appears to carry money or needs another null, whereas a receipt has an obvious place for
   a future ``refunded_at``.

**WHY NOT A ``plan_purchases`` ROW.** ``plan`` is NOT NULL, ``songs_included > 0`` is
CHECKed and ``plan_ends_at`` is NOT NULL — but the decisive objection is behavioural, not
cosmetic: ``plan_sql.current_plan`` and ``live_plan`` would then SEE that row. A top-up
would block the sale of a starter plan for the life of an invented end date, and
``claim_plan_song`` would mint a SECOND song out of a purchase that had already granted a
credit directly. A double-grant plus a refused sale, out of a schema reuse.

**THE COLUMN NAMES DELIBERATELY DUPLICATE ``plan_purchases``** wherever they mean the same
thing (``telegram_user_id``, ``amount_minor``, ``currency``, ``provider``, ``reference``,
``idempotency_key``, ``created_at``). That is not cosmetic: it makes the two receipt tables a
clean ``UNION ALL`` on ONE vocabulary, and a third product joins the same vocabulary rather
than inventing a third spelling of ``amount_minor``. It departs from ``plan_purchases`` in
exactly two places, both argued below: it is APPEND-ONLY, and it carries
``credits_granted`` instead of ``songs_included``/``songs_used``, because a top-up is a
receipt with no meter attached.

**WHY ``amount_minor`` IS NOT NULL, AGAINST THE NULL-NEVER-ZERO RULE — AND WHY THAT IS NOT
AN EXCEPTION TO IT.** That rule governs columns recording a MEASUREMENT (``cost_usd``,
``latency_ms``), where a default of 0 turns "nobody measured this" into "this cost nothing"
and no reader downstream can undo it. A sale amount is not a measurement; it is a TERM OF
THE CONTRACT, known to the writer at the instant it writes and supplied verbatim from
``hbd.checkout.Purchase`` (whose own ``amount_minor`` is ``Field(ge=0)``).
``plan_purchases.amount_minor`` is NOT NULL for exactly this reason and this table follows
it. ``amount_minor = 0`` is consequently a MEASURED price and a legal one —
``Settings.single_song_price_minor`` ships ``ge=0`` and a promo priced at zero is a real
sale — which is why the two ambiguous readings are separated STRUCTURALLY rather than by a
null:

* **"Sold before we recorded amounts"** is a ``credit_ledger`` GRANT with
  ``reason='topup_purchase'`` and NO row here sharing its ``idempotency_key``. The absence
  of a row IS the fact, and it is countable with a correlated ``NOT EXISTS``.
* **"Sold for zero"** is a row here with ``amount_minor = 0``.

**THERE IS NO BACKFILL, AND THERE CAN NEVER BE ONE.** Past top-ups left only a ledger GRANT
with an idempotency key and a clock. They cannot be back-priced at
``Settings.single_song_price_minor``, because that is a value read at QUERY time rather than
the price that was charged, so every historical figure would move the next time the price
does — LR-63's "retrofitting revenue recognition corrupts every prior reported period". This
codebase already refuses that shape twice, in the two places most adjacent to this one:
``plan_purchases.songs_included`` is stored on the row rather than read from
``starter_plan_songs`` "so a price or package change tomorrow cannot retroactively shrink a
plan somebody already paid for", and ``vendor_usage.cost_usd`` stays NULL rather than 0
because a rate applied after the fact is a fabricated number. The two populations therefore
travel together on the wire — "118 top-ups sold · 113 priced · 5 sold before amounts were
recorded" — which is the ``costUsd``/``costedCalls`` pairing applied at population level.

**THE RAIL IS A STUB, AND THE COLUMN IS WHAT KEEPS THAT LEGIBLE.**
``StubCheckoutProvider`` stamps ``is_paid=True`` having contacted nobody, so a row here
means A SALE WAS RECORDED and never that money was banked. ``provider`` is carried at the
finest grain all the way to the wire for exactly that reason, and no aggregate may collapse
providers together: a window mixing a stub row and a real Payme row must not be readable as
one settled figure.

**PRIVACY — in NEITHER set, and the reason is recorded in
``tests/test_db/test_privacy_constraints.py`` rather than left silent.** Not in
``tables_with_personal_data``: every column is a Telegram id, an integer, a three-letter ISO
currency, a closed enum, a machine-built idempotency key, a rail's own reference or a clock
— no name, no note, no lyric, no free text, so nothing here is text ABOUT a person. That is
precisely the argument ``credit_ledger`` and ``credit_accounts`` already make for holding a
``telegram_user_id`` without being classified as personal data. Not in
``tables_erased_on_request`` either: that set means the ABSENCE OF A ROW IS THE ERASURE
RECORD (``user_profiles`` is DELETEd outright), and this table is erased by ANONYMISATION —
the id comes off and the amount, the rail, the reference, the key and the clock stay,
because a deleted receipt would make ``/forget`` mean "refund me" and would destroy the
answer to a billing dispute for everyone. That third route is the one ``credit_ledger`` and
``plan_purchases`` take and neither set names it.

**NO RETENTION CLOCK, AND THE ABSENCE IS THE DECISION.** ``vendor_usage`` gets a 400-day
cutoff because it is telemetry whose growth must be bounded. A RECEIPT is an audit fact that
has to outlive every purge: it answers "was this customer charged 7 000 soʻm for a song they
never got?" months after the recipient's name, the customer's note and the rendered audio
are lawfully gone, and an audit trail that deletes itself on a schedule cannot answer a
dispute about the period it just erased. ``plan_purchases`` and ``credit_ledger`` are on no
clock for the identical reason, and growth is one row per song sold. No column is named
``*_expires_at``: ``tests/test_db/test_audit_retention.py`` derives "every clock in the
schema is read by a sweep" from that suffix alone, and using it here would claim a legal
schedule this table does not have.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.db.base import Base, UtcDateTime, enum_type, utc_now
from hbd.db.enums import TopupKind

__all__ = [
    "TopupPurchaseRow",
    "TOPUP_IDEMPOTENCY_KEY_LENGTH",
    "TOPUP_PROVIDER_LENGTH",
    "TOPUP_REFERENCE_LENGTH",
]

#: Matches ``PLAN_IDEMPOTENCY_KEY_LENGTH`` and ``credit_ledger.IDEMPOTENCY_KEY_LENGTH`` on
#: purpose: the top-up writes the SAME key into both this table and the ledger GRANT it
#: explains, and one purchase flow whose two keys had different ceilings would truncate on
#: one path and not the other — which is exactly the join the unpriced-backlog count needs.
TOPUP_IDEMPOTENCY_KEY_LENGTH: Final[int] = 128
#: ``"stub"`` today; a rail's own name the day one lands. Mirrors ``Purchase.provider``'s
#: ``max_length``, so a receipt that validated in ``hbd.checkout`` cannot fail its INSERT.
TOPUP_PROVIDER_LENGTH: Final[int] = 32
#: The rail's identifier for the charge. Mirrors ``Purchase.reference``'s ``max_length`` for
#: the same reason: the two widths are one decision, made in ``hbd.checkout``, stored here.
TOPUP_REFERENCE_LENGTH: Final[int] = 64


class TopupPurchaseRow(Base):
    """One single-song purchase: what was sold, for how much, on which rail.

    ``TimestampMixin`` is deliberately NOT used, and this is the one place this table
    departs from its sibling ``plan_purchases``. Nothing counts down from this row — the
    credit went straight to the balance the instant the charge was reported paid — so an
    ``updated_at`` could never be true, and offering one would invite a writer to amend a
    receipt whose whole value is that nobody amends it. ``plan_purchases`` DOES use the
    mixin because ``claim_plan_song`` genuinely UPDATEs ``songs_used``. A reviewer
    "restoring symmetry" here would be removing the append-only property.
    """

    __tablename__ = "topup_purchases"
    __table_args__ = (
        # A receipt that granted nothing is not a top-up; it is a charge with no
        # entitlement, and the customer would have paid for silence.
        sa.CheckConstraint("credits_granted > 0", name="credits_granted_positive"),
        # Zero is legal — a promo price is a real sale — but a negative amount is a refund
        # wearing a receipt's shape, and refunds have no row type here yet.
        sa.CheckConstraint("amount_minor >= 0", name="amount_not_negative"),
        # No composite index: every read of this table is a windowed rollup on
        # ``created_at`` or the erasure's predicate on ``telegram_user_id``, and neither
        # supplies the other as a second term.
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: Who bought it. **NULLABLE ONLY SO THAT ERASURE HAS SOMEWHERE TO GO** — every writer
    #: supplies it, and a ``NULL`` means one thing only: ``/forget`` ran. Indexed for that
    #: same erasure ``UPDATE``, which runs inside the transaction the customer is waiting on.
    telegram_user_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, index=True)
    #: Which one-off product. A closed enum, so a second product is a member and no DDL.
    product: Mapped[TopupKind] = mapped_column(enum_type(TopupKind), nullable=False)
    #: How many credits the sale put on the balance. Stored on the ROW rather than inferred
    #: from the product at read time, for ``plan_purchases.songs_included``'s stated reason:
    #: a package change tomorrow must not retroactively rewrite what somebody already bought.
    credits_granted: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: What was paid, in minor units (UZS tiyin) — the same units the rail quotes, so nothing
    #: on this path ever multiplies a price and rounds it wrong.
    amount_minor: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: ISO-4217, three letters. Travels with the amount always: no aggregate in this schema
    #: may produce a scalar total across currencies.
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)
    #: Which rail answered the charge. ``'stub'`` on every row until Payme lands — see the
    #: module docstring on why no aggregate may collapse this column.
    provider: Mapped[str] = mapped_column(sa.String(TOPUP_PROVIDER_LENGTH), nullable=False)
    #: The rail's own identifier for the charge — half of what an operator needs to find it
    #: in somebody else's dashboard, the other half being ``provider``.
    reference: Mapped[str] = mapped_column(sa.String(TOPUP_REFERENCE_LENGTH), nullable=False)
    #: The one thing that makes a double tap, a stale message and a redelivered Telegram
    #: update collapse into ONE sale. Unique globally — and it is the SAME string the
    #: ``credit_ledger`` GRANT is written under, which is a deterministic join key rather
    #: than a constraint: a future rail that writes one and not the other shows up as a
    #: countable discrepancy instead of a rejected INSERT.
    idempotency_key: Mapped[str] = mapped_column(
        sa.String(TOPUP_IDEMPOTENCY_KEY_LENGTH), nullable=False, unique=True, index=True
    )
    #: When the sale was recorded. Indexed because every read of this table is a window.
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now, index=True
    )
