#!/usr/bin/env bash
# prune-stale-sudo-grants.sh — remove the sudo grants on abdu-test that nothing needs any more,
# and (on its own flag) the blanket passwordless-root rule that makes all the others cosmetic.
# Runs ON THE HOST, as root. Nothing in this repo runs it for you, and nothing should.
#
# STAGE IT AS ROOT — DO NOT RUN IT OUT OF /tmp. The script AND the drop-in it installs both
# have to travel (it reads the policy from the repo, so there is one source of truth and no
# content is duplicated inside this script), and neither may sit, even for a minute, in a
# directory a non-root account can write. /tmp is world-writable and an scp lands the files
# developer:developer, so between the copy and the run anything that can write as `developer`
# chooses the sudoers policy that root installs. That is not theoretical:
# deploy/install-bayram-backup.sh carries the same warning for its own staging, and a
# developer-owned copy of THAT script has been sitting in /tmp since 2026-09-17, unrun.
#
#   # 1. copy to the world-writable landing zone, and note the digests on your workstation:
#   scp -r deploy/prune-stale-sudo-grants.sh deploy/sudoers.d aizu:/tmp/
#   shasum -a 256 deploy/prune-stale-sudo-grants.sh deploy/sudoers.d/bayram-deploy
#
#   # 2. IMMEDIATELY re-stage as root into a root-owned directory, and print what landed.
#   #    Compare those two digests with the ones from step 1 BEFORE step 3: that comparison
#   #    is what closes the /tmp window, and it is the operator's job, not the script's.
#   ssh -t aizu 'sudo install -d -m 0755 -o root -g root /opt/bayram/stage /opt/bayram/stage/sudoers.d &&
#                sudo install -m 0644 -o root -g root /tmp/prune-stale-sudo-grants.sh /opt/bayram/stage/ &&
#                sudo install -m 0644 -o root -g root /tmp/sudoers.d/bayram-deploy   /opt/bayram/stage/sudoers.d/ &&
#                sudo sha256sum /opt/bayram/stage/prune-stale-sudo-grants.sh /opt/bayram/stage/sudoers.d/bayram-deploy'
#
#   # 3. run it from there. The script REFUSES to read itself or the drop-in out of any path
#   #    that is not root-owned and unwritable by group and other — every directory up to /
#   #    included — so a run straight out of /tmp stops instead of installing whatever is
#   #    sitting there. It prints the same two digests before it does anything.
#   ssh -t aizu 'sudo bash /opt/bayram/stage/prune-stale-sudo-grants.sh plan'   # DRY RUN.
#   ssh -t aizu 'sudo bash /opt/bayram/stage/prune-stale-sudo-grants.sh apply'
#   ssh -t aizu 'sudo bash /opt/bayram/stage/prune-stale-sudo-grants.sh apply --drop-blanket'
#
#   # 4. clear the landing zone, so the next person does not find a stale copy and trust it:
#   ssh aizu 'rm -rf /tmp/prune-stale-sudo-grants.sh /tmp/sudoers.d'
#
# /opt/bayram/stage is only a suggestion, and the script checks rather than assumes: if
# /opt/bayram itself turns out to be developer-owned — /opt/hbd is — it names the offending
# directory and stops. /root/stage is the staging directory that is root-owned 0700 by
# definition on every host; use it instead and the rest of the recipe is unchanged.
#
# `plan` is the default and `apply` is the only verb that writes, the same split
# deploy/bayram-release uses for the same reason: the dry run is what an operator can afford to
# run without thinking about it, so it must be the thing that happens when they do.
#
# ------------------------------------------------------------------------------------------
# KEEP A SECOND ROOT SHELL OPEN ON THIS HOST FOR THE WHOLE OPERATION.
#
# A malformed sudoers file breaks sudo for EVERY account, and on abdu-test that is not
# recoverable over ssh: /root/.ssh/authorized_keys is zero bytes and sshd reports
# `permitrootlogin without-password`, so recovery means the VPS provider's out-of-band console.
# This script validates with `visudo -cf` BEFORE anything lands, validates the whole tree with
# `visudo -c` after, re-checks that a representative load-bearing verb still resolves, and
# restores its own backup if either fails. None of that replaces the second shell.
# ------------------------------------------------------------------------------------------
#
# WHAT IT DOES, and the evidence for each removal (survey of 2026-09-19, re-measured live):
#
#   1. Installs deploy/sudoers.d/bayram-deploy — the post-cutover version, with the hbd-*
#      rollback grants, the wildcard `journalctl` alias, the four `systemctl status` verbs and
#      the `tee /etc/bayram/payme.env` grant removed, and the still-live Caddy verbs re-homed
#      into it. That file's own header records each removal and the exact line to undo it.
#
#   2. Prunes /etc/sudoers.d/hbd-deploy. Every grant in it is now either stale (hbd-* units,
#      /etc/hbd paths), re-homed (caddy), or a duplicate (daemon-reload) — EXCEPT
#      `(postgres) NOPASSWD: /usr/bin/pg_dump hbd`, which the survey classified SUSPECT: no
#      script needs it (every candidate caller already runs as root, and root needs no sudoers
#      entry to `sudo -u postgres`), but docs/deployment/08-payme.md documents it as the
#      sanctioned read path into production data for debugging. SUSPECT ENTRIES ARE LISTED FOR
#      THE OWNER, NOT DELETED: the file is reduced to that one line unless --drop-pg-dump says
#      otherwise, and the reduced file carries a header saying why it survived.
#
#   3. On --drop-blanket ONLY, removes /etc/sudoers.d/90-developer-nopasswd, which contains
#      `developer ALL=(ALL) NOPASSWD:ALL` (33 bytes, mtime 2026-09-17 13:55 — the day after the
#      audit that closed the previous escalation). Verified live, not inferred:
#      `ssh aizu 'sudo -n /usr/bin/id -u'` -> 0. While that file exists, EVERY per-grant change
#      above is cosmetic.
#
# WHY THAT IS A SEPARATE FLAG. Removing it is a real behaviour change for humans: every ad-hoc
# `ssh aizu 'sudo ...'` without `-t` starts failing on a password prompt it cannot answer, and
# anyone with that muscle memory will read it as an outage. The clutter cleanup should not be
# held hostage to that decision, and the two acts should be separately reversible. It is safe
# in the sense that matters — `passwd -S developer` reports `P`, so the `(ALL:ALL) ALL` password
# path works, and this script REFUSES to drop the blanket rule if that is ever not true.
#
# WHAT IT DOES NOT TOUCH, on purpose:
#   * /etc/sudoers itself, /etc/sudoers.d/README, /etc/sudoers.d/aizu-deploy (a different
#     product's unit) and /etc/sudoers.d/bayram-release (current, and its `PASSWD:` lines are
#     the point).
#   * sshd. `PasswordAuthentication yes` plus a password-bearing `developer` plus NOPASSWD:ALL
#     is one guessed password away from unattended root on the host that terminates payment
#     callbacks, and turning it off is the right move — but it belongs to whoever owns ssh
#     policy and must not ride along inside a sudoers change.
#
# Exit codes: 0 ok · 1 usage/config · 2 precondition refused (nothing changed) · 3 failed
# mid-change (read the output; a restore was attempted) · 4 post-change verification failed
# (restored from backup).

