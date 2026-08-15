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
# The default is READ OUT OF the dispatcher rather than copied from it. Two reasons,
# and the second is a gate: a second copy would drift silently from kipi-dispatch.sh:38,
# and validate-separation.py's full skeleton sweep (validate-separation.py:975) greps
# every file under q-system/ for a hardcoded founder home-directory prefix (and for
# the old instance brand name) and fails the build on a single hit -- measured in CI,
# the full-skeleton-sweep check reported 1 file and the Phase 1 gate failed.
# kipi-dispatch.sh itself lives at the repo root, outside the swept tree, so it may
# carry that literal and this file may not. The sweep matches a SUBSTRING and reads
# comments like any other line, so neither pattern is spelled out anywhere above --
# quoting one to explain it trips the gate exactly like using it would.
HOME_REPO="${KIPI_REPO:-$(sed -n 's/^REPO="${KIPI_REPO:-\(.*\)}"$/\1/p' "$DISPATCH")}"

FAILED=0
ok()  { printf 'ok   %s\n' "$*"; }
bad() { printf 'FAIL %s\n' "$*"; FAILED=1; }

for f in "$DISPATCH" "$PREFLIGHT" "$REGISTRY"; do
  [ -f "$f" ] || { bad "missing $f"; exit 1; }
done

# The temp workspace is not optional: the extracted harness, the captured
# refusals and the empty-registry fixture all live in it. `set -u` without `-e`
# does not stop an assignment from a failed command, so an unchecked mktemp
# leaves WORK empty and every path below resolves to /-something. Both shapes
# were measured before this guard existed (ASK-757, codex finding on PR #184):
#   * observable host, / not writable -> exit 1 reading "pick_list returned the
#     home repo only", a FALSE red blaming dispatch for a broken mktemp, and the
#     mutation case below still printed ok because an empty result is what IT
#     wants -- so the load-bearing check certified the broken run;
#   * CI shape -> exit 0 via the n/a branch, the failure never noticed at all;
#   * and where / IS writable (root in a container) it would write /select.sh,
#     /err.real and /empty-registry.json outside any sandbox.
# This is a hard error and never the n/a branch: "the test could not run" is a
# different answer from "the property is unobservable here".
if ! WORK="$(mktemp -d)" || [ -z "$WORK" ] || [ ! -d "$WORK" ]; then
  bad "could not create a temp workspace (mktemp -d failed); the detector cannot run here"
  exit 1
fi
trap 'rm -rf "$WORK"' EXIT

# --- observability precondition ---------------------------------------------
# "Cannot observe here" and "observed bad" are different answers and this test
# must never conflate them. The property is about ENTERING a real checkout, so it
# is only observable where an opted-in checkout exists on disk. CI is
# ubuntu-latest with a fresh clone: instance-registry.json ships its rows, but
# none of their paths exist and neither does the home repo, so preflight refuses
# every candidate for the trivial reason that there is nothing there. Declaring
# this test in the capability manifest makes CI RUN it, and without this gate it
# reported the fleet unreachable on every PR -- measured, exit 1, before this
# block existed. That is a false red: it says "dispatch is broken" when the truth
# is "this machine has no fleet".
#
# The gate is deliberately narrow: it asks only whether an opted-in checkout is
# present, using the dispatcher's own opt-in rule (dispatch.enabled === true). A
# preflight REFUSAL with checkouts present is still a hard FAIL below -- that is
# the regression this exists to catch, and it is never skipped.
#
# Honest boundary: on the dispatch host itself, deleting every opted-in checkout
# would turn this green rather than red. That case is genuinely unobservable
# (dispatch has nothing to enter either), and registry-vs-disk drift is
# repo-preflight's job, not this test's.
OBSERVABLE="$(python3 - "$REGISTRY" "$HOME_REPO" <<'PY'
import json, os, sys
reg, home = sys.argv[1], sys.argv[2]
try:
    data = json.load(open(reg))
except Exception:
    print(0); raise SystemExit(0)
n = 0
for e in data.get("instances", []):
    d = e.get("dispatch")
    if not isinstance(d, dict) or d.get("enabled") is not True:
        continue
    p = e.get("path", "")
    if p and p != home and os.path.isdir(p):
        n += 1
print(n)
PY
)"

if [ "${OBSERVABLE:-0}" -eq 0 ]; then
  printf 'n/a  no opted-in instance checkout exists in this environment; the property is unobservable here, not violated\n'
  printf '     registry: %s\n' "$REGISTRY"
  exit 0
fi

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
