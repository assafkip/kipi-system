#!/usr/bin/env bash
# The refusal path: Sana judges an issue unexecutable, and that judgment sticks
# WITHOUT reaching the founder (ASK-275).
#
# WHAT IT PROVES
# --------------
# 1. a refusal applies the needs-scope label (the producer for the ready() filter
#    that test-worker-project-scope.sh proves the consumer half of)
# 2. a refusal does NOT bump the attempt counter -- being right is not a failure
# 3. a refusal does NOT spend the work budget: the loop continues to the next
#    ready issue in the SAME run. That is the difference between a rejection
#    costing a turn and costing a whole dispatch.
# 4. the sentinel is consumed, so a re-scoped issue is not refused forever by a
#    stale file, and the reusable worktree is not left dirty
# 5. it NEVER writes owner:assaf. That label is the founder queue, and routing a
#    re-scope there is the exact defect this path replaces (ASK-149, 2026-07-30).
# 6. a refusal that LEFT A PR still gets that PR reviewed (ASK-275, 2026-08-01).
#    A capability block is frequently PARTIAL -- the executable half ships, the
#    blocked half does not -- so the run ends with real code pushed and a PR
#    open. The first build of this path `continue`d straight past step 5, so
#    that PR got no reviewer, no verdict record, and no kipi/reviewer-approved.
#    Observed live: PRs #49 (ASK-134), #50 (ASK-133), #51 (ASK-132) all opened
#    by the loop on 2026-07-31, all three still unreviewed, all three orphaned
#    permanently -- the blocked:capability label removes the issue from the
#    picker, so no later run ever comes back for them. The loop had just been
#    taught to review everything it opens and then built a new way to abandon
#    a PR unreviewed.
#
# The agent is a stub that writes the sentinel. That is the honest seam: whether
# Sana DECIDES to refuse is a model judgment this suite cannot and should not
# assert. What it asserts is that the worker does the right thing once she has.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER="${KIPI_WORKER_UNDER_TEST:-$REPO_SCRIPTS/linear-worker.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT

# --- fixture Linear: two ready in-repo issues -------------------------------
# Two, not one, because case 3 is "does the loop reach the SECOND one after
# refusing the first". With a single-issue board that assertion cannot exist.
cat > "$WORK/fixture-server.py" <<'PY'
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

def issue(ident):
    return {"id": ident, "identifier": ident, "title": "fixture " + ident,
            "description": "## Definition of Ready\nOutcome: x",
            "state": {"name": "backlog", "type": "backlog"},
            "project": {"name": "kipi-system"},
            "labels": {"nodes": [{"name": "owner:sana"}]}}

