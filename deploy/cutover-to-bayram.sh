#!/usr/bin/env bash
#
# hbd -> bayram cutover. Run ON THE HOST as root:  sudo bash /opt/hbd/cutover-to-bayram.sh
#
# The package, its distribution, its settings prefix and its unit names all changed at once, so
# nothing about this is incremental: the wheel installs `bayram`, the running units exec `hbd.*`,
# and every value in /etc/hbd is keyed HBD_ while the new code reads BAYRAM_. Installing the wheel
# without this script takes all four services down together.
#
# WHAT MOVES, AND WHAT DELIBERATELY DOES NOT.
#   moves: /opt/hbd -> /opt/bayram (a FRESH venv, not a copied one), /etc/hbd -> /etc/bayram with
#          every key rewritten HBD_ -> BAYRAM_, and hbd-*.service -> bayram-*.service.
#   stays: the OS user `hbd` (uid 995), /var/lib/hbd and /var/log/hbd. That account owns the media
#          archive; renaming it means chowning customer artefacts during a cutover, which is risk
#          bought for tidiness. The units below therefore say User=hbd, and the repository's
#          deploy/systemd/bayram-*.service files — which say User=bayram, /srv/bayram and
#          /var/lib/bayram — are WRONG for this host and are not used. /srv/bayram has never
#          existed here any more than /srv/hbd did.
#
# THE VENV IS REBUILT, NOT MOVED. A virtualenv bakes absolute paths into pyvenv.cfg and into every
# console-script shebang, so `mv /opt/hbd /opt/bayram` produces a venv whose interpreter path lies.
# Rebuilding costs a pip resolve and is the difference between a cutover and an outage.
#
# ROLLBACK. The old units are DISABLED, never deleted, and /opt/hbd and /etc/hbd are left intact.
# To go back: stop and disable the bayram-* units, `systemctl enable --now hbd-{bot,worker,admin,payme}`.
# The database is the one thing that does not roll back, which is why step 1 dumps it first — but
# note that revision 0025 only ADDS an index, so the old code tolerates the new schema.
set -uo pipefail

# The build tag (PEP 427: it must start with a digit) is not decoration. An untagged
# `bayram_bot-0.1.0-py3-none-any.whl` from 2026-09-10 14:03 is ALSO staged in
# /opt/hbd/release, it predates the billing rail, and it has the basename this default used to
# carry — so the two were one `scp` away from being indistinguishable. Override with
# `WHEEL=<path>` when staging a newer one, and check the hash rather than the name.
#   2026-09-11  build: sha256 ef4cb2668d9ee9d9c98007d2f5cee0477084dd5d119c35d123c3280c58d0f73d
#   2026-09-11b build: sha256 b29d7924149087752b4bfa3434e500ee71bdb118b6dfead649ac7cfe0d62da21
#     (b is the artwork cover: brand/Logo-Bot.png whole, replacing the drawn text block)
WHEEL=${WHEEL:-/opt/hbd/release/bayram_bot-0.1.0-20260911b-py3-none-any.whl}
OLD_ROOT=/opt/hbd
NEW_ROOT=/opt/bayram
OLD_ETC=/etc/hbd
NEW_ETC=/etc/bayram
SVC_USER=hbd
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP=/var/backups/hbd/pre-cutover-$STAMP.sql.gz
UNITS=(bot worker admin payme)

die() { echo "FATAL: $*" >&2; exit 1; }

echo "=== 0/9  preflight ==="
test -f "$WHEEL" || die "wheel missing: $WHEEL"
python3 -c "
import sys,zipfile
n=zipfile.ZipFile('$WHEEL').namelist()
assert any(x.startswith('bayram/') for x in n), 'wheel does not contain the bayram package'
assert any('admin/routers/billing.py' in x for x in n), 'wheel has no billing router'
assert sum(1 for x in n if '/admin/static/' in x) > 0, 'wheel carries no SPA bundle'
assert any('audio/assets/cover.png' in x for x in n), 'wheel predates the artwork cover'
" || die "wheel contents are wrong"
test -f "$OLD_ROOT/migrations/versions/"*0025*.py || die "migration 0025 is not on this host"
for u in "${UNITS[@]}"; do
  test -f "/etc/systemd/system/hbd-$u.service" || die "hbd-$u.service missing — is this the right host?"
done
id "$SVC_USER" >/dev/null 2>&1 || die "service account $SVC_USER does not exist"
echo "preflight OK"

echo "=== 1/9  back up the database ==="
mkdir -p "$(dirname "$BACKUP")"
sudo -u postgres pg_dump hbd | gzip > "$BACKUP" || die "pg_dump failed"
test -s "$BACKUP" || die "backup is empty; refusing to continue"
ls -lh "$BACKUP"

echo "=== 2/9  stop the four hbd services ==="
systemctl stop hbd-bot hbd-worker hbd-admin hbd-payme || true
systemctl is-active hbd-bot hbd-worker hbd-admin hbd-payme || true

