"""Put generation_attempts.stt_transcript on the 30-day free-text clock.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-28

Revision 0002 widened ``stt_transcript`` from 200 to 4000 characters because inpainting is
enterprise-gated and name verification therefore hears — and transcribes — the entire song.
Revision 0003 added ``briefs.approved_lyrics`` and put it deliberately on the 30-day
free-text clock, because the lyric is words about a real person and, since the wizard's
preview step, words the customer may have written themselves.

Those two facts collide. The transcript is a near-verbatim copy of the lyric, and it sat on
the 90-day identity clock, so the copy would have outlived the original by sixty days and
three docstrings would have been asserting a retention schedule the schema did not keep.

This revision gives the transcript its own clock — ``text_expires_at`` / ``text_purged_at``,
stamped from ``RetentionPolicy.brief_text_days`` — while ``name_candidate_text`` stays on
the identity clock, because the candidate ladder is tuned from it and a name is not a song.
The identity sweep still clears the transcript as well, so whichever clock fires first wins.

Existing rows are backfilled from ``identity_expires_at`` rather than from a freshly
computed horizon. ``hbd.db.retention`` states the rule this follows: a row keeps the horizon
it was stamped with, so a schedule change never retroactively destroys data a user was
promised. New rows get the shorter clock from the moment this deploys.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "generation_attempts"
_EXPIRES = "text_expires_at"
_PURGED = "text_purged_at"
_INDEX = "ix_generation_attempts_text_sweep"


def upgrade() -> None:
    # batch_alter_table throughout: SQLite has no ALTER COLUMN and the test suite runs this
    # chain against SQLite. On Postgres each block emits the plain statement.
    with op.batch_alter_table(_TABLE) as batch:
        # Added nullable so existing rows can be backfilled before the constraint lands.
        batch.add_column(sa.Column(_EXPIRES, sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column(_PURGED, sa.DateTime(timezone=True), nullable=True))

    op.execute(
        sa.text(
            f"UPDATE {_TABLE} SET {_EXPIRES} = identity_expires_at WHERE {_EXPIRES} IS NULL"
        )
    )

    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column(
            _EXPIRES, existing_type=sa.DateTime(timezone=True), nullable=False
        )
        batch.create_index(_INDEX, [_EXPIRES], unique=False)


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_index(_INDEX)
        batch.drop_column(_PURGED)
        batch.drop_column(_EXPIRES)
