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

# --- the process-table seam --------------------------------------------------
# ci-redrive.py asks the process table whether a converge for the candidate issue
# is already running. The default stub prints an EMPTY table, so every case above
# is decided by its fixture and not by whatever happens to be running on the box
# -- the flakiness test-dispatch-liveness.sh already paid for once (17/17 alone,
# 15/17 alongside the fleet). Cases that need a live converge say so explicitly.
printf '#!/bin/sh\ncat "${PS_FIXTURE:-/dev/null}"\n' > "$TMP/ps"; chmod +x "$TMP/ps"
: > "$TMP/ps-empty"

fixture() { printf '%s' "$1" > "$TMP/prs.json"; }
ps_fixture() { printf '%s\n' "$1" > "$TMP/ps-table"; PS_FIXTURE="$TMP/ps-table"; }

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
  KIPI_PS="$TMP/ps" \
  KIPI_NOTIFY="$TMP/notify.sh" \
  KIPI_ATTEMPTS="$LEDGER" \
  GH_FIXTURE="$TMP/prs.json" \
  GH_RC="${GH_RC:-0}" \
  PS_FIXTURE="${PS_FIXTURE:-$TMP/ps-empty}" \
  NOTIFY_LOG="$NOTIFY_LOG" \
  python3 "$REDRIVE" --repo-dir "$TMP" "$@" 2>"$TMP/err"
}

