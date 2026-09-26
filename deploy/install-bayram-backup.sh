#!/usr/bin/env bash
#
# ============================================================================
# THIS FILE IS A BASH INSTALLER. IT IS NOT A SYSTEMD UNIT.
# ============================================================================
# The filename it was asked to carry — `bayram-backup.timer` — is wrong for what
# is inside it, and it is wrong in exactly the way pass 1 was wrong: it invites
# `scp <this file> aizu:/etc/systemd/system/`, which would put a shell script where
# systemd expects a unit. Do not do that. `systemd-analyze verify` on the result
# prints "Assignment outside of section" for every line of this script and the timer
# never fires — a silent no-op, which is the failure mode this whole file exists to
# prevent. The correct install is:
#
#     scp deploy/install-bayram-backup.sh aizu:/tmp/install-bayram-backup.sh
#     ssh -t aizu 'sudo bash /tmp/install-bayram-backup.sh'
#
# (The earlier copy of these two lines named `deploy/systemd/bayram-backup.timer` as the
# source. That path does not exist — deploy/systemd/ holds the four .service proposals and
# nothing else — so the scp failed and the install never happened. The file now carries the
# name it always should have had, and these lines carry it too.)
#
# RUN IT IMMEDIATELY AFTER THE scp, NOT LATER. /tmp is world-writable and the staged copy
# lands owned by `developer`, so between the copy and the run there is a window in which
# anything that can write as `developer` chooses what root executes. A copy of this file has
# in fact been sitting at /tmp/install-bayram-backup.sh since 2026-09-17 unrun; re-scp it
# and run it in the same breath rather than trusting the one that is already there.
#
# The guard at line ~120 refuses to run if it finds itself under /etc/systemd/system.
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
#   * 05-operations.md:1161 — `aizu-backup.timer` IS in `systemctl list-timers`, is
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
# THE OFF-BOX COPY IS PLUGGABLE, AND IT IS INERT UNTIL SOMEBODY CONFIGURES IT
# ============================================================================
# Earlier revisions of this installer took a root-owned 0700 executable at
# /etc/bayram/backup-offsite.hook and ran it after each verified dump. That hook was a
# FILE, which meant the destination, the credential and the transport all had to be
# written by hand before anything could be copied anywhere, and nothing was.
#
# The hook is now ENV-CONFIGURED and destination-agnostic. One file —
#
#     /etc/bayram/backup-offbox.env      0600 root:root
#
# — selects a transport with a single BAYRAM_BACKUP_OFFBOX_MODE:
#
#     (empty)  no off-box copy. Prints one honest line, exits 0, does NOT fail the unit.
#     s3       any S3-compatible endpoint, via rclone or awscli. Cloudflare R2 and
#              Backblaze B2 are the same mode with a different endpoint URL — no provider
#              is named anywhere in the generated script.
#     rsync    rsync over ssh to a second host.
#     command  an operator's own executable, which is the old hook contract preserved:
#              it is still called with the dump path as $1 (the destination is $2 now).
#              An existing /etc/bayram/backup-offsite.hook is picked up automatically.
#
# EMPTY IS THE SHIPPED STATE AND IT IS HEALTHY. The owner has not chosen a destination
# (see the OFF-BOX block at the end of this file for the three options and what each
# costs). An install with no destination must therefore look exactly as green as it is:
# one log line, `"offbox": "not-configured"` in the sentinel, exit 0, no OnFailure. The
# opposite — a red signal for a state nobody has decided to leave — teaches whoever reads
# /healthz next to ignore it, which is the failure this timer exists to avoid.
#
# WHY /etc/bayram/backup-offbox.env AND NOT /etc/bayram/bayram.env: the three env files
# already in /etc/bayram are 0640 root:hbd — readable by the account that serves customers
# and terminates payment callbacks. A write credential for the off-box copy must not be
# reachable from there. The new file is 0600 root:root and the script REFUSES to read it
# at any other owner or mode.
#
# WHY THE UNIT GAINS A DROP-IN: the service below sets RestrictAddressFamilies=AF_UNIX, so
# as installed it cannot open a network socket at all. That stays exactly as it is while no
# destination is configured. When one IS configured this installer writes
# /etc/systemd/system/bayram-backup.service.d/10-offbox.conf, which widens the socket
# families and nothing else. The main unit file is byte-identical either way, so the
# `cmp -s` idempotency below still reports "unchanged" on a rerun.
#
# ============================================================================
# CONVENTIONS COME FROM cutover-to-bayram.sh, NOT FROM deploy/systemd/*.service
# ============================================================================
# deploy/README.md, "They are a proposal, not a record" — the four .service files in
# this directory were authored with no host access, and they say User=bayram,
# /srv/bayram and /var/lib/bayram, none of which exist. The units that are running were
# written by cutover-to-bayram.sh:142-203, and the hardening block below is that
# block's `common()` (lines 142-163) adapted for a root-owned oneshot.
#
# ============================================================================
# EXIT CODES — the release contract's, so the two scripts read the same
# ============================================================================
#   0 success
#   1 usage/config error
#   2 preflight refused — NOTHING WAS CHANGED (with one harmless exception: an off-box
#     config refused in step 1b may have written /etc/bayram/backup-offbox.env.example
#     first. It is documentation, holds no secret, and no unit has been touched.)
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

# The off-box contract. Every one of these is also hardcoded in the generated script
# below and the two are cross-asserted at the drift check in step 2 — if they ever
# disagree, an operator reading this installer would be reading the wrong paths.
ETCDIR=/etc/bayram
OFFBOX_ENV="$ETCDIR/backup-offbox.env"
OFFBOX_EXAMPLE="$ETCDIR/backup-offbox.env.example"
OFFBOX_DIR=/var/lib/bayram-backup/offbox
OFFBOX_TIMEOUT=900
OFFBOX_REQUIRED=1
DROPIN_DIR="$UNITDIR/bayram-backup.service.d"
DROPIN="$DROPIN_DIR/10-offbox.conf"

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

# `timeout` is on this list because of the off-box push. That push runs while this script
# holds the flock, inside a unit whose TimeoutStartSec is 3600: an ssh or https transfer
# that hangs would otherwise sit there for an hour with no output and eat the NEXT night's
# run as well, since the second run cannot take the lock. Every off-box command is wrapped
# in `timeout` for that reason, so the binary is a hard requirement, not a nicety.
for b in systemctl systemd-analyze sudo pg_dump gzip sha256sum flock install df logger timeout stat; do
  command -v "$b" >/dev/null 2>&1 || die "missing required binary: $b" 2
done

# pg_dump is reached as the postgres role, which is the one route this host grants
# without a password (00-host-inventory.md row 44). Prove the route works BEFORE
# installing a timer that depends on it — a timer that fires nightly into a
# permission error is worse than no timer, because `list-timers` shows it as healthy.
#
# THE PROBE IS BROADER THAN THE GRANT, AND IT DOES NOT DEPEND ON ONE. The host's sudoers
# grants exactly one postgres vector, `(postgres) NOPASSWD: /usr/bin/pg_dump hbd`, and the
# argument vector below — `pg_dump --version` — does not match it. It does not need to:
# line 188 has already refused to run as anyone but root, and root reaches `sudo -u postgres`
# through the stock `root ALL=(ALL:ALL) ALL` rule that ships in /etc/sudoers, authenticating
# nothing. The same is true of the nightly unit, which also runs as root.
#
# SO NOTHING HERE IS HOLDING UP deploy/prune-stale-sudo-grants.sh, and an earlier copy of
# this comment that said otherwise was wrong. That script removes `developer`'s stale and
# blanket grants; not one of them is what makes this probe pass, and not one of them is what
# makes the 02:30 dump work. Removing `(postgres) NOPASSWD: /usr/bin/pg_dump hbd` along with
# them would not break this line either — run the prune. The probe is kept broad on purpose:
# it proves the binary and the root->postgres transition without touching the database.
sudo -n -u postgres pg_dump --version >/dev/null 2>&1 \
  || die "'sudo -u postgres pg_dump' does not work from this shell, even as root.
       That is the route this script and the nightly unit both take to the database.
       It does NOT depend on a sudoers grant for 'developer', so do not go looking for
       one. Check, in this order:
           id -u                                    # must be 0 (line 188 already checked)
           sudo -n -l -U root                       # the stock root rule must still be there
           getent passwd postgres                   # the role's account must exist
           command -v pg_dump" 2

id hbd >/dev/null 2>&1 || note "WARNING: service account 'hbd' not found — the sentinel's
       admin-side reader (see below) would have nobody to read it."

test -d /var/backups || die "/var/backups does not exist; this is not the expected host" 2
note "preflight OK"

