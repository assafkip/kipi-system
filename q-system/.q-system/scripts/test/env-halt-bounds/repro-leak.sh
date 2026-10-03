#!/usr/bin/env bash
# REPRO: the per-pid marker/run-output files are cleared only for THIS pid.
# A run killed mid-loop (launchd reap, SIGKILL, reboot) leaves its pair behind
# and nothing ever sweeps them.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd)"
WORKER="$ROOT/q-system/.q-system/scripts/linear-worker.sh"
WORK="$(mktemp -d)"; trap 'kill "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT

cat > "$WORK/srv.py" <<'PY'
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        b = self.rfile.read(int(self.headers["Content-Length"])).decode()
        d = ({"teams": {"nodes": [{"id": "t"}]}} if "teams(" in b else
             {"issues": {"nodes": [{"id": "ASK-811", "identifier": "ASK-811",
               "title": "f", "description": "## Definition of Ready\nOutcome: x",
               "state": {"name": "backlog", "type": "backlog"},
               "project": {"name": "kipi-system"},
               "labels": {"nodes": [{"name": "owner:sana"}]}}],
               "pageInfo": {"hasNextPage": False, "endCursor": None}}})
        o = json.dumps({"data": d}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(o))); self.end_headers(); self.wfile.write(o)
s = HTTPServer(("127.0.0.1", 0), H); print(s.server_port, flush=True); s.serve_forever()
PY
python3 "$WORK/srv.py" > "$WORK/port" 2>/dev/null &
SRV_PID=$!
for _ in $(seq 1 100); do PORT="$(cat "$WORK/port" 2>/dev/null)"; [ -n "${PORT:-}" ] && break; sleep 0.1; done

printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/gh"; chmod +x "$WORK/gh"
printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/x.sh"
STUB="$WORK/stub"; mkdir -p "$STUB"; cp "$WORK/gh" "$STUB/gh"
printf '#!/usr/bin/env bash\nprintf "no changes needed\\n"\nexit 0\n' > "$STUB/claude"
chmod +x "$STUB/claude"

STATE="$WORK/state"; mkdir -p "$STATE"
# What a killed previous run leaves behind (pids 99001/99002 are not live here):
: > "$STATE/linear-worker-env-halt.99001"
: > "$STATE/linear-worker-runout.99002"
echo "before: $(ls "$STATE" | grep -c 'env-halt\.\|runout\.') orphan file(s)"

mkdir -p "$WORK/p"; git init --quiet --bare "$WORK/p/origin.git"; git init --quiet "$WORK/p/kipi-system"
git -C "$WORK/p/kipi-system" config user.email t@t; git -C "$WORK/p/kipi-system" config user.name t
: > "$WORK/p/kipi-system/seed"; git -C "$WORK/p/kipi-system" add seed
git -C "$WORK/p/kipi-system" commit --quiet -m seed
git -C "$WORK/p/kipi-system" remote add origin "$WORK/p/origin.git"
git -C "$WORK/p/kipi-system" push --quiet -u origin HEAD:main 2>/dev/null

PATH="$STUB:$PATH" KIPI_SKEL="$WORK/p/kipi-system" KIPI_STATE_DIR="$STATE" \
  KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" KIPI_LINEAR_API_KEY="k" \
  KIPI_PR_REVIEWER="bash $WORK/x.sh" KIPI_CODEX_RUNNER="bash $WORK/x.sh" KIPI_SECOND_RUNNER_FALLBACK="" \
  KIPI_NOTIFY="/usr/bin/true" \
  bash "$WORKER" --apply --limit 1 > "$WORK/out" 2>&1
echo "worker rc=$? (a full healthy run)"
echo "after:  $(ls "$STATE" | grep -c 'env-halt\.\|runout\.') orphan file(s) still present"
ls "$STATE" | grep 'env-halt\.\|runout\.' || echo "  (none)"