# ORDER IS LOAD-BEARING for the budget assertion (cases 11-12). The worker breaks
# at the top of the loop once DONE reaches --limit (2 here), so the board is laid
# out so the ONLY way to reach ASK-807 is for the two continuations before it to
# have spent no budget. 805 sits between them and must NOT spend one: it is the
# empty-commit case, which parks.
BOARD = [issue("ASK-801"), issue("ASK-802"), issue("ASK-803"), issue("ASK-804"),
         issue("ASK-805"), issue("ASK-806"), issue("ASK-807")]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        data = ({"teams": {"nodes": [{"id": "t"}]}} if "teams(" in body else
                {"issues": {"nodes": BOARD,
                            "pageInfo": {"hasNextPage": False, "endCursor": None}}})
        out = json.dumps({"data": data}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers()
        self.wfile.write(out)

srv = HTTPServer(("127.0.0.1", 0), H)
print(srv.server_port, flush=True)
srv.serve_forever()
PY
python3 "$WORK/fixture-server.py" > "$WORK/port" 2> "$WORK/server.err" &
SRV_PID=$!
for _ in $(seq 1 100); do PORT="$(cat "$WORK/port" 2>/dev/null)"; [ -n "${PORT:-}" ] && break; sleep 0.1; done
[ -n "${PORT:-}" ] || { echo "fixture server did not start"; exit 1; }

# --- stubs ------------------------------------------------------------------
# `claude` refuses ASK-801 by writing the sentinel into its cwd (the worktree),
# and does nothing at all for ASK-802 -- so the two paths are distinguishable.
# python3 is NOT shadowed: the picker and the label call are the code under test.
STUB="$WORK/stub"; mkdir -p "$STUB"
cat > "$STUB/claude" <<'SH'
#!/usr/bin/env bash
# ASK-801 refuses on SCOPE, ASK-802 refuses on CAPABILITY. Two classes, so the
# suite can prove they are routed differently rather than merely both excluded.
if printf '%s' "$*" | grep -q 'ASK-801'; then
  printf '%s' "the DoR asks for 304 spillover triages, which is not one bounded change" > .sana-needs-scope
fi
if printf '%s' "$*" | grep -q 'ASK-802'; then
  printf '%s' "Edit(.claude/rules/**) refused by the harness sensitive-path guard" > .sana-blocked-capability
fi
# ASK-803 is the PARTIAL capability block, the shape all three live PRs had:
# the executable half is committed and pushed, the blocked half is not, so the
# run ends refusing WITH a PR open. Nothing here is a second refusal class --
# it is the same blocked:capability sentinel, plus the state the live runs
# actually left behind.
if printf '%s' "$*" | grep -q 'ASK-803'; then
  printf '%s' "PARTIAL: 3 of 4 files shipped; Edit(.claude/rules/**) refused for the 4th" > .sana-blocked-capability
  : > shipped-half.txt
  git add shipped-half.txt >/dev/null 2>&1
  git commit --quiet -m "ASK-803 the half that shipped" >/dev/null 2>&1
  # The marker is what flips the gh stub from "no PR" to "PR #803". Written
  # AFTER the commit so the ordering matches life: the PR exists only once the
  # agent has pushed something to open it for.
  : > "${TEST_PR_MARKER:-/dev/null}-803"
fi
# ASK-804 is the CONTINUATION case (ASK-281): Sana is blocked, Codex is not.
# Same sentinel as 802/803 -- the difference is entirely in what the OTHER
# runner does with it, which is the point: a capability Sana lacks is not
# automatically a capability the fleet lacks.
if printf '%s' "$*" | grep -q 'ASK-804'; then
  printf '%s' "Edit(.claude/rules/**) refused by the Claude Code sensitive-path guard" > .sana-blocked-capability
  # SHE SHIPS A HALF AND OPENS THE PR BEFORE SHE BLOCKS. That ordering is the
  # whole of case 12: a capability block is usually partial, so by the time the
  # handoff runs there is already a PR, and the worker's only push lived INSIDE
  # the "no PR yet" branch. The push is real (origin is a real bare repo here),
  # because the assertion is about what the remote holds, not about intent.
  : > sana-half-804.txt
  git add sana-half-804.txt >/dev/null 2>&1
  git commit --quiet -m "ASK-804 the half Sana could ship" >/dev/null 2>&1
  git push --quiet -u origin HEAD >/dev/null 2>&1
  : > "${TEST_PR_MARKER:-/dev/null}-804"
fi
# ASK-805 blocks identically to 804. The difference is entirely in what Codex
# leaves behind (an EMPTY commit), which is the point of the case: the worker
# must judge the WORK, not the fact that HEAD moved.
if printf '%s' "$*" | grep -q 'ASK-805'; then
  printf '%s' "Edit(.claude/rules/**) refused by the Claude Code sensitive-path guard" > .sana-blocked-capability
fi
# ASK-806 is the SECOND continuation. Two are needed, not one: --limit is 2, so a
# single continuation can never take DONE to the cap and the budget assertion
# would pass on a worker that spends nothing.
if printf '%s' "$*" | grep -q 'ASK-806'; then
  printf '%s' "Edit(.claude/rules/**) refused by the Claude Code sensitive-path guard" > .sana-blocked-capability
fi
# ASK-807 has no stub behaviour at all. It is the MARKER: it exists only so that
# "the budget was spent" has an observable consequence. Reaching it means the two
# continuations above cost nothing.
exit 0
SH
cat > "$STUB/gh" <<'SH'
#!/usr/bin/env bash
# No PRs exist in this world EXCEPT the one the ASK-803 stub opens mid-run.
# Stateful on purpose: the worker asks `gh pr list` twice per issue -- once at
# the severity-floor gate BEFORE the agent runs, once at step 5 AFTER. A stub
# that answered #803 to both would make the gate skip ASK-803 at GATE=20 (no
# verdict on an existing PR) and the agent would never run at all.
ARGV="$*"
# ONE MARKER PER ISSUE. A single shared marker file can only ever describe one
# issue's PR, and two issues now open one (ASK-803 and ASK-804). With the old
# shared file, ASK-804's `pr list` answered "PR #803" the moment ASK-803's stub
# ran -- so ASK-804 looked like it already had a PR before its own agent ever
# started, and the severity-floor gate skipped it.
# The issue number is read off the argv because it appears in both shapes the
# worker uses: `--head sana/ask-804` and the bare `804` that arm_automerge
# passes. Every fixture issue is ASK-80x, so `80[0-9]` is exact here.
NUM="$(printf '%s' "$ARGV" | grep -o '80[0-9]' | head -1)"
MARK="${TEST_PR_MARKER:-/dev/null}-${NUM:-none}"
case "$ARGV" in
  *"pr list"*)        [ -f "$MARK" ] && echo "$NUM" ;;
  # arm_automerge probes this first; "true" means already armed, which is the
  # silent healthy branch and keeps the arm out of this test's assertions.
  *autoMergeRequest*) [ -f "$MARK" ] && echo true ;;
  *headRefOid*)       [ -f "$MARK" ] && echo "000000000000000000000000000000000000$NUM" ;;