# Staged here rather than in step 2, because step 1b already needs somewhere to build a
# file before `install` puts it in place with the right owner and mode in one atomic move.
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
CHANGED=0

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
# 0700 root:root, and it lives UNDER $STATE_DIR on purpose: the unit already declares
# StateDirectory=bayram-backup, so this subdirectory is writable from inside
# ProtectSystem=strict without a single extra ReadWritePaths= line. It is where an off-box
# client keeps the things such clients need and nobody thinks about until the first run
# fails — an rclone config, a known_hosts, a cache, a $HOME that is not /root (ProtectHome=
# true makes /root invisible). Declaring it up front costs nothing and removes a whole class
# of first-run failures that read like credential errors and are not.
install -d -m 0700 -o root -g root "$OFFBOX_DIR"
note "$DUMP_DIR 0700 root:root · $STATE_DIR 0755 root:root · $OFFBOX_DIR 0700 root:root"

# ------------------------------------------------------- the off-box config ---
echo "=== 1b/6  $OFFBOX_ENV ==="
# Two files. The .example is rebuilt on every run, and rewritten only when it differs, so
# it always documents the variable set this installer actually implements; the real one is
# created ONLY IF ABSENT, so a rerun can never clobber a destination an operator filled in. Both are root:root — the .example 0644 because it holds no secret and is the
# thing somebody reads over your shoulder, the real file 0600 because it holds the write
# credential for every customer row this box has. The three env files already in
# /etc/bayram are 0640 root:hbd, i.e. readable by the application account; this one
# deliberately is not, and the backup script refuses to read it at any other mode.
[ -d "$ETCDIR" ] || install -d -m 0755 -o root -g root "$ETCDIR"

cat > "$TMP/backup-offbox.env.example" <<'OFFBOX_EXAMPLE'
# /etc/bayram/backup-offbox.env — where the nightly dump goes AFTER it is written.
#
# Install it as:  root:root 0600.  bayram-backup REFUSES to read it at any other
# owner or mode, because it holds a credential that can write (and, if you are careless
# with the scope, delete) every customer row this box has.
#
# EMPTY IS VALID AND EMPTY IS THE DEFAULT. With no MODE set, bayram-backup prints one
# line saying the copy is not configured, records "offbox": "not-configured" in its
# sentinel, and exits 0. It does NOT fail, because "nobody has chosen a destination yet"
# is the true state of this host and a nightly red light for a known state teaches
# people to ignore lights.
#
# IT IS KEY=value LINES, NOT A SHELL PROFILE. bayram-backup sources it in a subshell and
# lifts out only the BAYRAM_BACKUP_OFFBOX_* keys documented below, so an assignment to
# anything else here reaches nothing — and, deliberately, cannot reach the script's own
# DUMP_DIR or PREFIX. A file that does not parse, or whose last command exits non-zero, is a
# hard refusal in BOTH the installer and the nightly run; check yours with
#     bash -n /etc/bayram/backup-offbox.env
#
# After ANY change here, rerun the installer:
#     sudo bash /tmp/install-bayram-backup.sh
# The installer is what widens the unit's socket sandbox; editing this file alone leaves
# the service unable to open a network socket at all.

# ---------------------------------------------------------------------------
# THE ONE SWITCH
# ---------------------------------------------------------------------------
#   (empty) local only. No copy, no error.
#   s3      any S3-compatible endpoint (AWS S3, Cloudflare R2, Backblaze B2, MinIO,
#           Wasabi...). No provider is special-cased; an endpoint URL is all that
#           differs between them.
#   rsync   rsync over ssh to a second host.
#   command your own executable. Called as: CMD <dump path> <DEST>. A hook written for
#           the older /etc/bayram/backup-offsite.hook contract, which took only the dump
#           path, still works unchanged.
BAYRAM_BACKUP_OFFBOX_MODE=

# The destination, passed through UNTOUCHED except for having the dump's filename
# appended. Nothing in bayram-backup parses it beyond what the chosen transport needs,
# which is what keeps this file provider-agnostic.
#   s3      s3://bucket/prefix        (or an rclone remote: r2:bayram-backups/nightly)
#   rsync   backups@host:/srv/bayram-dumps
#   command whatever your script expects; it arrives as $2
BAYRAM_BACKUP_OFFBOX_DEST=

# ---------------------------------------------------------------------------
# FAILURE AND VERIFICATION SEMANTICS
# ---------------------------------------------------------------------------
# 1 (default): a failed off-box copy fails the whole backup — OnFailure fires, the
# sentinel says failed, the journal gets an emerg. The dump itself is already on disk and
# is kept. The default is 1 because a copy that quietly stopped copying is the same lie as
# a timer that quietly stopped firing. 0: log loudly, record "offbox": "failed", carry on.
BAYRAM_BACKUP_OFFBOX_REQUIRED=1

# 1 (default): after the upload, read the remote object back and compare it to the local
# dump — size for s3, an end-to-end checksum for rsync. This is the same guard as the
# `test -s` and `gzip -t` on the dump itself: a silently truncated upload is worse than no
# upload, because it looks like protection. Verification needs READ access to the object
# you just wrote (s3:GetObject on the key). If you scoped the credential write-only on
# purpose, set this to 0 and accept that nothing checks what arrived.
BAYRAM_BACKUP_OFFBOX_VERIFY=1

# Seconds. Wraps every off-box command. The push holds the backup lock and the unit's
# TimeoutStartSec is 3600, so an unbounded hang would eat the next night's run too.
BAYRAM_BACKUP_OFFBOX_TIMEOUT=900

# ---------------------------------------------------------------------------
# MODE=s3
# ---------------------------------------------------------------------------
# auto (default) prefers rclone if it is installed, else awscli. Neither is installed on
# this host today — installing one is a separate, deliberate host change.
BAYRAM_BACKUP_OFFBOX_S3_CLIENT=auto
# Leave empty for real AWS S3. Cloudflare R2: https://<accountid>.r2.cloudflarestorage.com
# Backblaze B2:  https://s3.<region>.backblazeb2.com
BAYRAM_BACKUP_OFFBOX_S3_ENDPOINT=
BAYRAM_BACKUP_OFFBOX_S3_REGION=auto
BAYRAM_BACKUP_OFFBOX_S3_ACCESS_KEY_ID=
BAYRAM_BACKUP_OFFBOX_S3_SECRET_ACCESS_KEY=
# rclone only, and only when it is not driving a named remote from its own config:
# the provider hint (Other, Cloudflare, Backblaze, Minio, AWS...). Purely a compatibility
# switch inside rclone; it names no service this script knows about.
BAYRAM_BACKUP_OFFBOX_S3_PROVIDER=Other
# An rclone config file, if you use named remotes rather than the credentials above.
# Keep it root:root 0600 and under /var/lib/bayram-backup/offbox.
BAYRAM_BACKUP_OFFBOX_RCLONE_CONFIG=

# ---------------------------------------------------------------------------
# MODE=rsync
# ---------------------------------------------------------------------------
# StrictHostKeyChecking is ON and there is no interactive prompt in a nightly unit, so the
# host key must be known BEFORE the first run or the copy fails with a message nobody
# reads until morning:
#     ssh-keyscan -p 22 backup-host | sudo tee -a /var/lib/bayram-backup/offbox/known_hosts
BAYRAM_BACKUP_OFFBOX_SSH_KNOWN_HOSTS=
# A passphrase-less key, root:root 0600. There is nobody to type a passphrase at 02:30.
# Restrict it at the far end (command=,restrict in authorized_keys) rather than trusting
# this end: this box terminates payment callbacks.
BAYRAM_BACKUP_OFFBOX_SSH_KEY=
BAYRAM_BACKUP_OFFBOX_SSH_PORT=

# ---------------------------------------------------------------------------
# MODE=command
# ---------------------------------------------------------------------------
# Absolute path to a root-owned 0700 executable. Anything else is refused: a script root
# runs nightly that another account can rewrite is a root shell with extra steps.
BAYRAM_BACKUP_OFFBOX_CMD=

# ---------------------------------------------------------------------------
# WHAT THIS FILE DOES NOT DECIDE
# ---------------------------------------------------------------------------
# RETENTION AT THE FAR END. bayram-backup prunes its own 14 local dailies and nothing
# else; it never deletes anything at the destination, on purpose — a script that can
# delete remote backups is a script that can delete all of them. Set a bucket lifecycle
# rule, or a cron at the far end, and write down which you chose.
#
# WHAT IS IN THE DUMP. Postgres only. Not /var/lib/hbd/var/archive (delivered songs and
# every customer avatar), not Redis (which since D17 decides whether a paid song renders),
# and not BAYRAM_ADMIN_AUDIT_HMAC_KEY — which is in no dump at all and MUST NOT be stored
# with one, since a backup holding both admin_audit_log and the key that authenticates it
# is a backup an insider can rewrite end to end.
OFFBOX_EXAMPLE
if ! cmp -s "$TMP/backup-offbox.env.example" "$OFFBOX_EXAMPLE" 2>/dev/null; then
  install -m 0644 -o root -g root "$TMP/backup-offbox.env.example" "$OFFBOX_EXAMPLE"; CHANGED=1
  note "$(basename "$OFFBOX_EXAMPLE") written (0644 root:root)"
else
  note "$(basename "$OFFBOX_EXAMPLE") unchanged"