set -euo pipefail
# -E so the ERR trap is inherited by functions and command substitutions, the same reason
# deploy/bayram-release sets it.
set -E

# ============================================================================================
# Constants
# ============================================================================================
ACCOUNT=developer
SUDOERSD=/etc/sudoers.d

LIVE_DEPLOY="$SUDOERSD/bayram-deploy"            # replaced with the repo's copy
LIVE_HBD="$SUDOERSD/hbd-deploy"                  # pruned to its SUSPECT remainder, or removed
LIVE_BLANKET="$SUDOERSD/90-developer-nopasswd"   # removed only on --drop-blanket

BACKUP_DIR=/var/backups/sudoers

# The four units that must be running for this to be the host we think it is.
UNITS=(bayram-admin bayram-bot bayram-worker bayram-payme)

# Where the new drop-in is read from. Defaults to sudoers.d/ beside this script, which is what
# the root-owned staging directory in the header produces. The policy is NOT embedded in this
# script: two copies of a sudoers file in one repo is two files to keep in step, and the one
# that drifts is the one that gets installed. Wherever it comes from, it has to pass
# require_trusted_inputs first.
SRC_DIR=""

MODE=plan
DROP_BLANKET=no
DROP_PG_DUMP=no

BACKUP=""          # set once the tarball exists
BACKUP_MEMBERS=""  # the tar members the backup MUST contain to be a usable rollback
CHANGED=no         # set the moment anything on disk has been written
STAGE_NAME="startup"
STAGE_EXIT=2

# Set by verify_load_bearing when the blanket rule is still in place and `sudo -l` therefore
# answers "yes" to everything. Read by check_verb so its lines do not read as proof.
VERIFY_BLIND=no

# ============================================================================================
# Output and failure
# ============================================================================================
say()  { printf '%s\n' "$*"; }
step() { printf '\n=== %s ===\n' "$*"; }
note() { printf '  %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }

die_usage() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
refuse()    { printf '\nREFUSED: %s\n' "$*" >&2
              # Only claim nothing changed when nothing has. A refusal that lies about the
              # state of the host is worse than no message: the operator stops looking.
              if [ "$CHANGED" = yes ]; then
                printf 'FILES WERE ALREADY WRITTEN. Restore with:  tar -xzpf %s -C /\n' \
                  "$BACKUP" >&2
                exit 3
              fi
              printf 'Nothing on this host was changed.\n' >&2; exit 2; }

on_err() {
  local code=$?
  # Disarm first: restore_backup below runs `tar` and `visudo`, and a failure in either would
  # otherwise re-enter this handler recursively.
  trap - ERR
  printf '\n%s\n' "-----------------------------------------------------------------" >&2
  printf 'ABORTED in stage "%s": command failed with status %s at line %s.\n' \
    "$STAGE_NAME" "$code" "${BASH_LINENO[0]:-?}" >&2
  if [ "$CHANGED" = yes ]; then
    printf 'FILES WERE ALREADY WRITTEN. Attempting to restore the backup.\n' >&2
    restore_backup || printf 'RESTORE FAILED. Restore by hand: tar -xzpf %s -C /\n' "$BACKUP" >&2
  else
    printf 'Nothing was changed on this host.\n' >&2
  fi
  exit "$STAGE_EXIT"
}
trap on_err ERR

usage() {
  cat <<'USAGE'
prune-stale-sudo-grants.sh — remove the sudo grants on abdu-test that nothing needs.

  prune-stale-sudo-grants.sh plan  [--drop-blanket] [--drop-pg-dump]
  prune-stale-sudo-grants.sh apply [--drop-blanket] [--drop-pg-dump] [--source-dir DIR]

  plan             DRY RUN, and the default. Prints every file it would touch, every grant
                   line it would remove and why, and exits. Changes nothing.
  apply            Do it: back up, validate, install, prune, verify, roll back on failure.

  --drop-blanket   ALSO remove /etc/sudoers.d/90-developer-nopasswd
                   (`developer ALL=(ALL) NOPASSWD:ALL`). This is the change that actually
                   matters; it is a separate flag because it is also the one that changes what
                   humans can do. Refused if `developer` has no usable password, because after
                   it the (ALL:ALL) ALL password path is the ONLY remaining route to root.
  --drop-pg-dump   ALSO remove `(postgres) NOPASSWD: /usr/bin/pg_dump hbd`. Without it that
                   grant is KEPT and listed: the survey classified it SUSPECT — no script needs
                   it, but it is a documented human debugging path, so it is an owner decision.
  --source-dir DIR Read the drop-in to install from DIR instead of ./sudoers.d beside this
                   script. DIR must contain a file named `bayram-deploy`.

Add `plan` to any invocation you are unsure about; `plan` and `apply` take the same flags and
`plan` prints exactly what `apply` would do with them.

Exit codes: 0 ok · 1 usage/config · 2 precondition refused (nothing changed) · 3 failed
mid-change · 4 post-change verification failed (restored from backup).
USAGE
}

# ============================================================================================
# Preconditions — every one of these is a thing that has actually been wrong on some host
# ============================================================================================
require_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    die_usage "run me as root:  sudo bash $0 $MODE"
  fi
}

require_binaries() {
  local b
  for b in visudo install tar gzip sudo systemctl getent passwd stat readlink dirname date grep; do
    command -v "$b" >/dev/null 2>&1 || die_usage "missing required binary: $b"
  done
}

