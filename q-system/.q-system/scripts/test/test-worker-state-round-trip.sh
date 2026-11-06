#!/usr/bin/env bash
# A started ticket nobody is working comes back, and a failed run sends its
# ticket back to Backlog (ASK-3825, RULE-2026-11-06-B).
#
# THE DEFECT, MEASURED 2026-11-06. The picker read backlog and unstarted only.
# 15 owner:sana tickets sat In Progress, the oldest 43 days, and `kipi work`
# listed none of them. Nothing moved a ticket back after a failed, capped or
# parked run, so the first failure made it invisible to every drain at once.
#
# THE TRAP THIS SUITE PINS. The orchestrator moves a lane's tickets to In
# Progress BY HAND so the fleet worker leaves them alone, and those tickets have
# no worker claim and often no PR. "Started and unclaimed" alone would race
# every live lane the moment this merged. So case 2 is a ticket moved to In
# Progress one hour ago with no claim, and it must NOT be picked.
#
# WHAT IS REAL AND WHAT IS STUBBED. The real linear-worker.sh picker, the real
# linear-sync.py (started_hold_reason, requeue) and the real linear-claim.py
# liveness rule run against a fixture Linear server through the transport seam
# KIPI_LINEAR_API_URL. Stubbed: gh, claude, codex, the reviewer, the notifier
# and the usage breaker. Nothing here reaches real Linear or a real repo.
#
# NEGATIVE SELF-TESTS (case 9). The picker cases run again against two mutant
# copies of the scripts dir: one with the started rule removed (case 1 must go
# red) and one with the 24h window set to zero (case 2 must go red).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER="${KIPI_WORKER_UNDER_TEST:-$REPO_SCRIPTS/linear-worker.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT

# --- fixture Linear, with state ----------------------------------------------
# It KEEPS state across requests, because the claim under test is a round trip:
# a run moves a ticket, and the next run must see where it went. Every mutation
# is appended to FIXTURE_LOG as one JSON line, which is what the cases read.
cat > "$WORK/fixture-server.py" <<'PY'
import json, os
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = os.environ["FIXTURE_LOG"]
NOW = datetime.now(timezone.utc)
NAMES = {"backlog": "Backlog", "unstarted": "Todo", "started": "In Progress",
         "completed": "Done"}
STATE_IDS = {"backlog": "st-backlog", "unstarted": "st-todo", "started": "st-progress",
             "completed": "st-done"}
BY_ID = {v: k for k, v in STATE_IDS.items()}


