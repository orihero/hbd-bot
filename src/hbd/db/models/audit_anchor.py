"""``audit_chain_anchors`` — the chain head, written down somewhere it can be compared.

Tiny: a handful of rows a day. It exists for two failures the chain alone cannot survive.

* **A swept prefix looks exactly like a deleted prefix.** The 730-day sweep removes the
  oldest rows, so the surviving first row carries a ``prev_hmac`` nothing can be checked
  against. Without a record of *where* the chain was cut, ``/audit/verify`` would have to
  either call every truncation a tamper or call every tamper a truncation. The
  ``TRUNCATION`` anchor records the cut: the seq the chain still verifies from, how many
  rows went, and the value at the boundary.
* **A chain stored only in the table it protects proves nothing to an adversary who owns
  the table.** Every anchor written here is **also emitted as a log line** (``audit chain
  anchor``, with ``seq`` and the value), because the log ships off this host. That line is
  the minimum viable out-of-band copy and §5.5 makes it required, not optional — an
  attacker who can rewrite the table and the key is unknown to them still cannot make the
  shipped head agree with a rewritten chain.

Anchors hold no personal data: a sequence number, an instant, and a MAC. They are not swept.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.db.base import SHA256_LENGTH, Base, UtcDateTime, enum_type

__all__ = ["AuditChainAnchorRow", "AuditAnchorKind"]


class AuditAnchorKind(StrEnum):
    """Why the anchor was written, which decides how ``/audit/verify`` reads it.

    ``HEAD`` is the periodic pin — the value the chain had at that moment, kept so a later
    walk can be compared against something that was recorded before any tampering. It says
    nothing about deletions.

    ``TRUNCATION`` is written by the retention sweep and carries ``truncated_below_seq``:
    every row below that number was deleted **on purpose**, so a walk starting there is
    expected to begin with a ``prev_hmac`` it cannot verify. Conflating the two kinds is
    what would make the alarm useless.
    """

    HEAD = "head"
    TRUNCATION = "truncation"


class AuditChainAnchorRow(Base):
    """One pin of the audit chain.

    ``id`` is ``sa.BigInteger().with_variant(sa.Integer, "sqlite")`` for the same reason
    ``admin_audit_log.seq`` is: ``BIGINT`` is not a ROWID alias on SQLite, so an
    autoincrement declared as one silently fails every insert in the unit suite.
    """

    __tablename__ = "audit_chain_anchors"

    id: Mapped[int] = mapped_column(
        sa.BigInteger().with_variant(sa.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    kind: Mapped[AuditAnchorKind] = mapped_column(enum_type(AuditAnchorKind), nullable=False)
    #: The ``admin_audit_log.seq`` this anchor pins — the chain head at ``at``.
    seq: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    #: That row's ``chain_hmac``. The same value is emitted in the anchor's log line.
    chain_hmac: Mapped[str] = mapped_column(sa.String(SHA256_LENGTH), nullable=False)
    #: ``TRUNCATION`` only: rows with ``seq`` below this were deleted by the 730-day sweep,
    #: so a chain that does not verify below it is expected rather than suspicious.
    truncated_below_seq: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    #: ``TRUNCATION`` only: how many rows that sweep removed.
    rows_deleted: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
