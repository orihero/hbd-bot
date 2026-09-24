#!/usr/bin/env bash
#
# set-probe-tokens.sh — generate and install the two /readyz probe tokens. Runs as root on
# abdu-test. Copy it up and run it; there is no repo checkout on that host:
#
#     scp deploy/set-probe-tokens.sh aizu:/tmp/set-probe-tokens.sh
#     ssh -t aizu 'sudo bash /tmp/set-probe-tokens.sh'
#
# ============================================================================================
# WHAT IT DOES, AND WHY IT IS A SCRIPT RATHER THAN FOUR COMMANDS IN A RUNBOOK
# ============================================================================================
# /readyz on both HTTP processes answers a CONSTANT `{"status":"ok"}` to an unauthenticated
# caller and pings nothing. The detailed body — database, redis, and the version or the sandbox
# flag — is behind an `X-Probe-Token` header compared with `compare_digest`. Where the token is
# empty, which is what ships, that path is off and nobody can turn it on from outside the box.
#
# Turning it on is four beats per file, and every one of them has a way to go wrong that takes
# the fleet down rather than failing loudly:
#
#   1. /etc/bayram/bayram-admin.env is 11 KB and holds the bot token plus four vendor
#      credentials. A truncated write there does not degrade anything — bayram-admin refuses to
#      boot, and so does whatever else reads it. So the rewrite is atomic: a temp file in the
#      SAME directory, attributes copied from the original, then rename(2). Never `sed -i` on a
#      file like this; `sed -i` writes a new inode with the default mode and umask, and on a
#      0640 root:hbd secret that is how a credential becomes world-readable.
#   2. The admin file ALREADY declares `BAYRAM_ADMIN_PROBE_TOKEN=` (empty). It must be REPLACED
#      in place, not appended to — a second declaration later in the file silently wins and an
#      operator reading the first one is looking at a value the process does not have.
#      /etc/bayram/payme.env does NOT declare `BAYRAM_PAYME_PROBE_TOKEN` at all, so that one is
#      appended. The two files need different treatment; this script asserts which case it is
#      in rather than assuming.
#   3. THE MODE AND GROUP ARE PRESERVED, NEVER ASSERTED. Both files are 0640 root:hbd today.
#      The group is `hbd`, NOT `bayram` — the hbd -> bayram rename moved the package, the units,
#      /opt and /etc's *contents*, and never touched the ownership of /etc/bayram/*. A script
#      that "corrected" the group to `bayram` would take every unit's ability to read its own
#      env file away at the next restart. So: `chown --reference` and `chmod --reference` off
#      the original file, and no literal 0640 or root:hbd anywhere below.
#   4. Neither process re-reads its env file. systemd hands it over at exec time, so the value
#      is only live after a restart — and a set-but-not-restarted token is the one failure this
#      whole area cannot self-diagnose, because a WRONG token and NO token produce byte-identical
#      answers. That is why this script restarts and then PROVES the tokens took by reading the
#      gated body back.
#
# ============================================================================================
# THE RESTART IS A LIVE-SERVICE ACTION. READ THIS BEFORE YOU RUN IT.
# ============================================================================================
# bayram-payme is the settlement rail. Under D17 a successful Payme payment auto-queues the
# render, so a restart that lands mid-settlement is not a cosmetic blip. The window is short —
# uvicorn comes back in a second or two and Payme retries — but run this when you are not
# expecting traffic, not during a certification slot, and not while you can see pending intents
# you care about. `deploy/payme-open-orders.py` is how you would have opened any.
#
# bayram-admin holds no queue and no in-flight customer work; restarting it costs an operator a
# page reload.
#
# --admin-only skips the payme half entirely if you want the settlement rail left alone.
#
# ============================================================================================
# WHAT THIS DOES *NOT* BUY YOU
# ============================================================================================
# NOTHING POLLS /readyz TODAY. `systemctl list-timers --all` has no bayram timer and
# /etc/cron.d holds only e2scrub_all and sysstat. Both endpoints bind 127.0.0.1 and all public
# traffic goes through the Cloudflare Tunnel, so an off-box monitor cannot reach them without a
# separate decision to expose them — which is its own exposure argument, not a side effect of
# setting a token.
#
# So after this runs, the concrete gain is: `bayram-release verify` stops printing "reachability
# only" once per release and starts asserting that each process actually reached postgres and
# redis. That is worth having. It is not monitoring. Pointing something at these endpoints is a
# separate piece of work.
# ============================================================================================

set -euo pipefail