esac
exit 0
SH
# The reviewer is RECORDED, not stubbed away: whether step 5 ran at all on the
# refusal path is the whole question, and the only deterministic answer is
# whether the reviewer was invoked with the PR number.
REVIEWER_LOG="$WORK/reviewer-calls.log"
cat > "$WORK/fake-reviewer.sh" <<SH
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$REVIEWER_LOG"
exit 0
SH
# The Codex handoff runner is INJECTED for the same reason the reviewer is: the
# question "what does the worker do when the second runner also refuses" is a
# real 3am state, and asserting it against the real `codex` binary would bill a
# model run per case -- so the branch would stay untested, which is how the
# single-runner assumption shipped in the first place (ASK-281).
CODEX_LOG="$WORK/codex-calls.log"
cat > "$WORK/fake-codex.sh" <<SH
#!/usr/bin/env bash
# ONE LINE PER INVOCATION, not the whole prompt. The handoff prompt names the
# issue several times and spans many lines, so logging it verbatim made
# \`grep -c\` count matching LINES and report 2 invocations for a single call --
# a cap assertion that fails on a correct worker is worse than none.
printf 'INVOKE %s\n' "\$(printf '%s' "\$*" | grep -o 'ASK-[0-9]*' | head -1)" >> "$CODEX_LOG"
printf '%s\n' "\$*" >> "$WORK/codex-prompts.log"
# ASK-804: Codex CAN do what Sana could not, and proves it with a commit.
# A commit is the bar on purpose -- "exited 0 having done nothing" is the exact
# shape that made ASK-221 invisible to the attempt counter, and treating it as a
# success here would silently un-park an issue nobody worked.
if printf '%s' "\$*" | grep -q 'ASK-804'; then
  : > codex-continued.txt
  git add codex-continued.txt >/dev/null 2>&1
  git commit --quiet -m "ASK-804 Codex continued what Sana could not" >/dev/null 2>&1
  exit 0
fi
# ASK-806: the same real continuation as 804. Present so the two of them together
# reach --limit 2 and the budget spend has an observable edge (ASK-807 unreached).
if printf '%s' "\$*" | grep -q 'ASK-806'; then
  : > codex-continued-806.txt
  git add codex-continued-806.txt >/dev/null 2>&1
  git commit --quiet -m "ASK-806 Codex continued what Sana could not" >/dev/null 2>&1
  exit 0
fi
# ASK-805: HEAD MOVES BUT NOTHING CHANGED. An empty commit is what a runner
# produces when it exits believing it worked and did not -- the ASK-221 shape one
# layer deeper. \`git commit --allow-empty\` is not exotic: \`--amend\`, a rebase
# that drops the only hunk, and a commit of an already-committed tree all land
# here. If a moved HEAD alone counts as proof, this un-parks an issue nobody
# worked, which is precisely what the commit bar exists to prevent.
if printf '%s' "\$*" | grep -q 'ASK-805'; then
  git commit --quiet --allow-empty -m "ASK-805 Codex committed nothing at all" >/dev/null 2>&1
  exit 0
fi
# Every other blocked issue: Codex is refused too, so the park still happens.
# This is what keeps cases 3b and 6 honest -- they now pass THROUGH the handoff.
printf '%s' "codex has no credential for the target host either" > .codex-blocked-capability
# ...AND it records how to re-test that refusal, which is what its own handoff
# prompt instructs it to do. The name is one nothing can have installed, so the
# probe FAILS when evaluated -- a probe that already passes is refused at record
# time and would tell us nothing about whether it survived the handoff.
printf '%s' "bin:a-binary-no-machine-has-installed" > .codex-blocked-capability.probe
exit 0
SH
# The label + progress calls are the thing under test, so they are RECORDED
# rather than stubbed away: a wrapper logs the argv and forwards nothing to
# Linear. Asserting on this log is how "which label did it write" is answered
# without a live board.
cat > "$STUB/linear-sync-recorder.py" <<'SH'
import sys
open(sys.argv[0].replace("linear-sync-recorder.py", "sync-calls.log"), "a").write(" ".join(sys.argv[1:]) + "\n")
sys.exit(0)
SH
chmod +x "$STUB/claude" "$STUB/gh"

# --- a real git repo for SKEL ------------------------------------------------
SKEL="$WORK/kipi-system"
git init --quiet --bare "$WORK/origin.git"
git init --quiet "$SKEL"
git -C "$SKEL" config user.email t@t; git -C "$SKEL" config user.name t
: > "$SKEL/seed"; git -C "$SKEL" add seed; git -C "$SKEL" commit --quiet -m seed
git -C "$SKEL" remote add origin "$WORK/origin.git"
git -C "$SKEL" push --quiet -u origin HEAD:main 2>/dev/null

