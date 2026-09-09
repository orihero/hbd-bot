#!/usr/bin/env bash
# Bring the host from revision 0014 to head, install the current wheel, and start the Payme
# gateway. Run ON THE HOST, as root:
#
#     sudo bash /opt/hbd/deploy-payme.sh
#
# ORDER IS LOAD-BEARING and is not the obvious one. The backup comes first because ten
# revisions against a live database is the only step here that cannot be undone by rerunning
# something. MIGRATIONS COME BEFORE THE WHEEL: every revision 0015-0024 is additive — new
# tables and new indexes, no column drops and no type changes — so the OLD code tolerates the
# NEW schema for the minute between them, whereas new code against an old schema does not
# tolerate anything. The services are restarted only after both have landed.
#
# It is idempotent. A rerun re-dumps, finds `alembic upgrade head` a no-op, reinstalls the same
# wheel and restarts. Nothing here destroys data.
set -euo pipefail

WHEEL=/opt/hbd/release/hbd_bot-0.1.0-PAYME-20260909.whl
VENV=/opt/hbd/venv
ALEMBIC=/opt/hbd/migrations/alembic.ini
ENVFILE=/etc/hbd/hbd.env
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=/var/backups/hbd
BACKUP="$BACKUP_DIR/pre-payme-$STAMP.sql.gz"

echo "=== 0/6  preflight ==="
test -f "$WHEEL"    || { echo "FATAL: wheel missing: $WHEEL"; exit 1; }
test -f "$ENVFILE"  || { echo "FATAL: env file missing: $ENVFILE"; exit 1; }
test -f /etc/systemd/system/hbd-payme.service || { echo "FATAL: hbd-payme.service not installed"; exit 1; }
# The ten revisions must actually be on disk. A wheel carries no migrations, so if these were
# not copied across, `upgrade head` would silently stop at whatever IS here — which looks like
# success and leaves the schema short.
PENDING=$(ls /opt/hbd/migrations/versions/*_00{15,16,17,18,19,20,21,22,23,24}_*.py 2>/dev/null | wc -l)
test "$PENDING" -eq 10 || { echo "FATAL: expected 10 pending migration files, found $PENDING"; exit 1; }
echo "preflight OK"

echo "=== 1/6  back up the database ==="
mkdir -p "$BACKUP_DIR"
sudo -u postgres pg_dump hbd | gzip > "$BACKUP"
ls -lh "$BACKUP"
test -s "$BACKUP" || { echo "FATAL: backup is empty, refusing to migrate"; exit 1; }

echo "=== 2/6  revision before ==="
set -a; . "$ENVFILE"; set +a
"$VENV/bin/python" -m alembic -c "$ALEMBIC" current

echo "=== 3/6  migrate 0014 -> head ==="
"$VENV/bin/python" -m alembic -c "$ALEMBIC" upgrade head
"$VENV/bin/python" -m alembic -c "$ALEMBIC" current

echo "=== 4/6  install the wheel ==="
# --no-deps because this release adds no new runtime dependency: the gateway is FastAPI and
# uvicorn, which the admin process already brought in. `pip check` immediately afterwards is
# what turns that assumption into an assertion rather than a hope.
"$VENV/bin/pip" install --force-reinstall --no-deps "$WHEEL"
"$VENV/bin/pip" check

echo "=== 5/6  restart the three existing services ==="
systemctl restart hbd-bot hbd-worker hbd-admin
sleep 3
systemctl is-active hbd-bot hbd-worker hbd-admin

echo "=== 6/6  start the gateway ==="
systemctl enable --now hbd-payme
sleep 3
systemctl --no-pager --full status hbd-payme | head -14
echo "--- loopback health ---"
curl -sS -o /dev/null -w "healthz=%{http_code}\n" http://127.0.0.1:8091/healthz || true

echo
echo "DONE. The rail is still OFF: HBD_CHECKOUT_PROVIDER is unset, so the composition root"
echo "builds StubCheckoutProvider exactly as before. Backup: $BACKUP"
