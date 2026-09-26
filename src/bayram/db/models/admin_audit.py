"""``admin_audit_log`` — what every operator did, in an order nobody can rewrite.

Append-only. There is exactly one writer, :func:`bayram.db.admin.audit.append`, and exactly two
sweeps that ever touch a row again: one nulls ``reason_text`` at 90 days, one deletes the row
at 730 days (§12.5). Nothing else updates, nothing else deletes, there is no ORM relationship
pointing here and no cascade that could reach these rows sideways.

Five properties of this table are security decisions rather than schema taste.

* **``seq`` is the ordering key and it is an autoincrementing integer PK**, declared
  ``sa.BigInteger().with_variant(sa.Integer, "sqlite")``. SQLite only treats a column
  declared exactly ``INTEGER PRIMARY KEY`` as a ROWID alias; a bare ``BIGINT`` gets no
  implicit value and every insert fails ``NOT NULL`` — in the unit suite, which is where the
  chain's tests live. The chain is verified in ``seq`` order, so this column is not
  bookkeeping: it *is* the sequence the HMAC protects.
* **The chain is keyed, not a bare digest.** ``chain_hmac`` is
  ``HMAC-SHA256(key, version ‖ prev_hmac ‖ canonical_json(row))`` where the key lives only in
  the admin process's environment (``AdminSettings.admin_audit_hmac_key``) and never in this
  database. An unkeyed ``sha256`` chain is recomputable by anyone who can write the table —
  which is exactly the adversary §12.4 names — so ``/audit/verify`` would report a rewritten
  chain as clean. §5.4 calls these columns ``prev_hash``/``entry_hash``; they are named for
  what they hold instead, because "hash" is the property this design deliberately does not
  have.
* **``actor_username`` is denormalised on purpose.** ``actor_id`` is
  ``ON DELETE RESTRICT``, so an operator row cannot be deleted out from under its history;
  the username is stored beside it anyway so a *rename* does not silently rewrite who did
  what. ``actor_role`` is likewise the role **at the time of the action**, not a join to
  today's.
* **``reason_text`` is excluded from the canonical form.** It is the one column a sweep
  nulls, and a chain that covered it would break itself every 90 days — the truncation
  turning into a "tamper" alarm nobody could distinguish from a real one. ``reason_code``
  and ``reason_ref`` carry the accountability and *are* covered.
* **No column here holds a value of personal data.** ``field_names`` records *that*
  ``briefs.note`` was revealed, never what it said; ``subject_id`` is a UUID or a Telegram
  id, never a name. ``reason_text`` is the exception the retention clock exists for, which is
  why this table appears in ``tables_with_personal_data`` in
  ``tests/test_db/test_privacy_constraints.py``.

``TimestampMixin`` is deliberately not used: an ``updated_at`` on an append-only table is a
column that promises something the design forbids. ``at`` is the instant, and it is the only
one.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from bayram.db.base import SHA256_LENGTH, Base, UtcDateTime, enum_type
from bayram.db.enums import AdminRole, AuditAction, AuditReasonCode

__all__ = [
    "AdminAuditRow",
    "AuditOutcome",
    "AUDIT_RETENTION_DAYS",
    "AUDIT_REASON_RETENTION_DAYS",
    "ACTOR_USERNAME_LENGTH",
    "SUBJECT_TYPE_LENGTH",
    "SUBJECT_ID_LENGTH",
    "REASON_REF_LENGTH",
    "REASON_TEXT_LENGTH",
    "ERROR_CODE_LENGTH",
    "CORRELATION_ID_LENGTH",
    "IP_LENGTH",
]

#: §12.5. Two years, longer than every data clock in the system — which is the point: the
#: accountability record for a purge has to outlive the data it purged.
AUDIT_RETENTION_DAYS: Final[int] = 730
#: The operator's free text has its own, much shorter clock. See the module docstring.
AUDIT_REASON_RETENTION_DAYS: Final[int] = 90

#: Matches ``admin_users.username``'s ``String(64)`` — this is a snapshot of that column.
ACTOR_USERNAME_LENGTH: Final[int] = 64
#: ``order``/``user``/``asset``/``chat``/``config``/``admin``/``session``/``wizard_draft``.
SUBJECT_TYPE_LENGTH: Final[int] = 32
#: A UUID string (36) or a Telegram id. Never a name.
SUBJECT_ID_LENGTH: Final[int] = 64
#: A ticket reference, validated against a closed character set before it is stored.
REASON_REF_LENGTH: Final[int] = 64
#: Capped so an operator cannot turn the longest-clocked table in the system into a notebook.
REASON_TEXT_LENGTH: Final[int] = 500
#: An ``ErrorCode`` or ``AdminErrorCode`` value.
ERROR_CODE_LENGTH: Final[int] = 48
#: ``new_correlation_id()`` renders 32 hex characters; the margin covers a longer future one.
CORRELATION_ID_LENGTH: Final[int] = 128
#: The longest textual IPv6 address, including an IPv4-mapped tail.
IP_LENGTH: Final[int] = 45


class AuditOutcome(StrEnum):
    """How the audited action ended.

    Three values, because the panel and an investigation ask three different questions of
    them: ``OK`` is what happened, ``DENIED`` is the permission matrix refusing somebody —
    the row that matters most and the one a "successes only" log would not have — and
    ``ERROR`` is the action that was allowed and then failed, which is an incident rather
    than an access-control event.

    Declared here rather than in ``bayram.db.enums`` because nothing outside this table has an
    opinion about it; it still reaches the database through ``enum_type``, so
    ``tests/test_db/test_enum_lengths.py``'s schema pass covers its width.
    """

    OK = "ok"
    DENIED = "denied"
    ERROR = "error"


class AdminAuditRow(Base):
    """One audited action. Written once, never updated.

    Constructing this class does **not** make an audit entry: the chain columns are computed
    under a lock by :func:`bayram.db.admin.audit.append`, which is the only supported write path
    and the only place that has the HMAC key.
    """

    __tablename__ = "admin_audit_log"
    __table_args__ = (
        # The panel's default view is "this action, most recent first"; the two columns
        # together are what keeps that an index scan rather than a filter over a sort.
        sa.Index("ix_admin_audit_log_action_at", "action", "at"),
    )

    #: The chain's order. See the module docstring for why the variant is load-bearing.
    seq: Mapped[int] = mapped_column(
        sa.BigInteger().with_variant(sa.Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    #: A stable external reference, so a URL or a ticket can name a row without leaking how
    #: many audited actions the system has performed.
    id: Mapped[UUID] = mapped_column(sa.Uuid, nullable=False, unique=True, default=uuid4)
    at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)

    #: ``NULL`` only for the system itself — the bootstrap CLI and the retention cron, which
    #: have no operator row. ``RESTRICT`` so history cannot be orphaned by a deletion.
    actor_id: Mapped[UUID | None] = mapped_column(
        sa.Uuid,
        sa.ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    #: Snapshot, not a join: a rename must not rewrite history.
    actor_username: Mapped[str] = mapped_column(sa.String(ACTOR_USERNAME_LENGTH), nullable=False)
    #: The role **at the time of the action**.
    actor_role: Mapped[AdminRole] = mapped_column(enum_type(AdminRole), nullable=False)

    action: Mapped[AuditAction] = mapped_column(enum_type(AuditAction), nullable=False)
    subject_type: Mapped[str] = mapped_column(sa.String(SUBJECT_TYPE_LENGTH), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(
        sa.String(SUBJECT_ID_LENGTH), nullable=True, index=True
    )

    #: The field **names** revealed or changed. Never their values (§12.4).
    field_names: Mapped[list[str] | None] = mapped_column(sa.JSON, nullable=True)
    #: How many records were exposed — 1 for a name reveal, N for a conversation. This is
    #: what the reveal budget and the dashboard measure.
    record_count: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    reason_code: Mapped[AuditReasonCode] = mapped_column(enum_type(AuditReasonCode), nullable=False)
    reason_ref: Mapped[str | None] = mapped_column(sa.String(REASON_REF_LENGTH), nullable=True)
    #: Optional, capped, **excluded from the chain HMAC**, and on its own 90-day clock.
    reason_text: Mapped[str | None] = mapped_column(sa.String(REASON_TEXT_LENGTH), nullable=True)
    #: ``NULL`` exactly when ``reason_text`` is. Indexed: the reason sweep is one predicate.
    reason_expires_at: Mapped[datetime | None] = mapped_column(
        UtcDateTime, nullable=True, index=True
    )
    #: Stamped when the reason sweep ran, so "empty because swept" and "empty because none
    #: was given" stay distinguishable.
    reason_purged_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    outcome: Mapped[AuditOutcome] = mapped_column(enum_type(AuditOutcome), nullable=False)
    error_code: Mapped[str | None] = mapped_column(sa.String(ERROR_CODE_LENGTH), nullable=True)
    #: Joins this row to the bot's and the worker's log lines for the same request.
    correlation_id: Mapped[str | None] = mapped_column(
        sa.String(CORRELATION_ID_LENGTH), nullable=True, index=True
    )
    ip: Mapped[str | None] = mapped_column(sa.String(IP_LENGTH), nullable=True)
    #: ``sha256`` of the User-Agent, not the string: it is a correlation key, not evidence.
    user_agent_hash: Mapped[str | None] = mapped_column(sa.String(SHA256_LENGTH), nullable=True)
    #: Which settings version a config action produced or rolled back to.
    config_version: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    #: 730 days from ``at``. Indexed: the row sweep is one predicate over this column.
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)

    #: The previous row's ``chain_hmac``. ``NULL`` on the first row ever written; non-null and
    #: unverifiable on the first row after a truncation, which is what the anchor pins.
    prev_hmac: Mapped[str | None] = mapped_column(sa.String(SHA256_LENGTH), nullable=True)
    #: ``HMAC-SHA256(key, version ‖ prev_hmac ‖ canonical_json(row))``, hex.
    chain_hmac: Mapped[str] = mapped_column(sa.String(SHA256_LENGTH), nullable=False)
