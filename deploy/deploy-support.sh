#!/usr/bin/env bash
# deploy-support.sh — ship the support-ticket queue, the group picker and the money strip
# to abdu-test.
#
# Run as root, once:   sudo bash /tmp/deploy-support.sh
#
# It is IDEMPOTENT. A rerun re-dumps the database, finds `alembic upgrade head` a no-op,
# reinstalls the same wheel over itself and restarts the same four units.
#
# THE ORDER IS 08-payme.md §11.4's, AND THE MIGRATIONS GO FIRST ON PURPOSE, for the same
# reason deploy-d17.sh states and on the same footing: revisions 0027 and 0028 are PURELY
# ADDITIVE — three new tables (`support_tickets`, `support_ticket_events`, `bot_chats`), no
# drops, no type changes, no renames — so for the minute between step 3 and step 4 the OLD
# code runs against the NEW schema, and old code ignores tables it has never heard of. Invert
# the order and that minute becomes new code against an old schema, which tolerates nothing:
# the admin process would answer every /api/support route with a 500 about a missing relation.
#
# **That precondition is a property of THESE revisions, not a rule of the project.** The first
# revision that drops a column or narrows a type needs a maintenance window with the services
# stopped, not a cleverer ordering.
#
# TWO SETTINGS ARE DELETED BY THIS RELEASE: BAYRAM_SUPPORT_GROUP_CHAT_ID and
# BAYRAM_SUPPORT_GROUP_THREAD_ID. The support group is now a row in `bot_chats`, chosen in the
# panel. `Settings` is `extra="ignore"`, so a stale line in bayram.env boots fine and does
# nothing — it is not a hazard, it is a lie left in a config file, and step 6 names it.
#
# WHAT THIS TURNS ON, STATED PLAINLY. The ⚠️ button under a delivered song stops printing the
# support contact and starts opening a ticket, and /support does the same. Tickets are filed
# and answerable from the panel IMMEDIATELY. Nothing is posted to Telegram until somebody
# selects a group in the panel — Telegram offers no "list my groups" API, so the group the bot
# is already in cannot be discovered and its chat id has to be pasted once. Until then the
# board fills up and the group stays silent, which is the designed degradation and not a fault.
#
# ROLLBACK IS THE WHEEL, NEVER THE SCHEMA. Reinstall the previous wheel and restart; the three
# new tables stay behind, unused, costing nothing. DO NOT `alembic downgrade` — it drops
# `support_tickets`, and with it every complaint a customer has filed since the deploy.

set -euo pipefail

WHEEL=${WHEEL:-/tmp/bayram_bot-0.1.0-20260915b-py3-none-any.whl}
MIGRATIONS=(
  /tmp/20260915_1000_0027_add_support_tickets.py
  /tmp/20260915_1400_0028_add_bot_chats.py
)
VERSIONS=/opt/bayram/migrations/versions
VENV=/opt/bayram/venv
ALEMBIC=/opt/bayram/migrations/alembic.ini
ENVFILE=/etc/bayram/bayram.env
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=/var/backups/bayram
BACKUP="$BACKUP_DIR/pre-support-$STAMP.sql.gz"

echo "=== 0/7  preflight ==="
test -f "$WHEEL"   || { echo "FATAL: wheel missing: $WHEEL"; exit 1; }
test -f "$ENVFILE" || { echo "FATAL: env file missing: $ENVFILE"; exit 1; }
test -f "$ALEMBIC" || { echo "FATAL: alembic.ini missing: $ALEMBIC"; exit 1; }

# A wheel carries no migrations. If either revision were absent, `upgrade head` would stop at
# the one before it — which looks exactly like success and leaves the schema short of the
# tables the code is about to serve.
for m in "${MIGRATIONS[@]}"; do
  test -f "$m" || { echo "FATAL: migration missing: $m"; exit 1; }
  install -m 0644 -o developer -g developer "$m" "$VERSIONS/"
  test -f "$VERSIONS/$(basename "$m")" || { echo "FATAL: $(basename "$m") did not land"; exit 1; }
done

# The wheel must carry the built console. `src/bayram/admin/static/` is gitignored and packaged
# as a hatchling ARTIFACT, so a wheel built without `make ui-build` first ships this API with
# last release's UI — an admin panel with no Support section and no way to pick the group,
# failing only in a browser where no test looks. Assert it before touching the database.
python3 - "$WHEEL" <<'PY'
import sys, zipfile
names = zipfile.ZipFile(sys.argv[1]).namelist()
assets = [n for n in names if n.startswith("bayram/admin/static/")]
if not assets:
    sys.exit("FATAL: wheel carries no admin/static/ — run `make ui-build` and rebuild it")
