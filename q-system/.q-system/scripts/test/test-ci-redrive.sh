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
# THE FIXTURES ARE THE PRODUCER'S OWN SHAPES, NOT MINE (PR #73 review, findings
# 1 and 3, and the `fixtures_from_producers` lesson). Round 1 of this suite
# invented a fixture where `kipi/reviewer-approved` arrived as a CheckRun with
# conclusion SUCCESS. GitHub actually delivers it as a StatusContext with
# `state: FAILURE`, which is the shape pr-review-agent.sh's `post_reviewer_status`
# posts -- so the suite was green while the script counted every REQUEST-CHANGES
# review as red CI. Every rollup below is copied verbatim from a real
# `gh pr list --json statusCheckRollup` against this repo on 2026-08-03.
#
# WHAT THIS SUITE PINS
# --------------------
#   1. Attribution: branch `sana/ask-295` -> ASK-295 first, and the PR TITLE's
#      issue id when the branch carries none (`sana/block-expiry` -> ASK-288).
#   2. Non-agent branches are none of this tool's business (the founder's own
#      PRs keep behaving exactly as they do today).
#   3. A REVIEW VERDICT IS NOT CI. `kipi/reviewer-approved` failing means the
#      reviewer asked for changes; that already has its own machine consumer.
#   4. ONE machine attempt per PR per failure signature, and the attempt is spent
#      when the dispatcher CONFIRMS the dispatch -- not when the pick is offered.
#   5. The founder is NOT paged on the red itself. He is paged once, AFTER the
#      machine tier is spent, by a message that names only what was observed.
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

# Real shapes, 2026-08-03, `gh pr list --state open --json ...` on this repo:
#   PR 73 sana/ask-295          validate SUCCESS + kipi/reviewer-approved FAILURE
#   PR 69 sana/block-expiry     validate FAILURE, no issue id in the branch
#   PR 71 sana/ask-292          statusCheckRollup: []
WORLD='[
 {"number":73,"headRefName":"sana/ask-295","isDraft":false,
  "headRefOid":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "url":"https://github.com/assafkip/kipi-system/pull/73",
  "title":"feat(dispatch): red CI is re-dispatched to its agent (ASK-295)",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"validate","status":"COMPLETED",
     "conclusion":"SUCCESS","workflowName":"Skeleton Validation"},
    {"__typename":"StatusContext","context":"kipi/reviewer-approved",
     "state":"FAILURE",
     "targetUrl":"https://github.com/assafkip/kipi-system/pull/73#issuecomment-1"}]},
 {"number":69,"headRefName":"sana/block-expiry","isDraft":false,
  "headRefOid":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "url":"https://github.com/assafkip/kipi-system/pull/69",
  "title":"A capability block re-tests itself and expires (ASK-288)",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"validate","status":"COMPLETED",
     "conclusion":"FAILURE","workflowName":"Skeleton Validation"}]},
 {"number":103,"headRefName":"assaf-hotfix","isDraft":false,
  "headRefOid":"cccccccccccccccccccccccccccccccccccccccc",
  "url":"https://github.com/assafkip/kipi-system/pull/103",
  "title":"chore: founder hand edit (ASK-999)",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"validate","status":"COMPLETED",
     "conclusion":"FAILURE","workflowName":"Skeleton Validation"}]}]'

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

pages() { wc -l < "$NOTIFY_LOG" | tr -d ' '; }

echo "== ci-redrive =="

# --- 1. attribution ----------------------------------------------------------
fresh_state attr
fixture "$WORLD"
OUT="$(run scan)"; RC=$?
check "scan exits 0 with candidates" "$RC" "0"
contains "the red agent PR is attributed to its issue" "$OUT" '"issue": "ASK-288"'
contains "the failing check is named" "$OUT" '"validate"'
contains "the PR number is carried" "$OUT" '"pr": 69'
contains "the head sha is carried" "$OUT" '"head_sha": "bbbbbbbb'

# --- 2. a branch with no issue id still reaches its agent (finding 3) --------
# `sana/block-expiry` (PR #69) is one of the three PRs that mailed the founder on
# 2026-08-02, and the first cut of BRANCH_RE skipped it: the worker names its own
# branches `sana/ask-288`, but a branch cut by hand in an interactive session is
# named for the work. The issue id is still there -- in the PR title, which the
# linear-first commit-msg gate makes mandatory. Reading it there is not guessing.
contains "the title's issue id is used when the branch has none" "$OUT" '"issue_source": "title"'

# --- 3. what it leaves alone -------------------------------------------------
lacks "a green agent PR is not a candidate" "$OUT" '"pr": 73'
lacks "a red PR on a non-agent branch is not a candidate" "$OUT" '"pr": 103'

