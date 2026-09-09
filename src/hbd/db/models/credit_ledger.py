"""``credit_ledger`` — append-only, so a balance is explainable rather than merely stored.

Every movement of a credit writes exactly one row here and rows are never updated or
deleted. That is what makes "why does this account have two credits?" answerable months
later, and it is what lets a real payment rail or the admin panel start writing to the same
table with no schema change: they add ``kind``/``reason`` members, not columns.

Two design points carry most of the weight:

* **Idempotency is keyed on the movement, not on the order.** ``idempotency_key`` is
  ``debit:{order}:{gen}`` / ``refund:{order}:{gen}`` / ``consume:{order}:{gen}`` /
  ``grant:period:{tg}:{index}`` / ``grant:admin:{uuid4}``, uniquely indexed, so two racing
  writers of the same movement produce one row and one loser. The ``generation`` component
  is what makes a *refunded* order chargeable again: the ALLOW decision reads the order's
  NET position (``SUM(delta) WHERE order_id``), so net < 0 means "already paid for, replay,
  charge nothing" while a refund returns the order to net 0 and its next authorisation
  debits at ``generation + 1``. Keying replay on the mere presence of a debit row instead
  would render every refunded-then-reauthorised order for free.
* **There is no foreign key to ``orders``.** The gate can run before the ``orders`` row
  exists, and a ledger entry must outlive the order it refers to — the same reasoning
  ``docs/product/ADMIN_PANEL_PLAN.md`` §5.8 gives for ``payments.order_id``. ``order_id`` is
  indexed because the net-position probe is exactly that predicate.

**Deliberately not personal data, and deliberately not on a retention clock.** Every column
is a closed enum, an integer, a machine-built key or a Telegram id; there is no free text
anywhere, so nothing here is text *about* a person and the table is correctly absent from
``tables_with_personal_data`` in ``tests/test_db/test_privacy_constraints.py``. That
absence is the point rather than an oversight: the retention clocks in
``hbd.db.retention`` delete the recipient's name, the customer's note and the rendered
audio, and an audit trail that deleted itself on the same schedule could not answer a
billing dispute or a fraud question about the period it just erased. ``/forget`` therefore
nulls ``telegram_user_id`` here (WU9) and keeps the anonymous aggregate, rather than
dropping the rows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.db.base import Base, UtcDateTime, enum_type, utc_now
from hbd.db.enums import CreditEntryKind, CreditReason

__all__ = ["CreditLedgerRow", "IDEMPOTENCY_KEY_LENGTH", "ACTOR_LENGTH"]

#: Sized for the longest key shape, ``grant:admin:{telegram_user_id}:{uuid4}`` — 68
#: characters at Telegram's widest id — with room for a future prefix. The account id is in
#: that shape rather than left out because this column is unique **globally**, so a key
#: without it would let one operator ``requestId`` reused across two customers credit the
#: first and silently no-op the second (``admin/routers/credits.py::grant_credits``). Short
#: enough that the unique index stays cheap on the hot debit path.
IDEMPOTENCY_KEY_LENGTH: Final[int] = 128
#: ``bot`` | ``pipeline`` | ``sweep`` | ``admin:{username}``. The username column is 64
#: characters, so a long operator name is truncated by the writer — the actor is diagnostic
#: attribution, not a key, and the audit log (Phase 5) is where identity is authoritative.
ACTOR_LENGTH: Final[int] = 32

#: Spelled against the enum *values*, not the member names, because ``enum_type`` persists
#: values (``"debit"``, not ``"DEBIT"``). Built from the enum so a renamed value cannot
#: leave the constraint checking a string the column can no longer hold.
_DELTA_MATCHES_KIND: Final[str] = (
    f"(kind IN ('{CreditEntryKind.GRANT.value}', '{CreditEntryKind.REFUND.value}')"
    " AND delta > 0)"
    f" OR (kind = '{CreditEntryKind.DEBIT.value}' AND delta < 0)"
    f" OR (kind = '{CreditEntryKind.CONSUME.value}' AND delta = 0)"
)


class CreditLedgerRow(Base):
    """One movement of one account's credits.

    ``TimestampMixin`` is deliberately not used. An append-only row has no ``updated_at``
    that could ever be true, and offering one would invite a writer to update it — the same
    reason ``AdminSessionRow`` and ``GenerationAttemptRow`` declare their own ``created_at``.
    """

    __tablename__ = "credit_ledger"
    __table_args__ = (
        # The sign of `delta` is the whole meaning of a row, and a writer that got it wrong
        # would mint or burn credits silently. The database refuses instead. CONSUME is
        # pinned to exactly 0 because it settles a debit without moving money — a non-zero
        # CONSUME would desynchronise `credit_accounts.balance` from SUM(delta) with no
        # other symptom until the invariant test caught it.
        sa.CheckConstraint(_DELTA_MATCHES_KIND, name="delta_matches_kind"),
        # An operator (and the sweep) reads one account's history newest-first; the leading
        # column alone would still scan a hot account's whole history to sort it.
        sa.Index("ix_credit_ledger_user_created", "telegram_user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: Whose credits moved. Not an FK for the same reason ``credit_accounts`` is not — the
    #: account may predate the ``users`` row.
    #:
    #: **NULLABLE ONLY SO THAT ERASURE HAS SOMEWHERE TO GO.** Every writer supplies it; a
    #: ``NULL`` here means one thing and one thing only — ``/forget`` ran, and this row is
    #: what is left of an account that asked to stop being identifiable
    #: (``hbd.db.credit_erasure.forget_account``). The row survives because the count is
    #: what answers a billing question months later and a deleted receipt answers nothing;
    #: the id goes because the count does not need to be *about* anyone to do that job.
    #:
    #: Two readers had to learn about it, and both are the kind of bug that only shows up
    #: after a customer exercises a right: ``credit_sql._ledger_only_drifts`` would have
    #: reported every erased account as balance drift, and ``credit_sql.stale_debits``
    #: would have handed the hourly sweep a ``StaleDebit`` with no owner. Both now filter
    #: ``IS NOT NULL`` explicitly rather than by accident.
    telegram_user_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, index=True)
    kind: Mapped[CreditEntryKind] = mapped_column(enum_type(CreditEntryKind), nullable=False)
    reason: Mapped[CreditReason] = mapped_column(enum_type(CreditReason), nullable=False)
    #: Signed, and constrained to agree with ``kind``. Zero is legal for CONSUME only.
    delta: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: The order this movement belongs to, where there is one — a period allowance and an
    #: operator grant have none. Indexed: the net-position probe filters on exactly this.
    order_id: Mapped[UUID | None] = mapped_column(sa.Uuid, nullable=True, index=True)
    #: Which charge attempt for this order. Bumped by a refund, so a re-authorisation after
    #: a refund gets a fresh idempotency key and therefore actually debits.
    generation: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    #: The one thing that makes concurrent duplicate writes impossible rather than unlikely.
    idempotency_key: Mapped[str] = mapped_column(
        sa.String(IDEMPOTENCY_KEY_LENGTH), nullable=False, unique=True, index=True
    )
    #: Which subsystem wrote the row. Diagnostic, so nullable: an entry with an unknown
    #: writer is still a true movement and must not be rejected.
    actor: Mapped[str | None] = mapped_column(sa.String(ACTOR_LENGTH), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=utc_now, index=True
    )
