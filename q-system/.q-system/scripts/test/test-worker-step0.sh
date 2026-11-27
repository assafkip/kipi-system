#!/usr/bin/env bash
# Step 0 in the worker: a ticket for something already built stops before the
# build prompt, a new ticket passes untouched, and a broken check passes loudly
# (ASK-5802).
#
# WHY THIS EXISTS. Founder, 2026-11-26: "chekcing if the ticket should exist
# should be step 0" and "improve_ground.py must be wired to run on its own
# before new scripts or gates get built". Before this, the worker reached the
# build prompt for any ready ticket, including one whose file already exists.
#
# THE SEAM is test-worker-priority-order.sh's: the REAL picker against a fixture
# Linear through KIPI_LINEAR_API_URL, dry runs only. A dry run prints
# `[dry] would work ASK-<n>`, the line kipi-dispatch.sh picks from, and it sits
# AFTER step 0, so a stopped ticket never reaches it and so never reaches the
# build prompt of an --apply run either.
#
# FIXTURES FROM THE PRODUCER: "risk-scored auto-merge for low-risk PRs" is
# improve_ground.py's own already-built case (test_improve_ground.py). The
# lessons corpus is an empty tmp dir, never the live one.
#
# REF HATCH: KIPI_WORKER_UNDER_TEST points at another copy of linear-worker.sh,
# so the pre-fix worker can be watched to FAIL.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER="${KIPI_WORKER_UNDER_TEST:-$REPO_SCRIPTS/linear-worker.sh}"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null; wait "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT

cat > "$WORK/fixture-server.py" <<'PY'
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

def issue(ident, title, created):
    return {"id": ident, "identifier": ident, "title": title,
            "description": "## Definition of Ready\nOutcome: x",
            "state": {"name": "Backlog", "type": "backlog"},
            "startedAt": None, "project": {"name": "kipi-system"},
            "labels": {"nodes": [{"name": "owner:sana"}]},
            "createdAt": created, "priority": 2, "dueDate": None}

# The built one is OLDER, so without step 0 it is the first pick.
BOARD = [
    issue("ASK-961", "add risk-scored auto-merge for low-risk PRs", "2026-08-01T10:00:00.000Z"),
    issue("ASK-962", "usage-pacer.py usage_pct() crashes on TimeoutExpired instead of returning None",
          "2026-08-02T10:00:00.000Z"),
]