fresh_state() {
  LEDGER="$TMP/attempts-$1.json"
  NOTIFY_LOG="$TMP/notify-$1.log"
  : > "$NOTIFY_LOG"
  rm -f "$LEDGER"
  PS_FIXTURE="$TMP/ps-empty"
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

# --- 13. work already in flight is not a dead end (PR #73 review r2, finding 1)
# The dispatcher's heartbeat is 900s and a converge run is minutes to tens of
# minutes. So the heartbeat AFTER a redrive dispatch finds the same PR still red
# -- the agent has not pushed yet -- with the attempt flag already set. Round 2
# went straight to escalate() there and paged the founder "it stopped rather than
# hand back an unchanged tree" about a run that was at that moment still running.
#
# The second half is the worse half: escalate() CLAIMS `ci_escalated_<sig>` on
# the way out, so when the converge really did finish and leave the PR red, the
# one true page was already spent on the false one. A wrong page that also
# silences the right page is strictly worse than no page at all.
# The offer half, with the attempt UNSPENT so a passing rc 1 can only come from
# the liveness guard. Asserting this against a spent attempt would pass for the
# wrong reason -- a spent attempt exits 1 anyway, and the case would grade
# nothing (the same vacuous shape the round-1 fixture was caught on).
fresh_state inflight_offer
fixture "$WORLD"
ps_fixture "bash /x/q-system/.q-system/scripts/converge.sh --issue ASK-288 --max-rounds 3"
run redrive >/dev/null; RC=$?
check "a candidate whose converge is live is not offered" "$RC" "1"
contains "the log says why it was skipped" "$(cat "$TMP/err")" "converge for it is already live"
PS_FIXTURE="$TMP/ps-empty"
run redrive >/dev/null; RC=$?
check "control: with no converge live the same candidate IS offered" "$RC" "0"

# The escalation half.
fresh_state inflight
fixture "$WORLD"
OUT="$(run redrive)"; SIG="$(printf '%s' "$OUT" | cut -f2)"
run mark-dispatched --issue ASK-288 --signature "$SIG" \
  --head-sha bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb >/dev/null
ps_fixture "bash /x/q-system/.q-system/scripts/converge.sh --issue ASK-288 --max-rounds 3"

run redrive >/dev/null; RC=$?
check "a spent attempt whose converge is live still exits 1" "$RC" "1"
check "and the founder is NOT paged that it stopped" "$(pages)" "0"

# THE SILENCING HALF. Once the converge is gone and the PR is still red, the page
# the founder was owed must still be available -- a run that fired nothing must
# not have consumed the once-per-signature budget.
PS_FIXTURE="$TMP/ps-empty"
run redrive >/dev/null; RC=$?
check "with the converge gone the attempt is still spent" "$RC" "1"
check "and the true page fires, not swallowed by the false one" "$(pages)" "1"
contains "the true page names the issue" "$(cat "$NOTIFY_LOG")" "ASK-288"

# A converge for a DIFFERENT issue says nothing about this one.
fresh_state otherissue
fixture "$WORLD"
ps_fixture "bash /x/converge.sh --issue ASK-999 --max-rounds 3"
run redrive >/dev/null; RC=$?
check "a converge on another issue does not block this one" "$RC" "0"

# An UNREADABLE process table is not evidence that nothing is running. Erring the
# other way pages the founder about a run that may be live and burns the flag
# doing it; erring this way costs one quiet heartbeat, which is what happens
# today anyway.
fresh_state psdown
fixture "$WORLD"
PS_FIXTURE="/nonexistent/ps-table-that-cannot-be-read"
printf '#!/bin/sh\nexit 3\n' > "$TMP/ps-broken"; chmod +x "$TMP/ps-broken"
OLD_PS="$TMP/ps"
cp "$TMP/ps-broken" "$TMP/ps"
run redrive >/dev/null; RC=$?
check "an unreadable process table offers nothing rather than guessing" "$RC" "1"
check "an unreadable process table pages nobody" "$(pages)" "0"
printf '#!/bin/sh\ncat "${PS_FIXTURE:-/dev/null}"\n' > "$OLD_PS"; chmod +x "$OLD_PS"

# --- 14. the shell integration, driven for real (PR #73 review r2, finding 3) --
# Round 2 shipped the entire kipi-dispatch.sh wiring covered by `bash -n` alone:
# syntax, not behaviour. `bash -n` cannot tell whether the offer is adopted,
# whether mark-dispatched actually gates the launch, or whether an rc 2 leaves
# the fresh pick standing. Every one of those is a live decision on a 900s timer.
#
# So this section runs the REAL kipi-dispatch.sh against the REAL ci-redrive.py
# and the REAL attempts-ledger.py. Only the two edges are stubbed: `gh` (the PR
# world) and `kipi` (the pick + the converge). What is asserted is which issue
# the dispatcher actually handed to converge, read off a file the stub writes.
echo
echo "== ci-redrive x kipi-dispatch =="

DISPATCH="$REPO_ROOT/kipi-dispatch.sh"
if [ ! -f "$DISPATCH" ]; then
  bad "14 kipi-dispatch.sh is present" "not found at $DISPATCH"
else

# UNIQUE IDS PER RUN. Case 14e puts a decoy converge in the GLOBAL process table,
# so a hardcoded id lets two concurrent runs of this suite (the capability gate
# runs the fleet's tests together) satisfy each other's guards. Same lesson
# test-dispatch-liveness.sh learned at 17/17 alone, 15/17 under the gate.
RED_ISS="ASK-8$$"          # the red PR the redrive should hand back
FRESH_ISS="ASK-7$$"        # what `kipi work` offers as the ordinary fresh pick
RED_BRANCH="sana/$(printf '%s' "$RED_ISS" | tr 'A-Z' 'a-z')"

DROOT="$TMP/dispatch"
FAKE_REPO="$DROOT/repo"
SCRIPTS="$FAKE_REPO/q-system/.q-system/scripts"
mkdir -p "$SCRIPTS" "$DROOT/home/.config/kipi" "$DROOT/bin"

# The dispatcher resolves ci-redrive.py off $REPO, and ci-redrive.py resolves
# attempts-ledger.py off its own directory. Both real, both copied.
cp "$REDRIVE" "$SCRIPTS/ci-redrive.py"
cp "$REPO_ROOT/q-system/.q-system/scripts/attempts-ledger.py" "$SCRIPTS/attempts-ledger.py"

cp "$TMP/gh" "$DROOT/bin/gh"
cp "$TMP/ps" "$DROOT/bin/ps-stub"
printf '#!/usr/bin/env bash\nsleep 30\n' > "$DROOT/converge.sh"; chmod +x "$DROOT/converge.sh"

# `kipi work` offers FRESH_ISS. `kipi converge` records the issue it was actually
# given and then stays alive, so the dispatcher's own liveness assert passes and
# the assertion below reads a fact rather than a log line.
cat > "$FAKE_REPO/kipi" <<SH
#!/usr/bin/env bash
case "\$1" in
  work) printf '1 ready issue\n[dry] would work $FRESH_ISS\n' ;;
  converge)
    printf '%s\n' "\$3" >> "$DROOT/dispatched"
    exec bash "$DROOT/converge.sh" --issue "\$3" --max-rounds 3
    ;;
esac
SH
chmod +x "$FAKE_REPO/kipi"

D_LEDGER="$DROOT/attempts.json"
D_PAGES="$DROOT/pages.txt"
D_PRS="$DROOT/prs.json"

RED_WORLD="[{\"number\":91,\"headRefName\":\"$RED_BRANCH\",\"isDraft\":false,
  \"headRefOid\":\"9999999999999999999999999999999999999999\",
  \"url\":\"https://x/91\",\"title\":\"t ($RED_ISS)\",
  \"statusCheckRollup\":[{\"__typename\":\"CheckRun\",\"name\":\"validate\",
   \"status\":\"COMPLETED\",\"conclusion\":\"FAILURE\",
   \"workflowName\":\"Skeleton Validation\"}]}]"

