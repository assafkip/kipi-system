#!/usr/bin/env bash
# A `blocked:capability` block re-tests itself and clears when the capability
# it names now exists (ASK-288).
#
# THE DEFECT THIS PINS
# --------------------
# `blocked:capability` never expired. The label removed the issue from the
# picker permanently, and the only thing that could put it back was a human
# noticing the Linear comment and deleting the label by hand. So the loop's
# terminal-but-recoverable state had no recovery: 10 issues parked on
# 2026-08-01 while the worker logged one consolidated count every 15 minutes
# and nothing ever re-tested the environment those 10 issues were waiting on.
# A capability that arrived (a binary installed, a credential exported) left
# the board exactly as blocked as a capability that never came.
#
# WHAT IT PROVES
# --------------
# 1. a recorded probe that PASSES removes the label -- the issue returns to the
#    picker with no human in the path
# 2. a recorded probe that FAILS leaves the issue parked, and posts no comment
#    (a re-test every 15 minutes must not be a comment every 15 minutes)
# 3. an issue with NO recorded probe is reported as unprobeable and is NEVER
#    expired. "Not doing: backfilling probes by hand" is the DoR line; a block
#    with no probe stays a block, it does not become a guess.
# 4. an unknown / malformed probe kind FAILS CLOSED. Un-parking an issue whose
#    capability was never actually tested is the one unrecoverable direction:
#    the label is gone and the picker never offers it again.
# 5. the probe runner executes no shell. The recorded probe is agent-authored
#    text read back by an unattended job, so `cmd:rm -rf ~` must be an unknown
#    kind, not a command.
# 6. dry by default: without --apply nothing mutates, same convention as the
#    worker and linear-sync create.
# 7. the worker RUNS this before it picks (the wiring proof). A correct expiry
#    script nothing calls is the same as no expiry script.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)"
EXPIRY="${KIPI_EXPIRY_UNDER_TEST:-$REPO_SCRIPTS/capability_block_expiry.py}"
WORKER="${KIPI_WORKER_UNDER_TEST:-$REPO_SCRIPTS/linear-worker.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT

# The PASSING probe points at a path this test creates, not at a binary that
# happens to be installed on the runner. A fixture built from "what my laptop
# has" is a fixture that fails on someone else's laptop for a reason that has
# nothing to do with the code under test.
PRESENT="$WORK/capability-that-now-exists"
: > "$PRESENT"
ABSENT="$WORK/capability-that-is-still-missing"

# --- fixture Linear ----------------------------------------------------------
# Five parked issues, one per class the expiry script must tell apart. Every
# request body is appended to requests.log so the assertions can ask what was
# actually sent rather than what the script says it sent.
cat > "$WORK/fixture-server.py" <<PY
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

REQ_LOG = "$WORK/requests.log"
PRESENT = "$PRESENT"
ABSENT  = "$ABSENT"

# One comment body per issue, in the shape linear-worker.sh writes at park time:
# prose for the human, plus a machine-readable probe marker for this script.
PROBES = {
    # 1. the capability arrived -> must be unblocked
    "ASK-901": "path:" + PRESENT,
    # 2. still missing -> must stay parked
    "ASK-902": "path:" + ABSENT,
    # 3. parked before probes existed -> unprobeable, never expired
    "ASK-903": None,
    # 4. a kind the allowlist does not know -> fail closed
    "ASK-904": "quantum:maybe",
    # 5. a shell command dressed as a probe -> must NOT run, must not unblock.
    #    If this ever executes, it writes the file the assertion looks for.
    "ASK-905": "cmd:touch $WORK/SHELL-ESCAPED",
}

def comments_for(ident):
    nodes = [{"id": "c0-" + ident, "createdAt": "2026-08-01T00:00:00.000Z",
              "body": "**sana** · park\n\nBlocked on a missing capability.",
              "user": {"name": "t"}, "botActor": None}]
    probe = PROBES.get(ident)
    if probe is not None:
        nodes.append({"id": "c1-" + ident, "createdAt": "2026-08-01T00:01:00.000Z",
                      "body": "**sana** · park\n\nBlocked on a missing capability, not on scope.\n\n<!-- capability-probe: " + probe + " -->",
                      "user": {"name": "t"}, "botActor": None})
    return nodes

def issue(ident, labels):
    return {"id": ident, "identifier": ident, "title": "fixture " + ident,
            "description": "## Definition of Ready\nOutcome: x",
            "state": {"id": "s", "name": "backlog", "type": "backlog"},
            "project": {"name": "kipi-system"}, "team": {"id": "t"},
            "labels": {"nodes": [{"id": "l-" + n, "name": n} for n in labels]}}