def ago(hours):
    return (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def issue(ident, state, started_hours=None, project="kipi-system"):
    return {"id": "uuid-" + ident, "identifier": ident, "title": "fixture " + ident,
            "description": "## Definition of Ready\nOutcome: x",
            "state": {"name": NAMES[state], "type": state},
            "startedAt": ago(started_hours) if started_hours is not None else None,
            "project": {"name": project}, "team": {"id": "team-fixture"},
            "labels": {"nodes": [{"id": "lab-sana", "name": "owner:sana"}]}}


def pr(branch, status, n):
    return {"url": "https://github.com/x/kipi-system/pull/%d" % n,
            "metadata": {"status": status, "branch": branch, "number": n}}


BOARD = {i["identifier"]: i for i in [
    issue("ASK-951", "started", 24 * 30),   # 1: abandoned 30 days, the ASK-2058 shape
    issue("ASK-952", "started", 1),         # 2: THE TRAP, a lane moved it an hour ago
    issue("ASK-953", "started", 24 * 30),   # 3: open PR on a lane branch
    issue("ASK-954", "started", 24 * 30),   # 4: open PR on the worker branch, still held
    issue("ASK-955", "started", 24 * 30),   # 5: a live claim on its worker tree
    issue("ASK-956", "started", 24 * 30),   # 6: a claim whose holder is dead
    issue("ASK-957", "started", 24 * 30),   # 7: a merged PR on a lane branch
    issue("ASK-958", "backlog"),            # control: the ordinary queue
    issue("ASK-959", "completed", 24 * 30), # control: done is never work
    issue("ASK-960", "started", 24 * 30),   # 8: its PRs cannot be read
    issue("ASK-961", "started", None),      # 8b: no startedAt at all
    issue("ASK-971", "started", 24 * 30),   # apply: run fails rc=1
    issue("ASK-972", "started", 24 * 30),   # apply: run exits 0 with no PR
    issue("ASK-973", "started", 24 * 30),   # apply: run refuses, parked needs-scope
]}
ATTACH = {
    "uuid-ASK-953": [pr("sana/ask-953-lane", "open", 953)],
    "uuid-ASK-954": [pr("sana/ask-954", "open", 954)],
    "uuid-ASK-957": [pr("sana/ask-957-lane", "merged", 957)],
}
LABELS = {"owner:sana": "lab-sana"}


def log(rec):
    with open(LOG, "a") as fh:
        fh.write(json.dumps(rec) + "\n")


def find(ref):
    for i in BOARD.values():
        if ref in (i["id"], i["identifier"]):
            return i
    return None


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, payload):
        out = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode())
        q, v = req.get("query", ""), req.get("variables") or {}
        if q.lstrip().startswith("mutation"):
            inp = v.get("input") or {}
            if "issueUpdate" in q:
                i = find(v.get("id"))
                if i and "stateId" in inp:
                    t = BY_ID[inp["stateId"]]
                    i["state"] = {"name": NAMES[t], "type": t}
                    log({"op": "state", "issue": i["identifier"], "to": t})
                if i and "labelIds" in inp:
                    names = [n for n, lid in LABELS.items() if lid in inp["labelIds"]]
                    i["labels"]["nodes"] = [{"id": LABELS[n], "name": n} for n in names]
                    log({"op": "labels", "issue": i["identifier"], "to": names})
                return self.reply({"data": {"issueUpdate": {"success": bool(i),
                                   "issue": {"id": "x", "identifier": "x"}}}})
            if "commentCreate" in q:
                i = find(inp.get("issueId"))
                log({"op": "comment", "issue": i["identifier"] if i else "?",
                     "body": inp.get("body", "")})
                return self.reply({"data": {"commentCreate": {"success": True,
                                   "comment": {"id": "c1"}}}})
            if "issueLabelCreate" in q:
                LABELS[inp["name"]] = "lab-" + inp["name"]
                return self.reply({"data": {"issueLabelCreate": {"success": True,
                                   "issueLabel": {"id": LABELS[inp["name"]], "name": inp["name"]}}}})
            return self.reply({"errors": [{"message": "fixture: unknown mutation"}]})
        if "teams(" in q:
            return self.reply({"data": {"teams": {"nodes": [{"id": "team-fixture", "key": "ASK"}]}}})
        if "attachments(" in q:
            if v.get("id") == "uuid-ASK-960":
                return self.reply({"errors": [{"message": "fixture: attachments unavailable"}]})
            return self.reply({"data": {"issue": {"attachments": {"nodes": ATTACH.get(v.get("id"), [])}}}})
        if "issues(filter" in q:
            return self.reply({"data": {"issues": {"nodes": list(BOARD.values()),
                               "pageInfo": {"hasNextPage": False, "endCursor": None}}}})
        if "states(first" in q:
            return self.reply({"data": {"team": {"states": {"nodes": [
                {"id": sid, "name": NAMES[t], "type": t, "position": n}
                for n, (t, sid) in enumerate(STATE_IDS.items())]}}}})
        if "labels(first" in q:
            return self.reply({"data": {"team": {"labels": {"nodes": [
                {"id": lid, "name": n} for n, lid in LABELS.items()]}}}})
        if "issue(id" in q:
            i = find(v.get("id"))
            if i is None:
                return self.reply({"errors": [{"message": "Entity not found: Issue"}]})
            node = dict(i)
            node["comments"] = {"nodes": []}
            return self.reply({"data": {"issue": node}})
        return self.reply({"errors": [{"message": "fixture: unknown query"}]})


