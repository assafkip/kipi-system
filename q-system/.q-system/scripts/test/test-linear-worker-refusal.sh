#!/usr/bin/env bash
# A blocked:capability refusal must STOP re-dispatch (ASK-2199).
#
# WHY A SECOND REFUSAL SUITE, next to test-worker-refusal.sh
# ----------------------------------------------------------
# That suite proves the worker REACHES the label call. It cannot prove the label
# LANDS, because its fixture Linear answers every non-teams query with the board
# list -- so `linear-sync.py label` reads no `issue` key, exits BLOCK: no issue,
# and the worker takes its own failure branch. That branch is inside the pass
# set there:
#
#   grep -q "label ASK-802 blocked:capability\
#            |ASK-802 labelled blocked:capability\
#            |ASK-802 REFUSED but the blocked:capability"   <-- the failure text
#
# So the single state this whole protocol exists to prevent -- the label did not
# apply, the issue returns as the top pick -- reads GREEN over there, and has
# since the assertion was written. ASK-1168 is what that costs: four dispatches
# on 2026-08-30 (19:42, 20:07, 20:28, 20:38) on a spec that was correct.
#
# WHAT THIS SUITE PROVES INSTEAD
# ------------------------------
# 1. the refusal ISSUES the label mutation: an `issueUpdate` really reaches
#    Linear, carrying the blocked:capability label id, and the run says so
# 2. the mutation is a UNION, so owner:sana survives -- stripping it drops the
#    issue out of the queue for the wrong reason and makes it un-findable
# 3. the picker then SKIPS that issue: it is not dispatched on the next pass
# 4. THE NEGATIVE, in the same pass: an issue with NO sentinel is still picked
#    up. This is how a refusal branch that exits too early would show, and it is
#    the control that keeps case 3 from passing on a worker that picks nothing
#
# The fixture Linear here is a RECORDING ROUTER, not a stub that swallows: every
# GraphQL operation is written to ops.jsonl and the assertions read that file.
# "The worker said it labelled it" is the claim under test; what Linear was
# actually asked to do is the answer.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER="${KIPI_WORKER_UNDER_TEST:-$REPO_SCRIPTS/linear-worker.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT

OPS="$WORK/ops.jsonl"
: > "$OPS"

# --- fixture Linear: a real router over the four operations cmd_label uses ---
# BOARD_FILE is re-read on every request, so a second run can serve a DIFFERENT
# board (ASK-810 now carrying the label) without restarting the server. That is
# what makes case 3 a test of the PICKER rather than of a fresh fixture.
cat > "$WORK/fixture-server.py" <<'PY'
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

OPS = os.environ["OPS_FILE"]
BOARD_FILE = os.environ["BOARD_FILE"]

# The team's label catalogue. blocked:capability and needs-scope already exist
# here on purpose: they have existed on team ASK since 2026-07-30 (a3e6f4bf), so
# a fixture that forced cmd_label down its create-the-label branch would be
# testing a path production never takes.
TEAM_LABELS = {"owner:sana": "lid-owner-sana",
               "blocked:capability": "lid-blocked-capability",
               "needs-scope": "lid-needs-scope"}

def board():
    return json.load(open(BOARD_FILE))