# --- 4. a review verdict is not CI (finding 1) -------------------------------
# `kipi/reviewer-approved` FAILURE means the reviewer asked for changes. It is
# posted by pr-review-agent.sh's post_reviewer_status, it arrives as a
# StatusContext, and it already HAS a machine consumer: the reviewer comments on
# the Linear issue and the worker re-dispatches from there. Counting it as red CI
# re-dispatches a PR whose build is green and pages the founder about a passing
# build.
fresh_state verdict
fixture '[{"number":73,"headRefName":"sana/ask-295","isDraft":false,
  "headRefOid":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "url":"https://x/73","title":"t (ASK-295)",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"validate","status":"COMPLETED",
     "conclusion":"SUCCESS","workflowName":"Skeleton Validation"},
    {"__typename":"StatusContext","context":"kipi/reviewer-approved",
     "state":"FAILURE","targetUrl":"https://x/73#c1"},
    {"__typename":"StatusContext","context":"kipi/codex-approved",
     "state":"FAILURE","targetUrl":"https://x/73#c2"}]}]'
run redrive >/dev/null; RC=$?
check "a REQUEST-CHANGES verdict on a green build is not red CI" "$RC" "1"
check "a REQUEST-CHANGES verdict does not page the founder" "$(pages)" "0"

# A third-party commit status is still real CI. The exclusion is the reviewer's
# own two slots, not the whole StatusContext half of the rollup.
fresh_state legacy
fixture '[{"number":74,"headRefName":"sana/ask-296","isDraft":false,
  "headRefOid":"dddddddddddddddddddddddddddddddddddddddd",
  "url":"https://x/74","title":"t (ASK-296)",
  "statusCheckRollup":[
    {"__typename":"StatusContext","context":"ci/external-builder",
     "state":"FAILURE","targetUrl":"https://x/74#c1"}]}]'
OUT="$(run redrive)"; RC=$?
check "a non-reviewer commit status IS red CI" "$RC" "0"
contains "the external status is the failing check" "$(run scan)" '"ci/external-builder"'

# --- 5. the attempt is spent on DISPATCH, not on the offer (finding 2) -------
# The offer is read-only. kipi-dispatch.sh can still abort between the pick and
# the launch (a converge run already live for that issue), and burning the one
# machine attempt on an offer that was never dispatched means the PR is marked
# handled while nothing ever handled it -- and then the founder is paged with a
# message asserting a re-dispatch that did not happen.
fresh_state spend
fixture "$WORLD"
OUT="$(run redrive)"; RC=$?
check "offer exits 0" "$RC" "0"
check "offer names the issue" "$(printf '%s' "$OUT" | cut -f1)" "ASK-288"
check "offer carries the signature" "$([ -n "$(printf '%s' "$OUT" | cut -f2)" ] && echo yes || echo no)" "yes"
check "offer carries the head sha" "$(printf '%s' "$OUT" | cut -f3)" "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
check "an un-dispatched offer pages nobody" "$(pages)" "0"

OUT2="$(run redrive)"; RC2=$?
check "an un-dispatched offer is NOT spent: it is offered again" "$RC2" "0"
check "the second offer is the same issue" "$(printf '%s' "$OUT2" | cut -f1)" "ASK-288"
check "still no page" "$(pages)" "0"

SIG="$(printf '%s' "$OUT" | cut -f2)"
run mark-dispatched --issue ASK-288 --signature "$SIG" \
  --head-sha bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb >/dev/null; RC=$?
check "mark-dispatched claims the attempt" "$RC" "0"
run mark-dispatched --issue ASK-288 --signature "$SIG" \
  --head-sha bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb >/dev/null; RC=$?
check "mark-dispatched is one-shot: a second caller must not dispatch" "$RC" "1"

run redrive >/dev/null; RC=$?
check "after a confirmed dispatch the attempt is spent" "$RC" "1"

# --- 6. the escalation says only what was observed (finding 2) ---------------
ESC="$(cat "$NOTIFY_LOG")"
check "the founder is paged exactly once" "$(pages)" "1"
contains "escalation names the issue" "$ESC" "ASK-288"
contains "escalation names the PR" "$ESC" "#69"
contains "escalation names the failing check" "$ESC" "validate"
contains "escalation says it handed the issue back" "$ESC" "handed ASK-288 back"
contains "head unchanged: it says no new commit landed" "$ESC" "no new commit has landed"
lacks "head unchanged: it does NOT claim a second failure" "$ESC" "failed again"

run redrive >/dev/null 2>&1
check "escalation pages ONCE per signature, not per run" "$(pages)" "1"

# The agent pushed a fix and the same check went red again. NOW "it failed again"
# is a true sentence, and it is the sentence the founder gets.
fresh_state repushed
fixture "$WORLD"
OUT="$(run redrive)"; SIG="$(printf '%s' "$OUT" | cut -f2)"
run mark-dispatched --issue ASK-288 --signature "$SIG" \
  --head-sha bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb >/dev/null