STATE="$WORK/state"
# REDIRECTED TO A FILE, never captured with $( ). run_bounded backgrounds a
# watchdog subshell and kills the SUBSHELL when the job finishes -- the `sleep`
# inside it survives as an orphan, still holding whatever stdout it inherited.
# Under a command substitution that orphan holds the pipe open for the full
# TIMEOUT_SECONDS, so the capture blocks long after the worker has exited. It
# looked exactly like the worker hanging and cost two 120s timeouts to tell
# apart. Production is unaffected: converge.sh runs the worker with >>"$LOG",
# a redirect, not a substitution. Captured as spillover, not fixed here.
RUN_OUT="$WORK/run.out"
PATH="$STUB:$PATH" \
   KIPI_SKEL="$SKEL" KIPI_STATE_DIR="$STATE" \
   KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
   KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
   KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
   KIPI_CODEX_RUNNER="bash $WORK/fake-codex.sh" \
   KIPI_NOTIFY="/usr/bin/true" \
   TEST_PR_MARKER="$WORK/pr-803-open" \
   bash "$WORKER" --apply --limit 2 > "$RUN_OUT" 2>&1
OUT="$(cat "$RUN_OUT")"

echo "== worker refusal path (worker under test: $WORKER)"

# --- 1. the refusal is recognised -------------------------------------------
if printf '%s\n' "$OUT" | grep -q "ASK-801 REFUSED as unexecutable"; then
  ok "recognises the refusal sentinel and says so"
else
  bad "recognises the refusal sentinel" "no REFUSED line in output"
fi

if printf '%s\n' "$OUT" | grep -q "not one bounded change"; then
  ok "carries the reason Sana wrote, not a generic message"
else
  bad "carries the reason Sana wrote" "the reason text did not reach the log"
fi

# --- 2. it tried to apply needs-scope, and never owner:assaf ----------------
# The log records the attempt even though the fixture Linear cannot apply it.
if printf '%s\n' "$OUT" | grep -q "needs-scope"; then
  ok "routes the refusal to the needs-scope label"
else
  bad "routes the refusal to the needs-scope label" "no needs-scope in output"
fi

ALL_WRITTEN="$OUT
$(cat "$STATE/linear-worker.log" 2>/dev/null)"
# SCOPED TO LABEL WRITES, not to the string anywhere. The picker's own status
# line reads "(owner:sana, has a DoR, not owner:assaf, project=...)", so a bare
# substring search matches on every healthy run. The first version of this check
# did exactly that and still reported ok -- because it piped into `grep -q`,
# which exits at the first match and left printf writing to a closed pipe, so
# the assertion was scoring a TRUNCATED input. Two bugs cancelling: a check that
# could not fail, reading text it could not see. Assert the thing itself: no
# label operation may name the founder queue.
if grep -n "owner:assaf" <<<"$ALL_WRITTEN" | grep -qi "label"; then
  bad "never routes a refusal to the founder queue" \
      "a label operation named owner:assaf: $(grep "owner:assaf" <<<"$ALL_WRITTEN" | grep -i label | head -1)"
else
  ok "never routes a refusal to the founder queue (no label op names owner:assaf)"
fi

# And the positive half: the label it DOES write is needs-scope. Asserting only
# the absence of owner:assaf would pass for a worker that labels nothing at all.
if grep -q "label .* needs-scope\|labelled needs-scope\|needs-scope label did NOT apply" <<<"$ALL_WRITTEN"; then
  ok "the label operation it performs is needs-scope"
else
  bad "the label operation it performs is needs-scope" "no needs-scope label operation found"
fi

# --- 3. a refusal does not spend the work budget ----------------------------
# --limit 2 with one refusal must still reach ASK-802. If the refusal consumed a
# budget slot this assertion fails, which is the whole of "a rejection costs a
# turn, not a dispatch".
if printf '%s\n' "$OUT" | grep -q "ASK-802"; then
  ok "continues to the next ready issue in the SAME run (refusal cost a turn, not the run)"
else
  bad "continues to the next ready issue in the same run" \
      "ASK-802 was never reached: $(printf '%s' "$OUT" | tr '\n' '|' | cut -c1-400)"
fi

# --- 3b. the two refusal classes are routed DIFFERENTLY ----------------------
# The defect this suite gained on 2026-07-30 after one live run: a single channel
# labelled a PERMISSION block as needs-scope, which sends linear-dor-drafter.py to
# rewrite a spec that was already correct. Both classes leaving the queue is not
# enough -- they must leave it toward different people.
if grep -q "ASK-802 BLOCKED on a missing capability" <<<"$ALL_WRITTEN"; then
  ok "a capability block is reported as a capability block, not as a bad spec"