fi

if [ -e "$OFFBOX_ENV" ]; then
  OWN=$(stat -c '%U %a' "$OFFBOX_ENV")
  if [ "$OWN" != "root 600" ]; then
    die "$OFFBOX_ENV exists but is '$OWN', not 'root 600'. It holds the off-box write
       credential and the backup script refuses to read it at any other mode. Fix it
       deliberately rather than having an installer silently re-chmod a credential file:
           sudo chown root:root $OFFBOX_ENV && sudo chmod 0600 $OFFBOX_ENV" 2
  fi
  note "$(basename "$OFFBOX_ENV") exists, left untouched (a rerun must not clobber a filled-in destination)"
else
  cat > "$TMP/backup-offbox.env" <<'OFFBOX_ENVFILE'
# /etc/bayram/backup-offbox.env — where the nightly dump goes after it is written.
# Every variable is present and EMPTY, and empty is the inert state: no copy, no error.
# The full commented set, with what each transport needs, is in
# /etc/bayram/backup-offbox.env.example. Rerun the installer after editing this file.
BAYRAM_BACKUP_OFFBOX_MODE=
BAYRAM_BACKUP_OFFBOX_DEST=
BAYRAM_BACKUP_OFFBOX_REQUIRED=1
BAYRAM_BACKUP_OFFBOX_VERIFY=1
BAYRAM_BACKUP_OFFBOX_TIMEOUT=900
BAYRAM_BACKUP_OFFBOX_S3_CLIENT=auto
BAYRAM_BACKUP_OFFBOX_S3_ENDPOINT=
BAYRAM_BACKUP_OFFBOX_S3_REGION=auto
BAYRAM_BACKUP_OFFBOX_S3_ACCESS_KEY_ID=
BAYRAM_BACKUP_OFFBOX_S3_SECRET_ACCESS_KEY=
BAYRAM_BACKUP_OFFBOX_S3_PROVIDER=Other
BAYRAM_BACKUP_OFFBOX_RCLONE_CONFIG=
BAYRAM_BACKUP_OFFBOX_SSH_KNOWN_HOSTS=
BAYRAM_BACKUP_OFFBOX_SSH_KEY=
BAYRAM_BACKUP_OFFBOX_SSH_PORT=
BAYRAM_BACKUP_OFFBOX_CMD=
OFFBOX_ENVFILE
  install -m 0600 -o root -g root "$TMP/backup-offbox.env" "$OFFBOX_ENV"
  CHANGED=1
  note "$(basename "$OFFBOX_ENV") created, every value empty (0600 root:root) — off-box copy is INERT"
fi

# Read back what is actually configured. In a subshell, so a stray assignment in that file
# cannot reach DUMP_DIR or KEEP in here; one value at a time, because this installer has no
# business holding the credential in a variable it might echo.
#
# AND WITH NO `|| true`. The earlier reads swallowed every failure of the source, which made
# the two halves of this system disagree about the same file: a syntax error in
# backup-offbox.env aborted the source partway, MODE came back empty, this installer printed
# "off-box: NOT CONFIGURED (inert)", REMOVED the 10-offbox.conf socket drop-in and exited 0 —
# while the generated script sources the very same file under `set -euo pipefail` with no
# fallback and dies at 02:30. The strict reading is the correct one for both: if this file
# will stop the nightly run, it stops the install, in front of the operator who just edited
# it. (`bash -n` is NOT enough on its own here — it catches the syntax error but not a file
# whose last command merely exits non-zero, which kills the nightly run just as dead.)
offbox_conf() {  # $1 = variable name, $2 = value to report when it is unset or empty
  local v
  v=$( set +u; . "$OFFBOX_ENV" >/dev/null || exit 9; printf '%s' "${!1-}" ) \
    || die "$OFFBOX_ENV could not be sourced — see the shell's own error above.
       The generated /opt/bayram/sbin/bayram-backup sources this same file under
       'set -euo pipefail' with no fallback, so a file this installer waved through is a
       unit that dies at 02:30 in front of nobody. Refusing here instead.
       It must be KEY=value lines only. Check it with:  bash -n $OFFBOX_ENV" 2
  printf '%s' "${v:-$2}"
}

OFFBOX_MODE_CONF=$(offbox_conf BAYRAM_BACKUP_OFFBOX_MODE "")
if [ -z "$OFFBOX_MODE_CONF" ] && [ -x /etc/bayram/backup-offsite.hook ]; then
  # The pre-env hook contract. If somebody wrote one, it is a configured destination.
  OFFBOX_MODE_CONF=command
  note "legacy /etc/bayram/backup-offsite.hook found — treated as MODE=command"
fi
case "$OFFBOX_MODE_CONF" in
  "")            note "off-box: NOT CONFIGURED (inert; the unit keeps RestrictAddressFamilies=AF_UNIX)" ;;
  s3|rsync|command) note "off-box: MODE=$OFFBOX_MODE_CONF" ;;
  *) die "BAYRAM_BACKUP_OFFBOX_MODE='$OFFBOX_MODE_CONF' in $OFFBOX_ENV is not one of:
       (empty) | s3 | rsync | command. Refusing at preflight rather than at 02:30." 2 ;;
esac
# If a transport is configured, its client has to exist NOW. Refusing here costs the
# operator a rerun; not refusing costs a nightly unit that fails at 02:30 in front of
# nobody, which is the thing this whole file is built to prevent. Neither rclone nor
# awscli is installed on this host today — installing one is a second, separate command.
case "$OFFBOX_MODE_CONF" in
  s3)
    S3C=$(offbox_conf BAYRAM_BACKUP_OFFBOX_S3_CLIENT auto)
    case "$S3C" in
      rclone|aws) command -v "$S3C" >/dev/null 2>&1 || die "BAYRAM_BACKUP_OFFBOX_S3_CLIENT=$S3C but '$S3C' is not installed.
       Install it, or blank BAYRAM_BACKUP_OFFBOX_MODE to go back to local-only." 2 ;;
      auto|"")    command -v rclone >/dev/null 2>&1 || command -v aws >/dev/null 2>&1 \
                    || die "MODE=s3 needs rclone or awscli and this host has neither.
       Install one (apt-get install rclone), or blank BAYRAM_BACKUP_OFFBOX_MODE." 2 ;;
      *) die "BAYRAM_BACKUP_OFFBOX_S3_CLIENT must be auto, rclone or aws; it is '$S3C'" 2 ;;
    esac ;;
  rsync)
    command -v rsync >/dev/null 2>&1 || die "MODE=rsync but rsync is not installed" 2
    command -v ssh   >/dev/null 2>&1 || die "MODE=rsync but ssh is not installed" 2 ;;
esac

# ------------------------------------------------------------- the script -----
echo "=== 2/6  $SCRIPT ==="

cat > "$TMP/bayram-backup" <<'BACKUP_SCRIPT'
#!/usr/bin/env bash
#
# bayram-backup — the nightly database dump, and the off-box copy of it.
# Installed by deploy/install-bayram-backup.sh. Do not edit in place: edit the installer
# and rerun it, or the next install silently reverts you.
#
# VERBS
#   run           take a dump, verify it, copy it off-box, prune, write the sentinel. (timer)
#   fail-notice   write the failure sentinel and make noise.                  (OnFailure)
#   check         exit 4 if the last backup is missing, failed or stale.      (for humans
#                 and for whatever eventually reads it — see SENTINEL below)
#   check-offbox  exit 4 only if an off-box copy IS configured and did not succeed.
#                 Separate from `check` on purpose: see the comment on that verb.
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
OFFBOX_ENV=/etc/bayram/backup-offbox.env
OFFBOX_DIR=/var/lib/bayram-backup/offbox
OFFBOX_LEGACY_HOOK=/etc/bayram/backup-offsite.hook
OFFBOX_TIMEOUT=900
OFFBOX_REQUIRED=1

# Every key this script honours from $OFFBOX_ENV, without the BAYRAM_BACKUP_OFFBOX_ prefix.
# offbox_load() sources that file in a SUBSHELL and lifts exactly these back out, so a stray
# assignment in it cannot reach DUMP_DIR, PREFIX or anything else named above. This list and
# the keys in backup-offbox.env.example are the same set; adding a key means adding it here.
OFFBOX_KEYS="MODE DEST CMD TIMEOUT REQUIRED VERIFY
             S3_CLIENT S3_ENDPOINT S3_REGION S3_PROVIDER
             S3_ACCESS_KEY_ID S3_SECRET_ACCESS_KEY RCLONE_CONFIG
             SSH_KNOWN_HOSTS SSH_KEY SSH_PORT"

