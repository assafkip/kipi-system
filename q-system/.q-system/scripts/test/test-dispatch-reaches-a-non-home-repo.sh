#!/usr/bin/env bash
# ASK-757. Pairs with: kipi-dispatch.sh (fleet_candidates/rotation/pick_list) and
# repo-preflight.sh.
#
# THE PROPERTY: dispatch can ENTER a repo that is not the home checkout.
#
# Reachability was never the problem -- ASK-755 proved the rotation reaches every
# opted-in candidate. Entry was. repo-preflight.sh check 7 requires the default
# branch to require a review or a status check, and on a PRIVATE repo under a free
# personal plan BOTH the classic protection API and the rulesets API answer 403
# ("Upgrade to GitHub Pro or make this repository public"). All 23 registered
# instances are private, so check 7 was unsatisfiable fleet-wide and pick_list
# returned the home repo and only the home repo, permanently. The gate was right:
# where GitHub can require nothing, arming auto-merge lands agent code in the
# default branch with nothing in its way.
#
# WHY THIS IS A TEST AND NOT A ONE-OFF MEASUREMENT. The fix was bought, not coded
# (GitHub Pro, plus protection configured on each opted-in repo), so it lives
# entirely in GitHub state that no file in this repo pins. It can be un-bought or
# un-configured without a single line changing here, and the symptom -- dispatch
# quietly serving only the home repo -- is indistinguishable from "nothing to do".
# A silent regression is exactly what this asserts against.
#
# HOW IT CAN FAIL (a check that cannot go red is decoration): plan downgraded,
# protection removed from a default branch, dispatch.enabled flipped off, or any
# other preflight item regressing on the opted-in repos. Verified red by pointing
# it at a registry with zero opted-in rows -- see the mutation case at the bottom.
#
# Drives the dispatcher's REAL selection functions the way test-repo-preflight.sh
# does -- awk the functions out and run them alone -- so the whole script never
# runs and no real work is ever dispatched. The cursor is redirected to a temp file
# so the live rotation order is untouched.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DISPATCH="$ROOT/kipi-dispatch.sh"
PREFLIGHT="$ROOT/q-system/.q-system/scripts/repo-preflight.sh"
REGISTRY="${KIPI_DISPATCH_REGISTRY:-$ROOT/instance-registry.json}"
# The home repo pick_list short-circuits on. Never touched on disk by the home row.
HOME_REPO="${KIPI_REPO:-/Users/assafkipnis/projects/kipi-system}"

FAILED=0
ok()  { printf 'ok   %s\n' "$*"; }
bad() { printf 'FAIL %s\n' "$*"; FAILED=1; }

for f in "$DISPATCH" "$PREFLIGHT" "$REGISTRY"; do
  [ -f "$f" ] || { bad "missing $f"; exit 1; }
done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

HARNESS="$WORK/select.sh"
{
  echo 'set -uo pipefail'
  echo 'say() { printf "SAY %s\n" "$*" >&2; }'
  printf 'REPO=%s\n' "$HOME_REPO"
  printf 'PREFLIGHT=%s\n' "$PREFLIGHT"
  awk '/^cursor_get\(\) \{/,/^\}/'       "$DISPATCH"
  awk '/^cursor_set\(\) \{/,/^\}/'       "$DISPATCH"
  awk '/^fleet_candidates\(\) \{/,/^\}/' "$DISPATCH"
  awk '/^rotation\(\) \{/,/^\}/'         "$DISPATCH"
  awk '/^pick_list\(\) \{/,/^\}/'        "$DISPATCH"
  echo 'pick_list'
} > "$HARNESS"

run_picks() {
  KIPI_DISPATCH_REGISTRY="$1" KIPI_DISPATCH_CURSOR="$WORK/cursor.$2" \
    bash "$HARNESS" 2>"$WORK/err.$2"
}

# --- the property -----------------------------------------------------------
PICKS="$(run_picks "$REGISTRY" real)"
NON_HOME="$(printf '%s\n' "$PICKS" | awk -F'\t' -v h="$HOME_REPO" 'NF && $2 != h')"

if [ -n "$NON_HOME" ]; then
  ok "pick_list emits a non-home row, so dispatch can enter a repo other than the home checkout"
  printf '%s\n' "$NON_HOME" | while IFS=$'\t' read -r n p; do printf '     entered: %s (%s)\n' "$n" "$p"; done
else
  bad "pick_list returned the home repo only. Every opted-in repo was refused or none is opted in."
  printf '     refusals:\n'; sed 's/^/     /' "$WORK/err.real"
fi

# --- the mutation: prove the assertion above can go red ---------------------
# A registry with no opted-in rows must produce the home row alone. If this case
# still reports a non-home row, the assertion above is not reading pick_list and
# its green above means nothing.
EMPTY="$WORK/empty-registry.json"
printf '%s' '{"skeleton":{"path":"/nonexistent"},"instances":[]}' > "$EMPTY"
EMPTY_NON_HOME="$(run_picks "$EMPTY" empty | awk -F'\t' -v h="$HOME_REPO" 'NF && $2 != h')"
if [ -z "$EMPTY_NON_HOME" ]; then
  ok "with zero opted-in rows the same assertion goes red, so the green above is load-bearing"
else
  bad "the assertion cannot distinguish an empty registry from a reachable fleet"
fi

exit "$FAILED"