else
  bad "a capability block is reported as a capability block" \
      "expected 'ASK-802 BLOCKED on a missing capability'"
fi

if grep -q "label ASK-802 blocked:capability\|ASK-802 labelled blocked:capability\|ASK-802 REFUSED but the blocked:capability" <<<"$ALL_WRITTEN"; then
  ok "a capability block routes to blocked:capability, not needs-scope"
else
  bad "a capability block routes to blocked:capability" "no blocked:capability label op for ASK-802"
fi

# The two must not be swapped: ASK-801 is the scope case and must NOT be labelled
# blocked:capability. Without this, a worker that labelled everything
# blocked:capability would satisfy both assertions above.
if grep "ASK-801" <<<"$ALL_WRITTEN" | grep -q "blocked:capability"; then
  bad "the classes are not swapped" "ASK-801 (a scope refusal) was labelled blocked:capability"
else
  ok "the classes are not swapped (ASK-801 stays needs-scope)"
fi

# --- 4. a refusal is not a failed attempt -----------------------------------
ATT="$STATE/linear-worker-attempts.json"
if [ -f "$ATT" ] && python3 -c "
import json,sys
d=json.load(open('$ATT'))
sys.exit(0 if d.get('ASK-801',{}).get('count',0)>0 else 1)" 2>/dev/null; then
  bad "a refusal does not burn an attempt" "ASK-801 has a nonzero attempt count: $(cat "$ATT")"
else
  ok "a refusal does not burn an attempt (being right is not a failure)"
fi

# --- 5. the sentinel is consumed --------------------------------------------
LEFT="$(find "$STATE" "$SKEL" -name '.sana-needs-scope' 2>/dev/null | head -1)"
if [ -n "$LEFT" ]; then
  bad "consumes the sentinel" "still on disk at $LEFT -- a re-scoped issue would be refused forever"
else
  ok "consumes the sentinel (a re-scoped issue can be picked up again)"
fi

# --- 6. a refusal that left a PR still gets that PR REVIEWED -----------------
# THE REGRESSION THIS CASE EXISTS FOR (ASK-275, 2026-08-01). A capability block
# is usually partial: the executable half ships. The refusal branch used to
# `continue` before step 5, so the PR that half opened was never handed to the
# reviewer -- no verdict record, no kipi/reviewer-approved, and the
# blocked:capability label then removes the issue from the picker, so nothing
# ever comes back for it. Live evidence: PRs #49/#50/#51, opened 2026-07-31,
# still unreviewed. "Every PR this worker opens gets the adversarial reviewer"
# was true on one path and false on the other.
REVIEWED="$(cat "$REVIEWER_LOG" 2>/dev/null)"
if grep -q '803' <<<"$REVIEWED" && grep -q -- '--issue ASK-803' <<<"$REVIEWED"; then
  ok "a capability block that left a PR still sends that PR to the reviewer"
else
  bad "a capability block that left a PR still sends that PR to the reviewer" \
      "reviewer was never invoked for PR #803 -- the refusal abandoned an open PR unreviewed. Log: '${REVIEWED:-<empty>}'"
fi

# The refusal semantics must SURVIVE the fall-through. Reviewing the PR is the
# only thing that changes: the issue is still blocked, still labelled, and still
# not a failed attempt. Without these three, the fix would trade one defect for
# a refusal that no longer refuses.
if grep -q "ASK-803 BLOCKED on a missing capability" <<<"$ALL_WRITTEN"; then
  ok "a partial capability block is still reported as blocked (reviewing it did not un-block it)"
else
  bad "a partial capability block is still reported as blocked" "no BLOCKED line for ASK-803"
fi

if grep -q "label ASK-803 blocked:capability\|ASK-803 labelled blocked:capability\|ASK-803 REFUSED but the blocked:capability" <<<"$ALL_WRITTEN"; then
  ok "a partial capability block still leaves the ready pool via blocked:capability"
else
  bad "a partial capability block still leaves the ready pool" "no blocked:capability label op for ASK-803"
fi

if [ -f "$ATT" ] && python3 -c "
import json,sys
d=json.load(open('$ATT'))
sys.exit(0 if d.get('ASK-803',{}).get('count',0)>0 else 1)" 2>/dev/null; then
  bad "a partial refusal does not burn an attempt" "ASK-803 has a nonzero attempt count: $(cat "$ATT")"
else
  ok "a partial refusal does not burn an attempt (it produced a diff AND a correct refusal)"
fi

