"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Checklist before merging a migration (SoW DAT-4, DAT-5):

* ``downgrade`` is real, not ``pass`` — a migration you cannot reverse is a migration you
  cannot deploy on a Friday.
* No column named for a recipient's birth year, in any form. ``tests/test_db`` fails the
  build if one appears.
* Any new personal-data column gets a retention clock and a branch in ``hbd.db.purge``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
