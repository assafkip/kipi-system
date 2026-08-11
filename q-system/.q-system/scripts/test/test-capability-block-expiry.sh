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

# --- the credential fixtures, RECORDED BY THE PRODUCER -----------------------
# ASK-909 and ASK-910 are both `env:` parks, and the difference between them is
# the whole of codex's finding on probe_env: a credential that is PRESENT AND
# EXPIRED is nonblank, so "is it set" answers yes on the very environment the
# park was refused in. Nothing arrived; the issue un-parks anyway, spends a
# dispatch, and blocks again.
#
# The recorded probe text is produced by the park-time validator rather than
# hand-written here. A probe string I typed from memory tests my mental model of
# the format; asking the producer tests the round trip the loop actually runs.
CRED_EXPIRED="expired-token-from-the-park"
CRED_ROTATED="a-freshly-rotated-credential"
record_probe() { # <env-value-at-park-time> <spec>
  KIPI_FIXTURE_CRED="$1" python3 - "$REPO_SCRIPTS" "$2" <<'PY' 2>/dev/null || true
import sys
sys.path.insert(0, sys.argv[1])
import capability_block_expiry as cbe
print(cbe.validate_recorded_probe(sys.argv[2]))
PY
}
# 909: the credential was SET (and expired) when the park was written.
FIXTURE_PROBE_909="$(record_probe "$CRED_EXPIRED" "env:KIPI_FIXTURE_CRED")"
# 910: the credential was genuinely ABSENT at park time. This is the honest
# arrival case and it must keep working -- unset -> set is real evidence.
FIXTURE_PROBE_910="$(record_probe "" "env:KIPI_FIXTURE_CRED")"
export FIXTURE_PROBE_909 FIXTURE_PROBE_910

# --- fixture Linear ----------------------------------------------------------
# Five parked issues, one per class the expiry script must tell apart. Every
# request body is appended to requests.log so the assertions can ask what was
# actually sent rather than what the script says it sent.
cat > "$WORK/fixture-server.py" <<PY
import json, os, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
    # 6. ANOTHER REPO'S PARKED ISSUE, and its probe PASSES. Without a passing
    #    probe the "out-of-repo issues are left alone" assertion below holds for
    #    the wrong reason -- there was nothing to clear either way -- and the
    #    unscoped-sweep case (codex round 3) has no way to go red at all.
    "ASK-906": "path:" + PRESENT,
    # 8. THE STALE MARKER (codex PR #77, capability_block_expiry.py:240). The
    #    marker below is real but belongs to a park from a MONTH ago that was
    #    already cleared. The CURRENT park's comment never posted (the progress
    #    call is best-effort: \`|| true\`), so the newest marker on the thread
    #    describes an environment question nobody asked this time -- and it
    #    passes. "Last marker on the thread wins" un-parks on the strength of it.
    "ASK-908": "path:" + PRESENT,
    # 9/10. the credential probe, recorded by the park-time validator (which is
    #    the producer -- these are not hand-written). Filled in by the harness
    #    below, because the value it carries depends on the environment the park
    #    observed, which is exactly the point.
    "ASK-909": os.environ.get("FIXTURE_PROBE_909") or "none",
    "ASK-910": os.environ.get("FIXTURE_PROBE_910") or "none",
}

# When \`blocked:capability\` was last ADDED, per issue. Linear records this as a
# history entry carrying addedLabelIds; verified live against ASK-281 on
# 2026-08-03 rather than assumed, because a fixture invented from my own mental
# model of the API is a test of that model (the scar this repo already carries).
PARKED_AT = {ident: "2026-08-01T00:00:30.000Z" for ident in
             ("ASK-901", "ASK-902", "ASK-903", "ASK-904", "ASK-905",
              "ASK-906", "ASK-909", "ASK-910")}
# The stale case: parked LAST, marker written FIRST. Everything else about the
# thread looks healthy.
PARKED_AT["ASK-908"] = "2026-08-02T12:00:00.000Z"

# The marker comment's timestamp. Default sits just after the park.
MARKED_AT = {ident: "2026-08-01T00:01:00.000Z" for ident in PROBES}
MARKED_AT["ASK-908"] = "2026-07-01T00:01:00.000Z"

