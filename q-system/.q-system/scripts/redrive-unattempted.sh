#!/usr/bin/env bash
# Return issues to the queue that were never really attempted (ASK-873).
#
# WHY THIS EXISTS. On 2026-08-15 the account hit its weekly limit and every
# `claude -p` on the machine returned nothing. The dispatcher did not stop: it
# marched the ready queue at ~31 minutes per issue for six hours, charged an
# attempt to each, and drove ELEVEN healthy issues to TERMINAL. Verified
# 2026-08-16 for all eleven -- no remote branch, local branch 0 commits ahead of
# main, worktree clean, no refusal sentinel. Nothing was theirs to fix. TERMINAL
# is a one-way door with no alarm: they have been skipped cheaply and silently on
# every tick since, and nothing distinguishes "this issue defeated three honest
# attempts" from "the machine was down when its number came up".
#
# WHY IT IS GATED ON origin/main. Clearing the counts returns real work to an
# autonomous queue. If the halt (linear-worker.sh, this same issue) is not in the
# code the dispatcher actually runs, the next outage burns exactly these issues
# again -- and now with a fix in the tree that reads as working. An unmerged fix
# protects nothing, so the precondition is asked of the MERGED copy, not of the
# working tree the operator happens to be standing in.
#
# WHY NO NEW LEDGER OP. `clear-flag` already goes through attempts-ledger.py's
# single locked writer, which is the whole reason hand-editing the JSON is
# banned. A bespoke `reset-attempts` would be a second write path to the same
# rows for no new behaviour.
#
# Usage:  redrive-unattempted.sh ASK-733 ASK-722 ...
#         redrive-unattempted.sh --dry ASK-733
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKEL="${KIPI_SKEL:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
STATE_DIR="${KIPI_STATE_DIR:-$HOME/.config/kipi}"
ATTEMPTS="$STATE_DIR/linear-worker-attempts.json"
LEDGER="$SCRIPT_DIR/attempts-ledger.py"

# EVERY KEY THE CAP READS, not just the count. `count` alone leaves `why`
# describing a failure that no longer has a counter behind it, and leaves
# `stuck_paged` claimed -- so if the issue genuinely does cap out later, the page
# that names the human action is suppressed and it parks silently a second time.
KEYS="count why last stuck_paged"

DRY=0
ISSUES=()
for arg in "$@"; do
  case "$arg" in
    --dry) DRY=1 ;;
    ASK-*) ISSUES+=("$arg") ;;
    *) echo "unknown argument: $arg" >&2; exit 1 ;;
  esac
done
if [ "${#ISSUES[@]}" -eq 0 ]; then
  echo "usage: redrive-unattempted.sh [--dry] ASK-123 [ASK-124 ...]" >&2
  exit 1
fi

# --- the gate ----------------------------------------------------------------
# Read from origin/main, not from the checkout: the question is whether the
# dispatcher's own copy carries the halt, and a worktree can hold the fix while
# main does not.
git -C "$SKEL" fetch --quiet origin 2>/dev/null || true
MERGED_WORKER="$(git -C "$SKEL" show origin/main:q-system/.q-system/scripts/linear-worker.sh 2>/dev/null || true)"
if ! printf '%s' "$MERGED_WORKER" | grep -q 'is_environmental'; then
  cat >&2 <<EOF
REFUSED: the environmental halt is not on origin/main yet.

Clearing these counts now returns them to a dispatcher that still charges an
issue for the machine's outage, so the next weekly limit burns exactly the same
issues again. Merge the ASK-873 halt first, then re-run this command verbatim.

Checked: git -C $SKEL show origin/main:q-system/.q-system/scripts/linear-worker.sh | grep is_environmental
Nothing was written.
EOF
  exit 2
fi

echo "halt is present on origin/main -- proceeding"
echo "ledger: $ATTEMPTS"

for ISSUE in "${ISSUES[@]}"; do
  BEFORE="$(python3 "$LEDGER" "$ATTEMPTS" get "$ISSUE" count 0 2>/dev/null || echo "?")"
  if [ "$DRY" = "1" ]; then
    echo "[dry] $ISSUE: count=$BEFORE -> would clear ($KEYS)"
    continue
  fi
  for KEY in $KEYS; do
    python3 "$LEDGER" "$ATTEMPTS" clear-flag "$ISSUE" "$KEY" >/dev/null
  done
  AFTER="$(python3 "$LEDGER" "$ATTEMPTS" get "$ISSUE" count 0 2>/dev/null || echo "?")"
  echo "$ISSUE: count $BEFORE -> $AFTER"
done