# --- 6b. NEGATIVE SELF-TEST for case 6 --------------------------------------
# Case 6 greps a file that may not exist. Prove the assertion can fail: an empty
# reviewer log must not satisfy it. Without this, a run where the reviewer was
# never wired at all would read as a pass on the one case this suite was
# extended to catch.
if grep -q '803' <<<"" 2>/dev/null; then
  bad "negative self-test (reviewer log)" "an empty reviewer log satisfied the review assertion -- the check is inert"
else
  ok "negative self-test: the review assertion rejects an empty reviewer log"
fi

# --- 8. blocked:capability HAS A CONTINUATION (ASK-281) ---------------------
# THE DEFECT: `blocked:capability` was terminal. The Linear comment named exactly
# one actor who could clear it -- whoever owns the config, i.e. the founder -- and
# the founder's answer on 2026-08-01 was "I'm not going to unblock it, Sana or
# Codex need to do that." Ten issues (ASK-116, 132-140) sat at that label while
# the loop logged `nothing ready (0 ready issue)` every 15 minutes. The queue was
# not empty, it was parked.
#
# The unstated assumption was that "not Sana" means "the founder". It skipped the
# third runner. Sana runs inside Claude Code, whose sensitive-path guard refuses
# Edit/Write under `.claude/**` and is not liftable by `permissions.allow`. Codex
# is a different binary and does not inherit that guard -- probed live on
# 2026-08-01: `codex exec -s workspace-write` created `.claude/rules/probe.md`
# from nothing, verified on disk, 14,332 tokens billed.
#
# So: a capability SANA lacks is not automatically a capability the FLEET lacks,
# and the worker must ask the other runner before parking.
CODEX_CALLS="$(cat "$CODEX_LOG" 2>/dev/null)"

if grep -q 'ASK-804' <<<"$CODEX_CALLS"; then
  ok "a capability block is handed to the Codex runner before it is parked"
else
  bad "a capability block is handed to the Codex runner before it is parked" \
      "codex was never invoked for ASK-804. Log: '${CODEX_CALLS:-<empty>}'"
fi

# The assertion the whole issue exists for: Codex succeeded, so the label that
# removes the issue from the picker must NOT be applied.
if grep "ASK-804" <<<"$ALL_WRITTEN" | grep -q "blocked:capability"; then
  bad "a Codex continuation does not park the issue" \
      "ASK-804 was labelled blocked:capability even though Codex continued it: $(grep "ASK-804" <<<"$ALL_WRITTEN" | grep "blocked:capability" | head -1)"
else
  ok "a Codex continuation does NOT apply blocked:capability (the state is no longer terminal)"
fi

# ...and it is reported as a continuation, not silently swallowed. An issue that
# quietly stops being blocked with nothing in the log is worse than one that
# parks: the 3am operator has no way to know a second runner touched the branch.
if grep -q "ASK-804 Codex CONTINUED" <<<"$ALL_WRITTEN"; then
  ok "the continuation is reported, so the 3am operator can see a second runner ran"
else
  bad "the continuation is reported" "no 'ASK-804 Codex CONTINUED' line"
fi

# ONE attempt, never a loop (loop-exits.md exit 7). A dead Codex at 3am must not
# become unbounded model spend, so the handoff is capped at a single call per
# issue per run.
# No `|| echo 0` fallback: grep -c already PRINTS 0 when it matches nothing and
# then exits 1, so the fallback appended a second line and `[` got "0\n0".
N804="$(grep -c '^INVOKE ASK-804$' <<<"$CODEX_CALLS" 2>/dev/null)" || true
if [ "${N804:-0}" -eq 1 ]; then
  ok "the handoff is ONE Codex attempt per issue per run, not a retry loop"
else
  bad "the handoff is ONE Codex attempt per issue per run" \
      "codex was invoked $N804 times for ASK-804"
fi

# When BOTH runners refuse, the park still happens AND the comment records both.
# Recording only Sana's refusal would send the reader back to the founder, which
# is the state this whole change removes.
if grep -q "codex has no credential for the target host either" <<<"$ALL_WRITTEN"; then
  ok "when Codex also refuses, its reason is recorded alongside Sana's"
else
  bad "when Codex also refuses, its reason is recorded alongside Sana's" \
      "the Codex refusal text never reached the log or the Linear note"
fi

# --- 8c. Codex's PROBE survives the handoff ---------------------------------
# (codex PR #77, linear-worker.sh:1537.) The probe files for BOTH runners were
# read in one loop that ran BEFORE the handoff, and deleted immediately after.
# Codex is instructed to write its probe during the handoff -- so the read
# happened before the file could exist, every Codex-recorded probe was dropped,
# and the park stored `none`. `none` means hand-clear-only, which is precisely
# the permanent block ASK-288 exists to remove: the second runner is the one
# with the different harness, so its probe is the one most likely to describe a
# capability that will actually arrive.
if grep -q "parked with probe 'bin:a-binary-no-machine-has-installed'" <<<"$ALL_WRITTEN"; then
  ok "a probe Codex recorded during the handoff reaches the park"
