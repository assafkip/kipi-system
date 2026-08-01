#!/usr/bin/env bash
# The redrive path: a `needs-scope` refusal comes BACK to the DoR drafter and is
# rewritten, instead of being parked forever behind a message promising exactly
# that (needs-scope-redrive, PRD prd-terminal-state-redrive-2026-08-01).
#
# WHAT IT PROVES
# --------------
# 1. BYPASS CHECK. An issue carrying BOTH a `## Definition of Ready` heading AND
#    the `needs-scope` label is SELECTED. That is the exact pair the old
#    needs_dor() excluded: it returned False on any description containing
#    "Definition of Ready", and a needs-scope issue HAS a DoR -- having a bad one
#    is why Sana refused it. Green here means the exclusion is gone, not renamed.
# 2. The drafter actually asks Linear for labels. It queried none before this
#    (zero `labels` references in the file), so selecting on a label is a real
#    GraphQL change and not a local rename. Asserted against the request bodies
#    the fixture server received, never against the source text.
# 3. A redraft REPLACES the DoR section and preserves everything above it, and
#    the same write drops the needs-scope label so the picker offers the issue
#    again next cycle.
# 4. Redrafts are capped per issue. At the cap the issue gets an honest terminal
#    with a written rationale and NO further claude calls -- and once marked, it
#    stops consuming a slot at all. No new escalation tier (PRD non-goal).
# 5. STARVATION PIN (codex finding-13). `batch = todo[:limit]` is unsorted, has
#    no cursor, and a failed draft leaves the issue in `todo`. Two runs over a
#    board whose head always fails attempt the IDENTICAL head both times and
#    never reach the issue behind it.
# 6. Redraft candidates sort AHEAD of the no-DoR backlog. Without this, 5 is not
#    a theoretical property: the live board had 93 issues lacking a DoR against a
#    limit of 8, so a redraft appended to the tail would never be reached.
#
# HERMETIC. Linear is a local HTTP fixture (KIPI_LINEAR_API_URL), `claude` is a
# stub (KIPI_CLAUDE_BIN), HOME is a temp dir so the live state file at
# ~/.config/kipi/linear-dor-state.json is never touched and slack-notify.sh finds
# no webhook. No check reads the real board and no check writes to it.
#
# Run: bash test-linear-dor-drafter-redrive.sh   (exit 0 = pass)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)"
DRAFTER="${KIPI_DRAFTER_UNDER_TEST:-$REPO_SCRIPTS/linear-dor-drafter.py}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT
mkdir -p "$WORK/home"

# --- fixture Linear ---------------------------------------------------------
# Reads the board from disk on every request so one server serves every case.
# Logs each request body, because check 2 is "did the drafter ASK for labels"
# and the only honest evidence of that is the query that went over the wire.
cat > "$WORK/fixture-server.py" <<'PY'
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

WORK = os.environ["WORK"]

