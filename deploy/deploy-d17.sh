#!/usr/bin/env bash
# deploy-d17.sh — ship DECISIONS.md D17 (a settled payment starts the song) to abdu-test.
#
# Run as root, once:   sudo bash /tmp/deploy-d17.sh
#
# It is IDEMPOTENT. A rerun re-dumps the database, finds `alembic upgrade head` a no-op,
# reinstalls the same wheel over itself and restarts the same four units.
#
# THE ORDER IS 08-payme.md §11.4's, AND THE MIGRATION GOES FIRST ON PURPOSE. "Ship the code,
# then the data" is what most people reach for and it is wrong here. Revision 0026 is
# ADDITIVE — two nullable columns on `payment_intents`, no drops, no type changes, no
# renames — so for the minute between step 3 and step 4 the OLD code runs against the NEW
# schema, and old code ignores columns it has never heard of. Invert the order and that
# minute becomes new code against an old schema, which tolerates nothing: the bot and the
# worker would restart into a schema missing the column they were just taught to claim.
#
# **That precondition is a property of THIS revision, not a rule of the project** — check the
# diff before inheriting this order for the next one. The first revision that drops a column
# or narrows a type needs a maintenance window with the services stopped, not a cleverer
# ordering.
#
# WHAT THIS TURNS ON, STATED PLAINLY. `BAYRAM_AUTO_RENDER_ON_PAYMENT` defaults to true and is
# not set in bayram.env, so the moment the worker restarts, a real customer who pays on the
# live Payme rail has their song started for them. That is the intended behaviour and it was
# chosen deliberately. The rollback is one line in /etc/bayram/bayram.env —
# `BAYRAM_AUTO_RENDER_ON_PAYMENT=false` — plus `systemctl restart bayram-worker`. No deploy,
# no migration, and NOT a downgrade of 0026: dropping those columns while the feature is on
# would take the at-most-once latch away with it.

set -euo pipefail

WHEEL=/tmp/bayram_bot-0.1.0-20260915-py3-none-any.whl
MIGRATION=/tmp/20260914_1000_0026_add_intent_resume_marker.py
VERSIONS=/opt/bayram/migrations/versions
VENV=/opt/bayram/venv
ALEMBIC=/opt/bayram/migrations/alembic.ini
ENVFILE=/etc/bayram/bayram.env
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=/var/backups/bayram
BACKUP="$BACKUP_DIR/pre-d17-$STAMP.sql.gz"

echo "=== 0/6  preflight ==="
test -f "$WHEEL"     || { echo "FATAL: wheel missing: $WHEEL"; exit 1; }
test -f "$ENVFILE"   || { echo "FATAL: env file missing: $ENVFILE"; exit 1; }
test -f "$ALEMBIC"   || { echo "FATAL: alembic.ini missing: $ALEMBIC"; exit 1; }
# A wheel carries no migrations. If 0026 were not on disk, `upgrade head` would stop at 0025 —
# which looks exactly like success and leaves the schema one column short of the code.
install -m 0644 -o developer -g developer "$MIGRATION" "$VERSIONS/"
test -f "$VERSIONS/$(basename "$MIGRATION")" || { echo "FATAL: 0026 did not land"; exit 1; }
echo "preflight OK"

echo "=== 1/6  back up the database ==="
# First, because it is the only step here that cannot be undone by running something again.
mkdir -p "$BACKUP_DIR"
sudo -u postgres pg_dump hbd | gzip > "$BACKUP"
ls -lh "$BACKUP"
# A pg_dump that failed on permissions still leaves a valid, empty gzip. A backup you did not
# check is a backup you do not have.
test -s "$BACKUP" || { echo "FATAL: backup is empty, refusing to migrate"; exit 1; }

echo "=== 2/6  revision before ==="
set -a; . "$ENVFILE"; set +a
"$VENV/bin/python" -m alembic -c "$ALEMBIC" current

echo "=== 3/6  migrate -> head (expect 0025 -> 0026) ==="
"$VENV/bin/python" -m alembic -c "$ALEMBIC" upgrade head
"$VENV/bin/python" -m alembic -c "$ALEMBIC" current

echo "=== 4/6  install the wheel ==="
# --no-deps states an assumption: this release adds no new runtime dependency (the new code
# imports nothing outside the stdlib and what is already installed). `pip check` on the very
# next line is what turns that assumption into an assertion that fails the deploy instead of
# a hope that fails a customer — see §11.5 and the pillow lesson. Keep the two together.
"$VENV/bin/pip" install --force-reinstall --no-deps "$WHEEL"
"$VENV/bin/pip" check

echo "=== 5/6  restart the fleet ==="
# All four, and the gateway included. It shares the venv, so leaving it on the old code would
# run two versions of bayram.db.payme against one schema — survivable here, since 0026 is
# additive, and not worth carrying as a difference nobody wrote down.
systemctl restart bayram-bot bayram-worker bayram-admin bayram-payme
sleep 4
systemctl is-active bayram-bot bayram-worker bayram-admin bayram-payme

echo "=== 6/6  prove the new code is the code that is running ==="
# Three assertions, each of which failed silently at some point in this project's history if
# it was left to inspection: the module exists, the setting resolves, and the schema has the
# two columns the code now writes.
"$VENV/bin/python" - <<'PY'
from bayram.runtime import render_resume
from bayram.config import Settings
from bayram.db.models.payment_intent import PaymentIntentRow

print("render_resume:", render_resume.__file__)
columns = {c.name for c in PaymentIntentRow.__table__.columns}
print("resume_order_id mapped:", "resume_order_id" in columns)
print("resumed_at mapped:", "resumed_at" in columns)
print("auto_render default:", Settings.model_fields["auto_render_on_payment"].default)
PY

echo
echo "DONE. D17 is live: a settled Payme payment now starts the song."
echo "Rollback without a deploy:"
echo "  echo 'BAYRAM_AUTO_RENDER_ON_PAYMENT=false' >> $ENVFILE && systemctl restart bayram-worker"
echo "Backup taken at: $BACKUP"
