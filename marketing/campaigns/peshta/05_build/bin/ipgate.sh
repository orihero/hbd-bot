#!/bin/bash
# IP gate. Exits non-zero if a forbidden token appears in any GENERATION INPUT.
#
# Two holes fixed 2026-09-19:
#   SCOPE  - it only ever grepped 05_build/prompts/, so it was blind to 06_local/,
#            where every generation input for the local rebuild now lives. A pass
#            said nothing about the new work.
#   REGEX  - 'polat' and 'necati' were missing entirely. 'elif' is added but
#            restricted to .json/.md, because bare 'elif' matches Python keywords
#            in every script in the tree and would make the gate useless.
set -uo pipefail
cd "$(dirname "$0")/../.."          # -> marketing/campaigns/peshta/

ROOTS=(05_build/prompts 06_local)
EXCLUDES=(--exclude-dir=superseded --exclude-dir=__pycache__ --exclude-dir=venv
          --exclude-dir=a_frames --exclude-dir=a_keyframes --exclude-dir=identity
          --exclude-dir=source_motion_stills)

# tokens safe to match anywhere
BROAD='alemdar|kurtlar|vadisi|sasmaz|şaşmaz|necati|özgü|ozgu|namal|pana ?film|sobirov|xamdam|hamdam|peshta|valley of the wolves|deepfake|face ?swap|lookalike|looks exactly like|celebrity|shot-for-shot'
# tokens that collide with code identifiers -> data files only
NARROW='polat|elif eyl|\belif\b'

fail=0
for r in "${ROOTS[@]}"; do
  [ -e "$r" ] || continue
  if grep -rniE "${EXCLUDES[@]}" "$BROAD" "$r"; then fail=1; fi
  if grep -rniE "${EXCLUDES[@]}" --include='*.json' --include='*.md' --include='*.txt' "$NARROW" "$r"; then fail=1; fi
done

if [ "$fail" -ne 0 ]; then
  echo "IP GATE: FAIL — a forbidden token is in a generation input. Do not submit."
  exit 1
fi
echo "IP GATE: pass (scope: ${ROOTS[*]}; superseded/ excluded as audit trail)"
