#!/usr/bin/env bash
# Pairs with ci-redrive.py (ASK-295): red CI on an agent-opened PR is a dead end
# with no machine consumer, so GitHub emails the founder and he cannot act.
#
# THE SCAR (2026-08-02)
# ---------------------
# The founder received three unprompted GitHub notifications in one day:
#   [assafkip/kipi-system] PR run failed: Skeleton Validation - ... (ASK-292)
#   [assafkip/kipi-system] PR run failed: Skeleton Validation - ... (ASK-288)
#   [assafkip/kipi-system] Run failed: Skeleton Validation - sana/block-expiry
# An autonomous agent opened each PR, CI went red, GitHub mailed the repo owner.
# The failures were a SINGLE CORRECT CATCH (test-terminal-states.sh). True, and
# still useless to him: he does not work on the code. The agent that opened the
# PR does. ready() in linear-worker.sh only returns backlog/unstarted issues, so
# an In Progress issue whose PR just went red is never re-picked -- the dead end.
#
# WHAT THIS SUITE PINS
# --------------------
#   1. Attribution: branch `sana/ask-295` -> ASK-295, with no Linear round-trip.
#   2. Non-agent branches are none of this tool's business (the founder's own
#      PRs keep behaving exactly as they do today).
#   3. ONE machine attempt per PR per failure signature. Not per run, not per
#      push -- a handler that re-runs CI without fixing the cause re-runs a
#      flake forever, which is the failure mode this issue names by hand.
#   4. The founder is NOT paged on the red itself. He is paged once, AFTER the
#      machine tier is spent, by a message that names what the machine tried.
#
# The `gh` seam is a fixture script, so no case here touches the network: what
# is under test is the decision, and a suite that needs a live red PR to run is
# a suite that never runs.
set -uo pipefail

PASS=0; FAIL=0
ok()  { printf '  PASS %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; FAIL=$((FAIL + 1)); }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expected [$3] got [$2]"; fi; }
contains() {
  if printf '%s' "$2" | grep -qF -- "$3"; then ok "$1"
  else bad "$1" "expected to find [$3] in [$2]"; fi
}
lacks() {
  if printf '%s' "$2" | grep -qF -- "$3"; then bad "$1" "did NOT expect [$3] in [$2]"
  else ok "$1"; fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# FOUR levels up: test -> scripts -> .q-system -> q-system -> repo root.
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
REDRIVE="$REPO_ROOT/q-system/.q-system/scripts/ci-redrive.py"
[ -f "$REDRIVE" ] || { echo "FATAL: ci-redrive.py not found at $REDRIVE" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- the gh seam -------------------------------------------------------------
# Prints whatever JSON $GH_FIXTURE names, and exits $GH_RC. Both are read at
# call time so a case can swap the world between two invocations.
cat > "$TMP/gh" <<'SH'
#!/usr/bin/env bash
[ "${GH_RC:-0}" = "0" ] || { echo "gh: could not read PRs" >&2; exit "${GH_RC}"; }
cat "$GH_FIXTURE"
SH
chmod +x "$TMP/gh"

# --- the notify seam ---------------------------------------------------------
# Appends its argument to $NOTIFY_LOG. Reading that file is how a case asserts
# the founder was, or was not, reached.
cat > "$TMP/notify.sh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$NOTIFY_LOG"
SH
chmod +x "$TMP/notify.sh"

fixture() { printf '%s' "$1" > "$TMP/prs.json"; }

# A red agent PR, a green agent PR, and a red PR on a branch carrying no issue
# id -- all in one payload, because the filter is what is under test.
RED_AND_FRIENDS='[
 {"number":101,"headRefName":"sana/ask-292","isDraft":false,
  "url":"https://github.com/assafkip/kipi-system/pull/101",
  "title":"feat: will-it-run (ASK-292)",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"Skeleton Validation","status":"COMPLETED",
     "conclusion":"FAILURE","detailsUrl":"https://github.com/x/runs/1"},
    {"__typename":"CheckRun","name":"kipi/reviewer-approved","status":"COMPLETED",
     "conclusion":"SUCCESS","detailsUrl":"https://github.com/x/runs/2"}]},
 {"number":102,"headRefName":"sana/ask-288","isDraft":false,
  "url":"https://github.com/assafkip/kipi-system/pull/102",
  "title":"fix: capability block expiry (ASK-288)",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"Skeleton Validation","status":"COMPLETED",
     "conclusion":"SUCCESS","detailsUrl":"https://github.com/x/runs/3"}]},
 {"number":103,"headRefName":"assaf-hotfix","isDraft":false,
  "url":"https://github.com/assafkip/kipi-system/pull/103",
  "title":"chore: founder hand edit",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"Skeleton Validation","status":"COMPLETED",
     "conclusion":"FAILURE","detailsUrl":"https://github.com/x/runs/4"}]}]'

