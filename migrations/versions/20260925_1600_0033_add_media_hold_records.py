"""The CSAM-class hold's record and the durable suspension (IMAGE_VIDEO_SPEC §6.4, §6.7, M3.R).

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-25

Four nullable columns, nothing backfilled:

* ``media_outputs.deleted_at`` — the legal-hold purge now deletes a held OBJECT and keeps its
  row, so the ``sha256``, size and time a report to the authorities quotes survive the 72 h
  clock (§6.7). ``media_inputs`` already had the column (0031).
* ``media_jobs.legal_hold_decision`` / ``legal_hold_decided_at`` — the escalation owner's
  reporting decision (``handover`` | ``delete``), recorded with
  ``python -m bayram.tools.media legal-hold``. ``handover`` stops the purge deleting the bytes.
* ``media_jobs.csam_cleared_at`` — a ``csam_blocked`` job with this NULL is a standing
  suspension of its account, read by the screen gate beside Redis, so a Redis restart no
  longer lifts it (§6.4). ``tools.media unsuspend`` stamps it.

No index: the gate's read leads with ``telegram_user_id``, which
``ix_media_jobs_user_created`` already covers, and the purge's decision read is by job id.

The enum is spelled literally as a ``VARCHAR(16)`` with no CHECK (``enum_type``'s rendering);
clocks are ``sa.DateTime(timezone=True)``: no migration imports application code.

**The downgrade drops the recorded decisions and clearances.** A job that was cleared then
reads as suspended again only through Redis, which the downgrade does not touch; a handover
decision lost this way lets the purge delete the bytes at their clock, so record the
decision again (or hold off the downgrade) while a handover is open.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("media_outputs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("media_jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "legal_hold_decision",
                sa.Enum(
                    "handover",
                    "delete",
                    name="medialegalholddecision",
                    native_enum=False,
                    length=16,
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("legal_hold_decided_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("csam_cleared_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("media_jobs", schema=None) as batch_op:
        batch_op.drop_column("csam_cleared_at")
        batch_op.drop_column("legal_hold_decided_at")
        batch_op.drop_column("legal_hold_decision")
    with op.batch_alter_table("media_outputs", schema=None) as batch_op:
        batch_op.drop_column("deleted_at")