# ---------------------------------------------------------------------------
# RETENTION: KEEP=14 DAILIES. THE ARITHMETIC.
#
#   * The largest dump this host has ever written is 23 KB
#     (/var/backups/hbd/pre-wipe-20260910-092203, 05-operations.md:1153).
#     14 x 23 KB = 322 KB.
#   * The root filesystem is 38 GB, 7.2 GB used, ~30 GB free
#     (00-host-inventory.md row 1). There is ONE filesystem on this box.
#   * 14 dailies exhaust that free space only when a single dump exceeds
#     30 GB / 14 = ~2.1 GB compressed. The database is 28 mapped tables of text
#     and money rows; the media archive is NOT in it. Three orders of magnitude
#     of growth still costs ~1% of the disk.
#   * 14 matches the only backup precedent on the machine: aizu-backup keeps 14
#     days (05-operations.md:1163). An operator comparing the two sees one number.
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

# Strip the three characters that would turn a detail string into malformed JSON, and cap
# the length. The detail can now carry a line of rsync or awscli output, which is not ours
# to trust the shape of, and a sentinel that will not parse is a sentinel nobody reads.
jsan() { printf '%s' "$*" | tr -d '\\"' | tr '\n\r\t' '   ' | cut -c1-300; }

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
  # THE OFF-BOX KEYS CARRY NO DESTINATION, AND THAT IS NOT AN OVERSIGHT. This file is
  # 0644 on purpose (see the block below) so that the admin API can read it. A bucket URL
  # or a `backups@host:/srv/dumps` written here would be a world-readable fact about where
  # this company's database dumps live, published by the very file whose job is to prove
  # they exist. The MODE is here because "s3" or "rsync" tells an operator which runbook to
  # open and tells an attacker nothing they could not guess.
  printf '  "offbox": "%s",\n'        "$OFFBOX_STATE" >> "$tmp"
  printf '  "offbox_mode": "%s",\n'   "$(jsan "${OFFBOX_MODE:-}")" >> "$tmp"
  printf '  "offbox_at": "%s",\n'     "$(jsan "${OFFBOX_AT:-}")" >> "$tmp"
  printf '  "offbox_detail": "%s",\n' "$(jsan "${OFFBOX_DETAIL:-}")" >> "$tmp"
  printf '  "detail": "%s"\n'       "$(jsan "${5:-}")" >> "$tmp"
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

# ---------------------------------------------------------------------------
# OFF-BOX: ONE INTERFACE, THREE TRANSPORTS, AND INERT UNTIL SOMEBODY CONFIGURES IT
#
# Everything below is driven by $OFFBOX_ENV. With no BAYRAM_BACKUP_OFFBOX_MODE set, the
# whole block is one printed line and `return 0` — no test, no stat, no network call, no
# non-zero exit, nothing that could trip OnFailure. THAT IS THE SHIPPED STATE AND IT IS
# CORRECT: nobody has chosen a destination yet, and a nightly red light for a state
# somebody deliberately left alone teaches whoever reads it next to stop reading it.
#
# What the modes have in common, which is the part worth reviewing:
#
#   * Nothing here names a provider. `s3` is an endpoint URL and a bucket path, so
#     Cloudflare R2, Backblaze B2, Wasabi, MinIO and AWS itself are the same three lines
#     of config with a different URL. `rsync` is a host and a path. `command` is somebody
#     else's executable and this script does not look inside it.
#   * Every command is wrapped in `timeout`. This runs while holding the flock at the top
#     of `run`, inside a unit with TimeoutStartSec=3600: a hung ssh would otherwise block
#     tomorrow night's run as well, and the only symptom would be a backup that stopped.
#   * Every upload is READ BACK AND COMPARED before the run is called a success. It is the
#     same argument as `test -s` and `gzip -t` on the dump itself, one hop further out: a
#     silently truncated upload is worse than no upload, because it looks like protection.
#     s3 compares the object's size; rsync compares an end-to-end checksum (`rsync -c`,
#     which reads both ends), which is strictly stronger and costs a second pass.
#   * A credential file that is not root:root 0600 is a refusal, not a warning.
#   * The destination string is never written to the sentinel, which is 0644.
#
# The config is SOURCED here even though the unit also carries EnvironmentFile= for it.
# That is deliberate and it is the same argument the installer's step 6 makes for taking a
# first dump by hand: `bayram-backup run` typed by an operator at 11:00 must do exactly
# what the timer does at 02:30, or the thing you tested is not the thing that runs.
# ---------------------------------------------------------------------------

OFFBOX_STATE=not-configured
OFFBOX_MODE=""
OFFBOX_DEST=""
OFFBOX_CMD=""
OFFBOX_AT=""
OFFBOX_DETAIL=""
OFFBOX_VERIFY=1
OFFBOX_VERIFY_KIND=""
OFFBOX_REMOTE_BYTES=""
OFFBOX_FAIL_DETAIL=""
OFFBOX_LEGACY=0

offbox_log() { echo "OFF-BOX: $*"; }

offbox_load() {
  if [ -e "$OFFBOX_ENV" ]; then
    local own blob
    own=$(stat -c '%U %a' "$OFFBOX_ENV")
    [ "$own" = "root 600" ] || die "$OFFBOX_ENV is '$own', not 'root 600'.
       It holds the credential that can write this database off this box. A credential
       file another account can read or rewrite is a refusal, not a warning:
           sudo chown root:root $OFFBOX_ENV && sudo chmod 0600 $OFFBOX_ENV" 2
    #
    # SOURCED IN A SUBSHELL. ONLY THE KEYS IN $OFFBOX_KEYS COME BACK OUT.
    #
    # This used to be a bare `set -a; . "$OFFBOX_ENV"; set +a` at top level, run from inside
    # the `run` verb — that is, AFTER DB, DUMP_DIR, STATE_DIR, SENTINEL, KEEP and PREFIX were
    # assigned above. A stray `DUMP_DIR=` or `PREFIX=` in a config file nobody thinks of as
    # code therefore silently retargeted the dump, the sentinel and — worse — the prune's
    #     rm -f "$DUMP_DIR/$PREFIX"-*
    # which is an `rm -f` with a glob on two values that file could choose. The installer
    # reads this same file in a subshell for precisely this reason and says so in its own
    # comment; there is no argument for the generated script being the lax one.
    #
    # The transport back out is `printf %q`, so a value containing spaces, quotes, `$`,
    # backticks or newlines survives intact and the `eval` below re-reads exactly the bytes
    # the subshell wrote and nothing else. Keys absent from the file come back empty, which
    # every reader below already treats as unset (they all use `${...:-default}`).
    #
    # CONSEQUENCE, STATED PLAINLY: a variable NOT on this list is no longer exported to the
    # off-box command by writing it in this file. That is deliberate — the file is a config,
    # not a shell profile — and $OFFBOX_KEYS is the complete documented set.
    blob=$( set +u
            # shellcheck disable=SC1090
            . "$OFFBOX_ENV" >/dev/null || exit 9
            for k in $OFFBOX_KEYS; do
              n="BAYRAM_BACKUP_OFFBOX_$k"
              printf 'export %s=%q\n' "$n" "${!n-}"
            done ) \
      || die "$OFFBOX_ENV could not be sourced — see the shell's own error above.
       It must be KEY=value lines only. Nothing was dumped and nothing was copied.
       Check it with:  bash -n $OFFBOX_ENV" 2
    eval "$blob"
  fi

  OFFBOX_MODE=${BAYRAM_BACKUP_OFFBOX_MODE:-}
  OFFBOX_DEST=${BAYRAM_BACKUP_OFFBOX_DEST:-}
  OFFBOX_CMD=${BAYRAM_BACKUP_OFFBOX_CMD:-}
  OFFBOX_TIMEOUT=${BAYRAM_BACKUP_OFFBOX_TIMEOUT:-$OFFBOX_TIMEOUT}
  OFFBOX_REQUIRED=${BAYRAM_BACKUP_OFFBOX_REQUIRED:-$OFFBOX_REQUIRED}
  OFFBOX_VERIFY=${BAYRAM_BACKUP_OFFBOX_VERIFY:-1}

  # The pre-env contract, kept working on purpose. Anyone who already wrote a root-owned
  # 0700 hook at the old path keeps their hook and their single-argument calling
  # convention; they just get the timeout, the failure policy and the sentinel keys for
  # free. An explicit MODE in the env file always wins over it.
  if [ -z "$OFFBOX_MODE" ] && [ -x "$OFFBOX_LEGACY_HOOK" ]; then
    OFFBOX_MODE=command
    OFFBOX_CMD=$OFFBOX_LEGACY_HOOK
    OFFBOX_LEGACY=1
  fi
}

offbox_need() {  # $1 binary
  command -v "$1" >/dev/null 2>&1 || die "BAYRAM_BACKUP_OFFBOX_MODE=$OFFBOX_MODE needs '$1', which is
       not installed on this host. The dump itself is fine and is on disk; only the copy
       off this box was refused. Install '$1', or blank BAYRAM_BACKUP_OFFBOX_MODE in
       $OFFBOX_ENV to go back to local-only and stop failing every night." 2
}