run() {  # run <op> [args...]
  KIPI_GH="$TMP/gh" \
  KIPI_NOTIFY="$TMP/notify.sh" \
  KIPI_ATTEMPTS="$LEDGER" \
  GH_FIXTURE="$TMP/prs.json" \
  GH_RC="${GH_RC:-0}" \
  NOTIFY_LOG="$NOTIFY_LOG" \
  python3 "$REDRIVE" --repo-dir "$TMP" "$@" 2>"$TMP/err"
}

fresh_state() {
  LEDGER="$TMP/attempts-$1.json"
  NOTIFY_LOG="$TMP/notify-$1.log"
  : > "$NOTIFY_LOG"
  rm -f "$LEDGER"
}

echo "== ci-redrive =="

# --- 1. attribution ----------------------------------------------------------
fresh_state attr
fixture "$RED_AND_FRIENDS"
OUT="$(run scan)"; RC=$?
check "scan exits 0 with candidates" "$RC" "0"
contains "red agent PR attributed to its issue" "$OUT" '"issue": "ASK-292"'
contains "the failing check is named" "$OUT" "Skeleton Validation"
contains "the PR number is carried" "$OUT" '"pr": 101'

# --- 2. what it leaves alone -------------------------------------------------
lacks "a GREEN agent PR is not a candidate" "$OUT" '"issue": "ASK-288"'
lacks "a red PR on a non-agent branch is not a candidate" "$OUT" '"pr": 103'

# --- 3. one machine attempt per PR per failure signature ---------------------
fresh_state cap
fixture "$RED_AND_FRIENDS"
OUT="$(run redrive)"; RC=$?
check "first red: redrive claims the attempt" "$RC" "0"
check "first red: the issue to re-dispatch is printed" "$OUT" "ASK-292"
check "first red does NOT page the founder" "$(wc -l < "$NOTIFY_LOG" | tr -d ' ')" "0"

OUT2="$(run redrive)"; RC2=$?
check "same signature: no second machine attempt" "$RC2" "1"
check "same signature: no issue printed" "$OUT2" ""

# --- 4. escalation, after the machine tier and naming what it tried ----------
ESC="$(cat "$NOTIFY_LOG")"
contains "escalation names the issue" "$ESC" "ASK-292"
contains "escalation names the PR" "$ESC" "#101"
contains "escalation names the failing check" "$ESC" "Skeleton Validation"
contains "escalation says the machine already re-dispatched" "$ESC" "re-dispatched"

run redrive >/dev/null 2>&1
check "escalation pages ONCE per signature, not per run" \
  "$(wc -l < "$NOTIFY_LOG" | tr -d ' ')" "1"

# --- 5. a DIFFERENT failure earns a fresh machine attempt --------------------
fixture "$(printf '%s' "$RED_AND_FRIENDS" | sed 's/Skeleton Validation/Lefthook Gate/')"
OUT3="$(run redrive)"; RC3=$?
check "new failure signature: a fresh attempt is claimed" "$RC3" "0"
check "new failure signature: the issue is printed again" "$OUT3" "ASK-292"

# --- 6. all-green is quiet, not an error state -------------------------------
fresh_state green
fixture '[{"number":104,"headRefName":"sana/ask-300","isDraft":false,
  "url":"https://x/104","title":"t (ASK-300)",
  "statusCheckRollup":[{"__typename":"CheckRun","name":"Skeleton Validation",
   "status":"COMPLETED","conclusion":"SUCCESS","detailsUrl":"https://x/5"}]}]'
run redrive >/dev/null; RC=$?
check "nothing red: exit 1, nothing to do" "$RC" "1"
check "nothing red: founder untouched" "$(wc -l < "$NOTIFY_LOG" | tr -d ' ')" "0"

# --- 7. gh could not answer: not a claim, and not silence --------------------
# The probe's rc is part of its answer (arm_automerge's finding 3, same class).
# Reading a failed `gh` as "no red PRs" is how a real red PR goes unhandled with
# a clean exit -- so it exits 2 and burns no attempt.
fresh_state ghdown
fixture "$RED_AND_FRIENDS"
GH_RC=7 run redrive >/dev/null; RC=$?
GH_RC=0
check "gh failure exits 2, not 0 and not 1" "$RC" "2"
check "gh failure writes no ledger" "$([ -f "$LEDGER" ] && echo yes || echo no)" "no"

# --- 8. a run still pending is not a failure ---------------------------------
fresh_state pending
fixture '[{"number":105,"headRefName":"sana/ask-301","isDraft":false,
  "url":"https://x/105","title":"t (ASK-301)",
  "statusCheckRollup":[{"__typename":"CheckRun","name":"Skeleton Validation",
   "status":"IN_PROGRESS","conclusion":"","detailsUrl":"https://x/6"}]}]'
run redrive >/dev/null; RC=$?
check "an in-flight check is not red" "$RC" "1"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