resolve_source() {
  if [ -z "$SRC_DIR" ]; then
    SRC_DIR="$(cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)/sudoers.d"
  fi
  SRC_DEPLOY="$SRC_DIR/bayram-deploy"
  if [ ! -r "$SRC_DEPLOY" ]; then
    refuse "cannot read $SRC_DEPLOY.
       This script installs the repo's drop-in rather than carrying a copy of it, so the file
       has to travel with it — into a ROOT-OWNED staging directory, not /tmp; the four-step
       install is in this script's header. Or point at it:
           --source-dir /path/to/root-owned/sudoers.d"
  fi
}

# --------------------------------------------------------------------------------------------
# The source has to be as trustworthy as the thing it becomes.
#
# Root runs this script and root installs what it reads, so nothing it reads may live where a
# non-root account can write it. The documented install used to be `scp ... aizu:/tmp/` and then
# `sudo bash /tmp/prune-stale-sudo-grants.sh apply`: /tmp is world-writable, the staged files
# land developer:developer, and in the window between the copy and the run whoever can write as
# `developer` picks the sudoers policy root installs. That is the same shape as the 2026-09-16
# finding this script exists to close (a NOPASSWD grant on a developer-owned script IS
# passwordless root), and deploy/install-bayram-backup.sh already warns about the window for its
# own staging. A stale developer-owned copy of that script has been in /tmp since 2026-09-17.
#
# WHAT IS REQUIRED, exactly: this script's own file and $SRC_DEPLOY must be owned by uid 0 and
# carry no write bit for group or other — 0600 or 0644 (and 0400/0440/0444/0640, which are
# stricter still) — and so must EVERY directory above them, up to /. The directory chain is not
# a detail: a root-owned 0644 file inside a developer-owned directory can be renamed out of the
# way and replaced, which is exactly what /tmp allows.
# --------------------------------------------------------------------------------------------

# Prints why $1 — or a directory above it — is not trustworthy, and prints NOTHING when the
# whole chain is root-owned and unwritable by anyone but root. It never returns non-zero: a
# `return 1` here would be a failed command inside the caller's `$( )`, and the ERR trap IS
# inherited into a command substitution (that is what `set -E` does) even when the substitution
# sits in an `if` condition — so a clean, trusted path printed "ABORTED in stage startup" and
# then carried on. The verdict is the string, not the status.
untrusted_reason() {
  local p u m
  # Every `|| true` here is INSIDE its substitution on purpose: `set -E` carries the ERR trap
  # into a command substitution, so a failure caught outside it still prints an ABORT banner
  # from the subshell first. An empty result is the failure signal instead.
  p="$(readlink -f -- "$1" 2>/dev/null || true)"
  if [ -z "$p" ]; then printf 'cannot resolve %s' "$1"; return 0; fi
  while : ; do
    u="$(stat -c '%u' -- "$p" 2>/dev/null || true)"
    m="$(stat -c '%a' -- "$p" 2>/dev/null || true)"
    if [ -z "$u" ] || [ -z "$m" ]; then printf 'cannot stat %s' "$p"; return 0; fi
    while [ "${#m}" -lt 4 ]; do m="0$m"; done
    if [ "$u" != 0 ]; then
      printf '%s is owned by uid %s, not root (mode %s)' "$p" "$u" "$m"; return 0
    fi
    # Digits are octal, so the write bit is 2: 2,3,6,7 all carry it. `other` is tested first
    # because it is the one that names the actual problem on the path people reach for: /tmp
    # is 1777, and "world-writable" is the sentence an operator needs to read.
    case "${m:3:1}" in 2|3|6|7) printf '%s is world-writable (mode %s)' "$p" "$m"; return 0 ;; esac
    case "${m:2:1}" in 2|3|6|7) printf '%s is group-writable (mode %s)' "$p" "$m"; return 0 ;; esac
    if [ "$p" = / ]; then break; fi
    p="$(dirname -- "$p")"
  done
  return 0
}

require_trusted_inputs() {
  local self reason
  self="$(readlink -f -- "$0" 2>/dev/null || true)"
  [ -n "$self" ] || self="$0"

  reason="$(untrusted_reason "$self")"
  if [ -n "$reason" ]; then
    refuse "this script is running from a path root cannot trust: $reason.
       Root executes this file and installs what it reads, so a path anyone else can write is
       a path where somebody else writes the sudoers policy. Re-stage as root and run it from
       there (step 2 of the install in this file's header):
           sudo install -d -m 0755 -o root -g root /opt/bayram/stage
           sudo install -m 0644 -o root -g root /tmp/prune-stale-sudo-grants.sh /opt/bayram/stage/
           sudo bash /opt/bayram/stage/prune-stale-sudo-grants.sh $MODE
       Required: uid 0 and no group/other write bit (0600 or 0644), on the file AND on every
       directory above it."
  fi

  reason="$(untrusted_reason "$SRC_DEPLOY")"
  if [ -n "$reason" ]; then
    refuse "the drop-in this would install lives on a path root cannot trust: $reason.
       $SRC_DEPLOY is the file that becomes $LIVE_DEPLOY — the whole operational grant — so it
       has to be root's before root reads it, not after. Re-stage it as root:
           sudo install -d -m 0755 -o root -g root /opt/bayram/stage/sudoers.d
           sudo install -m 0644 -o root -g root /tmp/sudoers.d/bayram-deploy /opt/bayram/stage/sudoers.d/
           sudo bash /opt/bayram/stage/prune-stale-sudo-grants.sh $MODE --source-dir /opt/bayram/stage/sudoers.d
       Required: uid 0 and no group/other write bit (0600 or 0644), on the file AND on every
       directory above it."
  fi

  # The digests, so the operator can compare them with the ones taken on the workstation before
  # the scp. The ownership check above proves nothing can change these files from here on; only
  # that comparison proves nothing changed them in the landing zone beforehand.
  if command -v sha256sum >/dev/null 2>&1; then
    say "source, verified root-owned and unwritable by anyone else:"
    sha256sum -- "$self" "$SRC_DEPLOY" 2>/dev/null | sed 's/^/  /' || true
    say "  ^ compare with: shasum -a 256 deploy/prune-stale-sudo-grants.sh deploy/sudoers.d/bayram-deploy"
  else
    say "source, verified root-owned and unwritable by anyone else: $self, $SRC_DEPLOY"
  fi
}

# The ordering assertion that keeps Caddy alive. hbd-deploy is the ONLY source of the Caddy
# grants on this host, and caddy.service is the local hop for pay.bayrambot.uz -> 127.0.0.1:8091
# (the Payme gateway) and admin.bayrambot.uz -> 127.0.0.1:8080 behind the Cloudflare tunnel.
# Pruning hbd-deploy before those verbs exist somewhere else takes the front end's operational
# verbs with it, so this refuses rather than trusting the order of the steps below.
require_caddy_rehomed() {
  local missing=0 v
  for v in \
    '/usr/bin/systemctl reload caddy.service' \
    '/usr/bin/systemctl restart caddy.service' \
    '/usr/bin/caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile'
  do
    grep -qF -- "$v" "$SRC_DEPLOY" || { warn "not re-homed: $v"; missing=1; }
  done
  if [ "$missing" -eq 1 ]; then
    refuse "$SRC_DEPLOY does not contain the Caddy verbs listed above, and this script is about
       to remove the only other file that grants them ($LIVE_HBD). caddy.service is live and
       fronts the Payme callback path. Fix the drop-in first."
  fi
}

require_host_identity() {
  local u state
  getent passwd "$ACCOUNT" >/dev/null 2>&1 \
    || refuse "no account named '$ACCOUNT' on this host; this is not abdu-test."

  for u in "${UNITS[@]}"; do
    state="$(systemctl is-active "$u.service" 2>/dev/null || true)"
    [ "$state" = active ] \
      || refuse "$u.service is '$state', not 'active'. This script assumes the four bayram-*
       units are the running fleet — that is the whole basis for calling the hbd-* grants
       stale. Sort the fleet out first."
  done

  test -x /opt/bayram/sbin/bayram-release \
    || refuse "/opt/bayram/sbin/bayram-release is missing or not executable. The release grant
       in /etc/sudoers.d/bayram-release points at it; if it is not there, this host is not in
       the state this cleanup was measured against."

  local owner
  owner="$(stat -c '%U:%G' /opt/bayram/sbin/bayram-release)"
  [ "$owner" = "root:root" ] \
    || refuse "/opt/bayram/sbin/bayram-release is owned by $owner, not root:root. A NOPASSWD
       grant on a file its invoker can write IS passwordless root — that is the 2026-09-16
       finding, and fixing this is a prerequisite, not a footnote."

  test -f "$LIVE_DEPLOY" \
    || refuse "$LIVE_DEPLOY does not exist. Install it the ordinary way first (its header has
       the three commands); this script replaces that file, it does not introduce it."
}