run_dispatch() {  # run_dispatch [GH_RC]
  ( cd "$FAKE_REPO" && HOME="$DROOT/home" PATH="$DROOT/bin:$PATH" \
      KIPI_REPO="$FAKE_REPO" KIPI_NOTIFY="$TMP/notify.sh" \
      KIPI_DISPATCH_DAILY_MAX=9 KIPI_DISPATCH_MAX=999 \
      KIPI_ATTEMPTS="$D_LEDGER" KIPI_GH="$DROOT/bin/gh" KIPI_PS="$DROOT/bin/ps-stub" \
      GH_FIXTURE="$D_PRS" GH_RC="${1:-0}" PS_FIXTURE="${PS_FIXTURE:-$TMP/ps-empty}" \
      NOTIFY_LOG="$D_PAGES" \
      bash "$DISPATCH" >/dev/null 2>&1 )
}
dlog() { cat "$DROOT/home/.config/kipi/dispatch.log" 2>/dev/null; }
dispatched() { tail -1 "$DROOT/dispatched" 2>/dev/null; }

d_reset() {
  rm -rf "$DROOT/home/.config/kipi"; mkdir -p "$DROOT/home/.config/kipi"
  # Seed the beacon so the one-off "heartbeat STARTED" page is not mistaken for
  # a fault page by the assertions below.
  date -u +%s > "$DROOT/home/.config/kipi/dispatch-lastbeat"
  : > "$D_PAGES"; : > "$DROOT/dispatched"
  rm -f "$D_LEDGER"
  PS_FIXTURE="$TMP/ps-empty"
  pkill -f "$DROOT/converge.sh" 2>/dev/null
}

# 14a. the red PR is preferred over the fresh pick, and the attempt is claimed.
d_reset
printf '%s' "$RED_WORLD" > "$D_PRS"
run_dispatch
check "14a the dispatcher hands the RED issue back, ahead of the fresh pick" \
  "$(dispatched)" "$RED_ISS"
contains "14b the log names the hand-back" "$(dlog)" "handing $RED_ISS back"
if grep -q "ci_redrive" "$D_LEDGER" 2>/dev/null; then
  ok "14c the attempt is claimed in the ledger by the DISPATCHER"
else
  bad "14c the attempt is claimed in the ledger by the DISPATCHER" "$(cat "$D_LEDGER" 2>/dev/null)"
fi
pkill -f "$DROOT/converge.sh" 2>/dev/null

# 14d. gh could not answer -> the fresh pick stands and nothing is claimed.
d_reset
printf '%s' "$RED_WORLD" > "$D_PRS"
run_dispatch 7
check "14d a gh failure leaves the fresh pick standing" "$(dispatched)" "$FRESH_ISS"
contains "14e the log says gh could not read PR state" "$(dlog)" "gh could not read PR state"
check "14f a gh failure claims nothing" \
  "$([ -f "$D_LEDGER" ] && echo yes || echo no)" "no"
pkill -f "$DROOT/converge.sh" 2>/dev/null

# 14g. THE FINDING-2 CASE, driven for real. A converge for the red issue is
# already live. Round 2 still offered it, NEXT was overwritten with it, and the
# duplicate guard 40 lines later exited 0 -- so the ready issue that WAS
# dispatchable was thrown away, every heartbeat, for the whole converge.
d_reset
printf '%s' "$RED_WORLD" > "$D_PRS"
bash "$DROOT/converge.sh" --issue "$RED_ISS" --max-rounds 3 >/dev/null 2>&1 &
DECOY=$!
disown "$DECOY" 2>/dev/null || true
sleep 1
# The real process table, not the stub: the point is that the guard sees what the
# dispatcher's own duplicate guard sees.
cp "$DROOT/bin/ps-stub" "$DROOT/ps-stub.bak"
printf '#!/bin/sh\nexec /bin/ps -Ao args=\n' > "$DROOT/bin/ps-stub"; chmod +x "$DROOT/bin/ps-stub"
run_dispatch
check "14g a live converge does not cost the fresh pick its slot" \
  "$(dispatched)" "$FRESH_ISS"
check "14h and no founder page is sent about a run that is still running" \
  "$([ -s "$D_PAGES" ] && cat "$D_PAGES" || echo silent)" "silent"
cp "$DROOT/ps-stub.bak" "$DROOT/bin/ps-stub"
kill "$DECOY" 2>/dev/null
pkill -f "$DROOT/converge.sh" 2>/dev/null

# 14i. nothing red -> the ordinary path is untouched.
d_reset
printf '[]' > "$D_PRS"
run_dispatch
check "14i with nothing red the fresh pick is dispatched as before" \
  "$(dispatched)" "$FRESH_ISS"
lacks "14j and no redrive line is logged" "$(dlog)" "handing"
pkill -f "$DROOT/converge.sh" 2>/dev/null

fi

echo
echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