# FIXTURE_BOARD=built-only: the --apply case. Step 0 sits before any claim,
# comment or model call, so an --apply run over only the built ticket spends
# nothing and must leave exactly one capout for cap-ladder.py.
if os.environ.get("FIXTURE_BOARD") == "built-only":
    BOARD = BOARD[:1]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        if "teams(" in body:
            data = {"teams": {"nodes": [{"id": "team-fixture"}]}}
        else:
            data = {"issues": {"nodes": BOARD, "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        out = json.dumps({"data": data}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

srv = HTTPServer(("127.0.0.1", 0), H)
print(srv.server_port, flush=True)
srv.serve_forever()
PY

python3 "$WORK/fixture-server.py" > "$WORK/port" 2> "$WORK/server.err" &
SRV_PID=$!
for _ in $(seq 1 100); do
  PORT="$(cat "$WORK/port" 2>/dev/null)"
  [ -n "${PORT:-}" ] && break
  sleep 0.1
done
[ -n "${PORT:-}" ] || { echo "fixture server did not start: $(cat "$WORK/server.err" 2>/dev/null)"; exit 1; }

ROOT="$WORK/kipi-system"
git init --quiet --bare "$WORK/origin.git" && git -C "$WORK/origin.git" symbolic-ref HEAD refs/heads/main
git init --quiet "$ROOT"
git -C "$ROOT" config user.email t@t; git -C "$ROOT" config user.name t
: > "$ROOT/seed"; git -C "$ROOT" add seed; git -C "$ROOT" commit --quiet -m seed
git -C "$ROOT" remote add origin "$WORK/origin.git"
git -C "$ROOT" push --quiet -u origin HEAD:main 2>/dev/null
mkdir -p "$WORK/lessons"
printf 'import sys\nsys.exit(1)\n' > "$WORK/broken.py"
printf 'import time\ntime.sleep(30)\n' > "$WORK/hang.py"

# KIPI_NOTIFY=/usr/bin/true: a suite that can reach slack-notify.sh pages the founder.
run_worker() {  # run_worker <limit> [args]
  env KIPI_SKEL="$ROOT" KIPI_STATE_DIR="$WORK/state" \
      KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
      KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" KIPI_NOTIFY="/usr/bin/true" \
      KIPI_LESSONS_CORPORA="$WORK/lessons" \
      bash "$WORKER" --limit "$@" 2>&1
}
picks() { printf '%s\n' "$1" | grep -o '\[dry\] would work ASK-[0-9]*' | sed 's/.*would work //' | tr '\n' ' '; }

echo "== worker step 0 (worker under test: $WORKER)"

OUT="$(run_worker 5)"
GOT="$(picks "$OUT")"
[ "$GOT" = "ASK-962 " ] \
  && ok "the built ticket never reaches the pick (so never the build prompt); the new one does" \
  || bad "only the new ticket reaches the pick" "got [$GOT], want [ASK-962 ]
     $(printf '%s\n' "$OUT" | grep -E 'step 0|Traceback|Error' | head -3)"
printf '%s\n' "$OUT" | grep -q 'step 0 ASK-961: STOP, already built: q-system/.q-system/scripts/review-tier.py' \
  && ok "the stop line names the file that already does it" \
  || bad "the stop line names review-tier.py" "$(printf '%s\n' "$OUT" | grep -E 'ASK-961' | head -3)"
printf '%s\n' "$OUT" | grep -q 'step 0 ASK-962: pass' \
  && ok "the new ticket's line says it was checked and passed" \
  || bad "the new ticket's line says pass" "$(printf '%s\n' "$OUT" | grep -E 'ASK-962' | head -3)"

GOT1="$(picks "$(run_worker 1)")"
[ "$GOT1" = "ASK-962 " ] \
  && ok "the dispatcher's one pick (--limit 1) moves past the stopped ticket" \
  || bad "the dispatcher's one pick moves past the stopped ticket" "got [$GOT1], want [ASK-962 ]"

[ ! -e "$WORK/state/linear-worker-attempts.json" ] || ! grep -q capout "$WORK/state/linear-worker-attempts.json" \
  && ok "a dry run records no capout for the stopped ticket (dry changes nothing)" \
  || bad "a dry run records no capout" "$(cat "$WORK/state/linear-worker-attempts.json")"
printf '%s\n' "$OUT" | grep -q 'skip ASK-961: stopped at step 0, already built; handed to cap-ladder.py rung 0' \
  && ok "the skip names cap-ladder.py as the next actor" \
  || bad "the skip names its consumer" "$(printf '%s\n' "$OUT" | grep -E 'skip ASK-961' | head -2)"

# --apply over only the built ticket: one capout, naming the file, and a second
# tick leaves the same capout_at (one record, so cap-ladder sees one signature).
kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
FIXTURE_BOARD=built-only python3 "$WORK/fixture-server.py" > "$WORK/port2" 2> "$WORK/server2.err" &
SRV_PID=$!
for _ in $(seq 1 100); do PORT="$(cat "$WORK/port2" 2>/dev/null)"; [ -n "${PORT:-}" ] && break; sleep 0.1; done
# THE CLAUDE SEAM IS A RECORDING STUB HERE, never fleet-claude.sh. Round 2 scar:
# a mutant worker that did not stop went on to a real bounded `claude -p` run
# and sat in run_bounded's 1800 s watchdog. A worker that fails to stop must
# fail this test fast and spend nothing. cap-ladder.py is stubbed the same way:
# the real --issue run writes Linear and the ledger, and test_cap_ladder.py owns it.
printf '#!/bin/sh\necho called >> "%s/claude-called"\nexit 1\n' "$WORK" > "$WORK/claude-stub"
chmod +x "$WORK/claude-stub"
# KIPI_NOTIFY stubbed on every ledger read: attempts-ledger.py can reach slack-notify.sh.
led_get() { KIPI_NOTIFY=/usr/bin/true python3 "$REPO_SCRIPTS/attempts-ledger.py" "$WORK/state/linear-worker-attempts.json" get ASK-961 "$1" "" 2>/dev/null; }
printf '#!/bin/sh\necho "$*" >> "%s/ladder-called"\n' "$WORK" > "$WORK/ladder-stub"
chmod +x "$WORK/ladder-stub"
apply_worker() { KIPI_FLEET_CLAUDE="$WORK/claude-stub" KIPI_CODEX_RUNNER="$WORK/claude-stub" \
  KIPI_CAP_LADDER="$WORK/ladder-stub" run_worker 1 --apply; }
# To a file, not $(...): run_bounded's watchdog `sleep` outlives a killed
# watchdog subshell and holds a captured stdout open for 1800 s (seen under the
# rc mutant, round 2). A plain redirect returns when the worker does.
apply_worker > "$WORK/apply.out" 2>&1
OUTA="$(cat "$WORK/apply.out")"
AT1="$(led_get capout_at)"
WHY="$(led_get capout_why)"
[ -n "$AT1" ] && printf '%s' "$WHY" | grep -q 'step 0: already built: q-system/.q-system/scripts/review-tier.py' \
  && ok "--apply records one capout naming the file, for cap-ladder.py to consume" \
  || bad "--apply records a capout naming the file" "at=[$AT1] why=[$WHY] $(printf '%s\n' "$OUTA" | grep -E 'step 0|WARN|ASK-961' | head -3)"
[ ! -e "$WORK/claude-called" ] \
  && ok "--apply spends nothing on the stopped ticket (the claude seam was never called)" \
  || bad "--apply spends nothing on the stopped ticket" "the claude stub was called $(wc -l < "$WORK/claude-called") time(s)"
grep -qx -- '--issue ASK-961 --apply' "$WORK/ladder-called" 2>/dev/null \
  && ok "--apply hands the stop to cap-ladder.py's own loop (--issue) in the same tick (no wait for 04:40)" \
  || bad "--apply calls cap-ladder.py --issue now" "$(cat "$WORK/ladder-called" 2>/dev/null || echo 'never called')"
sleep 1; apply_worker >/dev/null
AT2="$(led_get capout_at)"
[ -n "$AT1" ] && [ "$AT1" = "$AT2" ] \
  && ok "a second tick leaves the same capout (one signature, not one per tick)" \
  || bad "a second tick leaves the same capout" "first [$AT1] second [$AT2]"
kill "$SRV_PID" 2>/dev/null; wait "$SRV_PID" 2>/dev/null
python3 "$WORK/fixture-server.py" > "$WORK/port3" 2> "$WORK/server3.err" &
SRV_PID=$!
for _ in $(seq 1 100); do PORT="$(cat "$WORK/port3" 2>/dev/null)"; [ -n "${PORT:-}" ] && break; sleep 0.1; done

# Round 2, minor 5: a reopen wins. With step0_canceled on the ticket (cap-ladder
# set it when rung 0 canceled), step 0 stands down and the ticket is picked.
KIPI_NOTIFY=/usr/bin/true python3 "$REPO_SCRIPTS/attempts-ledger.py" "$WORK/state/linear-worker-attempts.json" claim-flag ASK-961 step0_canceled >/dev/null 2>&1
KIPI_NOTIFY=/usr/bin/true python3 "$REPO_SCRIPTS/attempts-ledger.py" "$WORK/state/linear-worker-attempts.json" clear-capout ASK-961 >/dev/null 2>&1
OUTR="$(run_worker 5)"
printf '%s\n' "$OUTR" | grep -q 'step 0 ASK-961: stands down, reopened after a step-0 cancel' \
  && [ "$(picks "$OUTR")" = "ASK-961 ASK-962 " ] \
  && ok "a reopened ticket is not re-stopped: step 0 stands down and it is picked" \
  || bad "a reopened ticket is not re-stopped" "got [$(picks "$OUTR")] $(printf '%s\n' "$OUTR" | grep ASK-961 | head -2)"
KIPI_NOTIFY=/usr/bin/true python3 "$REPO_SCRIPTS/attempts-ledger.py" "$WORK/state/linear-worker-attempts.json" clear-flag ASK-961 step0_canceled >/dev/null 2>&1

for kind in broken hang; do
  OUTB="$(KIPI_STEP0_GROUND="$WORK/$kind.py" KIPI_STEP0_TIMEOUT=1 run_worker 5)"
  GOTB="$(picks "$OUTB")"
  [ "$GOTB" = "ASK-961 ASK-962 " ] \
    && ok "a $kind check holds nothing: both tickets proceed" \
    || bad "a $kind check holds nothing" "got [$GOTB], want [ASK-961 ASK-962 ]"
  printf '%s\n' "$OUTB" | grep -q 'step 0 ASK-961: NOT CHECKED' \
    && ok "a $kind check says NOT CHECKED, never a silent pass" \
    || bad "a $kind check says NOT CHECKED" "$(printf '%s\n' "$OUTB" | grep -E 'ASK-961' | head -3)"
done

# PR #893 round 3, minor 4: step0_canceled expires on a CHECKED pass and only
# then. A NOT CHECKED fail-open keeps it, or a working check would re-cancel a
# reopened ticket. --apply with every spend seam stubbed (claude, cap-ladder).
# LAST in the file: these --apply runs bump ASK-961's attempts, which would
# make every later case see it as STUCK.
KIPI_NOTIFY=/usr/bin/true python3 "$REPO_SCRIPTS/attempts-ledger.py" "$WORK/state/linear-worker-attempts.json" claim-flag ASK-961 step0_canceled >/dev/null 2>&1
printf 'import json\nprint(json.dumps({"verdict": "adopt"}))\n' > "$WORK/adopt.py"
for kind in broken adopt; do
  KIPI_STEP0_GROUND="$WORK/$kind.py" apply_worker > "$WORK/expiry-$kind.out" 2>&1
  eval "FLAG_$kind=\"\$(led_get step0_canceled)\""
done
[ "$FLAG_broken" = "True" ] && [ -z "$FLAG_adopt" ] \
  && ok "step0_canceled survives a NOT CHECKED run and expires on a checked pass" \
  || bad "step0_canceled expires on a checked pass only" "after broken [$FLAG_broken] after adopt [$FLAG_adopt]"

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" = "0" ]
