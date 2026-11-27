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
import json
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
    issue("ASK-961", "risk-scored auto-merge for low-risk PRs", "2026-08-01T10:00:00.000Z"),
    issue("ASK-962", "usage-pacer.py usage_pct() crashes on TimeoutExpired instead of returning None",
          "2026-08-02T10:00:00.000Z"),
]

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

[ ! -e "$WORK/state/linear-worker-attempts.json" ] || ! grep -q step0_stopped "$WORK/state/linear-worker-attempts.json" \
  && ok "a dry run writes no step 0 flag (dry changes nothing)" \
  || bad "a dry run writes no step 0 flag" "$(cat "$WORK/state/linear-worker-attempts.json")"

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

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" = "0" ]