srv = HTTPServer(("127.0.0.1", 0), H)
print(srv.server_port, flush=True)
srv.serve_forever()
PY
FIXLOG="$WORK/linear-writes.jsonl"; : > "$FIXLOG"
FIXTURE_LOG="$FIXLOG" python3 "$WORK/fixture-server.py" > "$WORK/port" 2> "$WORK/server.err" &
SRV_PID=$!
for _ in $(seq 1 100); do PORT="$(cat "$WORK/port" 2>/dev/null)"; [ -n "${PORT:-}" ] && break; sleep 0.1; done
[ -n "${PORT:-}" ] || { echo "fixture server did not start: $(cat "$WORK/server.err")"; exit 1; }

# --- a real git skeleton, named for its project -------------------------------
# The basename is load-bearing: repo identity comes from it. The tree carries
# its own .claude/settings.json so the agent runs without the skeleton guard
# renderer, which resolves the skeleton from its own path and so cannot render
# from the copied scripts dir the negative runs use (an INFRA skip there made
# the first red run of this suite red for the wrong reason).
make_skel() {
  local parent="$1" skel="$1/kipi-system"
  mkdir -p "$parent"
  git init --quiet --bare "$parent/origin.git" && git -C "$parent/origin.git" symbolic-ref HEAD refs/heads/main
  git init --quiet "$skel"
  git -C "$skel" config user.email t@t; git -C "$skel" config user.name t
  mkdir -p "$skel/.claude"; printf '{}\n' > "$skel/.claude/settings.json"
  : > "$skel/seed"; git -C "$skel" add seed .claude/settings.json; git -C "$skel" commit --quiet -m seed
  git -C "$skel" remote add origin "$parent/origin.git"
  git -C "$skel" push --quiet -u origin HEAD:main 2>/dev/null
  printf '%s' "$skel"
}
SKEL="$(make_skel "$WORK/run")"
STATE="$WORK/state"; mkdir -p "$STATE/worktrees"

# --- the two claims ------------------------------------------------------------
# Written in the shape linear-claim.py writes, at the path the worker claims in.
# The live holder is the fixture server: it runs for the whole suite. The dead
# holder is a process that has already exited and been reaped.
true & DEAD_PID=$!; wait "$DEAD_PID" 2>/dev/null
for pair in "ASK-955:$SRV_PID" "ASK-956:$DEAD_PID"; do
  id="${pair%%:*}"; pid="${pair#*:}"
  dir="$STATE/worktrees/$(printf '%s' "$id" | tr 'A-Z' 'a-z')"; mkdir -p "$dir"
  printf '{"agent":"sana","session":"worker-fixture-%s","issue_id":"%s","holder_pid":%s}\n' \
    "$id" "$id" "$pid" > "$dir/.linear-claims.json"
done

STUBS="$WORK/bin"; mkdir -p "$STUBS"
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUBS/gh"
printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/fake-reviewer.sh"
printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/fake-codex.sh"
printf '#!/usr/bin/env bash\nprintf "NOTIFY %%s\\n" "$*" >> "%s/pages.log"\nexit 0\n' "$WORK" > "$WORK/notify.sh"
chmod +x "$STUBS/gh" "$WORK/fake-reviewer.sh" "$WORK/fake-codex.sh" "$WORK/notify.sh"

run_worker() {  # run_worker <worker-script> <out-file> [worker args...]
  local w="$1" out="$2"; shift 2
  PATH="$STUBS:$PATH" \
    KIPI_SKEL="$SKEL" KIPI_STATE_DIR="$STATE" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
    KIPI_CODEX_RUNNER="bash $WORK/fake-codex.sh" KIPI_SECOND_RUNNER_FALLBACK="" \
    KIPI_USAGE_BREAKER_CMD="true" KIPI_NOTIFY="$WORK/notify.sh" \
    bash "$w" "$@" > "$out" 2>&1
}

echo "== worker state round trip (worker under test: $WORKER)"