else
  bad "a probe Codex recorded during the handoff reaches the park" \
      "the park stored no Codex probe -- it was read before Codex ran, so the block is hand-clear-only. Saw: $(grep -o "parked with probe '[^']*'" <<<"$ALL_WRITTEN" | head -3 | tr '\n' ' ')$(grep -c 'parked with NO probe' <<<"$ALL_WRITTEN") park(s) recorded NO probe"
fi
# ORDERING, read from the source. The assertion above proves the probe arrives;
# this one names WHY it used to not, so a future edit that moves the read back
# above the handoff fails here with the reason attached rather than as 22
# mystery failures downstream (which is what the regression actually looks like:
# the unconsumed .probe leaves the worktree dirty and the position guard then
# refuses to reposition it, wedging every issue after the first).
CODEX_RUN_LINE="$(grep -n 'CODEX_CMD' "$WORKER" | head -1 | cut -d: -f1)"
CODEX_PROBE_LINE="$(grep -n 'read_capability_probe "\$TREE/\.codex-blocked-capability\.probe"' "$WORKER" | head -1 | cut -d: -f1)"
if [ -n "$CODEX_RUN_LINE" ] && [ -n "$CODEX_PROBE_LINE" ] && [ "$CODEX_PROBE_LINE" -gt "$CODEX_RUN_LINE" ]; then
  ok "the Codex probe is read AFTER the Codex run (line $CODEX_PROBE_LINE > $CODEX_RUN_LINE)"
else
  bad "the Codex probe is read after the Codex run" \
      "codex runs at '${CODEX_RUN_LINE:-none}', its probe is read at '${CODEX_PROBE_LINE:-none}' -- a read that precedes the run reads a file that cannot exist yet"
fi

# --- 8b. NEGATIVE SELF-TEST for case 8 --------------------------------------
# Case 8's central assertion is an ABSENCE (no blocked:capability for ASK-804),
# and an absence passes for free when the issue was never processed at all.
# Pin that ASK-804 really went down the refusal path in this run.
if grep -q "ASK-804 BLOCKED on a missing capability" <<<"$ALL_WRITTEN"; then
  ok "negative self-test: ASK-804 really entered the capability-refusal path"
else
  bad "negative self-test: ASK-804 really entered the capability-refusal path" \
      "no BLOCKED line for ASK-804 -- the 'not labelled' assertion above passed vacuously"
fi

# --- 9. a continuation is not still carried as a refusal ---------------------
# The bug this replaces: the handoff cleared $REFUSE_LABEL but still set
# $REFUSED, so every downstream consumer of $REFUSED read a completed issue as a
# park. The most visible consequence is the closing line an operator scans, which
# reported the issue "held at" a label that had just been deliberately emptied.
if grep "ASK-804" <<<"$ALL_WRITTEN" | grep -q "is NOT done: held at"; then
  bad "a continued issue is not reported as held" \
      "ASK-804 was continued but the closing line still reports it held: $(grep "ASK-804" <<<"$ALL_WRITTEN" | grep "is NOT done: held at" | head -1)"
else
  ok "a continued issue is NOT reported as held at a label (the closing line matches reality)"
fi

# --- 10. an EMPTY commit is not proof of work -------------------------------
# ASK-805's Codex exits 0 with a moved HEAD and an unchanged tree. Moving HEAD is
# not the same as doing the work, and the whole point of the commit bar is that
# "exited 0 having done nothing" must not un-park an issue.
if grep "ASK-805" <<<"$ALL_WRITTEN" | grep -q "blocked:capability"; then
  ok "an empty Codex commit does NOT count as a continuation (ASK-805 still parks)"
else
  bad "an empty Codex commit does not count as a continuation" \
      "ASK-805 was never labelled blocked:capability -- an empty commit un-parked it"
fi

# The same fact from the other side: it must not be announced as a continuation.
if grep -q "ASK-805 Codex CONTINUED" <<<"$ALL_WRITTEN"; then
  bad "an empty commit is not announced as a continuation" \
      "ASK-805 was reported CONTINUED on an empty commit"
else
  ok "an empty commit is not announced as a continuation"
fi

# 10b. NEGATIVE SELF-TEST for case 10. Both assertions above pass for free if
# ASK-805 never reached the handoff at all, so pin that Codex really ran on it.
if grep -q '^INVOKE ASK-805$' <<<"$CODEX_CALLS"; then
  ok "negative self-test: Codex really ran on ASK-805 (the empty-commit assertions are not vacuous)"
else
  bad "negative self-test: Codex really ran on ASK-805" \
      "codex was never invoked for ASK-805. Log: '${CODEX_CALLS:-<empty>}'"
fi

