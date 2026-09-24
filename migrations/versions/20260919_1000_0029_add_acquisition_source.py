"""Record the ``/start`` deep-link payload an account first arrived with.

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-19

One nullable column on ``user_profiles``, and no other change of any kind.

``acquisition_source`` is the campaign label a customer arrived under — ``ig_bio`` from the
Instagram bio link, ``ig_hl_narxlar`` from a highlight — taken from the payload of
``t.me/<bot>?start=<payload>``. Until this column existed the payload was not merely unread
but unreadable: ``handlers.start.handle_start`` declared no ``CommandObject``, so every
arrival from every campaign was indistinguishable from someone typing ``/start``, and the
acquisition figure the Instagram plan is measured on did not exist.

**It is a LABEL and not a referral edge**, which is what keeps it on the right side of the
line ``db/models/user.py`` draws: no user id, no join, no arithmetic, one scalar fact about
one arrival. It also lands on ``user_profiles`` rather than on ``users`` deliberately —
``users`` is the row that SURVIVES ``/forget`` so a block can outlive an erasure, and where a
customer came from is exactly the kind of fact erasure is supposed to take with it. Here it
is deleted with the rest of the profile row, by the erasure path that already exists.

``sa.String(64)`` because Telegram bounds a ``start`` payload at 64 characters of
``A-Za-z0-9_-``. The bound is the link format's, not ours, so a longer value could not have
reached us through a ``t.me`` link at all; the handler discards those rather than truncating
them, and the column is sized to agree with it.

**The downgrade is exact and loses data that cannot be rebuilt.** Dropping the column throws
away every acquisition label recorded while it existed, and nothing else in the system holds
a copy — the payload arrives once, in one update, and is never seen again. There is no
feature flag to turn off first: a rollback to 0028 is a decision to forget where every
customer since this migration came from.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROFILES = "user_profiles"

#: Spelled once, used in both directions, so the upgrade and the downgrade cannot disagree
#: about a name.
_ACQUISITION_SOURCE = "acquisition_source"

#: Telegram's ceiling on a ``start`` payload. Written as a literal rather than imported from
#: ``bayram.db.models.user_profile.ACQUISITION_SOURCE_LENGTH``: **no migration in this project
#: imports application code** — ``test_no_migration_imports_application_code`` enforces it —
#: because a revision that already ran everywhere must keep meaning what it meant after
#: ``bayram.*`` is refactored.
_SOURCE_LENGTH = 64


def upgrade() -> None:
    # SQLite cannot ALTER an existing table in place for most changes, so every schema change
    # in this project goes through batch_alter_table (render_as_batch=True). Adding a nullable
    # column is one of the few SQLite CAN do directly, but the batch form is used anyway:
    # a migration that is shaped like its neighbours is one a reader can skim.
    with op.batch_alter_table(_PROFILES, schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(_ACQUISITION_SOURCE, sa.String(length=_SOURCE_LENGTH), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table(_PROFILES, schema=None) as batch_op:
        batch_op.drop_column(_ACQUISITION_SOURCE)