def comments_for(ident):
    nodes = [{"id": "c0-" + ident, "createdAt": "2026-08-01T00:00:00.000Z",
              "body": "**sana** · park\n\nBlocked on a missing capability.",
              "user": {"name": "t"}, "botActor": None}]
    probe = PROBES.get(ident)
    if probe is not None:
        nodes.append({"id": "c1-" + ident, "createdAt": MARKED_AT.get(ident, "2026-08-01T00:01:00.000Z"),
                      "body": "**sana** · park\n\nBlocked on a missing capability, not on scope.\n\n<!-- capability-probe: " + probe + " -->",
                      "user": {"name": "t"}, "botActor": None})
    return nodes

def history_for(ident):
    """The label-change history Linear serves, shaped as the live API shapes it.

    Only the block label's add matters here, but the unrelated entries are kept
    so a reader of this fixture can see that the script has to FILTER rather
    than take the newest history row.
    """
    when = PARKED_AT.get(ident)
    nodes = [{"createdAt": "2026-07-20T00:00:00.000Z",
              "addedLabelIds": ["l-owner:sana"], "removedLabelIds": None}]
    if when:
        nodes.append({"createdAt": when,
                      "addedLabelIds": ["l-blocked:capability"],
                      "removedLabelIds": None})
    return nodes

def issue(ident, labels):
    return {"id": ident, "identifier": ident, "title": "fixture " + ident,
            "description": "## Definition of Ready\nOutcome: x",
            "state": {"id": "s", "name": "backlog", "type": "backlog"},
            "project": {"name": "kipi-system"}, "team": {"id": "t"},
            "labels": {"nodes": [{"id": "l-" + n, "name": n} for n in labels]}}

BOARD = [issue(i, ["owner:sana", "blocked:capability"])
         for i in ("ASK-901", "ASK-902", "ASK-903", "ASK-904", "ASK-905",
                   "ASK-908", "ASK-909", "ASK-910")]
# A parked issue in ANOTHER repo's project. The expiry script scopes to this
# checkout for the same reason the picker does: unblocking an issue this
# checkout cannot check out just moves the stall somewhere quieter.
FOREIGN = issue("ASK-906", ["owner:sana", "blocked:capability"])
FOREIGN["project"] = {"name": "some-other-repo"}
# Not blocked at all. Present so "it unblocked everything" cannot pass.
FREE = issue("ASK-907", ["owner:sana"])
BOARD = BOARD + [FOREIGN, FREE]
BY_ID = {i["identifier"]: i for i in BOARD}

# --- the concurrency fixture (codex PR #77 round 4) --------------------------
# ASK-911 is deliberately NOT on the team board: the surface under test is
# cmd_unblock itself, called directly by two processes at once, and putting a
# tenth clearable issue into the sweep would move every count assertion above
# for a reason that has nothing to do with this finding.
#
# Two things make the race real instead of theoretical here. The label state is
# MUTABLE -- a removal actually takes the label off, the way Linear does -- and
# the label READ for this issue is held for a second, so two processes started
# together both read "still parked" before either one mutates. That is the
# window inside cmd_unblock: read, decide, write, with nothing serialising the
# three. issueRemoveLabel answers success=True either way, exactly as the live
# API does, which is precisely why the loser cannot tell it lost by asking.
RACE = "ASK-911"
BY_ID[RACE] = issue(RACE, ["owner:sana", "blocked:capability"])
RACE_READ_DELAY = float(os.environ.get("FIXTURE_RACE_DELAY") or "1.0")
STATE_LOCK = threading.Lock()
REMOVED = set()  # (issue identifier, label id) pairs actually taken off