# The unit ships with RestrictAddressFamilies=AF_UNIX and therefore cannot open a network
# socket at all. The installer widens that with a drop-in ONLY when a destination is
# configured, so a config file edited without rerunning the installer produces a push that
# fails deep inside rclone or ssh with an errno nobody will connect to a systemd directive.
# Catch it here, with the sentence that names the fix.
offbox_assert_socket() {
  local fams
  fams=$(systemctl show bayram-backup.service -p RestrictAddressFamilies --value 2>/dev/null || true)
  case "$fams" in
    ""|*AF_INET*) return 0 ;;
  esac
  if [ -n "${INVOCATION_ID:-}" ]; then
    die "the unit is running with RestrictAddressFamilies=$fams, which means no network
       socket of any kind, but $OFFBOX_ENV configures MODE=$OFFBOX_MODE. Rerun the
       installer so the drop-in that widens the sandbox is written:
           sudo bash /tmp/install-bayram-backup.sh" 2
  fi
  offbox_log "WARNING: bayram-backup.service still restricts sockets to $fams. This hand
      run will work because it is not inside the unit; the 02:30 run will NOT. Rerun the
      installer."
}

# Every off-box command goes through here so that no transport can forget the timeout, and
# so that 'it hung' and 'it failed' are two different sentences in the journal.
offbox_run() {
  local rc=0
  timeout "$OFFBOX_TIMEOUT" "$@" || rc=$?
  if [ "$rc" -eq 124 ]; then
    OFFBOX_FAIL_DETAIL="$1 timed out after ${OFFBOX_TIMEOUT}s"
  elif [ "$rc" -ne 0 ]; then
    OFFBOX_FAIL_DETAIL="$1 exited $rc"
  fi
  return "$rc"
}

# --- MODE=s3 ---------------------------------------------------------------
# An S3-compatible endpoint. Credentials are passed in the ENVIRONMENT, never in argv:
# /proc/<pid>/cmdline is world-readable and this host has accounts that are not root.
offbox_push_s3() {  # $1 dump
  local dump=$1 name client remote rest bucket key out
  name=$(basename "$dump")
  client=${BAYRAM_BACKUP_OFFBOX_S3_CLIENT:-auto}
  case "$client" in
    auto|"") if command -v rclone >/dev/null 2>&1; then client=rclone; else client=aws; fi ;;
    rclone|aws) ;;
    *) die "BAYRAM_BACKUP_OFFBOX_S3_CLIENT must be auto, rclone or aws; it is '$client'" 2 ;;
  esac
  offbox_need "$client"

  if [ -n "${BAYRAM_BACKUP_OFFBOX_S3_ACCESS_KEY_ID:-}" ]; then
    export AWS_ACCESS_KEY_ID="$BAYRAM_BACKUP_OFFBOX_S3_ACCESS_KEY_ID"
    export RCLONE_S3_ACCESS_KEY_ID="$BAYRAM_BACKUP_OFFBOX_S3_ACCESS_KEY_ID"
  fi
  if [ -n "${BAYRAM_BACKUP_OFFBOX_S3_SECRET_ACCESS_KEY:-}" ]; then
    export AWS_SECRET_ACCESS_KEY="$BAYRAM_BACKUP_OFFBOX_S3_SECRET_ACCESS_KEY"
    export RCLONE_S3_SECRET_ACCESS_KEY="$BAYRAM_BACKUP_OFFBOX_S3_SECRET_ACCESS_KEY"
  fi
  if [ -n "${BAYRAM_BACKUP_OFFBOX_S3_REGION:-}" ]; then
    export AWS_DEFAULT_REGION="$BAYRAM_BACKUP_OFFBOX_S3_REGION"
    export RCLONE_S3_REGION="$BAYRAM_BACKUP_OFFBOX_S3_REGION"
  fi
  if [ -n "${BAYRAM_BACKUP_OFFBOX_S3_ENDPOINT:-}" ]; then
    export RCLONE_S3_ENDPOINT="$BAYRAM_BACKUP_OFFBOX_S3_ENDPOINT"
  fi
  # No instance metadata on this box. Without this, a missing credential turns into a
  # multi-second hang against 169.254.169.254 instead of an error.
  export AWS_EC2_METADATA_DISABLED=true

  if [ "$client" = "aws" ]; then
    case "$OFFBOX_DEST" in
      s3://*/*) ;;
      *) die "with the aws client BAYRAM_BACKUP_OFFBOX_DEST must be s3://bucket/prefix;
       it is '$OFFBOX_DEST'" 2 ;;
    esac
    remote="${OFFBOX_DEST%/}/$name"
    local ep=()
    [ -z "${BAYRAM_BACKUP_OFFBOX_S3_ENDPOINT:-}" ] || ep=(--endpoint-url "$BAYRAM_BACKUP_OFFBOX_S3_ENDPOINT")
    offbox_run aws ${ep[@]+"${ep[@]}"} s3 cp --only-show-errors "$dump" "$remote" || return 1

    [ "$OFFBOX_VERIFY" = "1" ] || return 0
    rest=${remote#s3://}; bucket=${rest%%/*}; key=${rest#*/}
    # HeadObject, not `s3 ls`: it needs s3:GetObject on this one key rather than
    # ListBucket on the whole bucket, which is the narrower grant of the two.
    out=$(timeout 120 aws ${ep[@]+"${ep[@]}"} s3api head-object \
            --bucket "$bucket" --key "$key" --query ContentLength --output text 2>&1) || {
      OFFBOX_FAIL_DETAIL="uploaded, but could not read it back to verify it: $out"
      return 1
    }
    OFFBOX_REMOTE_BYTES=$out
    OFFBOX_VERIFY_KIND=size
    return 0
  fi

  # rclone. A DEST that is already an rclone remote (r2:bucket/prefix) is used as written;
  # an s3:// URL is handed to rclone's on-the-fly :s3: backend with the endpoint and keys
  # above, so the same DEST works whichever client is installed.
  export HOME="$OFFBOX_DIR"
  export XDG_CONFIG_HOME="$OFFBOX_DIR/config"
  export RCLONE_CONFIG="${BAYRAM_BACKUP_OFFBOX_RCLONE_CONFIG:-$OFFBOX_DIR/rclone.conf}"
  export RCLONE_S3_PROVIDER="${BAYRAM_BACKUP_OFFBOX_S3_PROVIDER:-Other}"
  [ -e "$RCLONE_CONFIG" ] || { : > "$RCLONE_CONFIG"; chmod 0600 "$RCLONE_CONFIG"; }
  case "$OFFBOX_DEST" in
    s3://*) rest=${OFFBOX_DEST#s3://}; remote=":s3:${rest%/}/$name" ;;
    *)      remote="${OFFBOX_DEST%/}/$name" ;;
  esac
  offbox_run rclone copyto --quiet "$dump" "$remote" || return 1

  [ "$OFFBOX_VERIFY" = "1" ] || return 0
  out=$(timeout 120 rclone size --json "$remote" 2>&1) || {
    OFFBOX_FAIL_DETAIL="uploaded, but could not read it back to verify it: $out"
    return 1
  }
  OFFBOX_REMOTE_BYTES=$(printf '%s' "$out" | sed -n 's/.*"bytes":[[:space:]]*\([0-9][0-9]*\).*/\1/p')
  OFFBOX_VERIFY_KIND=size
  return 0
}

# --- MODE=rsync ------------------------------------------------------------
# rsync over ssh to a second host. No scp: rsync writes to a temporary name at the far end
# and renames it only when the transfer completes, so an interrupted copy never leaves a
# truncated file under the real name — and it can verify itself, which scp cannot.
offbox_push_rsync() {  # $1 dump
  local dump=$1 kh sshcmd dest out
  offbox_need rsync
  offbox_need ssh
  offbox_require_known_hosts
  kh=${BAYRAM_BACKUP_OFFBOX_SSH_KNOWN_HOSTS:-$OFFBOX_DIR/known_hosts}
  sshcmd="ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$kh -o ConnectTimeout=20"
  [ -z "${BAYRAM_BACKUP_OFFBOX_SSH_KEY:-}" ]  || sshcmd="$sshcmd -i ${BAYRAM_BACKUP_OFFBOX_SSH_KEY}"
  [ -z "${BAYRAM_BACKUP_OFFBOX_SSH_PORT:-}" ] || sshcmd="$sshcmd -p ${BAYRAM_BACKUP_OFFBOX_SSH_PORT}"
  export HOME="$OFFBOX_DIR"
  dest="${OFFBOX_DEST%/}/"

  offbox_run rsync -a --chmod=F0600 -e "$sshcmd" "$dump" "$dest" || return 1

  [ "$OFFBOX_VERIFY" = "1" ] || return 0
  # -c reads BOTH copies and compares checksums, so this catches a truncation that size
  # alone would miss. --no-perms/--no-times keep a mode or mtime difference from reading as
  # a content difference. Identical files produce NO output at all; anything printed here
  # is rsync telling us the far end does not match.
  out=$(timeout "$OFFBOX_TIMEOUT" rsync -n -c -i --no-perms --no-owner --no-group --no-times \
          -e "$sshcmd" "$dump" "$dest" 2>&1) || {
    OFFBOX_FAIL_DETAIL="uploaded, but the verify pass could not read it back: $out"
    return 1
  }
  if [ -n "$out" ]; then
    OFFBOX_FAIL_DETAIL="rsync -c says the remote copy differs from the local dump: $out"
    return 1
  fi
  OFFBOX_VERIFY_KIND=checksum
  return 0
}