fixture "$(printf '%s' "$WORLD" | sed 's/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee/')"
run redrive >/dev/null; RC=$?
check "a re-push failing the same check earns no second attempt" "$RC" "1"
ESC="$(cat "$NOTIFY_LOG")"
contains "head moved: it says the same check failed again" "$ESC" "failed again"
lacks "head moved: it does not also claim no commit landed" "$ESC" "no new commit has landed"

# --- 7. the signature is the CHECK SET, and this repo emits one check --------
# Documented plainly rather than promised: `validate` is the only CI check this
# repo posts, so the signature is constant per PR here and the cap is ONE
# hand-back per PR, full stop. The per-signature keying only begins to
# discriminate if a second required check is ever added -- which is why the case
# below asserts the DISCRIMINATION, not a behaviour reachable today.
fresh_state twocheck
fixture "$(printf '%s' "$WORLD" | sed 's/"name":"validate"/"name":"lefthook"/')"
OUT="$(run redrive)"
SIG2="$(printf '%s' "$OUT" | cut -f2)"
if [ "$SIG" != "$SIG2" ]; then ok "a different check set is a different signature"
else bad "a different check set is a different signature" "both were [$SIG]"; fi

# --- 8. ambiguity is refused, never guessed ----------------------------------
# Two distinct issue ids in one title is a title this tool cannot read. Picking
# either one is how the wrong issue gets re-dispatched.
fresh_state ambiguous
fixture '[{"number":88,"headRefName":"sana/two-things","isDraft":false,
  "headRefOid":"ffffffffffffffffffffffffffffffffffffffff",
  "url":"https://x/88","title":"fold ASK-100 into ASK-101",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"validate","status":"COMPLETED",
     "conclusion":"FAILURE","workflowName":"Skeleton Validation"}]}]'
run redrive >/dev/null; RC=$?
check "an ambiguous title is not attributed" "$RC" "1"
check "an ambiguous title does not page the founder" "$(pages)" "0"

# A non-agent branch prefix is left alone even with a clean issue id in the title.
fresh_state nonagent
fixture '[{"number":89,"headRefName":"feature/big-thing","isDraft":false,
  "headRefOid":"ffffffffffffffffffffffffffffffffffffffff",
  "url":"https://x/89","title":"a founder branch (ASK-102)",
  "statusCheckRollup":[
    {"__typename":"CheckRun","name":"validate","status":"COMPLETED",
     "conclusion":"FAILURE","workflowName":"Skeleton Validation"}]}]'
run redrive >/dev/null; RC=$?
check "an unknown branch owner is not an agent PR" "$RC" "1"

# --- 9. all-green is quiet, not an error state -------------------------------
fresh_state green
fixture '[{"number":104,"headRefName":"sana/ask-300","isDraft":false,
  "headRefOid":"1111111111111111111111111111111111111111",
  "url":"https://x/104","title":"t (ASK-300)",
  "statusCheckRollup":[{"__typename":"CheckRun","name":"validate",
   "status":"COMPLETED","conclusion":"SUCCESS","workflowName":"Skeleton Validation"}]}]'
run redrive >/dev/null; RC=$?
check "nothing red: exit 1, nothing to do" "$RC" "1"
check "nothing red: founder untouched" "$(pages)" "0"

# --- 10. gh could not answer: not a claim, and not silence -------------------
# The probe's rc is part of its answer (arm_automerge's finding 3, same class).
# Reading a failed `gh` as "no red PRs" is how a real red PR goes unhandled with
# a clean exit -- so it exits 2 and burns no attempt.
fresh_state ghdown
fixture "$WORLD"
GH_RC=7 run redrive >/dev/null; RC=$?
GH_RC=0
check "gh failure exits 2, not 0 and not 1" "$RC" "2"
check "gh failure writes no ledger" "$([ -f "$LEDGER" ] && echo yes || echo no)" "no"

# --- 11. a run still pending is not a failure --------------------------------
fresh_state pending
fixture '[{"number":105,"headRefName":"sana/ask-301","isDraft":false,
  "headRefOid":"2222222222222222222222222222222222222222",
  "url":"https://x/105","title":"t (ASK-301)",
  "statusCheckRollup":[{"__typename":"CheckRun","name":"validate",
   "status":"IN_PROGRESS","conclusion":"","workflowName":"Skeleton Validation"}]}]'
run redrive >/dev/null; RC=$?
check "an in-flight check is not red" "$RC" "1"

# --- 12. an empty rollup is not red ------------------------------------------
# PR #71 on 2026-08-03 really did carry `"statusCheckRollup": []`. No checks have
# reported, which is not the same claim as "the checks passed" and is certainly
# not "the checks failed".
fresh_state norollup
fixture '[{"number":71,"headRefName":"sana/ask-292","isDraft":false,
  "headRefOid":"3333333333333333333333333333333333333333",
  "url":"https://x/71","title":"t (ASK-292)","statusCheckRollup":[]}]'
run redrive >/dev/null; RC=$?
check "no checks reported is not red" "$RC" "1"

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