# ============================================================================
# THE PICKER, dry. --limit 99: assert on the pool, never on a truncated tail.
# ============================================================================
run_worker "$WORKER" "$WORK/dry.out" --limit 99
DRY="$(cat "$WORK/dry.out")"
picked() { grep -q "\[dry\] would work $1 " <<<"$DRY"; }
held_line="$(grep 'started ticket(s) held' <<<"$DRY")"

# Positive self-test first: the absences below are only real if the picker ran.
if picked ASK-958; then
  ok "self-test: the ordinary Backlog ticket ASK-958 is picked, so the picker ran"
else
  bad "self-test: the picker ran" "no dry line for ASK-958. Output: $(tr '\n' '|' <<<"$DRY" | cut -c1-600)"
fi

if grep -q '\[dry\] would work ASK-951 (attempt 1/3) -- started, no live claim' <<<"$DRY"; then
  ok "case 1: a ticket started 30 days ago with no claim and no PR is picked, reason 'started, no live claim'"
else
  bad "case 1: an abandoned started ticket is picked" \
      "THE DEFECT: no '[dry] would work ASK-951 ... -- started, no live claim'. Output: $(tr '\n' '|' <<<"$DRY" | cut -c1-600)"
fi
# kipi-dispatch.sh reads the next issue with exactly this grep. The reason must
# ride after the id, never break it.
NEXT="$(printf '%s' "$DRY" | grep -oE '\[dry\] would work ASK-[0-9]+' | grep -oE 'ASK-[0-9]+' | grep -c .)"
[ "${NEXT:-0}" -ge 2 ] \
  && ok "case 1b: the dispatcher's own grep still parses every dry line ($NEXT ids)" \
  || bad "case 1b: the dispatcher grep parses the dry lines" "it found $NEXT"

if picked ASK-952; then
  bad "case 2 (THE TRAP): a ticket moved to In Progress 1 hour ago with no claim is NOT picked" \
      "THE DEFECT: ASK-952 was picked; the fleet worker would race a live lane"
else
  ok "case 2 (THE TRAP): a ticket moved to In Progress 1 hour ago with no claim is NOT picked"
fi
grep -q 'ASK-952 (started 1.0h ago, inside the 24h window' <<<"$held_line" \
  && ok "case 2b: the held line names ASK-952 and the 24h window" \
  || bad "case 2b: the held line names the window" "held line: $held_line"

if picked ASK-953; then
  bad "case 3: an open PR on a lane branch holds the ticket" "THE DEFECT: ASK-953 was picked beside a live PR"
else
  ok "case 3: an open PR on a lane branch holds the ticket"
fi
grep -q 'ASK-953 (open PR https://github.com/x/kipi-system/pull/953 on sana/ask-953-lane)' <<<"$held_line" \
  && ok "case 3b: the held line names the PR and its branch" \
  || bad "case 3b: the held line names the PR" "held line: $held_line"

# The worker's own branch holds it too: that PR already has consumers (the
# redrives, converge, auto-merge), and an approved one waiting on CI would
# otherwise be the dispatcher's next issue on every tick.
if picked ASK-954; then
  bad "case 4: an open PR on the worker's own branch holds the ticket" "ASK-954 was picked"
else
  ok "case 4: an open PR on the worker's own branch holds the ticket (the PR pipeline owns it)"
fi
grep -q 'ASK-954 (open PR https://github.com/x/kipi-system/pull/954 on sana/ask-954)' <<<"$held_line" \
  && ok "case 4b: the held line names the worker-branch PR" \
  || bad "case 4b: the held line names the PR" "held line: $held_line"

if picked ASK-955; then
  bad "case 5: a live claim holds the ticket" "THE DEFECT: ASK-955 was picked while its tree is claimed by a live process"
else
  ok "case 5: a live claim on the worker tree holds the ticket"
fi
grep -q 'ASK-955 (a live claim by sana' <<<"$held_line" \
  && ok "case 5b: the held line names the live claim" \
  || bad "case 5b: the held line names the claim" "held line: $held_line"