echo "=== 3/9  rewrite the environment into $NEW_ETC ==="
# Keys are rewritten at the START of a line only, so a value that happens to contain the string
# HBD_ (a URL, a note) is left alone. Modes and ownership are copied from the source file rather
# than assumed: payme.env is root:hbd 0640 and the gateway cannot read it if that is lost.
mkdir -p "$NEW_ETC"
chmod 0755 "$NEW_ETC"
rewrite() {  # $1 = source, $2 = destination
  test -f "$1" || die "expected env file missing: $1"
  sed 's/^HBD_/BAYRAM_/' "$1" > "$2"
  chown --reference="$1" "$2"
  chmod --reference="$1" "$2"
  echo "  $1 -> $2  ($(grep -c '^BAYRAM_' "$2") keys)"
}
rewrite "$OLD_ETC/hbd.env"        "$NEW_ETC/bayram.env"
rewrite "$OLD_ETC/hbd-admin.env"  "$NEW_ETC/bayram-admin.env"
rewrite "$OLD_ETC/payme.env"      "$NEW_ETC/payme.env"
# The gateway's own pointer names the file it must read; it is a KEY, so the sed above already
# renamed it, but its VALUE still points into /etc/hbd. Fix the value too.
sed -i "s#$OLD_ETC/payme.env#$NEW_ETC/payme.env#" "$NEW_ETC/payme.env" 2>/dev/null || true

echo "=== 4/9  build a fresh venv at $NEW_ROOT ==="
mkdir -p "$NEW_ROOT"
rm -rf "$NEW_ROOT/venv"
python3 -m venv "$NEW_ROOT/venv" || die "venv creation failed"
"$NEW_ROOT/venv/bin/pip" install --quiet --upgrade pip || true
"$NEW_ROOT/venv/bin/pip" install "$WHEEL" || die "wheel install failed"
"$NEW_ROOT/venv/bin/pip" check || die "dependency check failed"
"$NEW_ROOT/venv/bin/python" -c "import bayram, bayram.payme.app, bayram.admin.app; print('bayram imports OK')" \
  || die "the installed package does not import"

echo "=== 5/9  migrations into $NEW_ROOT ==="
# `rm -rf` first, and it is not defensive noise: `cp -a src dst` copies INTO dst when dst
# already exists, so a SECOND run of this script would silently produce
# $NEW_ROOT/migrations/migrations and leave a stale revision tree beside the real one. This
# script has now been run twice on this host, so re-runnability is a property it has to have
# rather than one it may have. Everything else here is already idempotent: step 3 overwrites
# its outputs and step 4 removes the venv before rebuilding it.
rm -rf "$NEW_ROOT/migrations"
cp -a "$OLD_ROOT/migrations" "$NEW_ROOT/migrations"
rm -rf "$NEW_ROOT/migrations/__pycache__" "$NEW_ROOT/migrations/versions/__pycache__"
set -a; . "$NEW_ETC/bayram.env"; set +a
"$NEW_ROOT/venv/bin/python" -m alembic -c "$NEW_ROOT/migrations/alembic.ini" current || die "alembic cannot reach the database"
"$NEW_ROOT/venv/bin/python" -m alembic -c "$NEW_ROOT/migrations/alembic.ini" upgrade head || die "migration failed"
"$NEW_ROOT/venv/bin/python" -m alembic -c "$NEW_ROOT/migrations/alembic.ini" current

echo "=== 6/9  write the four bayram units ==="
# Parity with the four `hbd-*` units as they run TODAY (10-rename-cutover.md §3.2), which is
# the whole bar: a rename may not quietly relax a sandbox. Two things this block deliberately
# does NOT carry, because they are not shared:
#
#   * `ReadWritePaths` — the bot and the worker have it, the admin API and the gateway have
#     NONE and must keep none. The panel's read-only object store is not a `:ro` mount, it is
#     `ProtectSystem=strict` plus an empty `ReadWritePaths` (01-architecture.md, Decision 1).
#     Handing the panel write access to the media archive it only streams, and the
#     money-handling gateway write access to both, is the single worst line in this script's
#     first draft. `ReadWritePaths` is a LIST directive, so the two units that need it append
#     their own after this block.
#   * `Restart` — three units are `on-failure`; the gateway is `always` and stays `always`.
#     Passed as $1 rather than overridden afterwards: systemd's last-wins rule for scalar
#     directives would work, but a unit file that sets `Restart` twice is a file the next
#     person has to reason about instead of read.
common() { cat <<UNIT
[Service]
Type=simple
User=$SVC_USER
Group=$SVC_USER
WorkingDirectory=/var/lib/hbd
Restart=${1:-on-failure}
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
StandardOutput=journal
UNIT
}
{ echo "[Unit]"; echo "Description=Bayram bot (Telegram, long polling)"
  echo "After=network-online.target postgresql.service redis-server.service"; echo "Wants=network-online.target"
  common; echo "ReadWritePaths=/var/lib/hbd /var/log/hbd"
  echo "EnvironmentFile=$NEW_ETC/bayram.env"
  echo "ExecStart=$NEW_ROOT/venv/bin/python -m bayram.main"; echo "TimeoutStopSec=20"
  echo; echo "[Install]"; echo "WantedBy=multi-user.target"; } > /etc/systemd/system/bayram-bot.service