# The check that makes --drop-blanket safe to run at all. After the blanket rule goes, the
# `(ALL:ALL) ALL` password path is the ONLY route to root on this host: /root/.ssh/
# authorized_keys is zero bytes and sshd is `permitrootlogin without-password`.
require_password_path() {
  local raw state
  # `|| true` INSIDE each substitution, which is the same idiom require_host_identity uses on
  # `systemctl is-active`, and it is load-bearing twice over. As a bare assignment,
  #     state="$(passwd -S "$ACCOUNT" 2>/dev/null | awk '{print $2}')"
  # under `set -euo pipefail` aborted the whole script the moment `passwd -S` failed (no such
  # account on a shadow-less host, a locked-down /etc/shadow, a busybox passwd with no -S), so
  # the `*)` branch below — written precisely to explain that case — could never run. And
  # `set -E` puts the ERR trap inside the command substitution too, so catching the status in
  # an `if` is not enough: the subshell still printed 'ABORTED in stage "startup"' before the
  # parent carried on. Failing inside an OR-list is the only form that is silent.
  raw="$(passwd -S "$ACCOUNT" 2>/dev/null || true)"
  state="$(printf '%s\n' "$raw" | awk '{print $2}' || true)"
  case "$state" in
    P) return 0 ;;
    L) state="a locked password" ;;
    NP) state="no password at all" ;;
    '') state="an unreadable password status ('passwd -S $ACCOUNT' failed or printed nothing)" ;;
    *) state="an unrecognised password status ('$state')" ;;
  esac
  if [ "$DROP_BLANKET" = yes ]; then
    refuse "'$ACCOUNT' has $state, so removing $LIVE_BLANKET would leave NO usable route to
       root on this host (/root/.ssh/authorized_keys is empty and sshd is
       'permitrootlogin without-password'). Set a password first:  passwd $ACCOUNT"
  fi
  warn "'$ACCOUNT' has $state. Not fatal here because --drop-blanket was not given, but it"
  warn "means the password path to root is not usable, so --drop-blanket must not be run"
  warn "until it is. Check: passwd -S $ACCOUNT"
}