# --- 11. a continuation SPENDS a budget slot --------------------------------
# A refusal costs a turn, not a dispatch -- that is case 3 and it stays. But a
# continuation is not a refusal: a second runner really did work the issue, and
# an unattended run that treats real work as free processes issues past its own
# --limit. The board is ordered so this has one observable edge: with --limit 2,
# the two continuations (804, 806) are the entire budget, and ASK-807 sits behind
# them. Reaching ASK-807 means both continuations were counted as free.
if grep -q "ASK-807" <<<"$ALL_WRITTEN"; then
  bad "a Codex continuation spends a budget slot" \
      "ASK-807 was processed, so the two continuations before it cost no budget and the run overran --limit 2"
else
  ok "a Codex continuation spends a budget slot (--limit 2 stopped the run before ASK-807)"
fi

# 11b. NEGATIVE SELF-TEST for case 11. The assertion is an ABSENCE, and it passes
# for free if the run died before ASK-806 for an unrelated reason. Pin that the
# SECOND continuation actually happened -- that is what took DONE to the cap.
if grep -q "ASK-806 Codex CONTINUED" <<<"$ALL_WRITTEN"; then
  ok "negative self-test: ASK-806 really continued (the budget cap was reached, not stumbled into)"
else
  bad "negative self-test: ASK-806 really continued" \
      "no 'ASK-806 Codex CONTINUED' line -- the ASK-807 absence above passed vacuously"
fi

# --- 12. a continuation reaches the REMOTE the reviewer reads ---------------
# THE DEFECT: the worker's only `git push` lived inside the "no PR yet" branch,
# so it ran only when the worker opened the PR itself. A capability block is
# usually PARTIAL -- Sana ships a half and opens a PR, then blocks -- and the
# Codex handoff commits AFTER that. So on the exact path this issue built, the
# continuation stayed local: the reviewer was handed a PR whose remote head was
# still Sana's half, it reviewed a diff the continuation is absent from, and the
# run reported the issue CONTINUED. An approval for work nobody can see is worse
# than no review: the label is cleared, the issue leaves the parked pool, and the
# only copy of the work is a worktree on one machine.
#
# Asserted against the REMOTE, not against a log line. "The worker said it
# pushed" is the claim under test; what refs/heads/sana/ask-804 actually holds
# is the answer.
ORIGIN_FILES="$(git -C "$WORK/origin.git" ls-tree -r --name-only refs/heads/sana/ask-804 2>/dev/null)"
if grep -qx 'codex-continued.txt' <<<"$ORIGIN_FILES"; then
  ok "a Codex continuation is pushed to the remote before the review (the PR carries the work)"
else
  bad "a Codex continuation is pushed to the remote before the review" \
      "origin/sana/ask-804 does not hold codex-continued.txt -- the continuation never left the worktree, so the reviewed PR is missing it. Remote holds: '${ORIGIN_FILES:-<nothing>}'"
fi

# 12b. NEGATIVE SELF-TEST for case 12. The check above fails identically whether
# the push is broken or the fixture never pushed anything at all -- and those
# send a reader to opposite places. Pin that Sana's half IS on the remote, so a
# RED above is specifically the continuation missing from a live branch.
if grep -qx 'sana-half-804.txt' <<<"$ORIGIN_FILES"; then
  ok "negative self-test: Sana's half really is on the remote (the branch is live, not absent)"
else
  bad "negative self-test: Sana's half really is on the remote" \
      "origin/sana/ask-804 does not hold sana-half-804.txt -- case 12 above is failing on a dead branch, not on the push"
fi

# ...and the review really ran against that PR. Without this, case 12 would be
# asserting the remote state of a branch nobody reviewed, which is not the
# defect: the cost is that the REVIEWER read a stale head.
if grep -q -- '--issue ASK-804' <<<"$REVIEWED"; then
  ok "the continued issue's PR is the one handed to the reviewer (the stale head had a reader)"
else
  bad "the continued issue's PR is handed to the reviewer" \
      "no reviewer call for ASK-804. Log: '${REVIEWED:-<empty>}'"
fi

# --- 7. NEGATIVE SELF-TEST --------------------------------------------------
# Every assertion above greps a combined output blob. Prove the greps can miss:
# a worker that refuses NOTHING must fail assertion 1. Without this, an empty
# $OUT would satisfy assertions 4, 5 and 6 and read as three passes.
NEG_OUT="$(printf 'worker: 2 ready issue(s)\nok ASK-801\nok ASK-802\n')"
if printf '%s\n' "$NEG_OUT" | grep -q "REFUSED as unexecutable"; then
  bad "negative self-test" "a run with no refusal satisfied the REFUSED assertion -- the check is inert"
else
  ok "negative self-test: the REFUSED assertion rejects a run that refused nothing"
fi

echo
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
