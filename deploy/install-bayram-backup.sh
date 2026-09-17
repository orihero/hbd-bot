#!/usr/bin/env bash
#
# ============================================================================
# THIS FILE IS A BASH INSTALLER. IT IS NOT A SYSTEMD UNIT.
# ============================================================================
# The filename it was asked to carry — `bayram-backup.timer` — is wrong for what
# is inside it, and it is wrong in exactly the way pass 1 was wrong: it invites
# `scp deploy/systemd/bayram-backup.timer aizu:/etc/systemd/system/`, which would
# put a shell script where systemd expects a unit. Do not do that. `systemd-analyze
# verify` on the result prints "Assignment outside of section" for every line of
# this script and the timer never fires — a silent no-op, which is the failure mode
# this whole file exists to prevent. The correct install is:
#
#     scp deploy/systemd/bayram-backup.timer aizu:/tmp/install-bayram-backup.sh
#     ssh -t aizu 'sudo bash /tmp/install-bayram-backup.sh'
#
# The guard at line ~120 refuses to run if it finds itself under /etc/systemd/system.
# If this file is ever renamed, `deploy/systemd/install-backup.sh` is the honest name.
#
# ============================================================================
# WHAT IT INSTALLS, AND WHY EACH PIECE EXISTS
# ============================================================================
# CD prerequisite 2 (docs/deployment/11-ci-cd.md, "The prerequisites, in order",
# item 2). Today there is no scheduled backup of anything of ours:
#
#   * 00-host-inventory.md row 33 — "Nothing is scheduled. Every dump that exists
#     was taken by hand." Nine `*.sql.gz` in /var/backups/hbd, every one written by
#     a release script a human ran.
#   * 00-host-inventory.md row 34 — the media archive: "Nothing. No timer, no cron,
#     no copy off-box."
#   * 05-operations.md:1156 — `aizu-backup.timer` IS in `systemctl list-timers`, is
#     enabled, fires nightly at 03:30, and backs up a DIFFERENT tenant's SQLite file.
#     An operator who reads `list-timers`, sees a nightly backup and stops reading
#     has drawn the wrong conclusion. This installer's timer is deliberately named
#     `bayram-backup` so the two are distinguishable at a glance.
#
# Four artefacts land, each at its own path with its own mode:
#
#   /opt/bayram/sbin/bayram-backup             0755 root:root   the script
#   /etc/systemd/system/bayram-backup.service  0644 root:root   the oneshot
#   /etc/systemd/system/bayram-backup.timer    0644 root:root   the schedule
#   /etc/systemd/system/bayram-backup-failed.service            the noise
#
# /opt/bayram/sbin is the contract's directory for the release script
# (/opt/bayram/sbin/bayram-release), chosen over /usr/local/sbin because on some
# Debian installs /usr/local is group-writable by `staff`. The same argument applies
# to this script and it lands beside it.
#
# ============================================================================
# THE DATABASE IS NAMED `hbd`, NOT `bayram`
# ============================================================================
# The hbd -> bayram rename moved the package, the units, /opt, /etc and the env
# prefix. It did NOT rename the database. All three deploy scripts still run
# `sudo -u postgres pg_dump hbd` (deploy-support.sh:89, deploy-d17.sh, and
# cutover-to-bayram.sh:73) and so does this one. `pg_dump bayram` would fail with
# "database bayram does not exist" — which, in a nightly unit nobody watches, is a
# failure that only the OnFailure unit below would ever surface.
#
# ============================================================================
# WHAT IS *NOT* BACKED UP BY THIS, STATED BEFORE YOU TRUST IT
# ============================================================================
# 05-operations.md, "What must be in a backup for it to be sufficient", names four
# things. This timer covers ONE of them.
#
#   1. Postgres in full .............. COVERED by this timer.
#   2. <data root>/archive ........... NOT COVERED. /var/lib/hbd/var/archive holds
#      delivered songs AND every customer avatar (storage.py:73-84,
#      user_profiles.py:199-200). Size unknown — 00-host-inventory.md row 30 is the
#      one cell in that table with no route to an answer at all.
#   3. Redis ......................... NOT COVERED. It is not a cache here: every
#      in-progress wizard draft lives there under a 14-day TTL, and since D17 it
#      decides whether a paid song gets rendered.
#   4. BAYRAM_ADMIN_AUDIT_HMAC_KEY ... NOT COVERED, and it is not in any database
#      dump. It exists in /etc/bayram/bayram-admin.env and nowhere else, so a host
#      rebuild makes the entire audit chain unverifiable. 05-operations.md is also
#      explicit that it must NOT be stored with the dump: a backup holding both
#      admin_audit_log and the key that authenticates it is a backup an insider can
#      rewrite end to end.
#
# Covering 2, 3 and 4 is a separate change with separate arguments. This file does
# one thing and says loudly that it does one thing.
#
# ============================================================================
# CONVENTIONS COME FROM cutover-to-bayram.sh, NOT FROM deploy/systemd/*.service
# ============================================================================
# deploy/README.md:31-42 — the four .service files in this directory are "a proposal,
# not a record", authored with no host access, and they say User=bayram, /srv/bayram
# and /var/lib/bayram, none of which exist. The units that are actually running were
# written by cutover-to-bayram.sh:142-203, and the hardening block below is that
# block's `common()` (lines 142-163) adapted for a root-owned oneshot.
#
# ============================================================================
# EXIT CODES — the release contract's, so the two scripts read the same
# ============================================================================
#   0 success
#   1 usage/config error
#   2 preflight refused — NOTHING WAS CHANGED
#   3 failed mid-install, the system may be part-changed — READ THE OUTPUT
#   4 verify failed
#
# Rerunnable. A second run rewrites identical files, reports "unchanged", and takes
# a fresh dump (same as deploy-support.sh:7 — "a rerun re-dumps the database").
# Set SKIP_FIRST_RUN=1 to install without taking one.