ADMIN_ENVFILE=/etc/bayram/bayram-admin.env
PAYME_ENVFILE=/etc/bayram/payme.env
ADMIN_VAR=BAYRAM_ADMIN_PROBE_TOKEN
PAYME_VAR=BAYRAM_PAYME_PROBE_TOKEN
ADMIN_URL=http://127.0.0.1:8080/readyz
PAYME_URL=http://127.0.0.1:8091/readyz
PROBE_TOKEN_HEADER='X-Probe-Token'

# Backups go to /var/backups/bayram/env, 0700 root:root — NOT beside the originals. A
# `bayram-admin.env.bak` sitting in /etc/bayram would be a second copy of every vendor
# credential carrying group-read for `hbd`, and it would still be there in a year.
BACKUP_ROOT=/var/backups/bayram/env
STAMP="$(date -u +%Y%m%d-%H%M%S)"
BACKUP_DIR="$BACKUP_ROOT/$STAMP"

# `sleep 4` before asserting, the same settle bayram-release uses after a restart.
SETTLE=4

ROTATE=no
ADMIN_ONLY=no
ASSUME_YES=no

say()  { printf '%s\n' "$*"; }
step() { printf '\n=== %s ===\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf '\nREFUSED: %s\n' "$*" >&2; exit 2; }
fail() { printf '\nFAILED: %s\n' "$*" >&2; exit 3; }

usage() {
  cat <<'USAGE'
set-probe-tokens.sh — install the two /readyz probe tokens and prove they took.

  sudo bash set-probe-tokens.sh [--rotate] [--admin-only] [--yes]

  --rotate      replace tokens that are ALREADY set. Without it, a non-empty value is
                left alone and this script refuses, so a re-run cannot silently break a
                monitor that is already holding the old value.
  --admin-only  do not touch /etc/bayram/payme.env and do not restart bayram-payme.
                Use when the settlement rail must not be disturbed.
  --yes         skip the confirmation prompt (for a non-interactive run).

Prints the two tokens to stdout ONCE. They are not written anywhere you can read them
back in the clear afterwards, short of the env files themselves.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --rotate)     ROTATE=yes ;;
    --admin-only) ADMIN_ONLY=yes ;;
    --yes|-y)     ASSUME_YES=yes ;;
    -h|--help)    usage; exit 0 ;;
    *)            usage >&2; die "unknown argument: $1" ;;
  esac
  shift
done

[ "$(id -u)" -eq 0 ] || die "must run as root — it writes /etc/bayram and restarts units."

for tool in openssl curl systemctl awk install; do
  command -v "$tool" >/dev/null 2>&1 || die "$tool is not installed; it is required."
done

# ============================================================================================
# Preflight. Everything that could refuse, refuses BEFORE the first byte is written.
# ============================================================================================
step "Preflight"

# `current_value <file> <var>` — the value of a variable as the file declares it, read in a
# SUBSHELL so this script never inherits the rest of the file's contents. Empty when the
# declaration is absent or declared empty; `declared_count` separates those two cases.
current_value() {
  local file="$1" var="$2"
  [ -r "$file" ] || return 0
  ( set -a; . "$file" 2>/dev/null; set +a; printf '%s' "${!var:-}" ) || true
}

declared_count() {
  local file="$1" var="$2"
  [ -r "$file" ] || { printf '0'; return 0; }
  grep -c "^[[:space:]]*${var}=" "$file" || true
}

check_file() {
  local file="$1" var="$2" count value
  test -f "$file" || die "env file missing: $file"
  count="$(declared_count "$file" "$var")"
  value="$(current_value "$file" "$var")"

  if [ "$count" -gt 1 ]; then
    die "$file declares $var $count times. The LAST one wins and the others are decoration.
Fix that by hand first — this script will not guess which line you meant."
  fi
  if [ -n "$value" ] && [ "$ROTATE" != yes ]; then
    die "$var is already set in $file. Re-run with --rotate to replace it.
Rotating invalidates whatever is currently holding the old value."
  fi

  say "  $file"
  say "    $var declared: $count time(s), currently $([ -n "$value" ] && echo 'SET' || echo 'empty')"
  say "    mode/owner:    $(stat -c '%a %U:%G' "$file")"
}

check_file "$ADMIN_ENVFILE" "$ADMIN_VAR"
if [ "$ADMIN_ONLY" != yes ]; then
  check_file "$PAYME_ENVFILE" "$PAYME_VAR"
else
  say "  --admin-only: $PAYME_ENVFILE will not be touched and bayram-payme will not restart."
