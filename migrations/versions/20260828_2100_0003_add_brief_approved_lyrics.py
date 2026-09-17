"""Add briefs.approved_lyrics: the lyric the customer approved before paying.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-28

The wizard now writes the lyric, shows it, and lets the customer keep it, regenerate it or
paste their own. What they approve is what the worker must sing, so it has to survive the
queue — and the queue payload carries an order id and nothing else, which means the only
place the approved words can live is the brief row the worker re-reads.

It is stored as the serialised ``LyricDraft`` in a JSON column rather than as columns,
because a lyric is a nested shape (sections, lines, a hook flag) that no query ever filters
on, and ``bayram.db.mapping.approved_lyrics_from_json`` validates it back through the model on
the way out.

It rides the 30-day note clock, not the 90-day identity clock. A lyric is free text about a
real third party — often typed by the customer — so it belongs with ``briefs.note`` under
SoW DAT-3. The identity sweep nulls it too, so that a policy whose note clock is the longer
of the two cannot leave the recipient's name sitting in the hook after every other identity
column has been cleared.

Nullable with no default: every brief written before this revision, and every brief whose
note clock has already run, reads as ``NULL``, and ``NULL`` means what it has always meant —
the pipeline writes its own lyric.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "briefs"
_COLUMN = "approved_lyrics"


def upgrade() -> None:
    # batch_alter_table, not a bare add_column: the test suite runs this chain against
    # SQLite, and batch mode is the idiom this project has settled on for briefs so a
    # later constraint-touching migration does not need a different shape. On Postgres it
    # emits the plain ALTER TABLE ... ADD COLUMN.
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column(_COLUMN, sa.JSON(), nullable=True))


def downgrade() -> None:
    # Dropping the column discards approved lyrics outright. That is the correct downgrade:
    # the older code cannot read the column, and an order that loses its approved lyric
    # falls back to the pipeline writing one rather than failing.
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)
