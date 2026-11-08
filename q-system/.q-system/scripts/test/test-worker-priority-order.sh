#!/usr/bin/env bash
# The worker picks by Linear priority, then oldest first (ASK-248, NEW-6 of the
# stuck-work synthesis 2026-11-07).
#
# WHY THIS EXISTS. The picker query had no orderBy and selected no priority, so
# the pool came in Linear's default order. Measured live 2026-11-08 05:45Z: that
# order is NEWEST CREATED FIRST. So the queue was a stack, not a queue: 234
# ready-shaped kipi-system tickets, 39 of them under a week old and picked ahead
# of 119 that were over 60 days old, while the 3 Urgent and 62 High ones waited
# behind fresh Low and unprioritized filings. ASK-248, the ticket that asked for
# this order, was itself parked by triage after 30 days unpicked. A stack starves
# its bottom forever; a queue bounds every wait by its depth.
#
# THE SEAM is test-worker-project-scope.sh's: the REAL linear-worker.sh picker
# against a fixture Linear server through KIPI_LINEAR_API_URL, never a copy of
# the picker. The fixture serves its board newest first, as Linear does, and
# STRIPS priority and createdAt from every node unless the query asks for them,
# because real Linear returns only selected fields. A worker that sorted on a
# field it never requested would pass against a generous fixture and do nothing
# live.
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

def issue(ident, created, priority):
    return {"id": ident, "identifier": ident, "title": "fixture " + ident,
            "description": "## Definition of Ready\nOutcome: x",
            "state": {"name": "Backlog", "type": "backlog"}, "startedAt": None,
            "project": {"name": "kipi-system"},
            "labels": {"nodes": [{"name": "owner:sana"}]},
            "createdAt": created, "priority": priority}

# Linear priority: 1 Urgent, 2 High, 3 Medium, 4 Low, 0 No priority.
# Listed NEWEST FIRST, the order Linear itself returns (measured 2026-11-08).
BOARD = [
    issue("ASK-960", "2026-11-07T10:00:00.000Z", 4),
    issue("ASK-959", "2026-11-06T10:00:00.000Z", 0),
    issue("ASK-958", "2026-11-05T10:00:00.000Z", 3),
    issue("ASK-957", "2026-11-04T10:00:00.000Z", 2),
    issue("ASK-956", "2026-10-01T10:00:00.000Z", 2),
    issue("ASK-955", "2026-09-01T10:00:00.000Z", 1),
    # The OLDEST ticket, and unprioritized. Numeric priority puts 0 first, which
    # is the wrong reading: No priority sorts after Low, whatever its age.
    issue("ASK-954", "2026-08-01T10:00:00.000Z", 0),
]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        if "teams(" in body:
            data = {"teams": {"nodes": [{"id": "team-fixture"}]}}
        else:
            nodes = json.loads(json.dumps(BOARD))
            q = json.loads(body).get("query", "")
            for n in nodes:
                for field in ("priority", "createdAt"):
                    if field not in q:
                        n.pop(field, None)
            data = {"issues": {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}}
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

# stderr to a file: a child holding the suite's stderr keeps a caller's pipe open.
python3 "$WORK/fixture-server.py" > "$WORK/port" 2> "$WORK/server.err" &
SRV_PID=$!
for _ in $(seq 1 100); do
  PORT="$(cat "$WORK/port" 2>/dev/null)"
  [ -n "${PORT:-}" ] && break
  sleep 0.1
done
[ -n "${PORT:-}" ] || { echo "fixture server did not start: $(cat "$WORK/server.err" 2>/dev/null)"; exit 1; }

# The worker fetches origin before it picks, and repo identity is the directory
# name, so SKEL is a real repo called kipi-system with a real bare remote.
ROOT="$WORK/kipi-system"
git init --quiet --bare "$WORK/origin.git" && git -C "$WORK/origin.git" symbolic-ref HEAD refs/heads/main
git init --quiet "$ROOT"
git -C "$ROOT" config user.email t@t; git -C "$ROOT" config user.name t
: > "$ROOT/seed"; git -C "$ROOT" add seed; git -C "$ROOT" commit --quiet -m seed
git -C "$ROOT" remote add origin "$WORK/origin.git"
git -C "$ROOT" push --quiet -u origin HEAD:main 2>/dev/null

# KIPI_NOTIFY=/usr/bin/true: a suite that can reach slack-notify.sh pages the founder.
run_worker() {  # run_worker <limit>
  env KIPI_SKEL="$ROOT" KIPI_STATE_DIR="$WORK/state" \
      KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
      KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" KIPI_NOTIFY="/usr/bin/true" \
      bash "$WORKER" --limit "$1" 2>&1
}
picks() { printf '%s\n' "$1" | grep -o '\[dry\] would work ASK-[0-9]*' | sed 's/.*would work //' | tr '\n' ' '; }

echo "== worker pick order (worker under test: $WORKER)"

WANT="ASK-955 ASK-956 ASK-957 ASK-958 ASK-960 ASK-954 ASK-959 "
OUT="$(run_worker 99)"
GOT="$(picks "$OUT")"
if [ "$GOT" = "$WANT" ]; then
  ok "the pool is worked Urgent, High, Medium, Low, then No priority, oldest first in each"
else
  bad "the pool is worked by priority, then oldest first" "got  [$GOT]
     want [$WANT]
     $(printf '%s\n' "$OUT" | grep -E 'ready issue|Traceback|Error' | head -3)"
fi

# --limit 1 is what the dispatcher runs: it works the FIRST dry pick and no other.
GOT1="$(picks "$(run_worker 1)")"
[ "$GOT1" = "ASK-955 " ] \
  && ok "the dispatcher's one pick is the Urgent ticket, not the newest one" \
  || bad "the dispatcher's one pick is the Urgent ticket" "got [$GOT1], want [ASK-955 ]"

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" = "0" ]
