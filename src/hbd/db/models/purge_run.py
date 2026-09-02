"""``purge_runs`` — one row per retention sweep, so the schedule is auditable.

The retention design was complete and had never executed: ``purge_expired`` was called by
nothing, and the only trace a sweep would have left was a log line. A log line is not
evidence. This table exists so ``GET /api/retention`` reads a **record** rather than
scraping stdout, and so the two failures that matter are visible rather than inferred:

* **A sweep that silently did nothing.** Zero rows deleted and a scheduler that stopped
  firing produce the same silence in a log; they produce different rows here, because a
  run that happened writes a row of zeros and a run that never happened writes nothing.
* **A sweep that deleted rows but not the bytes behind them.** ``purge_expired`` returns
  storage keys for the caller to delete after the transaction commits (see
  ``hbd.db.purge``'s module docstring), so the number of keys handed over and the number
  actually removed from the object store are two different numbers. They are stored as two
  different columns — ``storage_keys_returned`` and ``storage_keys_deleted`` — precisely so
  a mismatch is a fact on the row instead of an average nobody can see. Smoothing them into
  one "objects cleaned up" count would hide exactly the leak this table was added to catch.

``is_batch_full`` is the honest "run me again" signal. It is true when ANY sweep filled its
``batch_size``, which is what "there is more due than one pass could take" actually means —
not ``total_rows_affected > 0``, which is true of every productive run and false of every
idle one.

**No personal data lives here — counts only.** That is what lets the row outlive every
clock it records: an audit trail on a 30-day schedule cannot answer "was the 90-day
identity sweep running last quarter?", which is the one question a regulator asks. The rows
are still bounded, at 365 days, by ``hbd.db.purge._purge_purge_runs``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hbd.db.base import Base, UtcDateTime, enum_type, utc_now
from hbd.db.enums import PurgeTrigger

__all__ = ["PurgeRunRow", "TRIGGERED_BY_LENGTH", "ERROR_CODE_LENGTH"]

#: Mirrors ``admin_users.username``; a sweep is attributed to an operator, not to free text.
TRIGGERED_BY_LENGTH: Final[int] = 64
#: ``HbdError.error_code`` is a short symbolic name, never a message.
ERROR_CODE_LENGTH: Final[int] = 48


class PurgeRunRow(Base):
    """What one retention sweep did, including what it failed to do.

    ``TimestampMixin`` is deliberately not used: a purge run has one meaningful instant
    (``ran_at``) and is never updated, so an ``updated_at`` would be a second clock that
    always equals the first and an indexed ``created_at`` would duplicate ``ran_at``'s own
    index. ``created_at`` is kept — unindexed — only to record when the ROW was written,
    which differs from ``ran_at`` by the duration of the sweep.
    """

    __tablename__ = "purge_runs"

    id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid4)
    #: When the sweep started. Indexed: every read of this table is "the last N runs".
    ran_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    trigger: Mapped[PurgeTrigger] = mapped_column(enum_type(PurgeTrigger), nullable=False)
    #: Set for ``MANUAL`` only. The operator also appears in the audit log; this column is
    #: what makes the retention view answer "who ran this" without a join.
    triggered_by_username: Mapped[str | None] = mapped_column(
        sa.String(TRIGGERED_BY_LENGTH), nullable=True
    )
    duration_ms: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    # -- rows ---------------------------------------------------------------
    assets_deleted: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    brief_notes_purged: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    brief_identities_purged: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    attempt_identities_purged: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    attempt_transcripts_purged: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    name_records_deleted: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    abandoned_orders_deleted: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    #: The admin panel's own three clocks, added once they had a sweep to be counted by.
    #: They were written in slice 1b and executed by nothing, which is the same defect this
    #: whole table exists to make visible — so they are counted here like every other.
    audit_reasons_purged: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    audit_rows_deleted: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    admin_sessions_deleted: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    purge_runs_deleted: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    # -- bytes --------------------------------------------------------------
    #: Keys ``purge_expired`` handed back, i.e. rows whose objects are now orphaned.
    storage_keys_returned: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    #: Keys the object store confirmed gone. Below ``storage_keys_returned`` means a leak.
    storage_keys_deleted: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    storage_delete_failures: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    # -- verdict ------------------------------------------------------------
    #: The bound each sweep ran under, stored so ``is_batch_full`` can be re-derived.
    batch_size: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    #: True when ANY sweep hit ``batch_size``. The real "run me again" signal.
    is_batch_full: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    #: Set when ``purge_expired`` returned ``Err``. The row is still written: a failed
    #: sweep is the one an operator most needs to see, and no row at all is unreadable.
    error_code: Mapped[str | None] = mapped_column(sa.String(ERROR_CODE_LENGTH), nullable=True)

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)

    @property
    def is_storage_leaking(self) -> bool:
        """True when bytes were handed over and not confirmed gone. Never smoothed over."""
        return self.storage_keys_deleted < self.storage_keys_returned
