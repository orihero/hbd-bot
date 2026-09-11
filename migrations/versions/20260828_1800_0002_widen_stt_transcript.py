"""Widen generation_attempts.stt_transcript from 200 to 4000 characters.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-28

``stt_transcript`` was sized on the assumption that name verification transcribes an
isolated ~8s name chunk. That assumption depended on Eleven Music inpainting, which is
enterprise-gated: the vendor accepts an inpaint request, ignores the parts it will not
honour, and returns a whole new track. Verification therefore hears the ENTIRE song, and
the first live order produced a ~700-character transcript.

The insert failed with ``value too long for type character varying(200)`` at the persisting
stage — after the song and all three greetings had been generated and billed. The customer
saw a failure for a kit that existed.

The column is still bounded, and writers now clip to the bound
(``bayram.db.attempts.truncate_transcript``), so a longer song cannot revive this failure.

This DOES change what is retained, and the first draft of this docstring claimed otherwise.
Going from 200 to 4000 characters turns a fragment of a transcript into the whole song, and
the whole song is the lyric — which, since the wizard's preview step, may be free text the
customer wrote about a named third party. Revision 0004 is the consequence: it puts the
transcript on the 30-day free-text clock alongside ``briefs.approved_lyrics`` instead of
leaving it on the 90-day identity clock alone.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_TABLE = "generation_attempts"
_COLUMN = "stt_transcript"
_WIDENED = 4_000
_ORIGINAL = 200


def upgrade() -> None:
    # batch_alter_table, not alter_column: SQLite has no ALTER COLUMN and the test suite
    # runs this chain against SQLite. On Postgres this emits the plain ALTER.
    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column(
            _COLUMN,
            existing_type=sa.String(length=_ORIGINAL),
            type_=sa.String(length=_WIDENED),
            existing_nullable=True,
        )


def downgrade() -> None:
    # Truncate before narrowing: rows written since the upgrade may exceed the old bound,
    # and a downgrade that raises is a downgrade nobody can run.
    op.execute(
        sa.text(
            f"UPDATE {_TABLE} SET {_COLUMN} = SUBSTR({_COLUMN}, 1, {_ORIGINAL}) "
            f"WHERE {_COLUMN} IS NOT NULL"
        )
    )
    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column(
            _COLUMN,
            existing_type=sa.String(length=_WIDENED),
            type_=sa.String(length=_ORIGINAL),
            existing_nullable=True,
        )