# --- MODE=command ----------------------------------------------------------
offbox_push_command() {  # $1 dump
  local dump=$1
  offbox_require_cmd
  # $1 dump, $2 destination. A hook written against the old single-argument contract
  # ignores $2 and keeps working.
  offbox_run "$OFFBOX_CMD" "$dump" "$OFFBOX_DEST" || return 1
  OFFBOX_VERIFY_KIND=delegated
  return 0
}

offbox_fail() {  # $1 detail, WITHOUT the destination in it
  OFFBOX_STATE=failed
  OFFBOX_DETAIL="$1"
  # OnFailure runs fail-notice as a SEPARATE process, which knows nothing about this one.
  # Leave it the one fact it cannot reconstruct: the dump succeeded, the copy did not.
  { printf 'dump=%s mode=%s %s\n' "$DUMP" "$OFFBOX_MODE" "$1" > "$STATE_DIR/last-error"
    chmod 0600 "$STATE_DIR/last-error"; } 2>/dev/null || true
  if [ "$OFFBOX_REQUIRED" = "1" ]; then
    die "off-box copy FAILED: $1
       The dump itself is good and is kept at $DUMP.
       This fails the whole backup on purpose: a copy that quietly stopped copying is the
       same lie as a timer that quietly stopped firing. If you would rather be told and
       carry on, set BAYRAM_BACKUP_OFFBOX_REQUIRED=0 in $OFFBOX_ENV." 3
  fi
  offbox_log "FAILED: $1"
  offbox_log "BAYRAM_BACKUP_OFFBOX_REQUIRED=0, so the run continues. The sentinel will say
      \"offbox\": \"failed\" and this dump exists ONLY on this disk."
}

offbox_require_known_hosts() {
  local kh=${BAYRAM_BACKUP_OFFBOX_SSH_KNOWN_HOSTS:-$OFFBOX_DIR/known_hosts}
  [ -s "$kh" ] || die "MODE=rsync, but there is no known_hosts at $kh.
       StrictHostKeyChecking stays ON: a nightly unit has nobody to answer a host-key
       prompt, and turning it off would make this push trust whatever answers on that
       address. Pin the key once, deliberately:
           ssh-keyscan -p \${BAYRAM_BACKUP_OFFBOX_SSH_PORT:-22} <host> | sudo tee -a $kh" 2
}

offbox_require_cmd() {
  local own
  [ -n "$OFFBOX_CMD" ] || die "MODE=command needs BAYRAM_BACKUP_OFFBOX_CMD set to an
       absolute path in $OFFBOX_ENV" 2
  [ -x "$OFFBOX_CMD" ] || die "BAYRAM_BACKUP_OFFBOX_CMD=$OFFBOX_CMD is not an executable file" 2
  own=$(stat -c '%U %a' "$OFFBOX_CMD")
  # Root runs this every night. Anything writable by another account here is a root shell
  # with extra steps — the same argument that closed the sudo escalation on this host.
  [ "$own" = "root 700" ] || die "$OFFBOX_CMD must be root-owned mode 0700; it is $own" 2
}

# EVERY OFF-BOX REFUSAL THAT DOES NOT NEED THE DUMP HAPPENS HERE, BEFORE THE DUMP IS TAKEN.
# A typo in MODE, a missing client, an unpinned host key: all of those are configuration
# errors, and a configuration error that first shows up after a 90-second pg_dump has cost
# the machine the dump and told the operator nothing earlier than it had to. Exit 2 here
# still means what it means everywhere else in these two scripts: refused, nothing written.
offbox_preflight() {
  case "$OFFBOX_MODE" in
    ""|none) return 0 ;;
    s3|rsync|command) ;;
    *) die "BAYRAM_BACKUP_OFFBOX_MODE='$OFFBOX_MODE' is not one of: (empty) | s3 | rsync |
       command. Refusing rather than guessing what you meant." 2 ;;
  esac
  if [ -z "$OFFBOX_DEST" ] && [ "$OFFBOX_MODE" != "command" ]; then
    die "BAYRAM_BACKUP_OFFBOX_MODE=$OFFBOX_MODE with an empty BAYRAM_BACKUP_OFFBOX_DEST.
       A configured transport with nowhere to send is a misconfiguration, not a no-op." 2
  fi
  [ "$OFFBOX_MODE" = "command" ] || offbox_assert_socket
  case "$OFFBOX_MODE" in
    s3)
      case "${BAYRAM_BACKUP_OFFBOX_S3_CLIENT:-auto}" in
        auto|"")    command -v rclone >/dev/null 2>&1 || offbox_need aws ;;
        rclone|aws) offbox_need "${BAYRAM_BACKUP_OFFBOX_S3_CLIENT}" ;;
        *) die "BAYRAM_BACKUP_OFFBOX_S3_CLIENT must be auto, rclone or aws; it is
       '${BAYRAM_BACKUP_OFFBOX_S3_CLIENT}'" 2 ;;
      esac ;;
    rsync)   offbox_need rsync; offbox_need ssh; offbox_require_known_hosts ;;
    command) offbox_require_cmd ;;
  esac
}

offbox_push() {  # $1 dump, $2 local byte count
  local dump=$1 bytes=$2 ok=1
  OFFBOX_REMOTE_BYTES=""; OFFBOX_VERIFY_KIND=""; OFFBOX_FAIL_DETAIL=""

  case "$OFFBOX_MODE" in
    ""|none)
      OFFBOX_STATE=not-configured
      # THE INERT PATH. One line, exit status untouched, straight on to the prune.
      offbox_log "not configured. This dump is on the same disk as the database it came
      from, so it protects against a bad migration and a dropped table, and against
      nothing that loses the disk. Choose a destination in $OFFBOX_ENV
      (see $OFFBOX_ENV.example) and rerun the installer. This is NOT an error and does
      not fail the backup."
      return 0 ;;
    s3|rsync|command) ;;
    *) die "BAYRAM_BACKUP_OFFBOX_MODE='$OFFBOX_MODE' is not one of: (empty) | s3 | rsync |
       command. Refusing rather than guessing what you meant." 2 ;;
  esac

  if [ -z "$OFFBOX_DEST" ] && [ "$OFFBOX_MODE" != "command" ]; then
    die "BAYRAM_BACKUP_OFFBOX_MODE=$OFFBOX_MODE with an empty BAYRAM_BACKUP_OFFBOX_DEST.
       A configured transport with nowhere to send is a misconfiguration, not a no-op." 2
  fi
  [ "$OFFBOX_MODE" = "command" ] || offbox_assert_socket
  install -d -m 0700 -o root -g root "$OFFBOX_DIR"

  OFFBOX_STATE=running
  [ "$OFFBOX_LEGACY" = "0" ] || offbox_log "using the legacy hook $OFFBOX_LEGACY_HOOK (no MODE set)"
  offbox_log "$OFFBOX_MODE, $bytes bytes"
  case "$OFFBOX_MODE" in
    s3)      offbox_push_s3 "$dump"      || ok=0 ;;
    rsync)   offbox_push_rsync "$dump"   || ok=0 ;;
    command) offbox_push_command "$dump" || ok=0 ;;
  esac
  if [ "$ok" = "0" ]; then
    offbox_fail "${OFFBOX_FAIL_DETAIL:-the push command failed}"
    return 0
  fi

  # VERIFY. Same reasoning as `test -s` and `gzip -t` twenty lines up, one hop further out.
  if [ "$OFFBOX_VERIFY" != "1" ]; then
    OFFBOX_VERIFY_KIND=disabled
    offbox_log "WARNING: verification is OFF (BAYRAM_BACKUP_OFFBOX_VERIFY=0). Nothing has
      checked what actually arrived."
  elif [ "$OFFBOX_VERIFY_KIND" = "checksum" ]; then
    : # rsync -c already compared both ends; there is nothing left to compare here.
  elif [ "$OFFBOX_VERIFY_KIND" = "delegated" ]; then
    offbox_log "verification is your command's job: this script cannot see where it put
      the file. If it does not check what arrived, nothing does."
  elif [ -n "$OFFBOX_REMOTE_BYTES" ]; then
    if [ "$OFFBOX_REMOTE_BYTES" != "$bytes" ]; then
      offbox_fail "remote copy is $OFFBOX_REMOTE_BYTES bytes, local dump is $bytes"
      return 0
    fi
  else
    offbox_fail "verification is on but the transport returned no remote size"
    return 0
  fi

  OFFBOX_STATE=ok
  OFFBOX_AT="$NOW_RFC3339"
  OFFBOX_DETAIL="$OFFBOX_MODE, verified by ${OFFBOX_VERIFY_KIND:-nothing}"
  rm -f "$STATE_DIR/last-error" 2>/dev/null || true
  offbox_log "ok — $OFFBOX_DETAIL"
}