BOARD = [issue(i, ["owner:sana", "blocked:capability"])
         for i in ("ASK-901", "ASK-902", "ASK-903", "ASK-904", "ASK-905")]
# A parked issue in ANOTHER repo's project. The expiry script scopes to this
# checkout for the same reason the picker does: unblocking an issue this
# checkout cannot check out just moves the stall somewhere quieter.
FOREIGN = issue("ASK-906", ["owner:sana", "blocked:capability"])
FOREIGN["project"] = {"name": "some-other-repo"}
# Not blocked at all. Present so "it unblocked everything" cannot pass.
FREE = issue("ASK-907", ["owner:sana"])
BOARD = BOARD + [FOREIGN, FREE]
BY_ID = {i["identifier"]: i for i in BOARD}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        with open(REQ_LOG, "a") as fh:
            fh.write(body + "\n")
        payload = json.loads(body)
        q, v = payload["query"], payload.get("variables") or {}
        if "teams(" in q:
            data = {"teams": {"nodes": [{"id": "t", "key": "ASK", "name": "ASK"}]}}
        elif "issueUpdate" in q:
            data = {"issueUpdate": {"success": True}}
        elif "commentCreate" in q:
            data = {"commentCreate": {"success": True, "comment": {"id": "new"}}}
        elif "comments(" in q:
            i = BY_ID.get(v.get("id"))
            data = {"issue": dict(i, comments={"nodes": comments_for(i["identifier"])}) if i else None}
        elif "issue(" in q:
            data = {"issue": BY_ID.get(v.get("id"))}
        else:
            data = {"issues": {"nodes": BOARD,
                               "pageInfo": {"hasNextPage": False, "endCursor": None}}}
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
[ -n "${PORT:-}" ] || { echo "fixture server did not start"; cat "$WORK/server.err"; exit 1; }

LINEAR_ENV=(
  KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql"
  KIPI_LINEAR_API_KEY="fixture-key-not-a-secret"
)

echo "== capability block expiry (script under test: $EXPIRY)"

# --- 6. dry by default ------------------------------------------------------
# Asserted FIRST, before any --apply run has dirtied requests.log with real
# mutations. Ordering is the only thing that makes this assertion possible.
env "${LINEAR_ENV[@]}" python3 "$EXPIRY" --repo-project kipi-system > "$WORK/dry.out" 2>&1
DRY_RC=$?
if [ "$DRY_RC" -ne 0 ]; then
  bad "dry run exits 0" "rc=$DRY_RC: $(head -3 "$WORK/dry.out")"
else
  ok "dry run exits 0"
fi
if grep -q "issueUpdate" "$WORK/requests.log" 2>/dev/null; then
  bad "dry by default" "a dry run sent an issueUpdate mutation"
else
  ok "dry by default: no mutation without --apply"
fi
if grep -q "ASK-901" "$WORK/dry.out"; then
  ok "a dry run still SAYS what it would clear"
else
  bad "a dry run says what it would clear" "ASK-901 absent from dry output"
fi

# --- the real run -----------------------------------------------------------
env "${LINEAR_ENV[@]}" python3 "$EXPIRY" --repo-project kipi-system --apply \
  > "$WORK/run.out" 2>&1
RC=$?
OUT="$(cat "$WORK/run.out")"
MUTATIONS="$(grep "issueUpdate" "$WORK/requests.log" 2>/dev/null || true)"

if [ "$RC" -ne 0 ]; then
  bad "the apply run exits 0" "rc=$RC: $(head -5 "$WORK/run.out")"
else
  ok "the apply run exits 0"
fi

# --- 1. a probe that passes clears the block --------------------------------
# The bar is the MUTATION, not the log line. A script that says "unblocked" and
# sends nothing is the exact shape of the discarded-mutation defect linear-sync
# already carries two comments about.
if printf '%s' "$MUTATIONS" | grep -q "ASK-901"; then
  ok "a passing probe sends the label removal for ASK-901"
else
  bad "a passing probe clears the block" "no issueUpdate naming ASK-901 in requests.log"
fi
# And the label set it wrote back must have DROPPED blocked:capability while
# KEEPING owner:sana. Sending only the survivors is right; sending an empty set
# would also "remove" the block and would drop the issue out of the queue for a
# completely different reason.
if printf '%s' "$MUTATIONS" | grep "ASK-901" | grep -q "l-owner:sana"; then
  ok "the label removal keeps owner:sana"
else
  bad "the label removal keeps owner:sana" "owner:sana missing from the ASK-901 labelIds"
fi
if printf '%s' "$MUTATIONS" | grep "ASK-901" | grep -q "l-blocked:capability"; then
  bad "the label removal drops blocked:capability" "blocked:capability still in the ASK-901 labelIds"
else
  ok "the label removal drops blocked:capability"