set -euo pipefail

SBIN=/opt/bayram/sbin
SCRIPT="$SBIN/bayram-backup"
UNITDIR=/etc/systemd/system
DUMP_DIR=/var/backups/bayram
STATE_DIR=/var/lib/bayram-backup
SENTINEL="$STATE_DIR/status.json"
KEEP=14

die()  { echo "FATAL: $*" >&2; exit "${2:-3}"; }
note() { echo "  $*"; }

# ---------------------------------------------------------------- preflight ---
echo "=== 0/6  preflight ==="

[ "${EUID:-$(id -u)}" -eq 0 ] || die "run me as root:  sudo bash $0" 1

# The misfiling guard. If this file was copied into the unit directory instead of
# run, say so in the one place somebody will be looking.
case "$(readlink -f "$0")" in
  /etc/systemd/system/*|/lib/systemd/system/*|/usr/lib/systemd/system/*)
    die "this is a bash INSTALLER that was copied into a systemd unit directory.
       Delete $(readlink -f "$0"), copy it to /tmp instead, and run it." 1 ;;
esac

for b in systemctl systemd-analyze sudo pg_dump gzip sha256sum flock install df logger; do
  command -v "$b" >/dev/null 2>&1 || die "missing required binary: $b" 2
done

# pg_dump is reached as the postgres role, which is the one route this host grants
# without a password (00-host-inventory.md row 44). Prove the route works BEFORE
# installing a timer that depends on it — a timer that fires nightly into a
# permission error is worse than no timer, because `list-timers` shows it as healthy.
sudo -n -u postgres pg_dump --version >/dev/null 2>&1 \
  || die "'sudo -u postgres pg_dump' does not work from this shell.
       That is the one granted route to the database on this host (row 44).
       Check: sudo -n -l | grep pg_dump" 2

id hbd >/dev/null 2>&1 || note "WARNING: service account 'hbd' not found — the sentinel's
       admin-side reader (see below) would have nobody to read it."

test -d /var/backups || die "/var/backups does not exist; this is not the expected host" 2
note "preflight OK"

# ------------------------------------------------------- directories + modes ---
echo "=== 1/6  directories ==="
# NOT ConditionPathIsDirectory= on the unit. A failed condition SKIPS the unit and
# records the job as SUCCESSFUL, so `systemctl status` would show a green nightly
# backup that has never dumped a byte. Create the directory here and let the script
# fail loudly at run time if it has gone.
#
# /opt/bayram is NOT chmod'd or chown'd here — it already exists and holds the venv
# and the migrations tree, and an installer for a backup timer has no business
# restating their modes. Created only if genuinely absent.
[ -d /opt/bayram ] || install -d -m 0755 -o root -g root /opt/bayram
install -d -m 0755 -o root -g root "$SBIN"
#
# $DUMP_DIR IS TIGHTENED TO 0700 IF IT ALREADY EXISTS. The deploy scripts create it
# with a bare `mkdir -p` (deploy-support.sh:88), so it inherits root's umask and is
# very likely 0755 today — which is why the nine dumps in the OLD /var/backups/hbd
# are world-readable (00-host-inventory.md row 33) and were readable enough to
# answer rows 14 and 15 with no privilege at all. That was a convenient accident and
# it is not one worth keeping for a directory that will now fill up nightly with
# every customer's rows. 0700 is the release contract's mode; /var/backups/hbd is
# untouched, so the citations that depend on it still resolve.
install -d -m 0700 -o root -g root "$DUMP_DIR"
# 0755, unlike the dumps, ON PURPOSE. The sentinel carries a timestamp, a byte
# count and a hash — no rows, no secrets — and it is useless if only root can read
# it. The dumps themselves stay 0700/0600. Note that the nine existing dumps in
# /var/backups/hbd are 0644 root:root and world-readable (row 33), so this is
# strictly less exposure than what the box already has.
install -d -m 0755 -o root -g root "$STATE_DIR"
note "$DUMP_DIR 0700 root:root · $STATE_DIR 0755 root:root"

# ------------------------------------------------------------- the script -----
echo "=== 2/6  $SCRIPT ==="
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

cat > "$TMP/bayram-backup" <<'BACKUP_SCRIPT'
#!/usr/bin/env bash
#
# bayram-backup — the nightly database dump. Installed by deploy/systemd/bayram-backup.timer
# (which is a bash installer despite its name). Do not edit in place: edit the installer
# and rerun it, or the next install silently reverts you.
#
# VERBS
#   run           take a dump, verify it, prune, write the success sentinel.  (the timer)
#   fail-notice   write the failure sentinel and make noise.                  (OnFailure)
#   check         exit 4 if the last backup is missing, failed or stale.      (for humans
#                 and for whatever eventually reads it — see SENTINEL below)
#   status        print the sentinel.
#
# EXIT CODES: 0 ok · 1 usage · 2 preflight refused, nothing written · 3 failed mid-run
#             4 check failed
set -euo pipefail

DB=hbd
DUMP_DIR=/var/backups/bayram
STATE_DIR=/var/lib/bayram-backup
SENTINEL=/var/lib/bayram-backup/status.json
LOCK_DIR=/run/bayram-backup
KEEP=14
STALE_HOURS=48
MIN_FREE_KB=1048576
PREFIX=bayram-daily
OFFSITE_HOOK=/etc/bayram/backup-offsite.hook

# ---------------------------------------------------------------------------
# RETENTION: KEEP=14 DAILIES. THE ARITHMETIC.
#
#   * The largest dump this host has ever written is 23 KB
#     (/var/backups/hbd/pre-wipe-20260910-092203, 05-operations.md:1148).
#     14 x 23 KB = 322 KB.
#   * The root filesystem is 38 GB, 7.2 GB used, ~30 GB free
#     (00-host-inventory.md row 1). There is ONE filesystem on this box.
#   * 14 dailies exhaust that free space only when a single dump exceeds
#     30 GB / 14 = ~2.1 GB compressed. The database is 28 mapped tables of text
#     and money rows; the media archive is NOT in it. Three orders of magnitude
#     of growth still costs ~1% of the disk.
#   * 14 matches the only backup precedent on the machine: aizu-backup keeps 14
#     days (05-operations.md:1158). An operator comparing the two sees one number.
#
# WHAT 14 COSTS YOU: corruption discovered on day 15 is not recoverable from here.
# If that is not acceptable, the fix is off-box copies with a longer tail, not a
# bigger N on the same disk — see OFF-BOX below.
#
# MIN_FREE_KB is 1 GiB and it is a REFUSAL, not a warning. A dump written into a
# full disk is a truncated gzip, and `test -s` passes on a truncated gzip. Refusing
# early exits 2 and lights the OnFailure unit; writing a torn dump would exit 0.
# ---------------------------------------------------------------------------

STAMP=$(date -u +%Y%m%d-%H%M%S)
NOW_RFC3339=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DUMP="$DUMP_DIR/$PREFIX-$STAMP.sql.gz"

die() { echo "FATAL: $*" >&2; exit "${2:-3}"; }

write_sentinel() {  # $1 result, $2 file, $3 bytes, $4 sha256, $5 detail
  mkdir -p "$STATE_DIR"
  local tmp="$STATE_DIR/.status.json.$$"
  printf '{\n' > "$tmp"
  printf '  "result": "%s",\n'      "$1" >> "$tmp"
  printf '  "finished_at": "%s",\n' "$NOW_RFC3339" >> "$tmp"
  printf '  "database": "%s",\n'    "$DB" >> "$tmp"
  printf '  "file": "%s",\n'        "$2" >> "$tmp"
  printf '  "bytes": %s,\n'         "${3:-0}" >> "$tmp"
  printf '  "sha256": "%s",\n'      "${4:-}" >> "$tmp"
  printf '  "keep": %s,\n'          "$KEEP" >> "$tmp"
  printf '  "stale_after_hours": %s,\n' "$STALE_HOURS" >> "$tmp"
  printf '  "offsite": "%s",\n'     "$OFFSITE_STATE" >> "$tmp"
  printf '  "detail": "%s"\n'       "${5:-}" >> "$tmp"
  printf '}\n' >> "$tmp"
  chmod 0644 "$tmp"
  mv -f "$tmp" "$SENTINEL"
}

# ---------------------------------------------------------------------------
# THE SENTINEL, AND WHO READS IT — READ THIS BEFORE BELIEVING IT PROTECTS YOU.
#
# $SENTINEL is rewritten on every success AND on every failure. Its value is that
# a STOPPED TIMER looks identical to a working one in `systemctl status`, and a
# timer that was never re-enabled after a reboot produces no failure at all —
# nothing to alert on, because nothing ran. Only staleness catches that.
#
# NOTHING READS THIS FILE TODAY. Two exact places a read belongs, neither of which
# exists yet, so that the next person adds it rather than assuming it is there:
#
#   1. src/bayram/admin/routers/health.py:127, inside readyz()'s authorised branch
#      (the `return {...}` at lines 132-139): add a "backup" key alongside
#      "database"/"redis", reading $SENTINEL and comparing finished_at to now.
#      The admin unit runs as `hbd` under ProtectSystem=strict, which is read-only,
#      not invisible, so it can open a 0644 file under /var/lib — hence the mode.
#      11-ci-cd.md's third CD prerequisite is precisely "give /healthz something to
#      say"; this is one true thing it could say.
#   2. /opt/bayram/sbin/bayram-release's preflight (beat 0), which does not exist
#      yet — it is CD prerequisite 4. One line: `/opt/bayram/sbin/bayram-backup check`
#      and refuse the deploy with exit 2 if it fails. Deploying onto a host whose
#      last good backup is eight days old is a decision, and it should be one
#      somebody makes on purpose.
# ---------------------------------------------------------------------------

OFFSITE_STATE=not-configured

case "${1:-}" in

run)
  mkdir -p "$LOCK_DIR" 2>/dev/null || true
  exec 9>"$LOCK_DIR/lock"
  flock -n 9 || die "another bayram-backup is already running" 2

  test -d "$DUMP_DIR" || die "$DUMP_DIR is gone. Recreate it (0700 root:root) and rerun.
       This is deliberately a hard failure and not a ConditionPathIsDirectory=,
       because a failed condition would record SUCCESS." 2

  FREE_KB=$(df -Pk "$DUMP_DIR" | awk 'NR==2 {print $4}')
  [ "${FREE_KB:-0}" -ge "$MIN_FREE_KB" ] \
    || die "only ${FREE_KB} KB free on $DUMP_DIR, need $MIN_FREE_KB. Refusing:
       a dump into a full disk is a truncated gzip and test -s does not catch it." 2

  # The dump. Verbatim from the three deploy scripts (deploy-support.sh:89) --
  # `sudo -u postgres pg_dump hbd`, no --no-acl either way. NOT a considered flag
  # set: 05-operations.md says so plainly. It is kept identical on purpose, so a
  # nightly dump and a pre-deploy dump restore the same way. Changing the flags is
  # a change to restore semantics and belongs in its own commit with its own test.
  umask 077
  sudo -u postgres pg_dump "$DB" | gzip > "$DUMP" \
    || die "pg_dump failed. Dump left at $DUMP for inspection, then delete it." 3

  # THE GUARD THAT MUST SURVIVE VERBATIM (deploy-support.sh:91-93):
  # "A pg_dump that failed on permissions still leaves a valid, empty gzip.
  #  A backup you did not check is a backup you do not have."
  test -s "$DUMP" || { rm -f "$DUMP"; die "backup is empty; refusing to record success" 3; }

  # And one guard the deploy scripts do NOT have, for the failure `test -s` misses:
  # a dump cut off mid-stream by a full disk or a killed pg_dump is non-empty and
  # is not a valid gzip. `gzip -t` walks the whole stream.
  gzip -t "$DUMP" || { rm -f "$DUMP"; die "backup is a truncated gzip; deleted" 3; }

  BYTES=$(stat -c %s "$DUMP")
  SHA=$(sha256sum "$DUMP" | cut -d' ' -f1)
  chmod 0600 "$DUMP"

  # OFF-BOX. See the installer's OFF-BOX block: no destination is invented here.
  # If the owner installs a root-owned 0700 hook at $OFFSITE_HOOK it runs now, and
  # ITS FAILURE FAILS THE WHOLE BACKUP -- a copy that quietly stopped copying is
  # the same lie as a timer that quietly stopped firing.
  if [ -x "$OFFSITE_HOOK" ]; then
    if [ "$(stat -c '%U %a' "$OFFSITE_HOOK")" = "root 700" ]; then
      OFFSITE_STATE=running
      "$OFFSITE_HOOK" "$DUMP" || die "off-box hook failed for $DUMP" 3
      OFFSITE_STATE=ok
    else
      die "$OFFSITE_HOOK must be root-owned mode 0700; it is $(stat -c '%U %a' "$OFFSITE_HOOK")" 2
    fi
  else
    echo "OFF-BOX: not configured. This dump is on the same disk as the database it
      came from, so it protects against a bad migration and a dropped table, and
      against nothing that loses the disk. See the installer's OFF-BOX block."
  fi

  # Prune. Scoped to OUR OWN filename prefix and nothing else: /var/backups/bayram
  # also receives pre-<release>-<stamp>.sql.gz from the deploy scripts, and those
  # are release evidence, not dailies. A prune that ate them would delete the only
  # dump taken immediately before the change somebody is trying to undo.
  mapfile -t OLD < <(ls -1t "$DUMP_DIR/$PREFIX"-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)))
  for f in "${OLD[@]:-}"; do
    [ -n "$f" ] || continue
    rm -f -- "$f" && echo "pruned $(basename "$f")"
  done
  KEPT=$(ls -1 "$DUMP_DIR/$PREFIX"-*.sql.gz 2>/dev/null | wc -l)

  write_sentinel ok "$DUMP" "$BYTES" "$SHA" "kept $KEPT of max $KEEP"
  echo "backup ok: $DUMP ($BYTES bytes, sha256 ${SHA:0:12}...), $KEPT kept"
  ;;

fail-notice)
  # Reached only via OnFailure=. Three channels, because this host has no mail, no
  # pager and no monitoring of any kind (11-ci-cd.md: "nothing to notice"):
  #   1. the journal at emerg. journald's defaults are unmodified on this box
  #      (00-host-inventory.md row 32 - no Storage, no MaxRetentionSec, no
  #      SystemMaxUse set), so ForwardToWall=yes and MaxLevelWall=emerg apply and
  #      an emerg record is written to every logged-in terminal by journald itself.
  #   2. the failure sentinel, so a later reader sees "failed" rather than "stale"
  #      and knows the difference between a backup that broke and one that never ran.
  #   3. stderr into the journal under this unit, for `journalctl -u bayram-backup`.
  RESULT=$(systemctl show bayram-backup.service -p Result --value 2>/dev/null || echo unknown)
  CODE=$(systemctl show bayram-backup.service -p ExecMainStatus --value 2>/dev/null || echo '?')
  MSG="bayram-backup FAILED: result=$RESULT exit=$CODE. The database has NO fresh backup. journalctl -u bayram-backup.service -n 50"
  logger -p daemon.emerg -t bayram-backup -- "$MSG" || true
  echo "$MSG" >&2
  write_sentinel failed "" 0 "" "result=$RESULT exit=$CODE"
  ;;

check)
  # Exit 4 on missing, failed or stale. Intended for the two readers named above.
  [ -f "$SENTINEL" ] || { echo "NO BACKUP SENTINEL at $SENTINEL"; exit 4; }
  grep -q '"result": "ok"' "$SENTINEL" || { echo "last backup did NOT succeed:"; cat "$SENTINEL"; exit 4; }
  AGE=$(( ($(date +%s) - $(stat -c %Y "$SENTINEL")) / 3600 ))
  [ "$AGE" -le "$STALE_HOURS" ] \
    || { echo "last backup is ${AGE}h old (stale after ${STALE_HOURS}h). Is bayram-backup.timer enabled?"; exit 4; }
  echo "backup ok, ${AGE}h old"
  ;;

status)
  cat "$SENTINEL" 2>/dev/null || { echo "no sentinel at $SENTINEL"; exit 4; }
  ;;

*)
  echo "usage: bayram-backup {run|fail-notice|check|status}" >&2
  exit 1 ;;
esac
BACKUP_SCRIPT

# Drift assertion: the installer and the generated script both hardcode these paths
# (the heredoc is quoted so the installer's variables are NOT interpolated, which is
# what keeps $-signs inside the script intact). If they ever disagree, an operator
# reading the installer would be reading the wrong paths.
grep -q "^DUMP_DIR=$DUMP_DIR$"  "$TMP/bayram-backup" || die "generated script disagrees with installer on DUMP_DIR" 2
grep -q "^STATE_DIR=$STATE_DIR$" "$TMP/bayram-backup" || die "generated script disagrees with installer on STATE_DIR" 2
grep -q "^KEEP=$KEEP$"          "$TMP/bayram-backup" || die "generated script disagrees with installer on KEEP" 2
bash -n "$TMP/bayram-backup" || die "generated script is not valid bash" 2

CHANGED=0
if ! cmp -s "$TMP/bayram-backup" "$SCRIPT" 2>/dev/null; then
  install -m 0755 -o root -g root "$TMP/bayram-backup" "$SCRIPT"; CHANGED=1; note "written"
else
  note "unchanged"
fi

# --------------------------------------------------------------- the units ---
echo "=== 3/6  unit files ==="
# NO INLINE COMMENTS ANYWHERE BELOW. In a systemd unit '#' starts a comment only at
# the beginning of a line; a trailing "Persistent=true  # survives a reboot" makes
# the value literally "true  # survives a reboot" and the directive is then rejected
# or, worse, silently misparsed. Every explanation here is a full line of its own.

cat > "$TMP/bayram-backup.service" <<UNIT
[Unit]
Description=Bayram nightly database backup (pg_dump of the 'hbd' database)
Documentation=file://$SCRIPT
After=postgresql.service
Wants=postgresql.service
OnFailure=bayram-backup-failed.service

[Service]
Type=oneshot
ExecStart=$SCRIPT run
TimeoutStartSec=3600
Nice=10
IOSchedulingClass=idle
SyslogIdentifier=bayram-backup
StandardOutput=journal
StandardError=journal

RuntimeDirectory=bayram-backup
StateDirectory=bayram-backup
StateDirectoryMode=0755

ProtectSystem=strict
ReadWritePaths=$DUMP_DIR
ReadWritePaths=-/run/sudo
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
RestrictSUIDSGID=true
RestrictRealtime=true
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=yes
RestrictAddressFamilies=AF_UNIX
CapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_AUDIT_WRITE CAP_DAC_OVERRIDE
UMask=0077
UNIT

cat > "$TMP/bayram-backup.timer" <<UNIT
[Unit]
Description=Daily Bayram database backup
Documentation=file://$SCRIPT

[Timer]
OnCalendar=*-*-* 02:30:00
RandomizedDelaySec=900
FixedRandomDelay=true
AccuracySec=1m
Persistent=true
Unit=bayram-backup.service

[Install]
WantedBy=timers.target
UNIT

cat > "$TMP/bayram-backup-failed.service" <<UNIT
[Unit]
Description=Bayram backup FAILED - write the failure sentinel and make noise
Documentation=file://$SCRIPT

[Service]
Type=oneshot
ExecStart=$SCRIPT fail-notice
SyslogIdentifier=bayram-backup-failed
StandardOutput=journal
StandardError=journal
StateDirectory=bayram-backup
StateDirectoryMode=0755
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
UMask=0022
UNIT

for u in bayram-backup.service bayram-backup.timer bayram-backup-failed.service; do
  if ! cmp -s "$TMP/$u" "$UNITDIR/$u" 2>/dev/null; then
    install -m 0644 -o root -g root "$TMP/$u" "$UNITDIR/$u"; CHANGED=1; note "$u written"
  else
    note "$u unchanged"
  fi
done

# ------------------------------------------------------- reload and verify ----
echo "=== 4/6  daemon-reload and systemd-analyze verify ==="
systemctl daemon-reload
for u in bayram-backup.service bayram-backup.timer bayram-backup-failed.service; do
  systemd-analyze verify "$UNITDIR/$u" || die "$u does not verify" 4
  note "$u verifies"
done

# ------------------------------------------------------------ enable + fire ---
echo "=== 5/6  enable the timer ==="
systemctl enable --now bayram-backup.timer
systemctl is-enabled bayram-backup.timer >/dev/null || die "timer did not enable" 3
systemctl is-active  bayram-backup.timer >/dev/null || die "timer is not active" 3
systemctl list-timers --all bayram-backup.timer --no-pager

echo "=== 6/6  take one backup NOW and prove the whole path works ==="
# This is the step that converts assumptions into facts, and it is why the unit can
# carry hardening this specific without being a gamble. A first run here exercises,
# in one go: sudo-to-postgres from inside the sandbox, pg_dump against the database
# named `hbd`, the gzip pipe, the write into $DUMP_DIR under ProtectSystem=strict,
# RestrictAddressFamilies=AF_UNIX against however Postgres is actually reached, the
# CapabilityBoundingSet against what sudo's PAM stack wants, and the sentinel write.
# If any of those is wrong on this host, it is wrong HERE, in front of an operator,
# instead of at 02:30 in front of nobody.
#
# NoNewPrivileges is deliberately NOT set on the service. It is the one hardening
# directive from cutover-to-bayram.sh:150's common() block that is omitted, and the
# reason is mechanical: the unit runs as root and calls setuid `sudo`. It buys
# little on a root unit and can cost the entire backup.
if [ "${SKIP_FIRST_RUN:-0}" = "1" ]; then
  note "SKIP_FIRST_RUN=1 — skipped. Run 'systemctl start bayram-backup.service' yourself."
else
  systemctl start bayram-backup.service || true
  RESULT=$(systemctl show bayram-backup.service -p Result --value)
  if [ "$RESULT" != "success" ]; then
    echo "--- journal ---" >&2
    journalctl -u bayram-backup.service -n 40 --no-pager >&2 || true
    die "the first backup FAILED (Result=$RESULT). The timer is installed and enabled,
       but it will fail the same way at 02:30. Fix this before you walk away." 4
  fi
  "$SCRIPT" check || die "the backup reported success but the sentinel does not agree" 4
  "$SCRIPT" status
fi

echo
if [ "$CHANGED" = "1" ]; then echo "DONE — files changed."; else echo "DONE — nothing changed (idempotent rerun)."; fi
cat <<'CLOSING'

WHAT IS NOW TRUE
  Nightly at 02:30 local (+05) with up to 15 minutes of random delay, Persistent=true
  so a box that was powered off at 02:30 runs it at the next boot instead of skipping
  the day. 03:30 is deliberately avoided: that is aizu-backup.timer's slot, and this
  box has 2 vCPU and 1.9 GiB of RAM (00-host-inventory.md row 1) — two dumps in one
  window is a self-inflicted load spike.

  14 dailies in /var/backups/bayram, pruned after each successful run, scoped to the
  bayram-daily-* prefix so the deploy scripts' pre-*.sql.gz evidence is never touched.

HOW YOU FIND OUT IT BROKE
  On a failed run: OnFailure fires bayram-backup-failed.service, which logs at
  daemon.emerg (journald's unmodified defaults wall an emerg to every logged-in
  terminal) and rewrites the sentinel with "result": "failed".

  On a timer that was stopped, masked or never re-enabled: NOTHING FIRES AND THERE IS
  NO FAILURE TO ALERT ON. That case is caught only by staleness, and only if something
  reads it:
      /opt/bayram/sbin/bayram-backup check      # exit 4 if missing, failed or >48h old
  NOTHING READS IT TODAY. Two exact insertion points are named in the comment block at
  the top of /opt/bayram/sbin/bayram-backup — health.py:127's readyz(), and
  bayram-release's preflight. Until one of them exists, "failure is visible" means
  "visible to a person who looks", and the person has to be told to look:
      sudo systemctl list-timers bayram-backup.timer
      sudo /opt/bayram/sbin/bayram-backup check

OFF-BOX: A DECISION THE OWNER HAS TO MAKE. THIS INSTALLER DOES NOT MAKE IT.
  Everything above puts the dump on /dev/mapper/ubuntu--vg-ubuntu--lv — the SAME AND
  ONLY filesystem the database is on. That is real protection against a bad migration,
  a dropped table and a mistaken DELETE. It is ZERO protection against losing the disk,
  the volume or the VM, which is the scenario people mean when they say "backup".

  No destination and no credential is invented here. The three honest options:

  A. PULL from a machine that already has access. The operator's workstation already
     reaches the host as `ssh aizu` (aizu-deployment-host). A cron THERE running
     `rsync` or `scp` needs no new outbound credential on the payment host, which is
     the property that makes it the safest of the three. What it does need: the dumps
     are 0700 root:root and `developer` cannot read them, so it needs either a narrow
     sudoers verb (`/usr/bin/cat /var/backups/bayram/bayram-daily-*.sql.gz`) or a
     group-readable mode. Both are decisions; pick one deliberately.
  B. PUSH to object storage (S3/R2/B2) with rclone or awscli from the hook below.
     Costs pennies and is the only option that survives the provider account. It puts
     a long-lived write credential on the host that holds the cashbox key, so scope it
     to one write-only bucket with no delete and no list.
  C. Provider-level volume snapshots. Nobody has recorded who the provider is or
     whether snapshots are available, so this cannot be evaluated from here.

  When the decision is made, install the destination as a root-owned 0700 executable
  at /etc/bayram/backup-offsite.hook taking the dump path as $1. bayram-backup runs it
  after every verified dump, FAILS THE WHOLE BACKUP if it exits non-zero, and records
  "offsite": "ok" in the sentinel. Until then every run prints OFF-BOX: not configured
  and the sentinel says "not-configured", which is the honest state rather than a
  silent absence.

  And the thing off-box copies still will not fix: BAYRAM_ADMIN_AUDIT_HMAC_KEY is in
  no database dump at all, so none of A/B/C protects the audit chain. 05-operations.md
  is also explicit that the key must NOT travel with the dump.

TO REMOVE
  sudo systemctl disable --now bayram-backup.timer
  sudo rm /etc/systemd/system/bayram-backup{.timer,.service,-failed.service}
  sudo rm /opt/bayram/sbin/bayram-backup
  sudo systemctl daemon-reload
  (The dumps in /var/backups/bayram are left alone on purpose.)
CLOSING
