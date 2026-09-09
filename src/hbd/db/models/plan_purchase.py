"""``plan_purchases`` — the receipt for a subscription, and the meter that mints it.

One row per plan the customer has bought. It is a receipt (what was paid, to which rail,
under which idempotency key) and a counter (``songs_used`` out of ``songs_included``, until
``plan_ends_at``) in the same row, because those two facts are written by the same charge
and separating them would let a row exist that says a plan was bought without saying how
much of it is left.

**Why the songs live here and not on the balance.** The obvious shape — grant twelve credits
when the plan is bought — cannot express "and they are gone in thirty days".
``credit_accounts.balance`` is a single fungible scalar with no lot structure, and the
invariant ``balance == SUM(credit_ledger.delta)`` is asserted by ``verify_balances`` after
every operation, so an expiry sweep would have to write a compensating DEBIT — and with no
lots it could only GUESS whether it was burning unused plan money or a top-up the customer
had paid 7 000 soʻm for. So nothing is granted up front: ``hbd.db.credits._mint_plan_song``
takes ONE song out of this row inside the debit's own transaction, exactly the way
``_mint_due_allowance`` takes the rolling allowance, and use-it-or-lose-it becomes a
read-time predicate on :attr:`plan_ends_at` that cannot be got wrong.

Two column shapes are decisions rather than taste, and both are stated here because a
reviewer will otherwise correct them back:

* **The clock is ``plan_ends_at`` and NOT ``plan_expires_at``.** The ``*_expires_at`` suffix
  is reserved for RETENTION clocks — ``tests/test_db/test_audit_retention.py`` derives "every
  clock in the schema is read by a sweep" from precisely that suffix — and a plan's end date
  is a BUSINESS clock that no sweep reads and no purge acts on. Naming it ``expires_at``
  would make that test demand a retention branch for a date whose whole point is that nothing
  ever collects it.
* **``telegram_user_id`` is nullable so that ``/forget`` has somewhere to go.** Every writer
  supplies it; a ``NULL`` means one thing only — ``hbd.db.credit_erasure.forget_account`` ran
  and anonymised this row. It follows ``credit_ledger`` exactly: a receipt is an audit fact
  that answers "was this customer charged for songs they never got?" months later, so
  deleting it would make ``/forget`` mean "refund me" and would destroy the answer for
  everyone. The identity comes off; the movement, the amount and the clock stay.

There is no foreign key to ``users`` for the same reason ``credit_accounts`` has none: a
customer can buy before any ``users`` row exists, and the receipt must outlive the account.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.db.base import Base, TimestampMixin, UtcDateTime, enum_type
from hbd.db.enums import PlanKind

__all__ = [
    "PlanPurchaseRow",
    "PLAN_IDEMPOTENCY_KEY_LENGTH",
    "PLAN_PROVIDER_LENGTH",
    "PLAN_REFERENCE_LENGTH",
]

#: Sized to the widest key a purchase can carry, ``plan:starter:{telegram_user_id}:{uuid4}:{n}``,
#: with room to spare. Matches ``credit_ledger.idempotency_key`` on purpose: the single-song
#: purchase writes ITS key into that column, and one purchase flow whose two keys had
#: different ceilings would truncate on one path and not the other.
PLAN_IDEMPOTENCY_KEY_LENGTH: Final[int] = 128
#: ``"stub"`` today; a rail's own name the day one lands. Mirrors ``Purchase.provider``'s
#: ``max_length`` so a receipt that validated in ``hbd.checkout`` cannot then fail its INSERT.
PLAN_PROVIDER_LENGTH: Final[int] = 32
#: The rail's identifier for the charge. Mirrors ``Purchase.reference``'s ``max_length`` for
#: the same reason: the two widths are one decision, made in ``hbd.checkout`` and stored here.
PLAN_REFERENCE_LENGTH: Final[int] = 64


class PlanPurchaseRow(Base, TimestampMixin):
    """One plan somebody bought, and how much of it they have spent.

    ``TimestampMixin`` rather than a hand-rolled ``created_at``, unlike ``CreditLedgerRow``:
    this row is genuinely UPDATEd — :func:`hbd.db.plan_sql.claim_plan_song` bumps
    ``songs_used`` on every mint — so ``updated_at`` is a column that can be true, and it is
    the cheapest evidence an operator has of when a plan was last drawn on.
    """

    __tablename__ = "plan_purchases"
    __table_args__ = (
        # The counter is the whole entitlement, and a writer that lost the optimistic guard
        # in `claim_plan_song` would hand out a thirteenth song with no other symptom. The
        # database refuses instead, so the failure is an IntegrityError inside the customer's
        # own transaction rather than a free render nobody can find afterwards.
        sa.CheckConstraint(
            "songs_used >= 0 AND songs_used <= songs_included", name="songs_used_within_plan"
        ),
        # A zero-song plan is a paid-for nothing: `is_live` would be False from the instant it
        # was written, so the customer would be charged and immediately paywalled again.
        sa.CheckConstraint("songs_included > 0", name="songs_included_positive"),
        # Both plan reads are "this customer's rows, newest end date first"
        # (`plan_sql.current_plan` / `live_plan`), which the leading column alone would answer
        # only by scanning and sorting every plan the customer has ever bought.
        sa.Index("ix_plan_purchases_user_ends", "telegram_user_id", "plan_ends_at"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: Whose plan it is. **NULLABLE ONLY SO THAT ERASURE HAS SOMEWHERE TO GO** — see the
    #: module docstring. Indexed because every read of this table filters on it.
    telegram_user_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, index=True)
    plan: Mapped[PlanKind] = mapped_column(enum_type(PlanKind), nullable=False)
    #: How many songs this plan may ever mint. Stored on the ROW rather than read from
    #: ``Settings.starter_plan_songs`` at mint time, so a price or package change tomorrow
    #: cannot retroactively shrink a plan somebody already paid for.
    songs_included: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: How many it has minted. Moved only by ``UPDATE … WHERE songs_used = :seen``, so two
    #: concurrent charges cannot take the same song; a REFUND deliberately does NOT move it
    #: back (``hbd.db.credits.charge`` argues why).
    songs_used: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    #: What was paid, in minor units (UZS tiyin) — the same units the rail quotes, so nothing
    #: on this path ever multiplies a price and rounds it wrong.
    amount_minor: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: ISO-4217, three letters.
    currency: Mapped[str] = mapped_column(sa.String(3), nullable=False)
    #: Which rail answered the charge.
    provider: Mapped[str] = mapped_column(sa.String(PLAN_PROVIDER_LENGTH), nullable=False)
    #: The rail's own identifier for it — half of what an operator needs to find the charge in
    #: somebody else's dashboard, the other half being ``provider``.
    reference: Mapped[str] = mapped_column(sa.String(PLAN_REFERENCE_LENGTH), nullable=False)
    #: The one thing that makes a double tap, a stale message and a redelivered Telegram
    #: update collapse into ONE plan. Unique globally, so the second insert is an ignored
    #: no-op rather than a second end date written over the one the customer paid for.
    idempotency_key: Mapped[str] = mapped_column(
        sa.String(PLAN_IDEMPOTENCY_KEY_LENGTH), nullable=False, unique=True, index=True
    )
    #: When the plan stops minting. A business clock, not a retention clock — see the module
    #: docstring on why the name matters. Indexed because both plan reads bound on it.
    plan_ends_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