def load(name, default):
    try:
        with open(os.path.join(WORK, name)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"])).decode()
        with open(os.path.join(WORK, "requests.log"), "a") as fh:
            fh.write(raw.replace("\n", " ") + "\n")
        payload = json.loads(raw)
        query = payload.get("query") or ""
        variables = payload.get("variables") or {}

        # Order matters: issueUpdate and the comments lookup both contain
        # substrings that a looser later branch would swallow.
        if "issueUpdate" in query:
            with open(os.path.join(WORK, "updates.jsonl"), "a") as fh:
                fh.write(json.dumps(variables) + "\n")
            data = {"issueUpdate": {"success": True, "issue": {"identifier": "fixture"}}}
        elif "comments(" in query:
            data = {"issue": {"comments": {"nodes": load("comments.json", [])}}}
        elif "teams(" in query:
            data = {"teams": {"nodes": [{"id": "team-1"}]}}
        elif "issues(" in query:
            data = {"issues": {"nodes": load("board.json", []),
                               "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        elif "projects" in query:
            data = {"team": {"projects": {"nodes": []}}}
        else:
            data = {}
        out = json.dumps({"data": data}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers()
        self.wfile.write(out)

srv = HTTPServer(("127.0.0.1", 0), H)
print(srv.server_port, flush=True)
srv.serve_forever()
PY
WORK="$WORK" python3 "$WORK/fixture-server.py" > "$WORK/port" 2> "$WORK/server.err" &
SRV_PID=$!
for _ in $(seq 1 100); do PORT="$(cat "$WORK/port" 2>/dev/null)"; [ -n "${PORT:-}" ] && break; sleep 0.1; done
[ -n "${PORT:-}" ] || { echo "fixture server did not start"; cat "$WORK/server.err"; exit 1; }

# --- claude stub ------------------------------------------------------------
# STUB_MODE=good emits a well-formed DoR body; =fail exits 1 the way a real bad
# night does. Every call appends the issue title to calls.log -- the fixtures use
# the identifier as the title so the log reads as "who was actually attempted",
# which is the whole of check 5.
STUB="$WORK/stub"; mkdir -p "$STUB"
cat > "$STUB/claude" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" | grep -o 'Title: ASK-[0-9]*' | sed 's/Title: //' >> "$CALLS_LOG"
if [ "${STUB_MODE:-good}" = "fail" ]; then
  echo "stub refuses" >&2
  exit 1
fi
cat <<'BODY'
- **Outcome:** the fixture issue has a bounded, machine-executable scope.
- **Files:** q-system/.q-system/scripts/linear-dor-drafter.py
- **Check:** bash q-system/.q-system/scripts/test/test-linear-dor-drafter-redrive.sh
- **Blast radius:** skeleton script, propagates via kipi update.
- **Not doing:** the worker side.

**Energy:** Deep Focus · **Time Est:** 2 h
BODY
exit 0
SH
chmod +x "$STUB/claude"

export KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql"
export KIPI_LINEAR_API_KEY="fixture-key"
export KIPI_CLAUDE_BIN="$STUB/claude"
export KIPI_SLACK_WEBHOOK=""
export HOME="$WORK/home"
export CALLS_LOG="$WORK/calls.log"

# --- harness ----------------------------------------------------------------
reset() {
  : > "$WORK/requests.log"; : > "$WORK/updates.jsonl"; : > "$WORK/calls.log"
  echo '[]' > "$WORK/comments.json"
}

run_drafter() {  # run_drafter <args...>  -> stdout+stderr in $WORK/out.txt
  STUB_MODE="${STUB_MODE:-good}" python3 "$DRAFTER" "$@" > "$WORK/out.txt" 2>&1
}

board() { cat > "$WORK/board.json"; }

FOUNDER_TEXT='Bring back the per-repo dispatch. It has been dark for days.'
BAD_DOR='## Definition of Ready

- **Outcome:** triage all 304 spillover items.
- **Files:** unknown'

echo "== case 1+2: bypass check -- DoR heading AND needs-scope label is SELECTED =="
reset
python3 - "$WORK/board.json" "$FOUNDER_TEXT" "$BAD_DOR" <<'PY'
import json, sys
path, founder, dor = sys.argv[1:4]
json.dump([{
    "id": "u-901", "identifier": "ASK-901", "title": "ASK-901",
    "description": founder + "\n\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"},
                         {"id": "L-sana", "name": "owner:sana"}]},
}], open(path, "w"))
PY
run_drafter --limit 5
if grep -q 'ASK-901' "$WORK/out.txt"; then
  ok "a needs-scope issue WITH a DoR heading is selected"
else
  bad "a needs-scope issue WITH a DoR heading is selected" \
      "not in the batch. drafter said: $(tr '\n' '|' < "$WORK/out.txt" | cut -c1-200)"
fi
if grep -q 'redraft' "$WORK/out.txt"; then
  ok "it is selected as a REDRAFT, not as a first draft"
else
  bad "it is selected as a REDRAFT, not as a first draft" \
      "no redraft verb in: $(tr '\n' '|' < "$WORK/out.txt" | cut -c1-200)"
fi
if grep -q 'labels' "$WORK/requests.log"; then
  ok "the drafter asked Linear for labels (real GraphQL change)"
else
  bad "the drafter asked Linear for labels (real GraphQL change)" \
      "no query body mentioned labels; selection cannot be label-driven"
fi

echo "== case 3: redraft replaces the DoR, keeps the founder text, drops the label =="
reset
python3 - "$WORK/board.json" "$FOUNDER_TEXT" "$BAD_DOR" <<'PY'
import json, sys
path, founder, dor = sys.argv[1:4]
json.dump([{
    "id": "u-902", "identifier": "ASK-902", "title": "ASK-902",
    "description": founder + "\n\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"},
                         {"id": "L-sana", "name": "owner:sana"}]},
}], open(path, "w"))
PY
run_drafter --limit 5 --apply
python3 - "$WORK/updates.jsonl" "$FOUNDER_TEXT" > "$WORK/verdict.txt" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
founder = sys.argv[2]
ups = [r for r in rows if "description" in (r.get("input") or {})]
if not ups:
    print("no-update"); raise SystemExit