{ echo "[Unit]"; echo "Description=Bayram ARQ worker (song generation pipeline)"
  echo "After=network-online.target postgresql.service redis-server.service"; echo "Wants=network-online.target"
  common; echo "ReadWritePaths=/var/lib/hbd /var/log/hbd"
  echo "EnvironmentFile=$NEW_ETC/bayram.env"
  echo "ExecStart=$NEW_ROOT/venv/bin/python -m arq bayram.worker.WorkerSettings"; echo "TimeoutStopSec=60"
  echo; echo "[Install]"; echo "WantedBy=multi-user.target"; } > /etc/systemd/system/bayram-worker.service

{ echo "[Unit]"; echo "Description=Bayram admin API and console (loopback only)"
  echo "After=network-online.target postgresql.service redis-server.service"; echo "Wants=network-online.target"
  common; echo "EnvironmentFile=$NEW_ETC/bayram-admin.env"
  echo "ExecStart=$NEW_ROOT/venv/bin/python -m uvicorn bayram.admin.app:app --host 127.0.0.1 --port 8080"
  echo "TimeoutStopSec=20"; echo; echo "[Install]"; echo "WantedBy=multi-user.target"; } > /etc/systemd/system/bayram-admin.service

# The gateway reads its secret through a POINTER, not EnvironmentFile, so the cashbox key never
# enters the process environment and never appears in `systemctl show`.
#
# Four directives below exist ONLY on this unit, because this is the only process holding the
# cashbox key, and all four are parity with `hbd-payme` as it runs today (§3.2):
#   * `Restart=always` — not `on-failure`. A gateway that stays down after a clean exit is a
#     gateway answering Payme with connection refused, which they retry and then escalate.
#   * `TimeoutStopSec=90` — systemd's own default, written out explicitly. The current unit
#     gets 90 s by not setting it; saying it here keeps the behaviour identical while making
#     it a decision somebody can see, instead of the 20 s this script used to impose.
#   * `MemoryDenyWriteExecute`, `RestrictNamespaces`, `RestrictAddressFamilies`.
# NO `ReadWritePaths`: the gateway writes nothing to disk and must keep no write access.
{ echo "[Unit]"; echo "Description=Bayram — Payme Merchant API endpoint"
  echo "After=network-online.target postgresql.service redis-server.service"; echo "Wants=network-online.target"
  common always; echo "Environment=BAYRAM_PAYME_ENV_FILE=$NEW_ETC/payme.env"
  echo "ExecStart=$NEW_ROOT/venv/bin/python -m uvicorn bayram.payme.app:app --host 127.0.0.1 --port 8091"
  echo "TimeoutStopSec=90"; echo "InaccessiblePaths=$NEW_ETC/bayram.env $NEW_ETC/bayram-admin.env"
  echo "MemoryDenyWriteExecute=yes"; echo "RestrictNamespaces=yes"
  echo "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX"
  echo; echo "[Install]"; echo "WantedBy=multi-user.target"; } > /etc/systemd/system/bayram-payme.service

chmod 0644 /etc/systemd/system/bayram-*.service
systemctl daemon-reload
for u in "${UNITS[@]}"; do systemd-analyze verify "/etc/systemd/system/bayram-$u.service" || die "bayram-$u.service does not verify"; done
echo "four units written and verified"

echo "=== 7/9  disable the old units (files kept for rollback) ==="
systemctl disable hbd-bot hbd-worker hbd-admin hbd-payme 2>/dev/null || true

echo "=== 8/9  start the bayram units ==="
systemctl enable --now bayram-bot bayram-worker bayram-admin bayram-payme
sleep 5
systemctl is-active bayram-bot bayram-worker bayram-admin bayram-payme

echo "=== 9/9  verify ==="
curl -sS -o /dev/null -w "gateway  /healthz      = %{http_code}\n" http://127.0.0.1:8091/healthz || true
curl -sS -o /dev/null -w "admin    /api/ops/rail = %{http_code}  (401 or 403 means MOUNTED)\n" http://127.0.0.1:8080/api/ops/rail || true
echo
echo "DONE. Backup: $BACKUP"
echo "Rollback: systemctl disable --now bayram-{bot,worker,admin,payme} && systemctl enable --now hbd-{bot,worker,admin,payme}"
echo "NOTE: /etc/sudoers.d/hbd-deploy still names the hbd-* units and will not cover bayram-*."