# ============================================================================================
# Classifying the lines in hbd-deploy
# ============================================================================================
# Every grant line gets a verdict, and an UNRECOGNISED one is a refusal rather than a guess.
# The file was surveyed on 2026-09-19; if somebody has since added a line, this script has no
# basis for calling it stale and says so instead of deleting it.
#
#   STALE     names an hbd-* unit or an /etc/hbd path — the rollback window closed 2026-09-14
#   REHOMED   a caddy verb, now carried by bayram-deploy
#   DROPPED   `tee /etc/caddy/Caddyfile` — deliberately NOT re-homed; it is an unattended root
#             write of arbitrary content into the front end of the Payme callback path
#   DUPLICATE daemon-reload, already granted by bayram-deploy
#   SUSPECT   pg_dump — kept unless --drop-pg-dump
#
# The verdict is per LINE, and a sudoers line can carry several commands: the live
# `tee /etc/hbd/payme.env, tee /etc/caddy/Caddyfile` line is one STALE command and one DROPPED
# one. The verdict names the strongest reason the line goes; every command on these lines goes
# for one of the reasons listed above, and the removal record in deploy/sudoers.d/bayram-deploy
# carries the exact line to put any of them back.
classify_line() {
  local line="$1"
  case "$line" in
    *pg_dump*)                                   printf 'SUSPECT' ;;
    *tee*Caddyfile*)                             printf 'DROPPED' ;;
    *caddy*|*Caddyfile*)                         printf 'REHOMED' ;;
    *hbd-*|*/etc/hbd/*)                          printf 'STALE' ;;
    *'systemctl daemon-reload')                  printf 'DUPLICATE' ;;
    *)                                           printf 'UNKNOWN' ;;
  esac
}

# Prints "VERDICT<TAB>line" for every non-comment, non-blank line of $LIVE_HBD.
survey_hbd() {
  local line verdict
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    verdict="$(classify_line "$line")"
    printf '%s\t%s\n' "$verdict" "$line"
  done < "$LIVE_HBD"
}

# An unrecognised grant in hbd-deploy is a REFUSAL, and it has to happen here — before the
# first write — or the refusal arrives after bayram-deploy is already installed, which is a
# half-done cleanup and a message that has to walk it back.
require_recognised_hbd() {
  [ -f "$LIVE_HBD" ] || return 0
  local verdict line unknown=0
  while IFS=$'\t' read -r verdict line; do
    [ "$verdict" = UNKNOWN ] || continue
    warn "unrecognised grant in $LIVE_HBD: $line"
    unknown=1
  done < <(survey_hbd)
  [ "$unknown" -eq 0 ] || refuse "$LIVE_HBD contains grant lines that were not in the
       2026-09-19 survey (listed above). This script will not guess whether they are stale.
       Survey them, then either fold them into deploy/sudoers.d/bayram-deploy or delete them by
       hand, and run this again."
}

# ============================================================================================
# Backup and restore
# ============================================================================================
# The members the backup MUST contain to be a usable rollback, captured from what is live at
# the moment the backup is taken — which is exactly the set of files this run may replace or
# delete. `etc/sudoers.d/90-developer-nopasswd` is the one that matters most: on
# --drop-blanket the tarball is the ONLY route back to passwordless root, and by the time you
# want it back it is no longer on disk to compare against.
expected_backup_members() {
  printf '%s\n' "etc/sudoers"
  [ -f "$LIVE_DEPLOY" ]  && printf '%s\n' "${LIVE_DEPLOY#/}"
  [ -f "$LIVE_HBD" ]     && printf '%s\n' "${LIVE_HBD#/}"
  [ -f "$LIVE_BLANKET" ] && printf '%s\n' "${LIVE_BLANKET#/}"
  return 0
}

# Every file this run is allowed to create, replace or remove. A restore means putting the
# tree back to exactly what the tarball holds FOR THESE PATHS — which includes deleting one
# that the run created and the tarball therefore cannot carry.
managed_paths() {
  printf '%s\n' "$LIVE_DEPLOY" "$LIVE_HBD" "$LIVE_BLANKET"
}

# "A backup you did not check is a backup you do not have" — deploy/install-bayram-backup.sh
# applies `test -s` AND `gzip -t` to the nightly database dump for this reason, and this
# tarball is the only thing standing between a bad apply and a host with no route to root.
# It gets the same two guards plus a manifest check: an empty or truncated archive, or one
# that somehow does not carry the drop-ins, is not a rollback.
verify_backup() {
  local listing m missing=0
  [ -n "$BACKUP" ] && [ -f "$BACKUP" ] || { warn "there is no backup file to verify."; return 1; }
  test -s "$BACKUP" || { warn "the backup $BACKUP is empty."; return 1; }
  gzip -t -- "$BACKUP" 2>/dev/null || {
    warn "the backup $BACKUP is not a complete gzip (truncated, or the disk filled)."
    return 1
  }
  listing="$(tar -tzf "$BACKUP" 2>/dev/null || true)"
  [ -n "$listing" ] || {
    warn "the backup $BACKUP lists no members: it is not a tar archive, or it is empty."
    return 1
  }
  while IFS= read -r m; do
    [ -n "$m" ] || continue
    # A here-string for the reason restore_backup gives: `grep -q` + `pipefail` turns a
    # match into a 141. Here that spelling would report a present member as missing, and
    # restore_backup refuses to extract a backup that "did not verify".
    grep -qxF -- "$m" <<<"$listing" || {
      warn "the backup $BACKUP is missing $m — it cannot restore what this run removes."
      missing=1
    }
  done <<MEMBERS
$BACKUP_MEMBERS
MEMBERS
  [ "$missing" -eq 0 ] || return 1
  return 0
}

take_backup() {
  install -d -m 0700 -o root -g root "$BACKUP_DIR"
  BACKUP="$BACKUP_DIR/sudoers-$(date +%Y%m%dT%H%M%S).tar.gz"
  BACKUP_MEMBERS="$(expected_backup_members)"
  # 0600 root:root: this tarball contains the whole sudo policy, including the blanket rule
  # this run may be about to remove. It is a map of the host's privilege boundaries.
  ( umask 077; tar -czf "$BACKUP" -C / etc/sudoers etc/sudoers.d )
  chmod 0600 "$BACKUP"
  # Before anything is written, and before the operator is told to trust it. Nothing has
  # changed yet, so a bad archive is a plain refusal.
  verify_backup || refuse "the backup just taken did not verify (above), so there would be no
       way back from this change. Nothing else was attempted. Check the free space on
       $BACKUP_DIR and that /etc/sudoers.d is readable, then run this again."
  say "backup: $BACKUP"
  say "verified: non-empty, a complete gzip, and it carries:"
  printf '%s\n' "$BACKUP_MEMBERS" | sed 's/^/  \//'
  say "rollback, at any point, in one line:   tar -xzpf $BACKUP -C /"
}

restore_backup() {
  [ -n "$BACKUP" ] && [ -f "$BACKUP" ] || return 1
  # Verify BEFORE extracting. An unverified `tar -xzpf` over /etc/sudoers.d is a second
  # failure landing on top of the first one, and this path only runs when something has
  # already gone wrong.
  verify_backup || {
    warn "REFUSING to extract $BACKUP: it did not verify (above). The host is in whatever"
    warn "state the failed step left it in. Do not close your other root shell; fix"
    warn "$SUDOERSD by hand from the diff this run printed. The one-line rollback printed"
    warn "earlier names this same archive, so it will not work either."
    return 1
  }
  say "restoring $BACKUP"
  # -p to keep 0440 root:root on the drop-ins. Extraction puts back files this run removed and
  # overwrites files it replaced. It does NOT delete a file the tarball lacks, and this script
  # DOES create filenames that were not there when the backup was taken:
  # install_deploy_dropin writes $LIVE_DEPLOY whether or not it existed — on a host that has
  # never carried a bayram-deploy drop-in, that file is not in the tarball, so extraction
  # alone leaves the newly installed grant LIVE while this function prints "restored, and
  # 'visudo -c' parses". That is the loudest possible way to be wrong: a restore that reports
  # success and leaves the change it was undoing in place. So extraction is half the restore
  # and the sweep below is the other half.
  local listing m path member
  tar -xzpf "$BACKUP" -C / || {
    warn "the extraction itself failed. Do not close your other root shell."
    return 1
  }
  # Anything this script manages that the archive does not carry was created by this run.
  listing="$(tar -tzf "$BACKUP" 2>/dev/null || true)"
  [ -n "$listing" ] || { warn "the restored archive lists no members; cannot tell what this run created."; return 1; }
  while IFS= read -r path; do
    [ -e "$path" ] || continue
    member="${path#/}"
    # A here-string, NOT `printf ... | grep -q`: `grep -q` exits on its first match, the
    # writer takes SIGPIPE, and `set -o pipefail` hands the whole pipeline 141 — a match
    # read as a miss, which here would DELETE a file the backup does carry. It only shows
    # up once the listing outgrows the pipe buffer, which is the worst way to find out.
    if grep -qxF -- "$member" <<<"$listing"; then continue; fi
    rm -f -- "$path" || {
      warn "$path was created by this run and is not in the backup, and it could not be"
      warn "removed. It is STILL LIVE. Do not close your other root shell."
      return 1
    }
    say "  removed $path — this run created it and the backup predates it."
  done < <(managed_paths)
  # And the other end: the members are back on disk, not merely present in the archive.
  while IFS= read -r m; do
    [ -n "$m" ] || continue
    [ -e "/$m" ] || { warn "after the restore, /$m is still missing."; return 1; }
  done <<MEMBERS
$BACKUP_MEMBERS
MEMBERS
  visudo -c >/dev/null || {
    warn "the RESTORED tree does not parse. Do not close your other root shell."
    return 1
  }
  say "restored, and 'visudo -c' parses."
}

# ============================================================================================
# Verification
# ============================================================================================
# `sudo -l -U <user> <cmd>` asks the policy whether the account may run exactly that argument
# vector, and exits non-zero when it may not. It is a listing query: it runs nothing.
check_verb() {
  local desc="$1"; shift
  if sudo -l -U "$ACCOUNT" "$@" >/dev/null 2>&1; then
    if [ "$VERIFY_BLIND" = yes ]; then
      note "resolves (PROVES NOTHING — see above)  $desc"
    else
      note "OK      $desc"
    fi
    return 0
  fi
  note "MISSING $desc"
  return 1
}

verify_load_bearing() {
  local failed=0
  step "verify — the load-bearing verbs still resolve for '$ACCOUNT'"

  # The same blindness report_closed_holes already makes, for the same reason — and it matters
  # more here, because THIS function's result is what triggers the automatic restore. While
  # /etc/sudoers.d/90-developer-nopasswd grants ALL=(ALL) NOPASSWD:ALL, `sudo -l -U developer
  # <cmd>` resolves every command on the host, so all six checks below pass whatever was
  # installed — including a bayram-deploy that granted nothing at all. An OK line under that
  # file is not evidence, and this must not be the one place in the script that pretends
  # otherwise.
  VERIFY_BLIND=no
  if [ -f "$LIVE_BLANKET" ]; then
    VERIFY_BLIND=yes
    note "SKIPPED: $LIVE_BLANKET still grants ALL=(ALL) NOPASSWD:ALL, so the policy answers"
    note "         'yes' to every command below no matter what the scoped files say. The lines"
    note "         that follow CANNOT fail, so they verify nothing: this run has not proved"
    note "         that the scoped grants survived, and the rollback trigger below cannot fire."
    note "         To make this check mean something, re-run with --drop-blanket. To check by"
    note "         hand meanwhile, read the policy rather than query it:"
    note "             sudo cat $LIVE_DEPLOY"
  fi

  check_verb "systemctl restart bayram-payme.service" \
             /usr/bin/systemctl restart bayram-payme.service || failed=1
  check_verb "systemctl is-active bayram-admin.service" \
             /usr/bin/systemctl is-active bayram-admin.service || failed=1
  check_verb "systemctl daemon-reload" \
             /usr/bin/systemctl daemon-reload || failed=1
  check_verb "systemctl reload caddy.service" \
             /usr/bin/systemctl reload caddy.service || failed=1
  check_verb "caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile" \
             /usr/bin/caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile || failed=1
  check_verb "bayram-release plan   (NOPASSWD)" \
             /opt/bayram/sbin/bayram-release plan || failed=1

  # INFORMATIONAL, and deliberately not a rollback trigger. `sudo -l <cmd>` is a listing query
  # and lists password-gated commands too, so this should print OK — but if some sudo build
  # ever answers differently for a PASSWD verb, a false negative here would roll back a
  # perfectly good change. This script does not touch that grant, so it cannot have broken it.
  check_verb "bayram-release deploy (PASSWD — listed, still password-gated; informational)" \
             /opt/bayram/sbin/bayram-release deploy \
    || note "        ^ informational only; /etc/sudoers.d/bayram-release is untouched by this
          script. Confirm by hand with: sudo -l -U $ACCOUNT | grep bayram-release"

  if [ "$VERIFY_BLIND" = yes ]; then
    warn "the verify step above was BLIND: $LIVE_BLANKET was still in place, so nothing it"
    warn "printed is evidence about the scoped grants. Do not record this run as verified."
  fi
  # Still returned, blind or not: a failure here while the blanket rule exists would mean sudo
  # itself is answering wrongly, and rolling back is the right response to that too.
  return "$failed"
}

# Informational only, and honest about when it means nothing.
report_closed_holes() {
  step "the holes this closes — checked the same way, expecting a REFUSAL"
  if [ -f "$LIVE_BLANKET" ]; then
    note "SKIPPED: $LIVE_BLANKET still grants ALL=(ALL) NOPASSWD:ALL, so every vector below"
    note "         resolves no matter what the scoped files say. Re-run with --drop-blanket"
    note "         to make this check mean something."
    return 0
  fi
  local v
  for v in "journalctl -u bayram-payme --rotate" \
           "systemctl status bayram-payme.service" \
           "tee /etc/bayram/payme.env" \
           "tee /etc/caddy/Caddyfile"
  do
    # shellcheck disable=SC2086
    if sudo -l -U "$ACCOUNT" /usr/bin/$v >/dev/null 2>&1; then
      note "STILL GRANTED (unexpected): $v"
    else
      note "closed: $v"
    fi
  done
}

# ============================================================================================
# plan
# ============================================================================================
cmd_plan() {
  STAGE_NAME="plan"; STAGE_EXIT=2
  local verdict line

  cat <<PLAN

===================== PLAN — NOTHING ON THIS HOST HAS BEEN CHANGED =====================
source drop-in      $SRC_DEPLOY
backups would go to $BACKUP_DIR
--drop-blanket      $DROP_BLANKET
--drop-pg-dump      $DROP_PG_DUMP

PLAN

  say "1. $LIVE_DEPLOY"
  if cmp -s "$SRC_DEPLOY" "$LIVE_DEPLOY"; then
    note "already identical to the repo copy — would be left alone."
  else
    note "would be REPLACED with $SRC_DEPLOY (visudo -cf first, install -m 0440 -o root -g root)."
    note "diff, live -> new:"
    diff -u "$LIVE_DEPLOY" "$SRC_DEPLOY" | sed 's/^/      /' || true
  fi

  say ""
  say "2. $LIVE_HBD"
  if [ ! -f "$LIVE_HBD" ]; then
    note "does not exist — nothing to prune. (Already run?)"
  else
    while IFS=$'\t' read -r verdict line; do
      case "$verdict" in
        SUSPECT)
          if [ "$DROP_PG_DUMP" = yes ]; then
            note "REMOVE    [SUSPECT, --drop-pg-dump given] $line"
          else
            note "KEEP      [SUSPECT — owner decision, not deleted] $line"
          fi ;;
        STALE)     note "REMOVE    [stale: hbd-* / /etc/hbd — rollback window closed 2026-09-14] $line" ;;
        REHOMED)   note "REMOVE    [re-homed into bayram-deploy] $line" ;;
        DROPPED)   note "REMOVE    [tee /etc/caddy/Caddyfile — dropped as exposure, NOT re-homed;"
                   note "           the line to put it back is in bayram-deploy's header] $line" ;;
        DUPLICATE) note "REMOVE    [already granted by bayram-deploy] $line" ;;
        UNKNOWN)   note "REFUSE    [UNRECOGNISED — added since the 2026-09-19 survey] $line" ;;
      esac
    done < <(survey_hbd)
  fi

  say ""
  say "3. $LIVE_BLANKET"
  if [ ! -f "$LIVE_BLANKET" ]; then
    note "does not exist — nothing to remove."
  elif [ "$DROP_BLANKET" = yes ]; then
    note "would be REMOVED. Contents:"
    sed 's/^/      /' "$LIVE_BLANKET"
    note "After this, ad-hoc 'ssh aizu \"sudo ...\"' WITHOUT -t stops working: sudo will want a"
    note "password and a non-TTY ssh cannot supply one. Use 'ssh -t', or the scoped verbs."
  else
    note "LEFT IN PLACE (no --drop-blanket). Contents:"
    sed 's/^/      /' "$LIVE_BLANKET"
    note "While this file exists, every removal above is COSMETIC: '$ACCOUNT' keeps"
    note "passwordless root regardless. Verified 2026-09-19: sudo -n /usr/bin/id -u -> 0."
  fi

  cat <<'PLAN'

NOT DONE BY apply, and still a person's job:
  * sshd. `PasswordAuthentication yes` on a host with a password-bearing operator account is
    the amplifier behind all of this. Owner: whoever owns ssh policy.
  * /opt/hbd/deploy-payme.sh is still developer:developer 0755 in a developer-owned directory.
    Its sudo grant is gone; the shape that made it dangerous is not.
  * the docs. The live grant list is transcribed in docs/deployment/08-payme.md §3.2 and will
    be wrong the moment this runs.
========================================================================================
PLAN
  say "plan complete. Nothing on this host was changed."
}

# ============================================================================================
# apply
# ============================================================================================
# A scratch path only root can reach, for the moment between "this content validates" and
# "this content is installed".
#
# mktemp with no template writes to $TMPDIR or /tmp. require_trusted_inputs refuses to READ
# this script or the drop-in out of a world-writable directory — and then the reduced hbd-deploy
# was WRITTEN into exactly such a directory, validated there with `visudo -cf`, and read back
# from that same path by `install`. Nothing is exploitable today: the sticky bit stops another
# account unlinking root's file and mktemp creates it 0600 root-owned. But that is two defaults
# happening to cover a gap, not this script applying to its own output the rule it applies to
# its input — and "safe by accident" is what the next edit breaks silently.
#
# $BACKUP_DIR is `install -d -m 0700 -o root -g root` — root's by construction, not by umask —
# so the validate and the install both happen somewhere no other account can reach between
# them. It is created here rather than assumed: this must not depend on take_backup having run.
root_owned_tmp() {
  install -d -m 0700 -o root -g root "$BACKUP_DIR"
  install -d -m 0700 -o root -g root "$BACKUP_DIR/work"
  mktemp "$BACKUP_DIR/work/staged.XXXXXX"
}

install_deploy_dropin() {
  STAGE_NAME="install bayram-deploy"; STAGE_EXIT=3
  step "1/4  install $LIVE_DEPLOY"
  if cmp -s "$SRC_DEPLOY" "$LIVE_DEPLOY"; then
    note "already identical to the repo copy; nothing to do."
    return 0
  fi
  # VALIDATE BEFORE ANYTHING IS REMOVED. This is the step that must not be reordered: the
  # Caddy verbs live only in this file once step 2 has run.
  visudo -cf "$SRC_DEPLOY" || refuse "$SRC_DEPLOY does not parse. Nothing was changed."
  CHANGED=yes
  install -m 0440 -o root -g root "$SRC_DEPLOY" "$LIVE_DEPLOY"
  note "installed."
}

prune_hbd_dropin() {
  STAGE_NAME="prune hbd-deploy"; STAGE_EXIT=3
  step "2/4  prune $LIVE_HBD"
  if [ ! -f "$LIVE_HBD" ]; then
    note "does not exist; nothing to prune."
    return 0
  fi

  local verdict line unknown=0 keep=""
  while IFS=$'\t' read -r verdict line; do
    case "$verdict" in
      UNKNOWN) warn "unrecognised grant: $line"; unknown=1 ;;
      SUSPECT) [ "$DROP_PG_DUMP" = yes ] || keep="$keep$line"$'\n' ;;
    esac
  done < <(survey_hbd)

  # Belt and braces: require_recognised_hbd already refused on this before anything was
  # written. Reaching it here means the file changed under us mid-run.
  if [ "$unknown" -eq 1 ]; then
    refuse "$LIVE_HBD grew an unrecognised grant since the preflight check (above)."
  fi

  if [ -z "$keep" ]; then
    CHANGED=yes
    rm -f -- "$LIVE_HBD"
    note "removed: every grant in it was stale, re-homed or a duplicate."
    return 0
  fi

  # The SUSPECT remainder. Written through a temp file so the live file is never a
  # half-written sudoers file, and validated before it lands — in a directory only root can
  # open, so the path `visudo -cf` blesses is the path `install` reads. See root_owned_tmp.
  local tmp
  tmp="$(root_owned_tmp)"
  {
    cat <<'HDR'
# /etc/sudoers.d/hbd-deploy — REDUCED by deploy/prune-stale-sudo-grants.sh.
#
# Everything else that was in this file has gone: the hbd-* unit verbs (the rollback window
# closed 2026-09-14 — the unit files still exist and are `disabled`, so those grants were stale
# by POLICY, not dangling), `tee /etc/hbd/payme.env`, the wildcard `journalctl -u hbd-payme *`,
# a duplicate `systemctl daemon-reload`, and the Caddy verbs, which were re-homed into
# /etc/sudoers.d/bayram-deploy because caddy.service is very much alive.
#
# WHAT SURVIVES, AND WHY IT IS A DECISION AND NOT AN OVERSIGHT. The 2026-09-19 survey found no
# caller that needs the grant below: bayram-release and install-bayram-backup.sh both require
# EUID 0 before they reach their dumps, the three deploy-*.sh scripts are RETIRED 2026-09-19,
# and a process already at uid 0 needs no sudoers entry to become postgres. The nightly backup
# timer is not installed on this host at all. So nothing breaks when it goes.
#
# It is kept because docs/deployment/08-payme.md documents it as THE sanctioned read path into
# production data for live debugging, and removing it is a workflow change as well as a
# security fix — an owner's call, not a cleanup script's. It is also the largest standing
# data-exposure grant on the box: it lets a non-root account dump every customer record,
# payment and recipient name to anywhere it can write.
#
# To remove it once the owner has decided:
#   sudo bash prune-stale-sudo-grants.sh apply --drop-pg-dump
HDR
    printf '%s' "$keep"
  } > "$tmp"

  visudo -cf "$tmp" || { rm -f -- "$tmp"; refuse "the reduced $LIVE_HBD does not parse."; }
  CHANGED=yes
  install -m 0440 -o root -g root "$tmp" "$LIVE_HBD"
  rm -f -- "$tmp"
  note "reduced to its SUSPECT remainder:"
  printf '%s' "$keep" | sed 's/^/      /'
}

drop_blanket_rule() {
  STAGE_NAME="drop blanket rule"; STAGE_EXIT=3
  step "3/4  $LIVE_BLANKET"
  if [ ! -f "$LIVE_BLANKET" ]; then
    note "does not exist; nothing to remove."
    return 0
  fi
  if [ "$DROP_BLANKET" != yes ]; then
    note "LEFT IN PLACE — no --drop-blanket."
    note "Everything above is cosmetic until it goes: '$ACCOUNT' has passwordless root through"
    note "this one line regardless of any scoped grant."
    sed 's/^/      /' "$LIVE_BLANKET"
    return 0
  fi
  # Last, and only here: by this point the scoped files are installed and parse, so the verbs
  # an operator needs unattended exist before the blanket that was covering for them goes.
  CHANGED=yes
  rm -f -- "$LIVE_BLANKET"
  note "removed. Ad-hoc 'ssh aizu \"sudo ...\"' without -t will now fail on a password prompt;"
  note "that is the intended behaviour, not a fault."
}

cmd_apply() {
  STAGE_NAME="backup"; STAGE_EXIT=2
  step "0/4  backup"
  take_backup

  install_deploy_dropin
  prune_hbd_dropin
  drop_blanket_rule

  STAGE_NAME="verify"; STAGE_EXIT=4
  step "4/4  validate the whole tree"
  if ! visudo -c; then
    warn "'visudo -c' FAILED after the changes. Restoring."
    restore_backup || true
    printf '\nVERIFY FAILED: the sudoers tree did not parse; the backup was restored.\n' >&2
    exit 4
  fi
  note "visudo -c: OK"

  if ! verify_load_bearing; then
    warn "a load-bearing verb no longer resolves for '$ACCOUNT'. Restoring."
    restore_backup || true
    printf '\nVERIFY FAILED: a load-bearing verb stopped resolving; the backup was restored.\n' >&2
    printf 'Re-run with `plan` and read the diff before trying again.\n' >&2
    exit 4
  fi

  report_closed_holes

  step "the resulting policy for '$ACCOUNT' — read it before you close your second shell"
  sudo -l -U "$ACCOUNT" || true

  cat <<DONE

========================================================================================
DONE. Rollback, if anything about the above looks wrong:

    tar -xzpf $BACKUP -C /
    visudo -c

Then tell whoever maintains the docs: the live grant list is transcribed in
docs/deployment/08-payme.md §3.2 and is now out of date.
========================================================================================
DONE
}

# ============================================================================================
# main
# ============================================================================================
main() {
  local cmd="${1:-plan}"
  [ $# -gt 0 ] && shift || true

  case "$cmd" in
    -h|--help|help) usage; exit 0 ;;
    plan|apply) MODE="$cmd" ;;
    # `--check` and `--apply` are accepted because they are what the survey's write-up wrote.
    # They map onto the real verbs rather than becoming a second spelling with its own life.
    --check) MODE=plan ;;
    --apply) MODE=apply ;;
    *) usage >&2; die_usage "unknown subcommand: $cmd" ;;
  esac

  while [ $# -gt 0 ]; do
    case "$1" in
      --drop-blanket) DROP_BLANKET=yes ;;
      --drop-pg-dump) DROP_PG_DUMP=yes ;;
      --source-dir)   shift; [ $# -gt 0 ] || die_usage "--source-dir needs a directory"
                      SRC_DIR="$1" ;;
      --check)        MODE=plan ;;
      --apply)        MODE=apply ;;
      *) usage >&2; die_usage "unknown argument: $1" ;;
    esac
    shift
  done

  require_root
  require_binaries
  resolve_source
  require_trusted_inputs
  require_caddy_rehomed
  require_host_identity
  require_password_path
  require_recognised_hbd

  case "$MODE" in
    plan)  cmd_plan ;;
    apply) cmd_apply ;;
  esac
}

main "$@"