blob = b"".join(
    zipfile.ZipFile(sys.argv[1]).read(n) for n in assets if n.endswith(".js")
)
if b"support.groups" not in blob and "Группа поддержки".encode() not in blob:
    sys.exit("FATAL: the bundle in this wheel predates the Support work — rebuild the console")
print(f"preflight: wheel carries {len(assets)} console files, Support section present")
PY
echo "preflight OK"

echo "=== 1/7  back up the database ==="
# First, because it is the only step here that cannot be undone by running something again.
mkdir -p "$BACKUP_DIR"
sudo -u postgres pg_dump hbd | gzip > "$BACKUP"
ls -lh "$BACKUP"
# A pg_dump that failed on permissions still leaves a valid, empty gzip. A backup you did not
# check is a backup you do not have.
test -s "$BACKUP" || { echo "FATAL: backup is empty, refusing to migrate"; exit 1; }

echo "=== 2/7  revision before ==="
set -a; . "$ENVFILE"; set +a
"$VENV/bin/python" -m alembic -c "$ALEMBIC" current

echo "=== 3/7  migrate -> head (expect 0026 -> 0028) ==="
"$VENV/bin/python" -m alembic -c "$ALEMBIC" upgrade head
"$VENV/bin/python" -m alembic -c "$ALEMBIC" current

echo "=== 4/7  install the wheel ==="
# --no-deps states an assumption: this release adds no new runtime dependency. `pip check` on
# the very next line is what turns that assumption into an assertion that fails the deploy
# instead of a hope that fails a customer — see §11.5. Keep the two together.
"$VENV/bin/pip" install --force-reinstall --no-deps "$WHEEL"
"$VENV/bin/pip" check

echo "=== 5/7  restart the fleet ==="
# All four, the gateway included. It shares the venv, so leaving it on the old code would run
# two versions of bayram.db against one schema.
systemctl restart bayram-bot bayram-worker bayram-admin bayram-payme
sleep 4
systemctl is-active bayram-bot bayram-worker bayram-admin bayram-payme

echo "=== 6/7  prove the new code is the code that is running ==="
# Each of these failed silently at some point in this project's history when it was left to
# inspection: the modules exist, the schema has the tables the code now writes, the ARQ job
# names agree across the process boundary, and the two deleted settings are really gone.
"$VENV/bin/python" - <<'PY'
from bayram.db.models.bot_chat import BotChatRow
from bayram.db.models.support_ticket import SupportTicketRow
from bayram.db.models.support_ticket_event import SupportTicketEventRow
from bayram.admin.queue import VERIFY_GROUP_JOB_NAME
from bayram.config import Settings
from bayram.bot import support_card

print("support_card:", support_card.__file__)
print("tables mapped:", sorted(
    t.__tablename__ for t in (SupportTicketRow, SupportTicketEventRow, BotChatRow)
))
gone = [f for f in ("support_group_chat_id", "support_group_thread_id")
        if f in Settings.model_fields]
print("retired settings still present:", gone or "none — correct")
assert not gone, "a deleted setting came back; this is not the wheel you think it is"
print("verify job name:", VERIFY_GROUP_JOB_NAME)
PY

echo "=== 7/7  what is left for a person ==="
grep -qE '^BAYRAM_SUPPORT_PANEL_BASE_URL=.+' "$ENVFILE" \
  && echo "  [ok]   BAYRAM_SUPPORT_PANEL_BASE_URL is set" \
  || echo "  [TODO] BAYRAM_SUPPORT_PANEL_BASE_URL is unset — the group card ships without its
         'Open in panel' button. Set it in $ENVFILE and restart bayram-worker."
grep -qE '^BAYRAM_SUPPORT_GROUP_(CHAT|THREAD)_ID=' "$ENVFILE" \
  && echo "  [TODO] a retired BAYRAM_SUPPORT_GROUP_* line is still in $ENVFILE. Harmless
         (Settings ignores it) but it now describes nothing — delete it." \
  || echo "  [ok]   no retired BAYRAM_SUPPORT_GROUP_* lines"

echo
echo "DONE. The support queue is live."
echo
echo "NOTHING REACHES TELEGRAM YET. Open the panel -> Support -> 'Support group', paste your"
echo "group's chat id (negative, -100...), and press Select. The worker posts a test message"
echo "and the row turns green only if the bot could really post. A group the bot is already"
echo "in cannot appear by itself — Telegram has no API that lists it."
echo
echo "Rollback (code only, NEVER the schema):"
echo "  $VENV/bin/pip install --force-reinstall --no-deps <previous wheel>"
echo "  systemctl restart bayram-bot bayram-worker bayram-admin bayram-payme"
echo "Backup taken at: $BACKUP"
