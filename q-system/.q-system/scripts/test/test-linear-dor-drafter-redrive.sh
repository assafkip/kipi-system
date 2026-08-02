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
            # A refused write is a REAL Linear answer (HTTP 200, success:false),
            # not an exception. The first fixture only ever said True, which is
            # how the ignored-success hole stayed invisible.
            refused = os.path.exists(os.path.join(WORK, "update-fails"))
            data = {"issueUpdate": {"success": not refused,
                                    "issue": {"identifier": "fixture"}}}
        # The single-issue re-read the drafter does immediately before a write.
        # Serves live.json when a case has written one, which is how a case moves
        # the board BETWEEN selection and the write -- the only way to exercise the
        # concurrent-writer guard without real threads. Matched on description
        # because ISSUE_STATE_Q and the comments lookup also say `issue(id:`.
        elif "issue(id:" in query and "description" in query:
            nodes = load("live.json", None)
            if nodes is None:
                nodes = load("board.json", [])
            data = {"issue": next((n for n in nodes
                                   if n.get("identifier") == variables.get("id")), None)}
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
  # Absent by default: with no live.json the write-time re-read sees the same
  # board the selection saw, which is the uncontended case every other check wants.
  rm -f "$WORK/live.json"
}

# The description of the first update the fixture server recorded, or "" if the
# drafter never wrote. Every write-side assertion goes through this rather than
# through stdout, so a check cannot pass on a printed claim alone.
written_desc() {
  python3 - "$WORK/updates.jsonl" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
print(next((r["input"]["description"] for r in rows
            if "description" in (r.get("input") or {})), ""), end="")
PY
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

echo "== case 3: redraft rewrites ONLY the DoR section, and drops only that label =="
reset
# TRAILING_SECTION is the part the first cut of rebuild_description deleted: it
# took everything from the heading to the end as replaceable, so a human note
# written BELOW the DoR vanished on every redraft (codex-review finding-1).
TRAILING_SECTION='## Notes

Chris asked for this before the Friday call. Do not drop that.'
python3 - "$WORK/board.json" "$FOUNDER_TEXT" "$BAD_DOR" "$TRAILING_SECTION" <<'PY'
import json, sys
path, founder, dor, trailing = sys.argv[1:5]
json.dump([{
    "id": "u-902", "identifier": "ASK-902", "title": "ASK-902",
    "description": founder + "\n\n" + dor + "\n\n" + trailing,
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
print("trailing-kept" if "Chris asked for this" in desc else "trailing-DELETED")
print("one-dor" if desc.count("## Definition of Ready") == 1 else
      "dor-count-%d" % desc.count("## Definition of Ready"))
print("rewritten" if "304 spillover" not in desc else "stale-dor-still-there")
print("counter-1" if "redrafts=1" in desc else "counter-wrong")
# Removal must be expressed as removedLabelIds. A full labelIds replacement is
# built from labels read before a 300s model call and deletes anything added in
# that window (codex-review finding-2).
if inp.get("labelIds") is not None:
    print("full-replacement-used")
removed = inp.get("removedLabelIds")
if removed is None:
    print("no-removedLabelIds")
else:
    print("label-dropped" if "L-needs" in removed else "label-KEPT")
    print("others-untouched" if "L-sana" not in removed else "others-REMOVED")
PY
V="$(cat "$WORK/verdict.txt")"
check3() { if printf '%s' "$V" | grep -qx "$1"; then ok "$2"; else bad "$2" "verdict was: $(printf '%s' "$V" | tr '\n' ' ')"; fi; }
check3 prefix-kept      "redraft preserves the founder text above the DoR"
check3 trailing-kept    "redraft preserves the human section BELOW the DoR"
check3 one-dor          "redraft leaves exactly ONE Definition of Ready section"
check3 rewritten        "the refused DoR body is gone, not appended to"
check3 counter-1        "the first redraft records redrafts=1, not the cap"
check3 label-dropped    "the needs-scope label is removed on success"
check3 others-untouched "removal is scoped to that label, not a full set replacement"
if printf '%s' "$V" | grep -qx full-replacement-used; then
  bad "removal does not send a full labelIds replacement" "labelIds was sent"
else
  ok "removal does not send a full labelIds replacement"
fi

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

echo "== case 7: the cap COUNTS UP 1,2,3 then terminates -- it does not jump =="
# The cap assertions above both used a fabricated marker, so an implementation
# that wrote redrafts=3 on the FIRST rewrite passed every one of them while
# capping after a single refusal (codex-adversarial finding-5). This drives the
# real cycle: redraft, worker refuses again (label back on), redraft, ... and
# reads the counter the drafter itself wrote each round.
reset
python3 - "$WORK/board.json" "$FOUNDER_TEXT" "$BAD_DOR" <<'PY'
import json, sys
path, founder, dor = sys.argv[1:4]
json.dump([{
    "id": "u-950", "identifier": "ASK-950", "title": "ASK-950",
    "description": founder + "\n\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}], open(path, "w"))
PY
PROGRESSION=""
for round in 1 2 3 4; do
  : > "$WORK/updates.jsonl"
  run_drafter --limit 5 --apply
  # Feed the drafter's own write back onto the board, with needs-scope reapplied
  # the way the worker reapplies it after refusing the rewrite again.
  MARK="$(python3 - "$WORK/updates.jsonl" "$WORK/board.json" <<'PY'
import json, re, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
ups = [r for r in rows if "description" in (r.get("input") or {})]
if not ups:
    print("no-write"); raise SystemExit
desc = ups[-1]["input"]["description"]
board = json.load(open(sys.argv[2]))
board[0]["description"] = desc
board[0]["labels"] = {"nodes": [{"id": "L-needs", "name": "needs-scope"}]}
json.dump(board, open(sys.argv[2], "w"))
m = re.search(r"redrafts=(\d+)( terminal)?", desc)
print(("%s%s" % (m.group(1), "T" if m.group(2) else "")) if m else "no-marker")
PY
)"
  PROGRESSION="$PROGRESSION $MARK"
done
if [ "$PROGRESSION" = " 1 2 3 3T" ]; then
  ok "the counter walks 1,2,3 and only then writes the terminal"
else
  bad "the counter walks 1,2,3 and only then writes the terminal" \
      "progression was:$PROGRESSION (want ' 1 2 3 3T')"
fi
# A 5th night must cost nothing at all: already terminal, so not selected.
: > "$WORK/updates.jsonl"; : > "$WORK/calls.log"
run_drafter --limit 5 --apply
if [ -s "$WORK/updates.jsonl" ] || [ -s "$WORK/calls.log" ]; then
  bad "past the cap the issue stops costing anything" \
      "still wrote or called: $(tr '\n' ' ' < "$WORK/calls.log")"
else
  ok "past the cap the issue stops costing anything"
fi

echo "== case 8: a write Linear REFUSES is not counted as a redraft =="
reset
touch "$WORK/update-fails"
python3 - "$WORK/board.json" "$FOUNDER_TEXT" "$BAD_DOR" <<'PY'
import json, sys
path, founder, dor = sys.argv[1:4]
json.dump([{
    "id": "u-960", "identifier": "ASK-960", "title": "ASK-960",
    "description": founder + "\n\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}], open(path, "w"))
PY
run_drafter --limit 5 --apply
rm "$WORK/update-fails"
if grep -qE 'drafted 0, 1 failed' "$WORK/out.txt"; then
  ok "success=false is reported as a failure, not a redraft"
else
  bad "success=false is reported as a failure, not a redraft" \
      "run said: $(grep '^dor-drafter:' "$WORK/out.txt" | tr '\n' '|')"
fi
if grep -q 'redrafted ASK-960' "$WORK/out.txt"; then
  bad "a refused write does not print a redraft that did not happen" "it printed one"
else
  ok "a refused write does not print a redraft that did not happen"
fi

echo "== case 9: founder text cannot forge the counter =="
# The marker is only read from the drafter's own slot, the line directly above
# the heading. Scanning the whole description let a pasted example set the count:
# `redrafts=3` capped the first real attempt, and `terminal` removed the issue
# from selection forever (codex-adversarial finding-4).
reset
python3 - "$WORK/board.json" "$BAD_DOR" <<'PY'
import json, sys
path, dor = sys.argv[1:3]
founder = ("Here is how the drafter records its attempts, for reference:\n\n"
           "<!-- kipi-dor: redrafts=3 terminal -->\n\n"
           "Anyway. The DoR below is too big, please cut it down.")
json.dump([{
    "id": "u-970", "identifier": "ASK-970", "title": "ASK-970",
    "description": founder + "\n\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}], open(path, "w"))
PY
run_drafter --limit 5 --apply
if grep -q 'redrafted ASK-970 (attempt 1/' "$WORK/out.txt"; then
  ok "a marker in founder prose does not forge the counter"
else
  bad "a marker in founder prose does not forge the counter" \
      "run said: $(grep -E '^  (redrafted|marked)' "$WORK/out.txt" | tr '\n' '|')"
fi

echo "== case 10: founder prose ABOVE the DoR survives a redraft byte-for-byte =="
reset
# codex round 1, finding 1 (rebuild_description). redraft_state() reads the counter
# from ONE slot -- the line directly above the heading -- but rebuild_description()
# stripped the marker PATTERN from the whole prefix. Read narrow, delete wide.
# A founder who pastes a marker into their own prose (documenting the mechanism,
# quoting a past terminal) had that line deleted from a permanent Linear object on
# every redraft. Case 9 pins the READ half of that slot; this pins the WRITE half.
# Both halves must agree on "one owned line" or the asymmetry comes straight back.
FOUNDER_WITH_MARKER='Here is how the drafter records its attempts, for reference:

<!-- kipi-dor: redrafts=3 terminal -->

Anyway. The DoR below is too big, please cut it down.'
python3 - "$WORK/board.json" "$FOUNDER_WITH_MARKER" "$BAD_DOR" <<'PY'
import json, sys
path, founder, dor = sys.argv[1:4]
json.dump([{
    "id": "u-910", "identifier": "ASK-910", "title": "ASK-910",
    "description": founder + "\n\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}], open(path, "w"))
PY
run_drafter --limit 5 --apply
DESC10="$(written_desc)"
if [ -n "$DESC10" ] && [ "${DESC10#*"$FOUNDER_WITH_MARKER"}" != "$DESC10" ]; then
  ok "founder prose containing a marker survives the redraft byte-for-byte"
else
  bad "founder prose containing a marker survives the redraft byte-for-byte" \
      "written description was: $(printf '%s' "$DESC10" | tr '\n' '|' | cut -c1-240)"
fi
# The counter this job DOES own still has to land, or the fix above would pass by
# simply never writing a marker at all.
if printf '%s' "$DESC10" | grep -q '<!-- kipi-dor: redrafts=1 -->'; then
  ok "the owned counter slot is still written on the redraft"
else
  bad "the owned counter slot is still written on the redraft" \
      "no redrafts=1 marker in: $(printf '%s' "$DESC10" | tr '\n' '|' | cut -c1-240)"
fi

echo "== case 11: a redraft that another writer beat to the issue is not written =="
reset
# codex round 1, finding 2 (update_issue). The description is read at selection and
# written up to `--timeout` seconds later, with a `claude` call in between. A second
# drafter that finished first has already bumped the counter and dropped the label;
# writing the stale text over it overwrites a NEWER DoR, re-removes a label the
# worker may have re-applied, and counts a redraft that added nothing.
# The counter is this job's own single-writer token, so it doubles as the compare-
# and-swap: if it moved, someone else owns this issue tonight.
python3 - "$WORK/board.json" "$WORK/live.json" "$FOUNDER_TEXT" "$BAD_DOR" <<'PY'
import json, sys
board, live, founder, dor = sys.argv[1:5]
issue = {
    "id": "u-911", "identifier": "ASK-911", "title": "ASK-911",
    "description": founder + "\n\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}
json.dump([issue], open(board, "w"))
# What the board actually holds by the time the write goes out: a rival drafter
# landed attempt 1 and took the label off with it.
moved = dict(issue,
             description=(founder + "\n\n<!-- kipi-dor: redrafts=1 -->\n"
                          "## Definition of Ready\n\n- **Outcome:** already rewritten."),
             labels={"nodes": []})
json.dump([moved], open(live, "w"))
PY
run_drafter --limit 5 --apply
if [ -z "$(written_desc)" ]; then
  ok "the stale redraft is NOT written over the newer one"
else
  bad "the stale redraft is NOT written over the newer one" \
      "it wrote: $(written_desc | tr '\n' '|' | cut -c1-240)"
fi
if ! grep -q 'redrafted ASK-911' "$WORK/out.txt"; then
  ok "a skipped redraft is not counted as one"
else
  bad "a skipped redraft is not counted as one" \
      "run claimed: $(grep 'ASK-911' "$WORK/out.txt" | tr '\n' '|')"
fi

echo "== case 12: a redraft is rebuilt from the description as it stands NOW =="
reset
# The other half of finding 2. Skipping is only correct when a RIVAL DRAFTER moved
# the issue. A human adding a note during the same window has not taken ownership,
# so the redraft proceeds -- but it must be rebuilt from the CURRENT description,
# not the copy read before the `claude` call, or the note is overwritten by text
# that predates it. Same class as case 3, except the edit lands mid-run.
LATE_NOTE='## Notes

Chris added this while the drafter was still thinking. Do not drop it.'
python3 - "$WORK/board.json" "$WORK/live.json" "$FOUNDER_TEXT" "$BAD_DOR" "$LATE_NOTE" <<'PY'
import json, sys
board, live, founder, dor, note = sys.argv[1:6]
issue = {
    "id": "u-912", "identifier": "ASK-912", "title": "ASK-912",
    "description": founder + "\n\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}
json.dump([issue], open(board, "w"))
json.dump([dict(issue, description=issue["description"] + "\n\n" + note)],
          open(live, "w"))
PY
run_drafter --limit 5 --apply
DESC12="$(written_desc)"
if [ -n "$DESC12" ] && printf '%s' "$DESC12" | grep -q 'Chris added this while the drafter'; then
  ok "a note added mid-run survives the redraft that lands after it"
else
  bad "a note added mid-run survives the redraft that lands after it" \
      "written description was: $(printf '%s' "$DESC12" | tr '\n' '|' | cut -c1-240)"
fi
if printf '%s' "$DESC12" | grep -q 'triage all 304 spillover items'; then
  bad "the stale DoR is gone, not carried through" \
      "the refused DoR text is still in the written description"
else
  ok "the stale DoR is gone, not carried through"
fi

echo "== case 13: the status line does not say a redrive issue lacks a DoR =="
reset
# codex round 1, finding 3. Cosmetic, but it is the line an operator reads: every
# redrive candidate HAS a Definition of Ready -- having a bad one is the entire
# reason it is here -- so folding them into "N issue(s) need a Definition of Ready"
# reports the opposite of the state the run is acting on.
python3 - "$WORK/board.json" "$FOUNDER_TEXT" "$BAD_DOR" <<'PY'
import json, sys
path, founder, dor = sys.argv[1:4]
json.dump([{
    "id": "u-913", "identifier": "ASK-913", "title": "ASK-913",
    "description": founder + "\n\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}, {
    "id": "u-914", "identifier": "ASK-914", "title": "ASK-914",
    # Must not contain the words "Definition of Ready" even in prose: selection_mode
    # excludes on that substring, so the obvious wording for "this issue has no DoR"
    # deletes the issue from the batch and leaves the count-splitting assertion below
    # passing against a one-issue board, which it would do on unfixed code too.
    "description": "A plain backlog issue, nothing scoped on it yet.",
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": []},
}], open(path, "w"))
PY
run_drafter --limit 5
STATUS="$(grep '^dor-drafter 2' "$WORK/out.txt" || true)"
if printf '%s' "$STATUS" | grep -qE '2 issue\(s\) need a Definition of Ready'; then
  bad "the status line counts only the issues that actually lack a DoR" \
      "claimed all 2 need one, but ASK-913 already has one: $STATUS"
else
  ok "the status line counts only the issues that actually lack a DoR"
fi
# Positive on BOTH numbers, so the check cannot be satisfied by dropping the
# claim instead of correcting it: 1 of the 2 genuinely lacks a DoR, 1 is a redrive.
if printf '%s' "$STATUS" | grep -q '1 lacking a Definition of Ready' &&
   printf '%s' "$STATUS" | grep -q '1 needs-scope redrive'; then
  ok "the redrive candidates are still counted, separately"
else
  bad "the redrive candidates are still counted, separately" \
      "status line was: $STATUS"
fi

echo "== case 14: an inline MENTION of the phrase is not the section boundary =="
reset
# codex round 2. THE CLASS: three sites in this file matched the PHRASE
# "Definition of Ready" where the intent was the STRUCTURE (a heading). Here the
# owned span was located with desc.find(), so a founder SENTENCE containing the
# words became the section start and everything from that sentence to the next
# heading was replaced on redraft. Now one resolver, find_dor_heading(), decides,
# and it requires a heading at line start.
MENTION_TEXT='I have not had time to write the ## Definition of Ready for this yet.

Some context that must survive: the Friday call with Chris is the deadline.'
python3 - "$WORK/board.json" "$MENTION_TEXT" "$BAD_DOR" <<'PY'
import json, sys
path, mention, dor = sys.argv[1:4]
json.dump([{
    "id": "u-920", "identifier": "ASK-920", "title": "ASK-920",
    "description": mention + "\n\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}], open(path, "w"))
PY
run_drafter --limit 5 --apply
DESC14="$(written_desc)"
if [ -n "$DESC14" ] && [ "${DESC14#*"$MENTION_TEXT"}" != "$DESC14" ]; then
  ok "text between an inline mention and the next heading survives"
else
  bad "text between an inline mention and the next heading survives" \
      "written description was: $(printf '%s' "$DESC14" | tr '\n' '|' | cut -c1-260)"
fi

echo "== case 15: prose mentioning the phrase does not hide an issue (sp-b784a19a) =="
reset
# The second instance of the same class. selection_mode excluded on the bare
# substring, so an issue whose description merely TALKED about needing a DoR was
# removed from the drafter permanently -- silent, and forever.
python3 - "$WORK/board.json" <<'PY'
import json, sys
json.dump([{
    "id": "u-921", "identifier": "ASK-921", "title": "ASK-921",
    "description": "Someone should write a Definition of Ready for this one.",
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": []},
}], open(sys.argv[1], "w"))
PY
run_drafter --limit 5
if grep -q 'would draft ASK-921' "$WORK/out.txt"; then
  ok "an issue that only MENTIONS the phrase is still drafted"
else
  bad "an issue that only MENTIONS the phrase is still drafted" \
      "drafter said: $(tr '\n' '|' < "$WORK/out.txt" | cut -c1-200)"
fi

echo "== case 16: a real heading still counts as having a DoR =="
reset
# The negative half of case 15: narrowing to headings must not make the drafter
# start appending a second DoR to issues that already have one.
python3 - "$WORK/board.json" "$BAD_DOR" <<'PY'
import json, sys
json.dump([{
    "id": "u-922", "identifier": "ASK-922", "title": "ASK-922",
    "description": "Some context.\n\n" + sys.argv[2],
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": []},
}], open(sys.argv[1], "w"))
PY
run_drafter --limit 5
if grep -q 'ASK-922' "$WORK/out.txt"; then
  bad "an issue with a real DoR heading is still excluded" \
      "it was selected: $(tr '\n' '|' < "$WORK/out.txt" | cut -c1-200)"
else
  ok "an issue with a real DoR heading is still excluded"
fi

echo "== case 17: the TERMINAL write re-reads too, like every other write =="
reset
# codex round 2. The freshness guard from round 1 covered the redraft branch only.
# The terminal path built its payload from the selection-time description, so an
# edit landing after selection was overwritten by text that predated it -- the
# same defect, on the branch that was not touched. Both now route through
# apply_write(), so there is no second path to forget.
TERMINAL_LATE_NOTE='## Notes

Added while the run was working. Must survive the terminal write.'
python3 - "$WORK/board.json" "$WORK/live.json" "$BAD_DOR" "$TERMINAL_LATE_NOTE" <<'PY'
import json, sys
board, live, dor, note = sys.argv[1:5]
# redrafts=3 -> the cap is spent, so this issue takes the terminal path.
desc = "Founder context above.\n\n<!-- kipi-dor: redrafts=3 -->\n" + dor
issue = {
    "id": "u-923", "identifier": "ASK-923", "title": "ASK-923",
    "description": desc,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}
json.dump([issue], open(board, "w"))
json.dump([dict(issue, description=desc + "\n\n" + note)], open(live, "w"))
PY
run_drafter --limit 5 --apply
DESC17="$(written_desc)"
if printf '%s' "$DESC17" | grep -q 'Must survive the terminal write'; then
  ok "a note added mid-run survives the TERMINAL write"
else
  bad "a note added mid-run survives the TERMINAL write" \
      "written description was: $(printf '%s' "$DESC17" | tr '\n' '|' | cut -c1-260)"
fi
if printf '%s' "$DESC17" | grep -q 'Redraft cap reached'; then
  ok "the terminal rationale is still written"
else
  bad "the terminal rationale is still written" \
      "no rationale in: $(printf '%s' "$DESC17" | tr '\n' '|' | cut -c1-260)"
fi

echo "== case 18: the CLOSING status line does not say a redrive lacks a DoR =="
reset
# codex round 2, twin of round 1 finding 3. The opening line was corrected and the
# closing line kept the old claim, which is exactly why both now call one
# formatter. STUB_MODE=fail so the issue stays queued and is counted in the tail.
python3 - "$WORK/board.json" "$FOUNDER_TEXT" "$BAD_DOR" <<'PY'
import json, sys
path, founder, dor = sys.argv[1:4]
json.dump([{
    "id": "u-924", "identifier": "ASK-924", "title": "ASK-924",
    "description": founder + "\n\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}], open(path, "w"))
PY
STUB_MODE=fail run_drafter --limit 5 --apply
CLOSING="$(grep '^dor-drafter: drafted' "$WORK/out.txt" || true)"
if printf '%s' "$CLOSING" | grep -q 'still lack a DoR'; then
  bad "the closing line does not claim a redrive issue lacks a DoR" \
      "closing line was: $CLOSING"
else
  ok "the closing line does not claim a redrive issue lacks a DoR"
fi
if printf '%s' "$CLOSING" | grep -q '1 needs-scope redrive'; then
  ok "the closing line counts the unfinished redrive as a redrive"
else
  bad "the closing line counts the unfinished redrive as a redrive" \
      "closing line was: $CLOSING"
fi

echo "== case 19: a DoR heading inside a FENCED BLOCK is not the section boundary =="
reset
# codex round 3. Sixth layer of the phrase-vs-structure class: phrase anywhere ->
# heading at line start -> heading not inside a code fence. Real hazard here
# specifically, because this repo's own DoR template gets pasted into fenced
# blocks in issue descriptions. A founder quoting the template had the QUOTE
# treated as the section start: their prose was deleted from the quote onward and
# the actually-refused DoR below was left untouched.
python3 - "$WORK/board.json" > "$WORK/expect19.txt" <<'PY'
import json, sys
fence = "```"
quoted = (f"Here is the template we all use:\n\n{fence}markdown\n"
          "## Definition of Ready\n\n- **Outcome:** one sentence.\n"
          f"{fence}\n\nThat quote is documentation, not this issue's own section.")
real = ("## Definition of Ready\n\n"
        "- **Outcome:** triage all 304 spillover items.\n- **Files:** unknown")
json.dump([{
    "id": "u-930", "identifier": "ASK-930", "title": "ASK-930",
    "description": quoted + "\n\n" + real,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}], open(sys.argv[1], "w"))
print(quoted)
PY
run_drafter --limit 5 --apply
python3 - "$WORK/updates.jsonl" "$WORK/expect19.txt" > "$WORK/v19.txt" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
desc = next((r["input"]["description"] for r in rows
             if "description" in (r.get("input") or {})), "")
quoted = open(sys.argv[2]).read().rstrip("\n")
kept = quoted in desc
gone = "triage all 304 spillover items" not in desc
print("PASS" if (kept and gone) else "FAIL")
print(f"quote_survived={kept} refused_dor_replaced={gone} :: {desc[:200]!r}")
PY
if head -1 "$WORK/v19.txt" | grep -q PASS; then
  ok "a fenced DoR quote survives and the REAL section is the one replaced"
else
  bad "a fenced DoR quote survives and the REAL section is the one replaced" \
      "$(sed -n 2p "$WORK/v19.txt")"
fi

echo "== case 20: an UNCLOSED fence does not hide the real DoR heading =="
reset
# The dangerous half of fence handling. If an unclosed ``` is treated as opening a
# region that runs to end-of-description, the real heading below it disappears,
# the refused DoR is never replaced, and a second one is appended instead. So an
# unclosed fence is deliberately NOT a fence.
python3 - "$WORK/board.json" > "$WORK/expect20.txt" <<'PY'
import json, sys
fence = "```"
before = (f"Bring back the per-repo dispatch.\n\n{fence}\n"
          "some snippet whose fence was never closed")
real = ("## Definition of Ready\n\n"
        "- **Outcome:** triage all 304 spillover items.\n- **Files:** unknown")
json.dump([{
    "id": "u-931", "identifier": "ASK-931", "title": "ASK-931",
    "description": before + "\n\n" + real,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}], open(sys.argv[1], "w"))
print(before)
PY
run_drafter --limit 5 --apply
python3 - "$WORK/updates.jsonl" "$WORK/expect20.txt" > "$WORK/v20.txt" <<'PY'
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
desc = next((r["input"]["description"] for r in rows
             if "description" in (r.get("input") or {})), "")
before = open(sys.argv[2]).read().rstrip("\n")
kept = before in desc
replaced = "triage all 304 spillover items" not in desc
one = desc.count("## Definition of Ready") == 1
print("PASS" if (kept and replaced and one) else "FAIL")
print(f"prefix_kept={kept} replaced={replaced} exactly_one_dor={one} :: {desc[:200]!r}")
PY
if head -1 "$WORK/v20.txt" | grep -q PASS; then
  ok "an unclosed fence does not hide the heading below it"
else
  bad "an unclosed fence does not hide the heading below it" \
      "$(sed -n 2p "$WORK/v20.txt")"
fi

echo "== case 21: an issue completed by another writer is not still 'queued' =="
reset
# codex round 3, fourth instance of the status-line class. A skip means the issue
# got what it needed from someone else, so it has LEFT the queue. Counting it as
# remaining reports work that no longer exists.
python3 - "$WORK/board.json" "$WORK/live.json" "$FOUNDER_TEXT" "$BAD_DOR" <<'PY'
import json, sys
board, live, founder, dor = sys.argv[1:5]
issue = {
    "id": "u-932", "identifier": "ASK-932", "title": "ASK-932",
    "description": founder + "\n\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}
json.dump([issue], open(board, "w"))
json.dump([dict(issue,
                description=(founder + "\n\n<!-- kipi-dor: redrafts=1 -->\n"
                             "## Definition of Ready\n\n- **Outcome:** already done."),
                labels={"nodes": []})], open(live, "w"))
PY
run_drafter --limit 5 --apply
CLOSING21="$(grep '^dor-drafter: drafted' "$WORK/out.txt" || true)"
if printf '%s' "$CLOSING21" | grep -q '0 still queued'; then
  ok "a concurrently-completed issue leaves the queued count"
else
  bad "a concurrently-completed issue leaves the queued count" \
      "closing line was: $CLOSING21"
fi
if printf '%s' "$CLOSING21" | grep -q 'completed by another writer'; then
  ok "the closing line says where that issue went"
else
  bad "the closing line says where that issue went" \
      "closing line was: $CLOSING21"
fi

echo "== case 22: a fenced DoR quote does not count as HAVING a DoR (selection) =="
reset
# Found by mutation, not by review: breaking fence-skipping in find_dor_heading
# left every other case green, because they all carry needs-scope and are selected
# by the LABEL branch above the has-a-DoR exclusion. This is the selection half --
# an issue with no label whose description only QUOTES the template has no DoR of
# its own, so it must still be drafted. Without it, quoting the template hides the
# issue from the drafter forever, which is the sp-b784a19a failure with a fence
# around it.
python3 - "$WORK/board.json" <<'PY'
import json, sys
fence = "```"
json.dump([{
    "id": "u-933", "identifier": "ASK-933", "title": "ASK-933",
    "description": (f"Please scope this one.\n\n{fence}markdown\n"
                    "## Definition of Ready\n\n- **Outcome:** one sentence.\n"
                    f"{fence}\n\nThat is the template, not this issue's section."),
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": []},
}], open(sys.argv[1], "w"))
PY
run_drafter --limit 5
if grep -q 'would draft ASK-933' "$WORK/out.txt"; then
  ok "an issue whose only DoR heading is inside a fence is still drafted"
else
  bad "an issue whose only DoR heading is inside a fence is still drafted" \
      "drafter said: $(tr '\n' '|' < "$WORK/out.txt" | cut -c1-200)"
fi

echo "== case 23: terminalising a LONG DoR does not silently truncate it =="
reset
# codex round 4. existing_dor() capped the section at 3000 chars. That cap is fine
# for the redraft PROMPT (model input) but the TERMINAL path fed the same value
# back as the description it WRITES, so terminalising an issue whose DoR ran past
# 3000 characters silently deleted the tail from a permanent object. Measured as
# introduced by this PR: main has no existing_dor and no terminal path -- its only
# description write is a pure append, which cannot truncate.
python3 - "$WORK/board.json" <<'PY'
import json, sys
bullet = ("- **Outcome:** a deliberately long bounded outcome line that exists "
          "only to push this section past the three thousand character cap.\n")
long_dor = "## Definition of Ready\n\n" + (bullet * 60) + "\nTAIL-SENTINEL-DO-NOT-DROP\n"
assert len(long_dor) > 3000, len(long_dor)
json.dump([{
    "id": "u-940", "identifier": "ASK-940", "title": "ASK-940",
    # redrafts=3 -> the cap is spent, so this takes the terminal path.
    "description": ("Founder context above.\n\n<!-- kipi-dor: redrafts=3 -->\n"
                    + long_dor),
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}], open(sys.argv[1], "w"))
PY
run_drafter --limit 5 --apply
DESC23="$(written_desc)"
if printf '%s' "$DESC23" | grep -q 'TAIL-SENTINEL-DO-NOT-DROP'; then
  ok "the tail of a >3000 char DoR survives terminalisation"
else
  bad "the tail of a >3000 char DoR survives terminalisation" \
      "written description was ${#DESC23} chars, tail: $(printf '%s' "$DESC23" | tail -c 120 | tr '\n' '|')"
fi

echo "== case 24: a human edit INSIDE the DoR is not overwritten by the redraft =="
reset
# codex round 4, third site of the staleness class. The guard compared the counter
# marker and the label, so an edit to the DoR SECTION ITSELF -- the most likely
# human edit of all, someone fixing the scope by hand while the model runs -- left
# both signals untouched and the redraft wrote straight over it.
python3 - "$WORK/board.json" "$WORK/live.json" "$FOUNDER_TEXT" "$BAD_DOR" <<'PY'
import json, sys
board, live, founder, dor = sys.argv[1:5]
issue = {
    "id": "u-941", "identifier": "ASK-941", "title": "ASK-941",
    "description": founder + "\n\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}
json.dump([issue], open(board, "w"))
# Same counter, same label. A person rewrote the DoR by hand mid-run.
human = ("## Definition of Ready\n\n"
         "- **Outcome:** I scoped this myself: ship the one endpoint.\n"
         "- **Files:** api/routes.py")
json.dump([dict(issue, description=founder + "\n\n" + human)], open(live, "w"))
PY
run_drafter --limit 5 --apply
if [ -z "$(written_desc)" ]; then
  ok "a hand-edited DoR is left alone, not overwritten"
else
  bad "a hand-edited DoR is left alone, not overwritten" \
      "it wrote: $(written_desc | tr '\n' '|' | cut -c1-240)"
fi

echo "== case 25: a rival redraft that was REFUSED AGAIN is still queued =="
reset
# codex round 4, fifth site of the status class. A skip was always counted as
# "completed by another writer", but a rival redraft that the worker refused again
# still carries needs-scope: it is back in the queue, not done. Reporting it as
# completed removes real remaining work from the count.
python3 - "$WORK/board.json" "$WORK/live.json" "$FOUNDER_TEXT" "$BAD_DOR" <<'PY'
import json, sys
board, live, founder, dor = sys.argv[1:5]
issue = {
    "id": "u-942", "identifier": "ASK-942", "title": "ASK-942",
    "description": founder + "\n\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}
json.dump([issue], open(board, "w"))
# A rival redrafted it (counter moved) but the worker refused the result and put
# needs-scope straight back on. Still unscoped, still queued.
json.dump([dict(issue,
                description=(founder + "\n\n<!-- kipi-dor: redrafts=1 -->\n"
                             "## Definition of Ready\n\n- **Outcome:** rival attempt."),
                labels={"nodes": [{"id": "L-needs", "name": "needs-scope"}]})],
          open(live, "w"))
PY
run_drafter --limit 5 --apply
CLOSING25="$(grep '^dor-drafter: drafted' "$WORK/out.txt" || true)"
if printf '%s' "$CLOSING25" | grep -q '1 still queued'; then
  ok "an issue still wearing needs-scope stays in the remaining count"
else
  bad "an issue still wearing needs-scope stays in the remaining count" \
      "closing line was: $CLOSING25"
fi
if printf '%s' "$CLOSING25" | grep -q 'completed by another writer'; then
  bad "it is not reported as completed by another writer" \
      "closing line was: $CLOSING25"
else
  ok "it is not reported as completed by another writer"
fi

echo "== case 26: an already-terminalised issue HAS left the queue =="
reset
# Found by mutation, not by review: case 25 is a redraft, so it never exercised
# the TERMINAL call site's still-queued test and a mutation there survived.
# Writing this case then exposed a real bug in the first fix -- "still wears
# needs-scope" is the WRONG queued test, because a terminalised issue keeps the
# label deliberately (it really is unscoped) while being unselectable. The honest
# predicate is the selection predicate itself, so still_queued now asks
# selection_mode(). This case is the one that tells the two apart.
python3 - "$WORK/board.json" "$WORK/live.json" "$BAD_DOR" <<'PY'
import json, sys
board, live, dor = sys.argv[1:4]
issue = {
    "id": "u-950", "identifier": "ASK-950", "title": "ASK-950",
    # redrafts=3 -> this run picks it up in TERMINAL mode.
    "description": "Founder context.\n\n<!-- kipi-dor: redrafts=3 -->\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}
json.dump([issue], open(board, "w"))
# A rival already wrote the terminal. The label STAYS ON by design, so a
# label-based queued test would call this "still queued" -- but it is finished.
json.dump([dict(issue,
                description=("Founder context.\n\n<!-- kipi-dor: redrafts=3 terminal -->\n"
                             + dor))], open(live, "w"))
PY
run_drafter --limit 5 --apply
CLOSING26="$(grep '^dor-drafter: drafted' "$WORK/out.txt" || true)"
if [ -z "$(written_desc)" ]; then
  ok "the duplicate terminal write is skipped"
else
  bad "the duplicate terminal write is skipped" \
      "it wrote: $(written_desc | tr '\n' '|' | cut -c1-200)"
fi
if printf '%s' "$CLOSING26" | grep -q '0 still queued'; then
  ok "a terminalised issue is NOT counted as still queued despite keeping the label"
else
  bad "a terminalised issue is NOT counted as still queued despite keeping the label" \
      "closing line was: $CLOSING26"
fi

echo "== case 27: the operator's documented reset mid-run keeps the issue queued =="
reset
# Also found by mutation: case 26's terminal skip is NOT still-queued, so it could
# not tell `if not still_queued` from `if True` at the terminal call site. The
# case that separates them is the one TERMINAL_NOTE actually instructs the
# operator to perform -- "delete the <!-- kipi-dor: ... --> line above. The
# counter resets and the next nightly run redrafts it again." Do that while this
# run is mid-flight and the issue is genuinely back in the queue, so reporting it
# as completed would delete real work from the count.
python3 - "$WORK/board.json" "$WORK/live.json" "$BAD_DOR" <<'PY'
import json, sys
board, live, dor = sys.argv[1:4]
issue = {
    "id": "u-951", "identifier": "ASK-951", "title": "ASK-951",
    "description": "Founder context.\n\n<!-- kipi-dor: redrafts=3 -->\n" + dor,
    "project": {"name": "kipi-system"},
    "state": {"name": "Todo", "type": "unstarted"},
    "labels": {"nodes": [{"id": "L-needs", "name": "needs-scope"}]},
}
json.dump([issue], open(board, "w"))
# The operator deleted the marker line, exactly as the terminal note tells them to.
json.dump([dict(issue, description="Founder context.\n\n" + dor)], open(live, "w"))
PY
run_drafter --limit 5 --apply
CLOSING27="$(grep '^dor-drafter: drafted' "$WORK/out.txt" || true)"
if [ -z "$(written_desc)" ]; then
  ok "the terminal is not written over the operator's reset"
else
  bad "the terminal is not written over the operator's reset" \
      "it wrote: $(written_desc | tr '\n' '|' | cut -c1-200)"
fi
if printf '%s' "$CLOSING27" | grep -q '1 still queued'; then
  ok "the reset issue stays in the remaining count"
else
  bad "the reset issue stays in the remaining count" \
      "closing line was: $CLOSING27"
fi

echo
printf 'redrive: %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