def visible(ident):
    i = BY_ID.get(ident)
    # Mutable for the RACE issue ONLY. Making every issue's label state stick
    # would silently change what the second --apply run in this file sees, and
    # a fixture that moves under the assertions above is a fixture that makes
    # them pass or fail for reasons unrelated to the code under test.
    if not i or ident != RACE:
        return i
    with STATE_LOCK:
        gone = {lid for (who, lid) in REMOVED if who == ident}
    if not gone:
        return i
    kept = [n for n in i["labels"]["nodes"] if n["id"] not in gone]
    return dict(i, labels={"nodes": kept})

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        with STATE_LOCK:
            with open(REQ_LOG, "a") as fh:
                fh.write(body + "\n")
        payload = json.loads(body)
        q, v = payload["query"], payload.get("variables") or {}
        if "teams(" in q:
            data = {"teams": {"nodes": [{"id": "t", "key": "ASK", "name": "ASK"}]}}
        elif "issueRemoveLabel" in q:
            # Idempotent and always successful, like the live mutation. The
            # second remover of the same label gets the same answer as the first.
            with STATE_LOCK:
                REMOVED.add((v.get("id"), v.get("labelId")))
            data = {"issueRemoveLabel": {"success": True}}
        elif "issueUpdate" in q:
            data = {"issueUpdate": {"success": True}}
        elif "commentCreate" in q:
            data = {"commentCreate": {"success": True, "comment": {"id": "new"}}}
        elif "history(" in q:
            i = BY_ID.get(v.get("id"))
            data = {"issue": {"history": {"nodes": history_for(i["identifier"])}} if i else None}
        elif "comments(" in q:
            i = BY_ID.get(v.get("id"))
            data = {"issue": dict(i, comments={"nodes": comments_for(i["identifier"])}) if i else None}
        elif "issue(" in q:
            ident = v.get("id")
            if ident == RACE:
                time.sleep(RACE_READ_DELAY)
            data = {"issue": visible(ident)}
        else:
            data = {"issues": {"nodes": BOARD,
                               "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        out = json.dumps({"data": data}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers()
        self.wfile.write(out)

srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
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
  # The environment the sweep re-tests against. The credential is SET and holds
  # the SAME value the park refused, which is the whole of the expired-token
  # case: ASK-909 (fingerprinted at park time) must read that as no change,
  # while ASK-910 (parked when the variable was absent) must read it as arrival.
  # One variable, two verdicts, decided by what each park recorded.
  KIPI_FIXTURE_CRED="$CRED_EXPIRED"
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
# BOTH shapes. The correct removal is issueRemoveLabel; issueUpdate is matched
# too so that a regression back to the full-set rewrite is caught by the
# assertions below rather than silently passing every "was it unblocked" check
# for the opposite reason (no mutation of either shape looks identical to a
# mutation this grep cannot see).
MUTATIONS="$(grep -E "issueRemoveLabel|issueUpdate" "$WORK/requests.log" 2>/dev/null || true)"

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
# ...and it must name the BLOCK label, so the removal is the one that was asked
# for rather than whatever the label set happened to contain.
if printf '%s' "$MUTATIONS" | grep "ASK-901" | grep -q "l-blocked:capability"; then
  ok "the removal names blocked:capability"
else
  bad "the removal names blocked:capability" "no l-blocked:capability in the ASK-901 mutation"
fi
# --- 1b. the removal touches ONE label, not the whole set -------------------
# (codex PR #77, linear-sync.py:806.) issueUpdate takes labelIds as the COMPLETE
# set, so a read-modify-write here sends back a snapshot taken seconds earlier
# and silently deletes anything another worker added in between. This loop runs
# a picker, a worker and an expiry sweep against one board, so "another writer
# labelled it while I was thinking" is the normal case, not a rare interleaving.
# issueRemoveLabel names the single label and lets the server do the arithmetic.
if printf '%s' "$MUTATIONS" | grep "ASK-901" | grep -q "l-owner:sana"; then
  bad "the removal does not rewrite the whole label set" \
      "the ASK-901 mutation carries owner:sana -- it is sending a complete labelIds set, so a label added concurrently is erased"
else
  ok "the removal does not rewrite the whole label set (owner:sana is never resent)"
fi
if grep -q "issueRemoveLabel" "$WORK/requests.log" 2>/dev/null; then
  ok "the unblock goes through the single-label mutation"
else
  bad "the unblock goes through the single-label mutation" \
      "no issueRemoveLabel in requests.log -- the removal is still a full-set issueUpdate"
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

# --- 8. a marker from an EARLIER park does not clear the CURRENT one --------
# The park comment is posted best-effort (`|| true` in linear-worker.sh): the
# label lands, the comment can fail. When it does, the newest marker on the
# thread belongs to a park that was already cleared -- a different question,
# asked about a different capability, in a different month. It can pass. Taking
# "the last marker on the thread" then un-parks an issue whose current block was
# never tested at all, which is the one unrecoverable direction.
if printf '%s' "$MUTATIONS" | grep -q "ASK-908"; then
  bad "a marker older than the current park does not clear it" \
      "ASK-908 was unblocked on a probe recorded by a park from 2026-07-01 -- the current park (2026-08-02) recorded nothing"
else
  ok "a marker older than the current park does not clear it"
fi
# The absence above passes for free if ASK-908 was never examined. Pin that it
# was, and that the reason given is the honest one.
if printf '%s\n' "$OUT" | grep -q "ASK-908"; then
  ok "negative self-test: ASK-908 was examined and reported, not skipped"
else
  bad "negative self-test: ASK-908 was examined" \
      "ASK-908 never named in the output -- the assertion above passed vacuously"
fi

# --- 9. a credential that is present-and-expired is not 'arrived' -----------
# probe_env asked `is it nonblank`. An expired token is nonblank. So the park
# that refused BECAUSE the credential does not work re-tests as a pass on the
# unchanged environment, and the issue un-parks on the first sweep.
if printf '%s' "$MUTATIONS" | grep -q "ASK-909"; then
  bad "an unchanged credential does not un-park" \
      "ASK-909 was unblocked while KIPI_FIXTURE_CRED still holds the exact value the park refused"
else
  ok "an unchanged credential does not un-park"
fi
# The counterpart, and the reason this is not just 'never trust env:'. A
# credential that was genuinely ABSENT at park time and is now set DID arrive.
if printf '%s' "$MUTATIONS" | grep -q "ASK-910"; then
  ok "a credential that was absent at park time and is now set DOES un-park"
else
  bad "a credential that was absent at park time and is now set un-parks" \
      "ASK-910 stayed parked -- the fix over-corrected and env: probes can no longer clear anything"
fi
# And the park-time record must not be the bare variable name for a value that
# was already set, or there is nothing later to compare against.
if [ "$FIXTURE_PROBE_909" = "env:KIPI_FIXTURE_CRED" ]; then
  bad "a park over an already-set credential records what it saw" \
      "the validator recorded the bare 'env:KIPI_FIXTURE_CRED' -- it kept no record of the value it refused, so no later sweep can tell rotation from the status quo"
else
  ok "a park over an already-set credential records what it saw ($FIXTURE_PROBE_909)"
fi

# --- 9b. the rotated credential DOES clear it -------------------------------
# The whole point of ASK-288 is that no human is the next actor. If a
# present-but-expired credential could only ever be hand-cleared, the most
# common capability block in this fleet would be exactly as permanent as before.
# Rotate the value and the same recorded probe must now pass.
BEFORE_ROTATE="$(wc -l < "$WORK/requests.log")"
env "${LINEAR_ENV[@]}" KIPI_FIXTURE_CRED="$CRED_ROTATED" \
  python3 "$EXPIRY" --repo-project kipi-system --apply > "$WORK/rotated.out" 2>&1
ROTATED_MUTATIONS="$(tail -n +"$((BEFORE_ROTATE + 1))" "$WORK/requests.log" \
  | grep -E "issueRemoveLabel|issueUpdate" || true)"
if printf '%s' "$ROTATED_MUTATIONS" | grep -q "ASK-909"; then
  ok "rotating the credential clears the block with no human in the path"
else
  bad "rotating the credential clears the block" \
      "ASK-909 stayed parked after KIPI_FIXTURE_CRED changed -- the block is permanent, which is the defect ASK-288 exists to remove"
fi

# --- 9c. a rotation is not an arrival, and must not be reported as one ------
# (codex PR #77 round 4, capability_block_expiry.py:185.) The fingerprint proves
# the credential CHANGED. Nothing here can prove the replacement authenticates --
# an operator pasting a second expired token rotates the value just as well as an
# operator pasting a working one. Clearing on rotation is still right (the block
# is waiting on exactly that event, and refusing would make the commonest park
# hand-clear-only again), but the permanent comment it writes said "The
# capability arrived", which is a claim this script never checked. Linear
# comments cannot be deleted, so the false claim is the durable damage.
#
# ASK-910 in the SAME run is the control: it was parked while the variable was
# genuinely unset, so unset -> set is real evidence and it keeps the verified
# wording. One run, two verdicts, so the assertions cannot both pass by the
# script simply never claiming anything.
ROTATED_COMMENTS="$(tail -n +"$((BEFORE_ROTATE + 1))" "$WORK/requests.log" | grep "commentCreate" || true)"
ROT_909="$(printf '%s\n' "$ROTATED_COMMENTS" | grep "ASK-909" || true)"
ROT_910="$(printf '%s\n' "$ROTATED_COMMENTS" | grep "ASK-910" || true)"
if [ -n "$ROT_909" ] && ! printf '%s' "$ROT_909" | grep -q "The capability arrived"; then
  ok "a rotation-cleared block does not claim the capability arrived"
else
  bad "a rotation-cleared block does not claim the capability arrived" \
      "ASK-909 cleared on a fingerprint change and the permanent comment asserted arrival, which nothing tested: $(printf '%s' "$ROT_909" | head -c 300)"
fi
if printf '%s' "$ROT_909" | grep -q "not proof"; then
  ok "the rotation comment says what it actually checked"
else
  bad "the rotation comment says what it actually checked" \
      "no 'not proof' caveat on ASK-909 -- the reader cannot tell an unverified clear from a verified one: $(printf '%s' "$ROT_909" | head -c 300)"
fi
if [ -n "$ROT_910" ] && printf '%s' "$ROT_910" | grep -q "The capability arrived"; then
  ok "control: a genuine unset -> set arrival keeps the verified wording"
else
  bad "control: a genuine unset -> set arrival keeps the verified wording" \
      "ASK-910 was parked with the variable absent, so presence IS the evidence -- if this lost the arrival wording the fix over-corrected: $(printf '%s' "$ROT_910" | head -c 300)"
fi
if grep -q '"cleared_unverified": 1' "$WORK/rotated.out"; then
  ok "the summary counts an unverified clear apart from a verified one"
else
  bad "the summary counts an unverified clear apart from a verified one" \
      "the run summary folds both into one number, so the log cannot answer how many blocks were lifted on evidence: $(grep 'capability-expiry: {' "$WORK/rotated.out" | head -c 300)"
fi

# --- 12. two processes unblocking at once: exactly one clears ---------------
# (codex PR #77 round 4, linear-sync.py:813.) Round 3 taught the CALLER to tell
# a real removal from a no-op, which fixed the case where the loser arrives
# after the winner finished. It left the case where they overlap: both read the
# label present, both call issueRemoveLabel, both are answered success=True, so
# both report a clear and both post the permanent recovery comment.
#
# The fixture holds the label read for a second so the two processes are
# genuinely inside that window together. Without serialisation this is not a
# rare interleaving -- it is what happens every time the pre-pick sweep and the
# scheduled sweep land on the same issue.
RACE_LOCKS="$WORK/locks"
BEFORE_RACE="$(wc -l < "$WORK/requests.log")"
env "${LINEAR_ENV[@]}" KIPI_LOCK_DIR="$RACE_LOCKS" \
  python3 "$REPO_SCRIPTS/linear-sync.py" unblock ASK-911 blocked:capability \
  > "$WORK/race-a.out" 2>&1 &
RACE_A=$!
env "${LINEAR_ENV[@]}" KIPI_LOCK_DIR="$RACE_LOCKS" \
  python3 "$REPO_SCRIPTS/linear-sync.py" unblock ASK-911 blocked:capability \
  > "$WORK/race-b.out" 2>&1 &
RACE_B=$!
wait "$RACE_A"; RC_A=$?
wait "$RACE_B"; RC_B=$?
# EXIT_NOOP read from the module, not typed as 4 here: a literal is a second
# copy of the contract and would keep passing after the contract moved.
NOOP_CODE="$(python3 - "$REPO_SCRIPTS" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ls", sys.argv[1] + "/linear-sync.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
print(mod.EXIT_NOOP)
PY
)"
RACE_WINNERS=0; RACE_LOSERS=0
for rc in "$RC_A" "$RC_B"; do
  [ "$rc" = "0" ] && RACE_WINNERS=$((RACE_WINNERS+1))
  [ "$rc" = "$NOOP_CODE" ] && RACE_LOSERS=$((RACE_LOSERS+1))
done
if [ "$RACE_WINNERS" = "1" ] && [ "$RACE_LOSERS" = "1" ]; then
  ok "two overlapping unblocks report exactly one clear and one no-op"
else
  bad "two overlapping unblocks report exactly one clear and one no-op" \
      "rc=$RC_A and rc=$RC_B (noop=$NOOP_CODE): $RACE_WINNERS reported a clear, so the caller posts that many permanent recovery comments"
fi
RACE_REMOVALS="$(tail -n +"$((BEFORE_RACE + 1))" "$WORK/requests.log" \
  | grep -c "issueRemoveLabel" || true)"
if [ "$RACE_REMOVALS" = "1" ]; then
  ok "only one removal mutation is sent for one label"
else
  bad "only one removal mutation is sent for one label" \
      "$RACE_REMOVALS removals sent -- both processes were inside the read-decide-write window at once"
fi
# The two assertions above must not pass because BOTH runs failed -- "one clear
# and one no-op" and "one removal" are also what two crashes would look like if
# the counters were reading errors. Pin that the label really came off.
if [ "$RACE_REMOVALS" -ge 1 ] && grep -qh "removed blocked:capability" "$WORK/race-a.out" "$WORK/race-b.out"; then
  ok "negative self-test: the race actually removed the label (not two failures)"
else
  bad "negative self-test: the race actually removed the label" \
      "no successful removal: a=$(head -2 "$WORK/race-a.out") b=$(head -2 "$WORK/race-b.out")"
fi

# --- 10. an UNSCOPED run refuses; it does not sweep the whole team ----------
# (codex PR #77 round 3, capability_block_expiry.py:317.) The scope filter was
# `if repo_project and ...` -- so an unset scope did not mean "this repo", it
# meant NO FILTER, and `--apply` then cleared parked blocks belonging to every
# other repo on the team. The blast radius is the opposite of the one the guard
# was written for: one checkout wakes work no runner here can check out, and the
# label is gone. An unset scope is not a permissive default; it is missing
# information, and this file's rule for missing information is fail closed.
BEFORE_UNSCOPED="$(wc -l < "$WORK/requests.log")"
env -u REPO_PROJECT "${LINEAR_ENV[@]}" python3 "$EXPIRY" --apply \
  > "$WORK/unscoped.out" 2>&1
UNSCOPED_RC=$?
UNSCOPED_MUTATIONS="$(tail -n +"$((BEFORE_UNSCOPED + 1))" "$WORK/requests.log" \
  | grep -E "issueRemoveLabel|issueUpdate" || true)"
if [ "$UNSCOPED_RC" -ne 0 ]; then
  ok "an unscoped --apply refuses (rc=$UNSCOPED_RC)"
else
  bad "an unscoped --apply refuses" \
      "rc=0 -- the sweep ran with no repo scope: $(head -3 "$WORK/unscoped.out")"
fi
if printf '%s' "$UNSCOPED_MUTATIONS" | grep -q "ASK-906"; then
  bad "an unscoped run never clears another repo's block" \
      "ASK-906 (some-other-repo) was unblocked by a checkout that cannot check it out"
else
  ok "an unscoped run never clears another repo's block"
fi
# The refusal has to SAY what is missing, or the next operator reads exit 1 as
# "Linear is down" and retries it forever.
if grep -qi "repo-project\|REPO_PROJECT" "$WORK/unscoped.out"; then
  ok "the refusal names the missing scope"
else
  bad "the refusal names the missing scope" \
      "nothing about --repo-project in: $(head -3 "$WORK/unscoped.out")"
fi

# --- 11. the loser of two overlapping sweeps reports nothing ----------------
# (codex PR #77 round 3, capability_block_expiry.py:400.) Two sweeps can be in
# flight over one board: each lists the parked issues, each probes, each calls
# unblock. The first removes the label. The second's removal is a NO-OP -- and
# it exited 0, because "already absent" is deliberately idempotent -- so the
# caller counted a clear it did not perform and posted a second permanent
# "the capability arrived" comment onto an issue that already had one. Linear
# comments cannot be deleted, so a duplicate is forever.
#
# ASK-907 carries no `blocked:capability`, which is exactly what the losing
# sweep sees when it gets there: the label is already gone.
BEFORE_NOOP="$(wc -l < "$WORK/requests.log")"
env "${LINEAR_ENV[@]}" python3 - "$REPO_SCRIPTS" > "$WORK/noop.out" 2>&1 <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import capability_block_expiry as cbe
outcome, detail = cbe.clear_block("ASK-907", "path:/fixture", "fixture evidence")
# Compared against the module's own constant, not against the literal "noop".
# A test that hard-codes the string still passes if the caller stops recognising
# it, which is the exact class of drift this finding is.
print("outcome=%s is_clear=%s detail=%s" % (outcome, outcome == cbe.CLEARED, detail))
PY
NOOP_REQS="$(tail -n +"$((BEFORE_NOOP + 1))" "$WORK/requests.log" || true)"
if grep -q "is_clear=False" "$WORK/noop.out"; then
  ok "a no-op unblock is not reported as a clear"
else
  bad "a no-op unblock is not reported as a clear" \
      "clear_block said it cleared a label that was already gone: $(head -3 "$WORK/noop.out")"
fi
if printf '%s' "$NOOP_REQS" | grep "commentCreate" | grep -q "ASK-907"; then
  bad "a no-op unblock posts no recovery comment" \
      "a second 'the capability arrived' comment was posted onto ASK-907 -- Linear comments are permanent"
else
  ok "a no-op unblock posts no recovery comment"
fi
# The absence above must not pass because clear_block crashed before it got
# there. Pin that the call completed and returned a verdict.
if grep -q "^outcome=" "$WORK/noop.out"; then
  ok "negative self-test: clear_block ran to a verdict (not an exception)"
else
  bad "negative self-test: clear_block ran to a verdict" \
      "no verdict line -- the two assertions above passed vacuously: $(head -5 "$WORK/noop.out")"
fi

# --- 7. the worker calls it before picking (wiring) -------------------------
# Read from the worker's source rather than by running it: the run itself is
# already covered by test-worker-refusal.sh, and what is being asserted here is
# that the pre-pick step EXISTS and precedes the pick. Grepping for the call is
# the load-path proof for a step whose only observable effect is on Linear.
#
# MATCH THE INVOCATION, NOT THE NAME (codex PR #77, this file:285). The first cut
# grepped for `capability_block_expiry.py`, whose first hit is the line that
# builds the PATH -- `EXPIRY="$SCRIPT_DIR/capability_block_expiry.py"`. Deleting
# the line that actually RUNS it left this assertion green, so the wiring proof
# proved only that the worker knows the filename. The pattern below requires the
# script to be executed.
expiry_invocation_line() { # <worker-file>
  grep -nE 'python3[[:space:]]+"\$EXPIRY"' "$1" | head -1 | cut -d: -f1
}
PRE_PICK_LINE="$(expiry_invocation_line "$WORKER")"
PICK_LINE="$(grep -n "^PICKED=" "$WORKER" | head -1 | cut -d: -f1)"
if [ -n "$PRE_PICK_LINE" ] && [ -n "$PICK_LINE" ] && [ "$PRE_PICK_LINE" -lt "$PICK_LINE" ]; then
  ok "the worker runs the expiry BEFORE it picks (line $PRE_PICK_LINE < $PICK_LINE)"
else
  bad "the worker runs the expiry before it picks" \
      "expiry invocation at '${PRE_PICK_LINE:-none}', pick at '${PICK_LINE:-none}'"
fi
# NEGATIVE SELF-TEST for the assertion above, which is the only reason to trust
# it. Strip the invocation from a copy and the check must go RED. Without this,
# the next loosening of the pattern is invisible exactly the way the last one was.
MUTILATED="$WORK/worker-without-the-call.sh"
grep -vE 'python3[[:space:]]+"\$EXPIRY"' "$WORKER" > "$MUTILATED"
if [ -z "$(expiry_invocation_line "$MUTILATED")" ]; then
  ok "negative self-test: removing the expiry invocation makes the wiring check fail"
else
  bad "negative self-test: removing the expiry invocation makes the wiring check fail" \
      "the check still finds an invocation in a worker that has none -- it is matching something other than the call"
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