fi
# The comment is how a reader learns WHY it came back. Without it the issue
# silently reappears in the picker and the trail says nothing.
if grep "commentCreate" "$WORK/requests.log" | grep -q "ASK-901"; then
  ok "an unblock posts the probe result onto the issue"
else
  bad "an unblock posts the probe result" "no commentCreate for ASK-901"
fi

# --- 2. a probe that fails leaves it parked, quietly ------------------------
if printf '%s' "$MUTATIONS" | grep -q "ASK-902"; then
  bad "a failing probe leaves the block in place" "ASK-902 was unblocked anyway"
else
  ok "a failing probe leaves the block in place"
fi
if grep "commentCreate" "$WORK/requests.log" | grep -q "ASK-902"; then
  bad "a still-failing probe posts no comment" "ASK-902 got a comment on a re-test that changed nothing"
else
  ok "a still-failing probe posts no comment (re-tests are not comment spam)"
fi

# --- 3. no recorded probe -> unprobeable, never expired ---------------------
if printf '%s' "$MUTATIONS" | grep -q "ASK-903"; then
  bad "an issue with no probe is never expired" "ASK-903 was unblocked with nothing to test"
else
  ok "an issue with no probe is never expired"
fi
if printf '%s\n' "$OUT" | grep -q "ASK-903"; then
  ok "an unprobeable block is REPORTED, not silently held"
else
  bad "an unprobeable block is reported" "ASK-903 never named in the output"
fi

# --- 4. an unknown kind fails closed ----------------------------------------
if printf '%s' "$MUTATIONS" | grep -q "ASK-904"; then
  bad "an unknown probe kind fails closed" "ASK-904 was unblocked on a probe nobody can run"
else
  ok "an unknown probe kind fails closed"
fi

# --- 5. no shell execution --------------------------------------------------
if [ -f "$WORK/SHELL-ESCAPED" ]; then
  bad "the probe runner executes no shell" "cmd: probe ran and touched $WORK/SHELL-ESCAPED"
else
  ok "the probe runner executes no shell"
fi
if printf '%s' "$MUTATIONS" | grep -q "ASK-905"; then
  bad "a shell-shaped probe does not unblock" "ASK-905 was unblocked"
else
  ok "a shell-shaped probe does not unblock"
fi

# --- scope: another repo's parked issue is not touched ----------------------
if printf '%s' "$MUTATIONS" | grep -q "ASK-906"; then
  bad "out-of-repo parked issues are left alone" "ASK-906 (some-other-repo) was mutated"
else
  ok "out-of-repo parked issues are left alone"
fi
# ASK-907 is not blocked at all. If it appears in a mutation the script is
# operating on the whole board rather than on the parked set.
if printf '%s' "$MUTATIONS" | grep -q "ASK-907"; then
  bad "unblocked issues are not touched" "ASK-907 (never parked) was mutated"
else
  ok "unblocked issues are not touched"
fi

# --- 7. the worker calls it before picking (wiring) -------------------------
# Read from the worker's source rather than by running it: the run itself is
# already covered by test-worker-refusal.sh, and what is being asserted here is
# that the pre-pick step EXISTS and precedes the pick. Grepping for the call is
# the load-path proof for a step whose only observable effect is on Linear.
PRE_PICK_LINE="$(grep -n "capability_block_expiry.py" "$WORKER" | head -1 | cut -d: -f1)"
PICK_LINE="$(grep -n "^PICKED=" "$WORKER" | head -1 | cut -d: -f1)"
if [ -n "$PRE_PICK_LINE" ] && [ -n "$PICK_LINE" ] && [ "$PRE_PICK_LINE" -lt "$PICK_LINE" ]; then
  ok "the worker runs the expiry BEFORE it picks (line $PRE_PICK_LINE < $PICK_LINE)"
else
  bad "the worker runs the expiry before it picks" \
      "expiry call at '${PRE_PICK_LINE:-none}', pick at '${PICK_LINE:-none}'"
fi

# The park path must RECORD a probe, or the expiry above has nothing to read on
# every issue parked from here on -- which is how the whole loop stays a
# permanent block dressed as a temporary one.
if grep -q "capability-probe:" "$WORKER"; then
  ok "the worker records a capability-probe marker when it parks"
else
  bad "the worker records a capability-probe marker" "no capability-probe: in $WORKER"
fi

# --- unblock verb ------------------------------------------------------------
# The expiry script must not hand-roll its own label mutation: linear-sync.py is
# the one writer of Linear state in this fleet, and a second copy drifts.
if grep -q "unblock" "$REPO_SCRIPTS/linear-sync.py"; then
  ok "linear-sync.py carries the unblock verb"
else
  bad "linear-sync.py carries the unblock verb" "no unblock subcommand"
fi

echo
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
