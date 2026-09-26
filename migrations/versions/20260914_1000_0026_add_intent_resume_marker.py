"""Record which render a payment was opened for, and when the settlement decided about it.

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-14

Two nullable columns on ``payment_intents``, and no other change of any kind.

``resume_order_id`` is the render the customer was paying FOR: the UUID5
``bayram.bot.order_id.order_id_for`` takes over their own answers, written by the BOT at the
instant it built the payment link. It is what lets the settlement — which happens in another
process, minutes or hours later, with the customer's phone in their pocket — start the song
they already paid for instead of asking them to come back and press a button. See
``DECISIONS.md D17``.

``resumed_at`` is the claim. The settlement takes it with a conditional ``UPDATE`` whose
rowcount is the lock, BEFORE it does anything else, so a redelivered notification job — and
there are four ways to get one — cannot queue a second render. It is a clock rather than a
boolean for the same reason ``settled_at`` and ``notified_at`` are two columns and not one
flag: money landing, the customer being told, and the render being decided are three events,
and an operator answering "why did this customer get no song?" needs to know which of them
happened.

**Nullable, with no server default and no backfill.** A pre-0026 paid intent has no render
recorded against it and never did, so NULL is not a missing value to be filled in — it is the
true answer, and it reads as "never resumable", which is exactly the behaviour that shipped
before this revision. Backfilling anything here would be inventing a render from a guess.

**No foreign key on ``resume_order_id``, and the reason is stronger than the one every other
column on this table has.** The rest have none because the two rows are written in one
transaction and an FK would be a second, weaker opinion about an ordering the commit already
guarantees. This one has none because the ``orders`` row DOES NOT EXIST YET and may never
exist: the value is a forward reference to a row a later process may write, and it is
deliberately recorded for drafts that are never rendered at all (an abandoned checkout is the
commonest thing that happens to a payment link). An FK would also invert the ordering the
resume depends on — the claim is taken before the order is created, precisely so that a crash
between them renders nothing rather than twice.

**This revision adds NO INDEX**, which is revision 0025's own rule applied rather than
repeated: index a clock when a reader appears. Both columns are reached through
``public_ref``, which is already unique and indexed, and neither is ever a filter on its own.
``test_the_migrated_indexes_match_the_model_metadata`` compares index NAMES, so an index here
that the model does not declare — or a model ``index=True`` this file does not create — is a
test failure rather than a silent divergence in the query plan.

**The downgrade is exact, and is safe ONLY with the feature off.** Dropping the columns loses
the at-most-once latch along with them: a deployment rolled back to 0025 while
``BAYRAM_AUTO_RENDER_ON_PAYMENT`` is still true would have no ``resumed_at`` to claim. The
rollback lever is the environment variable — it needs no deploy and no migration — and this
downgrade is for undoing the SCHEMA once that lever is already off.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INTENTS = "payment_intents"

#: Spelled once, used in both directions, so the upgrade and the downgrade cannot disagree
#: about a name.
_RESUME_ORDER_ID = "resume_order_id"
_RESUMED_AT = "resumed_at"


def upgrade() -> None:
    # SQLite cannot ALTER an existing table in place for most changes, so every schema change
    # in this project goes through batch_alter_table (render_as_batch=True). Adding a nullable
    # column is one of the few SQLite CAN do directly, but the batch form is used anyway:
    # a migration that is shaped like its neighbours is one a reader can skim.
    with op.batch_alter_table(_INTENTS, schema=None) as batch_op:
        batch_op.add_column(sa.Column(_RESUME_ORDER_ID, sa.Uuid(), nullable=True))
        # A plain timezone-aware ``DateTime``, never ``UtcDateTime``. **No migration in this
        # project imports application code** — ``test_no_migration_imports_application_code``
        # enforces it — because a revision that already ran everywhere must keep meaning what
        # it meant after ``bayram.*`` is refactored. ``env.py`` renders our own column type as
        # exactly this, which is why the two stay in step.
        batch_op.add_column(sa.Column(_RESUMED_AT, sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(_INTENTS, schema=None) as batch_op:
        batch_op.drop_column(_RESUMED_AT)
        batch_op.drop_column(_RESUME_ORDER_ID)