def record(op, body, variables):
    with open(OPS, "a") as fh:
        fh.write(json.dumps({"op": op, "variables": variables}) + "\n")

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode())
        q = payload.get("query", "")
        v = payload.get("variables", {}) or {}

        if "teams(" in q:
            record("teams", q, v)
            data = {"teams": {"nodes": [{"id": "t"}]}}

        elif "issueUpdate" in q:
            # THE OPERATION UNDER TEST. Recorded with its full variables so the
            # assertions can read WHICH label ids were sent, not merely that
            # something was mutated.
            record("issueUpdate", q, v)
            data = {"issueUpdate": {"success": True,
                                    "issue": {"id": v.get("id"), "identifier": v.get("id")}}}

        elif "issueLabelCreate" in q:
            record("issueLabelCreate", q, v)
            data = {"issueLabelCreate": {"success": True,
                                         "issueLabel": {"id": "lid-invented",
                                                        "name": v["input"]["name"]}}}

        elif "commentCreate" in q:
            record("commentCreate", q, v)
            data = {"commentCreate": {"success": True, "comment": {"id": "c1"}}}

        elif "labels(first:" in q and "team(" in q:
            record("teamLabels", q, v)
            data = {"team": {"labels": {"nodes": [{"id": i, "name": n}
                                                  for n, i in TEAM_LABELS.items()]}}}

        elif q.strip().startswith("query($id:String!)") and "issue(id:" in q:
            # ISSUE_LABELS: the read half of cmd_label's read-modify-write.
            record("issueLabels", q, v)
            found = [i for i in board() if i["identifier"] == v.get("id")]
            issue = None
            if found:
                issue = {"id": found[0]["id"], "identifier": found[0]["identifier"],
                         "team": {"id": "t"},
                         "labels": {"nodes": [{"id": TEAM_LABELS.get(l["name"], "lid-" + l["name"]),
                                               "name": l["name"]}
                                              for l in found[0]["labels"]["nodes"]]}}
            data = {"issue": issue}

        elif "issue(id:" in q:
            # cmd_progress reads the issue before commenting.
            record("issueRead", q, v)
            found = [i for i in board() if i["identifier"] == v.get("id")]
            data = {"issue": (dict(found[0], team={"id": "t"}) if found else None)}

        else:
            record("issues", q, v)
            data = {"issues": {"nodes": board(),
                               "pageInfo": {"hasNextPage": False, "endCursor": None}}}

        out = json.dumps({"data": data}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers()
        self.wfile.write(out)

srv = HTTPServer(("127.0.0.1", 0), H)
print(srv.server_port, flush=True)
srv.serve_forever()
PY

BOARD_FILE="$WORK/board.json"

write_board() {  # write_board <json>
  printf '%s' "$1" > "$BOARD_FILE"
}

issue_json() {  # issue_json <ident> [extra-label]
  local ident="$1" extra="${2:-}" labels='{"name":"owner:sana"}'
  [ -n "$extra" ] && labels="$labels,{\"name\":\"$extra\"}"
  printf '{"id":"%s","identifier":"%s","title":"fixture %s",' "$ident" "$ident" "$ident"
  printf '"description":"## Definition of Ready\\nOutcome: x",'
  printf '"state":{"name":"backlog","type":"backlog"},'
  printf '"project":{"name":"kipi-system"},'
  printf '"labels":{"nodes":[%s]}}' "$labels"
}

# Run 1's board: one clean capability-refusing issue.
write_board "[$(issue_json ASK-810)]"

OPS_FILE="$OPS" BOARD_FILE="$BOARD_FILE" \
  python3 "$WORK/fixture-server.py" > "$WORK/port" 2> "$WORK/server.err" &
SRV_PID=$!
for _ in $(seq 1 100); do PORT="$(cat "$WORK/port" 2>/dev/null)"; [ -n "${PORT:-}" ] && break; sleep 0.1; done
[ -n "${PORT:-}" ] || { echo "fixture server did not start: $(cat "$WORK/server.err")"; exit 1; }

# --- stubs ------------------------------------------------------------------
STUB="$WORK/stub"; mkdir -p "$STUB"
BLOCK_REASON="Edit(.claude/rules/**) refused by the Claude Code sensitive-path guard"
cat > "$STUB/claude" <<SH
#!/usr/bin/env bash
# ASK-810 blocks on CAPABILITY. ASK-811 does nothing at all -- it is the control
# that proves the picker still dispatches an unrefused issue.
if printf '%s' "\$*" | grep -q 'ASK-810'; then
  printf '%s' "$BLOCK_REASON" > .sana-blocked-capability
fi
exit 0
SH
cat > "$STUB/gh" <<'SH'
#!/usr/bin/env bash
# No PRs exist in this world. The refusal path is the whole subject here; the
# PR/review fall-through has its own coverage in test-worker-refusal.sh.
exit 0
SH
chmod +x "$STUB/claude" "$STUB/gh"

# Codex refuses too, so the park really happens rather than being continued away.
# Injected for the same reason the sibling suite injects it: asserting against
# the real binary would bill a model run per case, so the branch would stay
# untested.
cat > "$WORK/fake-codex.sh" <<'SH'
#!/usr/bin/env bash
printf '%s' "codex has no credential for the target host either" > .codex-blocked-capability
exit 0
SH

# --- a real git repo for SKEL ------------------------------------------------
new_skel() {  # new_skel <parent-dir>  -> echoes the skeleton path
  local parent="$1" skel="$1/kipi-system"
  mkdir -p "$parent"
  git init --quiet --bare "$parent/origin.git"
  git init --quiet "$skel"
  git -C "$skel" config user.email t@t; git -C "$skel" config user.name t
  : > "$skel/seed"; git -C "$skel" add seed; git -C "$skel" commit --quiet -m seed
  git -C "$skel" remote add origin "$parent/origin.git"
  git -C "$skel" push --quiet -u origin HEAD:main 2>/dev/null
  printf '%s' "$skel"
}

run_worker() {  # run_worker <skel> <state-dir> <out-file> [limit]
  PATH="$STUB:$PATH" \
    KIPI_SKEL="$1" KIPI_STATE_DIR="$2" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_PR_REVIEWER="/usr/bin/true" \
    KIPI_CODEX_RUNNER="bash $WORK/fake-codex.sh" \
    KIPI_NOTIFY="/usr/bin/true" \
    bash "$WORKER" --apply --limit "${4:-1}" > "$3" 2>&1
}

echo "== blocked:capability stops re-dispatch (worker under test: $WORKER)"

# ============================================================================
# RUN 1 -- the refusal issues the label mutation
# ============================================================================
SKEL1="$(new_skel "$WORK/run1")"
STATE1="$WORK/state1"
run_worker "$SKEL1" "$STATE1" "$WORK/run1.out"
OUT1="$(cat "$WORK/run1.out")
$(cat "$STATE1/linear-worker.log" 2>/dev/null)"

# 1a. POSITIVE SELF-TEST FIRST. Everything below reads the ops log; a run that
# never dispatched ASK-810 leaves an ops log that fails every assertion for a
# reason that has nothing to do with the label.
if grep -q "ASK-810 BLOCKED on a missing capability" <<<"$OUT1"; then
  ok "self-test: the run really entered the capability-refusal path for ASK-810"
else
  bad "self-test: the run entered the capability-refusal path" \
      "no BLOCKED line for ASK-810 -- every assertion below is vacuous. Output: $(tr '\n' '|' <<<"$OUT1" | cut -c1-600)"
fi

# 1b. THE ASSERTION THIS ISSUE EXISTS FOR. Not "the worker tried to label it" --
# an issueUpdate really reached Linear for ASK-810.
UPDATES="$(grep '"op": "issueUpdate"' "$OPS" 2>/dev/null)"
if grep -q 'ASK-810' <<<"$UPDATES"; then
  ok "the refusal ISSUES an issueUpdate mutation against ASK-810"
else
  bad "the refusal issues an issueUpdate mutation against ASK-810" \
      "THE DEFECT: no issueUpdate reached Linear, so the label never landed and the picker hands the issue back. Ops: '$(tr '\n' '|' < "$OPS" | cut -c1-600)'"
fi

# 1c. ...carrying the blocked:capability label id. An issueUpdate that mutated
# something else entirely would satisfy 1b.
if grep 'ASK-810' <<<"$UPDATES" | grep -q 'lid-blocked-capability'; then
  ok "the mutation carries the blocked:capability label id"
else
  bad "the mutation carries the blocked:capability label id" \
      "issueUpdate was issued without lid-blocked-capability: '$UPDATES'"
fi

# 1d. UNION, NOT REPLACE. Linear's issueUpdate takes labelIds as the COMPLETE
# set, so a mutation that sent only the new id would strip owner:sana -- and an
# issue with no owner label is out of the queue for the wrong reason and
# un-findable. The read-modify-write in cmd_label is what this pins.
if grep 'ASK-810' <<<"$UPDATES" | grep -q 'lid-owner-sana'; then
  ok "the mutation is a UNION: owner:sana survives the label write"
else
  bad "the mutation is a union" \
      "owner:sana is missing from labelIds -- the write replaced the label set instead of adding to it: '$UPDATES'"
fi

# 1e. ...and the run REPORTS the landing, not the failure branch. This is the
# exact text the sibling suite accepts as a pass; here it is a failure, because
# it is the state ASK-1168 was actually in.
if grep -q "ASK-810 labelled blocked:capability" <<<"$OUT1"; then
  ok "the run reports the label as applied"
elif grep -q "ASK-810 REFUSED but the blocked:capability label did NOT apply" <<<"$OUT1"; then
  bad "the run reports the label as applied" \
      "THE DEFECT: the worker took its own did-NOT-apply branch. It says so honestly and the issue still returns as the top pick next run."
else
  bad "the run reports the label as applied" "neither the applied nor the did-NOT-apply line is present"
fi

# 1f. NEGATIVE SELF-TEST for 1b-1d. All three grep a file that may be empty or
# absent; prove the greps can miss by running them against nothing.
if grep -q 'lid-blocked-capability' <<<"" 2>/dev/null; then
  bad "negative self-test (ops log)" "an empty ops log satisfied the mutation assertion -- the check is inert"
else
  ok "negative self-test: the mutation assertions reject an empty ops log"
fi

# ============================================================================
# RUN 2 -- the picker skips the labelled issue, AND still picks a clean one
# ============================================================================
# A SECOND SKELETON AND STATE DIR, not a re-run of the first: run 1 left
# sana/ask-810 checked out in its own worktree and git refuses to check one
# branch out twice. The BASENAME stays kipi-system -- the worker derives the
# repo identity from the checkout's directory name and filters the board to the
# matching Linear project, so a differently-named skeleton picks nothing and
# every assertion below goes vacuous. Same name, different parent.
#
# The board now holds BOTH: ASK-810 carrying the label the run above applied,
# and ASK-811 carrying nothing. One run answers both halves, and 811 is the live
# control -- without it, "810 was not dispatched" passes on a worker that
# dispatches nothing at all.
write_board "[$(issue_json ASK-810 blocked:capability),$(issue_json ASK-811)]"

SKEL2="$(new_skel "$WORK/run2")"
STATE2="$WORK/state2"
run_worker "$SKEL2" "$STATE2" "$WORK/run2.out" 2
OUT2="$(cat "$WORK/run2.out")
$(cat "$STATE2/linear-worker.log" 2>/dev/null)"

# 2a. THE NEGATIVE CASE, ASSERTED FIRST because it is the control. A refusal
# branch that exits too early stalls the whole queue, and that failure is
# invisible if the only assertion is an absence.
if grep -q "start ASK-811" <<<"$OUT2"; then
  ok "an issue with no refusal label is STILL dispatched (the queue is not stalled)"
else
  bad "an issue with no refusal label is still dispatched" \
      "THE DEFECT: ASK-811 carries no refusal label and was never dispatched -- the refusal path is stopping legitimate work. Output: $(tr '\n' '|' <<<"$OUT2" | cut -c1-600)"
fi

# 2b. AND THE EXCLUSION. ready() drops blocked:capability, so the labelled issue
# is never handed back.
if grep -q "start ASK-810" <<<"$OUT2"; then
  bad "a blocked:capability issue is NOT dispatched again" \
      "THE DEFECT: the picker handed back an issue carrying blocked:capability -- this is ASK-1168's third dispatch"
else
  ok "a blocked:capability issue is NOT dispatched again (ready() excludes it)"
fi

# 2c. ...and no Sana session was spent on it. The dispatch line is the loop's
# own report; the agent stub writing a sentinel into the tree is the machine
# fact underneath it. A worker that skipped the say line but ran the agent
# anyway would satisfy 2b and still burn the budget.
if find "$STATE2" -name '.sana-blocked-capability' 2>/dev/null | grep -q .; then
  bad "no agent run is spent on a blocked:capability issue" \
      "a sentinel was written under $STATE2 -- the agent ran on the parked issue"
else
  ok "no agent run is spent on a blocked:capability issue (no sentinel was written)"
fi

echo
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