case "${1:-}" in

run)
  mkdir -p "$LOCK_DIR" 2>/dev/null || true
  exec 9>"$LOCK_DIR/lock"
  flock -n 9 || die "another bayram-backup is already running" 2

  offbox_load
  offbox_preflight

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

  # OFF-BOX, and its position in this file is the argument: AFTER the dump has been
  # written, gzip-tested and hashed, and BEFORE the prune below. A dump is therefore always
  # offered to the destination before it can be rotated away, and the thing that gets
  # copied is a thing we have already proved is a complete gzip. No destination is invented
  # here — see the installer's OFF-BOX block and $OFFBOX_ENV.
  offbox_push "$DUMP" "$BYTES"

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

  # THIS PROCESS DID NOT RUN THE BACKUP. OnFailure starts a separate process that knows
  # nothing about the one that died, and its write_sentinel overwrites the good sentinel
  # the run may have left. So the off-box state here is "unknown" and not the module
  # default "not-configured" — claiming "not configured" when a configured push is exactly
  # what failed is a confident lie told in the one case that matters.
  #
  # The single fact the failing run could hand across that gap is $STATE_DIR/last-error,
  # which offbox_fail writes and nothing else does. Read it, then remove it, so tomorrow's
  # failure cannot inherit today's explanation.
  OFFBOX_STATE=unknown
  if [ -s "$STATE_DIR/last-error" ]; then
    OFFBOX_STATE=failed
    OFFBOX_DETAIL=$(head -c 300 "$STATE_DIR/last-error")
    rm -f "$STATE_DIR/last-error"
    MSG="$MSG -- the DUMP succeeded and the OFF-BOX COPY is what failed: $OFFBOX_DETAIL"
  fi

  logger -p daemon.emerg -t bayram-backup -- "$MSG" || true
  echo "$MSG" >&2
  write_sentinel failed "" 0 "" "result=$RESULT exit=$CODE"
  ;;

check)
  # Exit 4 on missing, failed or stale. Intended for the two readers named above.
  #
  # `offbox: not-configured` DOES NOT FAIL THIS CHECK AND MUST NOT START TO. The two
  # readers named above are /healthz and a future deploy preflight; if an unconfigured
  # off-box copy turned either of them permanently red, the first thing anyone would do is
  # stop believing the signal — and the signal's whole job is to be believed on the night
  # the dump actually stops. Not-configured is a decision nobody has made yet, not a
  # fault. Whoever wants that assertion has `check-offbox` below, which is opt-in and says
  # nothing at all until a destination exists.
  [ -f "$SENTINEL" ] || { echo "NO BACKUP SENTINEL at $SENTINEL"; exit 4; }
  grep -q '"result": "ok"' "$SENTINEL" || { echo "last backup did NOT succeed:"; cat "$SENTINEL"; exit 4; }
  AGE=$(( ($(date +%s) - $(stat -c %Y "$SENTINEL")) / 3600 ))
  [ "$AGE" -le "$STALE_HOURS" ] \
    || { echo "last backup is ${AGE}h old (stale after ${STALE_HOURS}h). Is bayram-backup.timer enabled?"; exit 4; }
  echo "backup ok, ${AGE}h old"
  ;;

check-offbox)
  # Exit 4 only when a copy IS configured and the last one did not succeed. Silent and
  # zero when nothing is configured, which is what keeps it safe to wire into a health
  # check before the owner has chosen a destination.
  offbox_load
  if [ -z "$OFFBOX_MODE" ]; then
    echo "off-box copy is not configured (BAYRAM_BACKUP_OFFBOX_MODE is empty in $OFFBOX_ENV)"
    exit 0
  fi
  [ -f "$SENTINEL" ] || { echo "off-box configured ($OFFBOX_MODE) but there is NO SENTINEL at $SENTINEL"; exit 4; }
  grep -q '"offbox": "ok"' "$SENTINEL" \
    || { echo "off-box copy configured ($OFFBOX_MODE) but the last run did not report ok:"; cat "$SENTINEL"; exit 4; }
  echo "off-box copy ok ($OFFBOX_MODE)"
  ;;

status)
  cat "$SENTINEL" 2>/dev/null || { echo "no sentinel at $SENTINEL"; exit 4; }
  ;;

*)
  echo "usage: bayram-backup {run|fail-notice|check|check-offbox|status}" >&2
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
# The off-box constants matter here more than the others, because the installer ACTS on
# them: it writes the config file at $OFFBOX_ENV and widens the unit's sandbox based on
# what it reads there. If the generated script were to read a different path, the operator
# would edit one file and the nightly run would consult another, and the symptom would be
# "I configured a destination and nothing was copied".
grep -q "^OFFBOX_ENV=$OFFBOX_ENV$"         "$TMP/bayram-backup" || die "generated script disagrees with installer on OFFBOX_ENV" 2
grep -q "^OFFBOX_DIR=$OFFBOX_DIR$"         "$TMP/bayram-backup" || die "generated script disagrees with installer on OFFBOX_DIR" 2
grep -q "^OFFBOX_TIMEOUT=$OFFBOX_TIMEOUT$" "$TMP/bayram-backup" || die "generated script disagrees with installer on OFFBOX_TIMEOUT" 2
grep -q "^OFFBOX_REQUIRED=$OFFBOX_REQUIRED$" "$TMP/bayram-backup" || die "generated script disagrees with installer on OFFBOX_REQUIRED" 2
bash -n "$TMP/bayram-backup" || die "generated script is not valid bash" 2

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
# The leading dash is the whole point: a missing file is not an error, so this line is
# inert on a host where nobody has configured an off-box copy. The script sources the same
# file itself, so a hand run behaves identically; this is here so that systemd, and
# `systemctl show`, agree with the script about what is configured.
EnvironmentFile=-$OFFBOX_ENV
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

# THE SOCKET DROP-IN, AND WHY IT IS A DROP-IN AND NOT AN `if` IN THE UNIT ABOVE.
# RestrictAddressFamilies=AF_UNIX in the service means the backup cannot open a network
# socket of any kind — which is exactly right while there is no off-box destination, and
# is the reason a push configured later would otherwise fail at 02:30 with an errno nobody
# connects to a systemd directive. Widening it belongs to the configured case only.
#
# It lands in a separate file so the unit itself is BYTE-IDENTICAL in both modes: the
# `cmp -s` above keeps reporting "unchanged" on a rerun, and `diff` between two hosts
# still shows one file's worth of difference rather than a unit that drifted.
#
# The empty assignment first is not decoration. RestrictAddressFamilies is a list and
# repeated assignments accumulate, so without the reset a later "AF_UNIX AF_INET AF_INET6"
# would merge with the unit's AF_UNIX rather than replace it — harmless here, and a trap
# the day somebody writes a drop-in that means to NARROW the list.
if [ -n "$OFFBOX_MODE_CONF" ]; then
  install -d -m 0755 -o root -g root "$DROPIN_DIR"
  cat > "$TMP/10-offbox.conf" <<UNIT
[Service]
RestrictAddressFamilies=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
UNIT
  if ! cmp -s "$TMP/10-offbox.conf" "$DROPIN" 2>/dev/null; then
    install -m 0644 -o root -g root "$TMP/10-offbox.conf" "$DROPIN"; CHANGED=1
    note "$(basename "$DROPIN") written — the unit may now open AF_INET/AF_INET6 sockets"
  else
    note "$(basename "$DROPIN") unchanged"
  fi
  # MemoryDenyWriteExecute=yes and the CapabilityBoundingSet are deliberately NOT touched
  # here. A Go binary such as rclone runs fine under MDWE; an interpreted client with a JIT
  # may not, and would fail with a mapping error that looks like nothing else. That is a
  # decision for whoever picks the destination, made once, in the open, with the client in
  # front of them — not a relaxation shipped in advance for a client nobody has chosen.
else
  if [ -e "$DROPIN" ]; then
    rm -f "$DROPIN"; CHANGED=1
    note "$(basename "$DROPIN") removed — no destination configured, sockets restricted again"
    rmdir "$DROPIN_DIR" 2>/dev/null || true
  fi
fi

# ------------------------------------------------------- reload and verify ----
echo "=== 4/6  daemon-reload and systemd-analyze verify ==="
systemctl daemon-reload
for u in bayram-backup.service bayram-backup.timer bayram-backup-failed.service; do
  systemd-analyze verify "$UNITDIR/$u" || die "$u does not verify" 4
  note "$u verifies"
done