picked ASK-956 \
  && ok "case 6: a claim whose holder is dead is no claim (linear-claim.py's own liveness rule)" \
  || bad "case 6: a dead holder's claim does not hold" "ASK-956 not picked"

picked ASK-957 \
  && ok "case 7: a MERGED PR on another branch does not hold it" \
  || bad "case 7: a merged PR does not hold" "ASK-957 not picked"

if picked ASK-960 || picked ASK-961; then
  bad "case 8: an unreadable PR list or a missing startedAt holds the ticket (fail closed)" \
      "picked: $(grep -oE 'would work ASK-96[01]' <<<"$DRY" | tr '\n' ' ')"
else
  ok "case 8: an unreadable PR list and a missing startedAt both hold the ticket (fail closed)"
fi
picked ASK-959 && bad "control: a completed ticket is never picked" "ASK-959 picked" \
               || ok "control: a completed ticket is never picked"

grep -q 'started, no live claim (In Progress with nobody on it, back in the pool):.*ASK-951' <<<"$DRY" \
  && ok "the run reports the re-picked started tickets on their own line" \
  || bad "the run reports the re-picked started tickets" "$(grep 'started' <<<"$DRY" | head -3)"

[ ! -s "$FIXLOG" ] \
  && ok "the dry run wrote nothing to Linear" \
  || bad "the dry run wrote nothing to Linear" "writes: $(cat "$FIXLOG")"

# ============================================================================
# THE ROUND TRIP, --apply, one exit per run
# ============================================================================
apply_case() {  # apply_case <issue> <claude-script-body>
  printf '#!/usr/bin/env bash\n%s\n' "$2" > "$STUBS/claude"; chmod +x "$STUBS/claude"
  : > "$FIXLOG"
  run_worker "$WORKER" "$WORK/apply-$1.out" --apply --issue "$1" --limit 1
}
state_writes() { grep -c "\"op\": \"state\", \"issue\": \"$1\", \"to\": \"backlog\"" "$FIXLOG"; }
exit_comment() { grep "\"op\": \"comment\", \"issue\": \"$1\"" "$FIXLOG" | grep 'Back to Backlog' ; }

# --- fail: claude exits non-zero (THE DoR CHECK) --------------------------------
apply_case ASK-971 'echo "boom: the fixture agent failed"; exit 1'
OUT="$(cat "$WORK/apply-ASK-971.out")"
# Positive self-test: every assertion below reads writes, and a run that never
# reached the agent writes none of them for a reason that has nothing to do
# with the exit under test.
grep -q "start ASK-971 " <<<"$OUT" && grep -q "fail ASK-971 rc=1" <<<"$OUT" \
  && ok "apply self-test: ASK-971 really ran and failed rc=1" \
  || bad "apply self-test: ASK-971 ran and failed" "$(tr '\n' '|' <<<"$OUT" | cut -c1-700)"
grep -q "start ASK-971 .* -- started, no live claim" <<<"$OUT" \
  && ok "the start line says why a started ticket was taken" \
  || bad "the start line names the reason" "$(grep 'start ASK-971' <<<"$OUT")"
[ "$(state_writes ASK-971)" = "1" ] \
  && ok "DoR check: a run that exits non-zero moves its ticket to Backlog, exactly once" \
  || bad "DoR check: a failed run moves the ticket to Backlog once" \
         "THE DEFECT: $(state_writes ASK-971) state write(s). Linear writes: $(cat "$FIXLOG")"
C="$(exit_comment ASK-971)"
if [ "$(printf '%s\n' "$C" | grep -c .)" = "1" ] && grep -q 'Exit: fail (claude run failed rc=1, attempt 1 of 3)' <<<"$C"; then
  ok "DoR check: one comment names the exit (fail, rc=1, attempt 1 of 3)"
else
  bad "DoR check: one comment names the exit" "comments: $C"
fi
python3 - "$C" <<'PY' && ok "the exit comment is one line" || bad "the exit comment is one line" "$C"
import json, sys
body = json.loads(sys.argv[1])["body"]
sys.exit(0 if "\n" not in body else 1)
PY

