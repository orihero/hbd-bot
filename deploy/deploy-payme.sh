#!/usr/bin/env bash
# Bring the host from revision 0014 to head, install the current wheel, and start the Payme
# gateway. Run ON THE HOST, as root:
# RETIRED 2026-09-19 — DO NOT RUN THE COMMAND BELOW. Superseded except 5.5/6; see footer.
#     sudo bash /opt/bayram/deploy-payme.sh
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
printf '%s\n' '' 'REFUSED: deploy-payme.sh is RETIRED (2026-09-19) and will not run.' '' '  It is superseded IN FULL. Use the release tool instead:' '      sudo /opt/bayram/sbin/bayram-release deploy' '' '  WHY THIS IS A HARD REFUSAL, NOT A WARNING: this file pins the wheel' '  bayram_bot-0.1.0-20260909 (:18), which is OLDER than the wheel live on' '  abdu-test (bayram_bot-0.1.0rc1, deployed 2026-09-17, schema head 0028).' '  Running it would pg_dump the database, run `alembic upgrade head`, install that' '  stale wheel over the live one and restart all four units -- rolling the host' '  BACKWARDS.' '' '  There is no override: no environment variable, no --force, no escape hatch. It is' '  retired IN PLACE, rather than deleted, so that it can still be READ. Read it; do' '  not run it.' '' >&2; if (return 0 2>/dev/null); then return 1; fi; exit 1  # replaces `set -euo pipefail` in place -- everything below is unreachable by design.

WHEEL=/opt/bayram/release/bayram_bot-0.1.0-20260909-py3-none-any.whl
VENV=/opt/bayram/venv
ALEMBIC=/opt/bayram/migrations/alembic.ini
ENVFILE=/etc/bayram/bayram.env
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=/var/backups/bayram
BACKUP="$BACKUP_DIR/pre-payme-$STAMP.sql.gz"