inp = ups[-1]["input"]
desc = inp["description"]
print("update")
print("prefix-kept" if founder in desc else "prefix-LOST")
print("one-dor" if desc.count("## Definition of Ready") == 1 else
      "dor-count-%d" % desc.count("## Definition of Ready"))
print("rewritten" if "304 spillover" not in desc else "stale-dor-still-there")
ids = inp.get("labelIds")
if ids is None:
    print("no-labelIds")
else:
    print("label-dropped" if "L-needs" not in ids else "label-KEPT")
    print("others-kept" if "L-sana" in ids else "others-LOST")
PY
V="$(cat "$WORK/verdict.txt")"
check3() { if printf '%s' "$V" | grep -qx "$1"; then ok "$2"; else bad "$2" "verdict was: $(printf '%s' "$V" | tr '\n' ' ')"; fi; }
check3 prefix-kept   "redraft preserves the founder text above the DoR"
check3 one-dor       "redraft leaves exactly ONE Definition of Ready section"
check3 rewritten     "the refused DoR body is gone, not appended to"
check3 label-dropped "the needs-scope label is removed on success"
check3 others-kept   "other labels survive the removal"

echo "== case 4: the redraft cap is an honest terminal, then stops costing a slot =="
reset
python3 - "$WORK/board.json" "$FOUNDER_TEXT" "$BAD_DOR" <<'PY'
import json, sys
path, founder, dor = sys.argv[1:4]
# Marker says this issue has already been redrafted to the cap and came back
# labelled anyway. Written in the drafter's own marker shape.
json.dump([{
    "id": "u-903", "identifier": "ASK-903", "title": "ASK-903",
    "description": founder + "\n\n<!-- kipi-dor: redrafts=3 -->\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}], open(path, "w"))
PY
run_drafter --limit 5 --apply
if [ ! -s "$WORK/calls.log" ]; then
  ok "a capped issue burns no claude call"
else
  bad "a capped issue burns no claude call" "claude was called for: $(tr '\n' ' ' < "$WORK/calls.log")"
fi
python3 - "$WORK/updates.jsonl" > "$WORK/verdict4.txt" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
ups = [r for r in rows if "description" in (r.get("input") or {})]
if not ups:
    print("no-terminal-write"); raise SystemExit
inp = ups[-1]["input"]
desc = inp["description"]
print("terminal-recorded" if "terminal" in desc.lower() else "no-terminal-marker")
# A rationale is prose a human can act on, not a status word. Demand length AND
# that it names the cap, so "terminal: true" alone cannot pass.
print("rationale-written" if (len(desc) > 200 and "3" in desc and
                              ("redraft" in desc.lower())) else "no-rationale")
ids = inp.get("labelIds")
print("label-held" if ids is None or "L-needs" in ids else "label-dropped-at-cap")
PY
V4="$(cat "$WORK/verdict4.txt")"
check4() { if printf '%s' "$V4" | grep -qx "$1"; then ok "$2"; else bad "$2" "verdict was: $(printf '%s' "$V4" | tr '\n' ' ')"; fi; }
check4 terminal-recorded "the cap is recorded on the issue as a terminal"
check4 rationale-written "the terminal carries a written rationale, not a flag"
check4 label-held        "the label is NOT dropped at the cap (it really is unscoped)"

# ...and once marked, it must stop being selected at all.
reset
TERMINAL_DESC="$(cat "$WORK/terminal-desc.txt" 2>/dev/null)"
python3 - "$WORK/board.json" "$FOUNDER_TEXT" "$BAD_DOR" <<'PY'
import json, sys
path, founder, dor = sys.argv[1:4]
json.dump([{
    "id": "u-904", "identifier": "ASK-904", "title": "ASK-904",
    "description": founder + "\n\n<!-- kipi-dor: redrafts=3 terminal -->\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}], open(path, "w"))
PY
run_drafter --limit 5 --apply
if grep -q 'ASK-904' "$WORK/out.txt" || [ -s "$WORK/updates.jsonl" ]; then
  bad "an already-terminal issue is not selected again" \
      "it was picked up: $(tr '\n' '|' < "$WORK/out.txt" | cut -c1-160)"
else
  ok "an already-terminal issue is not selected again"
fi

echo "== case 5: STARVATION PIN -- a failing head is re-attempted, the tail never is =="
reset
python3 - "$WORK/board.json" <<'PY'
import json, sys
json.dump([{
    "id": "u-%d" % n, "identifier": "ASK-9%02d" % n, "title": "ASK-9%02d" % n,
    "description": "no DoR here",
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": []},
} for n in range(10, 16)], open(sys.argv[1], "w"))
PY
STUB_MODE=fail run_drafter --limit 2 --apply
cp "$WORK/calls.log" "$WORK/calls-run1.log"
: > "$WORK/calls.log"
STUB_MODE=fail run_drafter --limit 2 --apply
if diff -q "$WORK/calls-run1.log" "$WORK/calls.log" >/dev/null 2>&1 && [ -s "$WORK/calls.log" ]; then
  ok "run 2 attempts the IDENTICAL head as run 1 (no cursor, no rotation)"
else
  bad "run 2 attempts the IDENTICAL head as run 1 (no cursor, no rotation)" \
      "run1=$(tr '\n' ' ' < "$WORK/calls-run1.log") run2=$(tr '\n' ' ' < "$WORK/calls.log")"
fi
if grep -q 'ASK-912' "$WORK/calls-run1.log" "$WORK/calls.log"; then
  bad "the issue behind the failing head is never reached" "ASK-912 was attempted"
else
  ok "the issue behind the failing head is never reached"
fi

echo "== case 6: a redraft outranks the no-DoR backlog, so it is reachable at all =="
reset
python3 - "$WORK/board.json" "$FOUNDER_TEXT" "$BAD_DOR" <<'PY'
import json, sys
path, founder, dor = sys.argv[1:4]
board = [{
    "id": "u-9%d" % n, "identifier": "ASK-9%d" % n, "title": "ASK-9%d" % n,
    "description": "no DoR here",
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": []},
} for n in range(20, 28)]
board.append({
    "id": "u-928", "identifier": "ASK-928", "title": "ASK-928",
    "description": founder + "\n\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
})
json.dump(board, open(path, "w"))
PY
run_drafter --limit 2
if grep -q 'ASK-928' "$WORK/out.txt"; then
  ok "the redraft is in the batch despite sorting last on the board"
else
  bad "the redraft is in the batch despite sorting last on the board" \
      "batch was: $(tr '\n' '|' < "$WORK/out.txt" | cut -c1-200)"
fi

echo
printf 'redrive: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