# `systemd-analyze verify <path>` reads ONE FILE and knows nothing about drop-ins, so it
# cannot tell us whether the merged unit can actually open a socket. Ask the manager, which
# can. This is the assertion that stops "I filled in the env file" from turning into a
# silent nightly failure three weeks later.
if [ -n "$OFFBOX_MODE_CONF" ]; then
  FAMS=$(systemctl show bayram-backup.service -p RestrictAddressFamilies --value)
  case "$FAMS" in
    *AF_INET*) note "socket sandbox: $FAMS (off-box push can reach the network)" ;;
    *) die "MODE=$OFFBOX_MODE_CONF is configured but the merged unit still restricts sockets
       to '$FAMS'. The drop-in at $DROPIN did not take effect. Check it and rerun." 4 ;;
  esac
else
  note "socket sandbox: AF_UNIX only (no off-box destination configured)"
fi

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
# RestrictAddressFamilies against however Postgres is actually reached, the
# CapabilityBoundingSet against what sudo's PAM stack wants, and the sentinel write.
# If any of those is wrong on this host, it is wrong HERE, in front of an operator,
# instead of at 02:30 in front of nobody.
#
# AND, WHEN A DESTINATION IS CONFIGURED, IT REALLY PUSHES. The first off-box copy is a
# real upload to the real destination with the real credential, verified by reading it
# back — which is the only way to find out that the bucket policy is write-only, the host
# key was never pinned, or the endpoint URL has a typo, while somebody is still watching.
# With no destination configured the same step prints one OFF-BOX line and exits 0.
#
# NoNewPrivileges is deliberately NOT set on the service. It is the one hardening
# directive from cutover-to-bayram.sh:150's common() block that is omitted, and the
# reason is mechanical: the unit runs as root and calls setuid `sudo`. It buys
# little on a root unit and can cost the entire backup.
if [ "${SKIP_FIRST_RUN:-0}" = "1" ]; then
  note "SKIP_FIRST_RUN=1 — skipped. Run 'systemctl start bayram-backup.service' yourself."
else
  # WHY THIS IS NOT `systemctl start ... || true` FOLLOWED BY A `Result` READ, WHICH IS WHAT
  # IT USED TO BE. Both halves of that pair lie, and together they made this gate — the one
  # step whose entire job is to fail — incapable of failing:
  #
  #   * `|| true` throws away the only status that reports the job. `systemctl start` on a
  #     Type=oneshot blocks until the job finishes and exits non-zero when it failed, or when
  #     the unit could not be loaded at all.
  #   * `Result` is `success` for a unit that HAS NEVER RUN. Measured read-only on abdu-test
  #     on 2026-09-19, while this timer was still uninstalled:
  #         systemctl show bayram-backup.service -p Result    --value  ->  success
  #         systemctl show bayram-backup.service -p LoadState --value  ->  not-found
  #     A start that never loaded a unit therefore scored "success" and the installer printed
  #     DONE.
  #
  # And `"$SCRIPT" check` below is not a backstop for either, because it passes on ANY
  # sentinel newer than STALE_HOURS=48 — including the one a PREVIOUS install left behind.
  # That is exactly the state the documented flow is in ("configure the off-box copy, then
  # rerun me"): a rerun whose start silently did nothing would print DONE while the first
  # real off-box push had never happened.
  #
  # So: keep the job's exit status, and prove a NEW run happened rather than trusting a
  # verdict that may predate it. InvocationID is systemd's own per-run id — empty for a unit
  # that never ran, and different on every start, successful or not. The sentinel's mtime is
  # the same question asked of our own script instead of systemd's bookkeeping; both have to
  # move, and only then is Result worth reading.
  INVOC_BEFORE=$(systemctl show bayram-backup.service -p InvocationID --value 2>/dev/null || true)
  SENT_BEFORE=$(stat -c %Y "$SENTINEL" 2>/dev/null || echo 0)

  START_RC=0
  systemctl start bayram-backup.service || START_RC=$?

  INVOC_AFTER=$(systemctl show bayram-backup.service -p InvocationID --value 2>/dev/null || true)
  RESULT=$(systemctl show bayram-backup.service -p Result --value 2>/dev/null || true)
  SENT_AFTER=$(stat -c %Y "$SENTINEL" 2>/dev/null || echo 0)

  FIRSTRUN_FAIL=""
  if [ "$START_RC" -ne 0 ]; then
    FIRSTRUN_FAIL="'systemctl start bayram-backup.service' exited $START_RC (Result=$RESULT)"
  elif [ -z "$INVOC_AFTER" ]; then
    FIRSTRUN_FAIL="the unit has no InvocationID after the start, so it never ran at all.
       Result=$RESULT is meaningless here — systemd reports 'success' for a unit it never
       executed. Ask whether it even loaded:
           systemctl show bayram-backup.service -p LoadState --value"
  elif [ "$INVOC_AFTER" = "$INVOC_BEFORE" ]; then
    FIRSTRUN_FAIL="the unit's InvocationID did not change across the start ($INVOC_AFTER),
       so no new run happened and Result=$RESULT is an EARLIER run's verdict."
  elif [ "$RESULT" != "success" ]; then
    FIRSTRUN_FAIL="the run finished with Result=$RESULT"
  elif [ "$SENT_AFTER" = "0" ]; then
    FIRSTRUN_FAIL="the run reported success but wrote no sentinel at $SENTINEL"
  elif [ "$SENT_AFTER" = "$SENT_BEFORE" ]; then
    FIRSTRUN_FAIL="the run reported success but did not rewrite $SENTINEL — its mtime is
       unchanged, so 'bayram-backup check' below would be passing on a PREVIOUS install's
       sentinel and this rerun proved nothing."
  fi

  if [ -n "$FIRSTRUN_FAIL" ]; then
    echo "--- journal ---" >&2
    journalctl -u bayram-backup.service -n 40 --no-pager >&2 || true
    die "the first backup FAILED: $FIRSTRUN_FAIL
       The timer is installed and enabled, but it will fail the same way at 02:30.
       Fix this before you walk away." 4
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

  THE MECHANISM IS INSTALLED; THE DESTINATION IS THE PART STILL MISSING. Nothing above
  needs another line of code — it needs A, B or C chosen. When one is:

      sudoedit /etc/bayram/backup-offbox.env        # 0600 root:root, refused at any other mode
        BAYRAM_BACKUP_OFFBOX_MODE=s3                #   or rsync, or command
        BAYRAM_BACKUP_OFFBOX_DEST=s3://bucket/bayram/nightly
        ...                                         # see backup-offbox.env.example
      sudo bash /tmp/install-bayram-backup.sh        # REQUIRED: this is what lets the unit
                                                     # open a socket at all (10-offbox.conf)
      sudo systemctl start bayram-backup.service
      sudo /opt/bayram/sbin/bayram-backup status     # "offbox": "ok", and when
      sudo /opt/bayram/sbin/bayram-backup check-offbox

  Three transports behind one switch, and no provider named in any of them: s3 is an
  endpoint URL and a bucket path, so R2, B2, Wasabi, MinIO and AWS are the same three
  lines with a different URL; rsync is a host and a path over ssh with the key pinned;
  command is your own root-owned 0700 executable, called with the dump as $1 and the
  destination as $2 — which is the OLD /etc/bayram/backup-offsite.hook contract, still
  honoured, and still picked up automatically if that file exists.

  Every upload is read back and compared before the run is called a success (size for s3,
  an end-to-end `rsync -c` checksum for rsync). That is the `test -s` argument one hop
  further out: a silently truncated copy is worse than no copy, because it looks like
  protection. Verifying needs read access to the object you just wrote — if you scoped the
  credential write-only, as option B above recommends, set BAYRAM_BACKUP_OFFBOX_VERIFY=0
  and know that you chose to have nothing check what arrived.

  A failed copy fails the whole backup, as it always did (BAYRAM_BACKUP_OFFBOX_REQUIRED=1).
  BAYRAM_BACKUP_OFFBOX_REQUIRED=0 downgrades it to a loud line and "offbox": "failed".

  OFF-BOX RETENTION IS THE DESTINATION'S JOB. This script prunes its own 14 local dailies
  and never deletes anything at the far end, on purpose: a nightly root job that can delete
  remote backups is a nightly root job that can delete all of them. Use a bucket lifecycle
  rule or a cron at the far end, and write down which you chose.

  Until a destination exists, every run prints OFF-BOX: not configured and the sentinel
  says "not-configured" — an honest state rather than a silent absence, and NOT a failure:
  the unit stays green, `check` stays green, and the unit keeps its AF_UNIX-only sandbox.

  And the thing off-box copies still will not fix: BAYRAM_ADMIN_AUDIT_HMAC_KEY is in
  no database dump at all, so none of A/B/C protects the audit chain. 05-operations.md
  is also explicit that the key must NOT travel with the dump.

TO REMOVE
  sudo systemctl disable --now bayram-backup.timer
  sudo rm /etc/systemd/system/bayram-backup{.timer,.service,-failed.service}
  sudo rm -rf /etc/systemd/system/bayram-backup.service.d
  sudo rm /opt/bayram/sbin/bayram-backup
  sudo systemctl daemon-reload
  (The dumps in /var/backups/bayram are left alone on purpose, and so is
   /etc/bayram/backup-offbox.env — it holds a credential and deleting it is a decision.)
CLOSING
