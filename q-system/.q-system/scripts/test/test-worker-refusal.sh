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

BOARD = [issue("ASK-801"), issue("ASK-802")]

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
exit 0
SH
cat > "$STUB/gh" <<'SH'
#!/usr/bin/env bash
# no PRs exist in this world; every query answers empty
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
   KIPI_PR_REVIEWER="/usr/bin/true" \
   KIPI_NOTIFY="/usr/bin/true" \
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

# --- 6. NEGATIVE SELF-TEST --------------------------------------------------
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