fi

if [ "$ASSUME_YES" != yes ]; then
  say ""
  say "This will REWRITE the files above and RESTART bayram-admin$([ "$ADMIN_ONLY" = yes ] || echo ' and bayram-payme')."
  [ "$ADMIN_ONLY" = yes ] || say "bayram-payme is the settlement rail — do not run this mid-settlement."
  printf 'Type yes to continue: '
  read -r reply
  [ "$reply" = yes ] || die "not confirmed; nothing was changed."
fi

# ============================================================================================
# Generate. 32 bytes of hex: a bearer secret compared verbatim, and ASCII because the value
# travels in an HTTP header — both handlers reject a non-ASCII header before comparing.
# Two INDEPENDENT values, deliberately: two processes, two files, two blast radii. One shared
# value would mean one leak unlocks both, and bayram-release now sends each unit only its own.
# ============================================================================================
step "Generating"
ADMIN_TOKEN="$(openssl rand -hex 32)"
PAYME_TOKEN="$(openssl rand -hex 32)"
[ ${#ADMIN_TOKEN} -eq 64 ] || fail "openssl produced a ${#ADMIN_TOKEN}-character admin token; expected 64."
[ ${#PAYME_TOKEN} -eq 64 ] || fail "openssl produced a ${#PAYME_TOKEN}-character payme token; expected 64."
say "  two independent 32-byte tokens"

# ============================================================================================
# Back up, then write. From here the host is being modified.
# ============================================================================================
step "Backing up to $BACKUP_DIR"
install -d -m 0700 -o root -g root "$BACKUP_ROOT"
install -d -m 0700 -o root -g root "$BACKUP_DIR"
cp -a "$ADMIN_ENVFILE" "$BACKUP_DIR/" || fail "could not back up $ADMIN_ENVFILE; nothing was written."
[ "$ADMIN_ONLY" = yes ] || cp -a "$PAYME_ENVFILE" "$BACKUP_DIR/" || fail "could not back up $PAYME_ENVFILE; nothing was written."
say "  $(ls -1 "$BACKUP_DIR" | tr '\n' ' ')"
say "  restore with: cp -a $BACKUP_DIR/<file> /etc/bayram/ && systemctl restart <unit>"

# `write_token <file> <var> <value> <replace|append>` — atomic, attribute-preserving.
#
# The temp file is created in the SAME directory so the final rename(2) is within one
# filesystem and therefore atomic: a reader either sees the whole old file or the whole new
# one, never a truncated one. Attributes are copied from the ORIGINAL with --reference, so
# whatever mode and group that file carries today is what the new inode carries — this script
# states no opinion about what they should be.
write_token() {
  local file="$1" var="$2" value="$3" mode="$4"
  local dir tmp count

  dir="$(dirname "$file")"
  tmp="$(mktemp "$dir/.$(basename "$file").XXXXXX")" || fail "could not create a temp file in $dir"
  # Attributes BEFORE content: if anything below fails, the leftover temp file is already as
  # locked down as the original rather than sitting at the default umask.
  chown --reference="$file" "$tmp" || fail "could not copy ownership from $file"
  chmod --reference="$file" "$tmp" || fail "could not copy mode from $file"

  if [ "$mode" = replace ]; then
    # awk, not sed: the value never becomes part of the program text, so no character in it
    # can be read as a delimiter or a backreference. `printed` asserts that exactly one line
    # was rewritten — a zero there means the declaration moved and this would have silently
    # produced a file with no token in it at all.
    #
    # AND IT TRAVELS IN THE ENVIRONMENT, NOT IN argv. `-v val="$value"` put the token on awk's
    # command line, and /proc/<pid>/cmdline is world-readable on this host: `ps -ww -A -o args=`
    # sampled while this ran over a large env file matched the token three times, and any local
    # account can sample it in a loop. An exported variable lands in /proc/<pid>/environ
    # instead, which is 0400 and readable only by the process owner — root, here. That is the
    # rule deploy/install-bayram-backup.sh states for this same host, and the rule probe_curl
    # below follows with `-K -`. ENVIRON is also the more faithful channel: `-v` expands
    # backslash escapes in the value it is given, so a token containing a backslash would be
    # rewritten on its way in; ENVIRON hands awk the bytes.
    PROBE_TOKEN_VALUE="$value" awk -v var="$var" '
      $0 ~ "^[[:space:]]*" var "=" { print var "=" ENVIRON["PROBE_TOKEN_VALUE"]; printed++; next }
      { print }
      END { if (printed != 1) exit 9 }
    ' "$file" >"$tmp" || { rm -f "$tmp"; fail "expected exactly one '$var=' line in $file; found a different number. Nothing was changed in that file."; }
  else
    cat "$file" >"$tmp" || { rm -f "$tmp"; fail "could not copy $file"; }
    # A declaration appended to a file whose last line has no newline would FUSE onto it —
    # `BAYRAM_PAYME_KEY=secretBAYRAM_PAYME_PROBE_TOKEN=…`, which is one corrupt variable and no
    # token. /etc/bayram/payme.env is 362 bytes written by hand; do not assume it is
    # newline-terminated. Written as a full `if` rather than an `&&` chain because a chain whose
    # middle test fails has a nonzero status, and reasoning about whether `set -e` forgives that
    # is not something a reader of a root script should have to do.
    if [ -s "$tmp" ] && [ "$(tail -c 1 "$tmp" | wc -l)" -eq 0 ]; then
      printf '\n' >>"$tmp"
    fi
    {
      printf '\n'
      printf '# Added by deploy/set-probe-tokens.sh on %s. Unlocks the detailed /readyz body\n' "$STAMP"
      printf '# to a caller presenting it in the %s header. See the matching .env.*.example.\n' "$PROBE_TOKEN_HEADER"
      printf '%s=%s\n' "$var" "$value"
    } >>"$tmp" || { rm -f "$tmp"; fail "could not append to the temp copy of $file"; }
  fi

  # Prove the value is readable back out of the temp file the way the process will read it,
  # BEFORE the rename replaces anything.
  count="$( set -a; . "$tmp" 2>/dev/null; set +a; printf '%s' "${!var:-}" )" || count=""
  [ "$count" = "$value" ] || { rm -f "$tmp"; fail "the rewritten $file did not read back with the new $var. Nothing was changed."; }

  mv -f "$tmp" "$file" || fail "the rename into $file failed. Check $BACKUP_DIR."
  say "  $file: $var written ($mode), $(stat -c '%a %U:%G' "$file")"
}

step "Writing"
# BRANCH, do not hardcode `replace`. The admin file declares BAYRAM_ADMIN_PROBE_TOKEN= today,
# but check_file only refuses when the declaration count is GREATER THAN ONE — a count of zero
# sails through preflight. A hardcoded `replace` then meets awk's `END { if (printed != 1)
# exit 9 }`, and the script exits 3 having ALREADY created the backup directory and copied both
# env files into it: a "failed mid-run" for a condition that should have refused at preflight
# with nothing touched. The payme half below has always branched on declared_count; the two
# files are now handled the same way, so a missing declaration is an append rather than a
# half-run. (Nothing is lost by this: write_token still reads the value back out of the temp
# file the way the process will, before the rename replaces anything.)
if [ "$(declared_count "$ADMIN_ENVFILE" "$ADMIN_VAR")" -ge 1 ]; then
  write_token "$ADMIN_ENVFILE" "$ADMIN_VAR" "$ADMIN_TOKEN" replace
else
  warn "$ADMIN_VAR is not declared in $ADMIN_ENVFILE — appending it rather than replacing.
That file is expected to declare it empty; check nothing has rewritten it."
  write_token "$ADMIN_ENVFILE" "$ADMIN_VAR" "$ADMIN_TOKEN" append
fi
if [ "$ADMIN_ONLY" != yes ]; then
  # payme.env does not declare the variable today, so this is the append case. If a previous
  # run of this script already added it, --rotate takes the replace path instead.
  if [ "$(declared_count "$PAYME_ENVFILE" "$PAYME_VAR")" -ge 1 ]; then
    write_token "$PAYME_ENVFILE" "$PAYME_VAR" "$PAYME_TOKEN" replace
  else
    write_token "$PAYME_ENVFILE" "$PAYME_VAR" "$PAYME_TOKEN" append
  fi
fi

# ============================================================================================
# Restart. Neither process re-reads its env file; systemd hands it over at exec time.
# ============================================================================================
step "Restarting"
systemctl restart bayram-admin || fail "bayram-admin failed to restart. Check: journalctl -u bayram-admin -n 50 --no-pager"
say "  bayram-admin restarted"
if [ "$ADMIN_ONLY" != yes ]; then
  systemctl restart bayram-payme || fail "bayram-payme failed to restart. Check: journalctl -u bayram-payme -n 50 --no-pager"
  say "  bayram-payme restarted"
fi
sleep "$SETTLE"

# ============================================================================================
# Prove it. This is the part that cannot be skipped, because the failure it catches is
# invisible: /readyz answers the same constant {"status":"ok"} to a WRONG token as to none at
# all. The `database` key appears ONLY in the authorised body, so getting it back is the proof
# that the value in the file and the value the running process loaded are the same string.
# ============================================================================================
step "Proving the tokens took"

# `probe_curl <url> <token>` — GET $url presenting the probe token, with the token NEVER in argv.
#
# `-H "$PROBE_TOKEN_HEADER: $token"` writes the secret into /proc/<pid>/cmdline, which is
# world-readable on this host, for the whole life of the curl process — up to --max-time 10,
# three attempts over. Any local account can read it with `ps -o args` in a loop, and this host
# has accounts that are not root. It also flatly contradicts the closing claim at the bottom of
# this script that the tokens are "stdout only — never a log, never a file, never an argv", and
# it breaks the rule the same change set states for the same host in
# deploy/install-bayram-backup.sh: "Credentials are passed in the ENVIRONMENT, never in argv:
# /proc/<pid>/cmdline is world-readable and this host has accounts that are not root."
#
# `-K -` makes curl read its options from STDIN instead — a pipe, which is neither a file on
# disk nor visible in another process's argv. The value sits inside curl's double-quoted config
# syntax, so the two characters that syntax escapes, backslash and double quote, are escaped
# here. A 64-hex token contains neither; the escaping is for the day this shape is copied
# somewhere that reads a token out of a file somebody else wrote.
probe_curl() {
  local url="$1" token="$2" esc
  esc="${token//\\/\\\\}"
  esc="${esc//\"/\\\"}"
  printf 'header = "%s: %s"\n' "$PROBE_TOKEN_HEADER" "$esc" \
    | curl -K - -s --max-time 10 -w '\n%{http_code}' "$url" 2>/dev/null || true
}

assert_gated() {
  local unit="$1" url="$2" token="$3" body code attempt
  for attempt in 1 2 3; do
    body="$(probe_curl "$url" "$token")"
    code="${body##*$'\n'}"
    body="${body%$'\n'*}"
    if [ "$code" = 200 ] && printf '%s' "$body" | grep -q '"database"'; then
      say "  $unit: GATED DETAIL READ — $body"
      return 0
    fi
    [ "$attempt" -lt 3 ] && sleep 3
  done
  warn "$unit answered HTTP ${code:-none} without the gated detail after three tries."
  warn "  The token IS in the env file — it read back before the rename — so either the unit"
  warn "  did not pick it up or it is not serving yet."
  warn "  Check: systemctl status $unit --no-pager; journalctl -u $unit -n 50 --no-pager"
  return 1
}

PROVEN=yes
assert_gated bayram-admin "$ADMIN_URL" "$ADMIN_TOKEN" || PROVEN=no
if [ "$ADMIN_ONLY" != yes ]; then
  assert_gated bayram-payme "$PAYME_URL" "$PAYME_TOKEN" || PROVEN=no
fi

# ============================================================================================
# The tokens, once. Printed LAST so they are the final thing on the operator's screen and the
# least likely to scroll away. Each token reaches exactly two places: the env file it belongs
# in, and this stdout. Never a log, never a scratch file of its own, and never an argv — not
# curl's (probe_curl feeds the header through `-K -` on a pipe) and not awk's (write_token
# exports it and reads it back through ENVIRON), because /proc/<pid>/cmdline is world-readable
# on this host and /proc/<pid>/environ is not.
# ============================================================================================
step "The tokens — copy them now, this is the only time they are shown"
cat <<TOKENS

  $ADMIN_VAR
      $ADMIN_TOKEN

TOKENS
if [ "$ADMIN_ONLY" != yes ]; then
  cat <<TOKENS
  $PAYME_VAR
      $PAYME_TOKEN

TOKENS
fi
say "They are now in /etc/bayram/*.env (0640, root-owned) and nowhere else. Your terminal"
say "scrollback holds them too — close the session when you are done, and do not paste them"
say "into a ticket, a chat or a commit."
say ""
say "Nothing polls these endpoints yet. Until something does, the only consumer is"
say "\`bayram-release verify\`, which will now read the gated body instead of printing"
say "\"reachability only\"."

if [ "$PROVEN" != yes ]; then
  fail "one or more processes did not return the gated body. The files ARE written and backed
up in $BACKUP_DIR. Read the warnings above before re-running."
fi

step "Done"