# --- the same ticket again: already Backlog, so nothing more is written ---------
apply_case ASK-971 'echo "boom again"; exit 1'
[ "$(state_writes ASK-971)" = "0" ] && [ -z "$(exit_comment ASK-971)" ] \
  && ok "a second failure on a ticket already in Backlog writes no state and no exit comment" \
  || bad "a repeat exit is a no-op" "writes: $(cat "$FIXLOG")"

# --- fail: exits 0 having opened no PR -----------------------------------------
apply_case ASK-972 'echo "did a little, opened nothing"; exit 0'
[ "$(state_writes ASK-972)" = "1" ] && grep -q 'Exit: fail (run exited 0 and opened no PR' <<<"$(exit_comment ASK-972)" \
  && ok "a run that exits 0 with no PR is a non-success exit: Backlog, exit named" \
  || bad "a no-PR run goes back to Backlog" "writes: $(cat "$FIXLOG")"

# --- park: the agent refuses the spec -------------------------------------------
apply_case ASK-973 'printf "the spec names no file" > .sana-needs-scope; exit 0'
if [ "$(state_writes ASK-973)" = "1" ] && grep -q 'Exit: park (refused on scope, labelled needs-scope)' <<<"$(exit_comment ASK-973)"; then
  ok "a parked run (needs-scope) goes back to Backlog with the exit named"
else
  bad "a parked run goes back to Backlog" "writes: $(cat "$FIXLOG") out: $(grep ASK-973 "$WORK/apply-ASK-973.out" | tail -4 | tr '\n' '|')"
fi

# --- dry never writes, even on an exit path -------------------------------------
: > "$FIXLOG"
run_worker "$WORKER" "$WORK/dry2.out" --issue ASK-951 --limit 1
[ ! -s "$FIXLOG" ] && ok "a dry run on a started ticket writes nothing" \
                   || bad "a dry run writes nothing" "$(cat "$FIXLOG")"

# ============================================================================
# 9. NEGATIVE SELF-TESTS: the picker cases above can fail
# ============================================================================
MUT="$WORK/mut/scripts"; mkdir -p "$WORK/mut"
cp -R "$REPO_SCRIPTS" "$MUT"
dry_with() {  # dry_with <scripts-dir> -> dry output
  run_worker "$1/linear-worker.sh" "$WORK/mut.out" --limit 99; cat "$WORK/mut.out"
}

# 9a. the picker without the started rule: the pre-ASK-3825 state filter.
python3 - "$MUT/linear-worker.sh" <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
old = 'return i["state"]["type"] == "started" and'
assert old in s, "mutation anchor missing"
open(p, "w").write(s.replace(old, 'return False and'))
PY
M="$(dry_with "$MUT")"
if grep -q '\[dry\] would work ASK-958 ' <<<"$M" && ! grep -q '\[dry\] would work ASK-951 ' <<<"$M"; then
  ok "mutant killed: without the started rule ASK-951 is invisible again, so case 1 can go red"
else
  bad "mutant 9a survived" "case 1 cannot tell the old picker from the new one: $(grep -c 'would work' <<<"$M") dry lines"
fi
cp "$REPO_SCRIPTS/linear-worker.sh" "$MUT/linear-worker.sh"

# 9b. the window removed: the trap case must go red.
python3 - "$MUT/linear-sync.py" <<'PY'
import sys
p = sys.argv[1]; s = open(p).read()
assert "STARTED_STALE_HOURS = 24" in s, "mutation anchor missing"
open(p, "w").write(s.replace("STARTED_STALE_HOURS = 24", "STARTED_STALE_HOURS = 0"))
PY
M="$(dry_with "$MUT")"
grep -q '\[dry\] would work ASK-952 ' <<<"$M" \
  && ok "mutant killed: with no window the hour-old lane ticket ASK-952 is picked, so case 2 can go red" \
  || bad "mutant 9b survived" "case 2 cannot tell a window from none"

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: a started ticket nobody works is picked again, a lane ticket is not, and a failed run returns its ticket to Backlog"