echo "=== 0/6  preflight ==="
test -f "$WHEEL"    || { echo "FATAL: wheel missing: $WHEEL"; exit 1; }
test -f "$ENVFILE"  || { echo "FATAL: env file missing: $ENVFILE"; exit 1; }
test -f /etc/systemd/system/bayram-payme.service || { echo "FATAL: bayram-payme.service not installed"; exit 1; }
# The ten revisions must actually be on disk. A wheel carries no migrations, so if these were
# not copied across, `upgrade head` would silently stop at whatever IS here — which looks like
# success and leaves the schema short.
PENDING=$(ls /opt/bayram/migrations/versions/*_00{15,16,17,18,19,20,21,22,23,24}_*.py 2>/dev/null | wc -l)
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
systemctl restart bayram-bot bayram-worker bayram-admin
sleep 3
systemctl is-active bayram-bot bayram-worker bayram-admin

echo "=== 5.5/6  give the gateway its database and queue ==="
# The gateway needs the SAME Postgres and Redis as the bot, and NOTHING else from bayram.env.
# Exactly two variables are copied, BY NAME, and only if absent — so this cannot drag a vendor
# credential into the one process whose whole justification is that it holds none, and cannot
# clobber the cashbox key an operator put there. Values are never echoed.
for var in BAYRAM_DATABASE_URL BAYRAM_REDIS_URL; do
  if ! grep -q "^${var}=" /etc/bayram/payme.env 2>/dev/null; then
    val=$(grep -E "^${var}=" "$ENVFILE" | head -1 | cut -d= -f2-)
    test -n "$val" || { echo "FATAL: $var not found in $ENVFILE"; exit 1; }
    printf "%s=%s\n" "$var" "$val" >> /etc/bayram/payme.env
    echo "added $var"
  else
    echo "$var already present"
  fi
done
# The gateway refuses to boot while BAYRAM_PAYME_ENABLED is false, and that flag is about THIS
# PROCESS, not about the rail. The rail is gated separately and independently by
# BAYRAM_CHECKOUT_PROVIDER on the BOT side, which stays "stub": the bot creates no intents, so a
# running gateway has nothing to settle and no customer can reach a purchase through it. Two
# switches, two questions, and this is the one that says "run the daemon".
sed -i "s/^BAYRAM_PAYME_ENABLED=.*/BAYRAM_PAYME_ENABLED=true/" /etc/bayram/payme.env
grep -q "^BAYRAM_PAYME_ENABLED=" /etc/bayram/payme.env || echo "BAYRAM_PAYME_ENABLED=true" >> /etc/bayram/payme.env
chown root:bayram /etc/bayram/payme.env && chmod 0640 /etc/bayram/payme.env

echo "=== 6/6  start the gateway ==="
systemctl enable --now bayram-payme
sleep 3
systemctl --no-pager --full status bayram-payme | head -14
echo "--- loopback health ---"
curl -sS -o /dev/null -w "healthz=%{http_code}\n" http://127.0.0.1:8091/healthz || true

echo
echo "DONE. The rail is still OFF: BAYRAM_CHECKOUT_PROVIDER is unset, so the composition root"
echo "builds StubCheckoutProvider exactly as before. Backup: $BACKUP"

# ----------------------------------------------------------------------------------------------
# RETIRED 2026-09-19 — BUT NOT FULLY SUPERSEDED. DO NOT RUN THIS FILE AS A DEPLOY.
#
# Kept verbatim, at its ORIGINAL LINE NUMBERS, as a citation target: :39 and :95 are cited from
# docs/deployment/04-release.md, docs/deployment/03-provisioning.md and
# marketing/strategy/03-concept-dossier.md. EDITING RULE: replace a line in place, or append below
# this block. Never insert, never reflow.
#
# Beats 0/6 through 5/6 belong to deploy/bayram-release now, and it does each of them better.
#
# STAGE 5.5/6 AND 6/6 ARE THE EXCEPTION, AND THEY ARE WHY THIS FILE WAS NOT DELETED. Lines 63-88
# — seeding /etc/bayram/payme.env with BAYRAM_DATABASE_URL and BAYRAM_REDIS_URL by name and only
# if absent, forcing BAYRAM_PAYME_ENABLED=true, chown root:bayram + chmod 0640, then
# `systemctl enable --now bayram-payme` — are a FIRST-INSTALL BOOTSTRAP with no equivalent
# anywhere in this repository:
#
#   * deploy/bayram-release only ever RESTARTS an already-enabled bayram-payme. It reads
#     /etc/bayram/payme.env as PAYME_ENVFILE and never creates or populates one.
#   * deploy/cutover-to-bayram.sh only REWRITES an existing /etc/hbd/payme.env into
#     /etc/bayram/payme.env. It cannot produce one from bayram.env.
#   * deploy/first-install-proposal.md enables bayram-bot, bayram-worker and bayram-admin, and
#     never enables the gateway at all.
#
# So these lines are the only executable record of how a Payme gateway is stood up on a fresh
# host. On abdu-test that work is already done — /etc/bayram/payme.env exists, 0640 root:hbd,
# and bayram-payme is active — which makes the stage dead weight for every release from here on,
# and load-bearing the first time anyone builds a SECOND host or rebuilds this one.
#
# Extracting that bootstrap into its own root-owned, idempotent, first-install-only script is
# the change that would make this file deletable. Such a script must refuse to run when
# /etc/bayram/payme.env already carries a cashbox key.
#
# The executable bit was dropped with the retirement.
#
# UNRELATED FILE, SAME NAME, ENDLESS CONFUSION: /opt/hbd/deploy-payme.sh on abdu-test is a
# 434-byte wrapper that `exec`s /opt/hbd/diagnose.sh, and its own header still claims it wraps
# the cutover. It is NOT this file, nothing in this repository manages it, and the sudoers grant
# that once made it a root entry point is gone (verified [HOST 2026-09-19]). The genuine
# pre-cutover script sits beside it as deploy-payme.sh.pre-cutover.bak — do not delete that one;
# docs/deployment/04-release.md §0.3 (committed-HEAD row) names it as the only faithful copy.
# ----------------------------------------------------------------------------------------------
