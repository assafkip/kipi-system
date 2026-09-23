#!/usr/bin/env bash
# PR #421 round 6, major. The halt deduped its page and its "Not attempted"
# comment, but the per-dispatch "Picked up by the autonomous worker. Attempt 1
# of 3." comment is posted BEFORE the runner is reached, so every tick of one
# outage wrote another. Before this PR the attempt charge capped that at 3;
# with the charge gone it was unbounded (5 ticks, 5 comments).
# Kept from the reviewer's reproducer, extended with two ticks where the runner
# ANSWERS so a fix that mutes the note for good cannot pass.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd)"
WORKER="$ROOT/q-system/.q-system/scripts/linear-worker.sh"

WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT

cat > "$WORK/srv.py" <<PY
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
LOG = "$WORK/comments.log"
def mk(i):
    return {"id": i, "identifier": i, "title": "fixture " + i,
            "description": "## Definition of Ready\nOutcome: x",
            "state": {"name": "backlog", "type": "backlog"},
            "project": {"name": "kipi-system"},
            "labels": {"nodes": [{"name": "owner:sana"}]}}
BOARD = [mk("ASK-811"), mk("ASK-812")]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        b = self.rfile.read(int(self.headers["Content-Length"])).decode()
        if "commentCreate" in b:
            open(LOG, "a").write(b[:300].replace("\\\\n", " ") + "\n")
            d = {"commentCreate": {"success": True, "comment": {"id": "c1"}}}
        elif "teams(" in b:
            d = {"teams": {"nodes": [{"id": "t"}]}}
        elif '"id"' in b and "issues(" not in b:
            d = {"issue": BOARD[0]}
        else:
            d = {"issues": {"nodes": BOARD,
                            "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        o = json.dumps({"data": d}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(o))); self.end_headers(); self.wfile.write(o)
s = HTTPServer(("127.0.0.1", 0), H); print(s.server_port, flush=True); s.serve_forever()
PY
python3 "$WORK/srv.py" > "$WORK/port" 2>"$WORK/srv.err" &
SRV_PID=$!
for _ in $(seq 1 100); do PORT="$(cat "$WORK/port" 2>/dev/null)"; [ -n "${PORT:-}" ] && break; sleep 0.1; done

printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/gh"; chmod +x "$WORK/gh"
printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/fake-reviewer.sh"
printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/fake-codex.sh"
cat > "$WORK/notify.sh" <<'SH'
#!/usr/bin/env bash
printf 'NOTIFY %s\n' "$*" >> "${TEST_NOTIFY_LOG:-/dev/null}"
exit 0
SH
chmod +x "$WORK/notify.sh"

STUB="$WORK/stub"; mkdir -p "$STUB"; cp "$WORK/gh" "$STUB/gh"
cat > "$STUB/claude" <<'SH'
#!/usr/bin/env bash
if [ "${TEST_CLAUDE_MODE:-limit}" = "healthy" ]; then echo "looked at it, nothing to change"; exit 0; fi
printf '%s\n' "You've hit your weekly limit · resets Sep 22 at 2pm (America/Los_Angeles)"
exit 0
SH
chmod +x "$STUB/claude"

mk() { mkdir -p "$1"; git init --quiet --bare "$1/origin.git"; git init --quiet "$1/kipi-system"
  git -C "$1/kipi-system" config user.email t@t; git -C "$1/kipi-system" config user.name t
  : > "$1/kipi-system/seed"; git -C "$1/kipi-system" add seed
  git -C "$1/kipi-system" commit --quiet -m seed
  git -C "$1/kipi-system" remote add origin "$1/origin.git"
  git -C "$1/kipi-system" push --quiet -u origin HEAD:main 2>/dev/null; }

STATE="$WORK/state"; NOTIFY_LOG="$WORK/notify.log"; : > "$NOTIFY_LOG"; : > "$WORK/comments.log"
for TICK in 1 2 3 4 5; do
  mk "$WORK/t$TICK"
  PATH="$STUB:$PATH" KIPI_SKEL="$WORK/t$TICK/kipi-system" KIPI_STATE_DIR="$STATE" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
    KIPI_CODEX_RUNNER="bash $WORK/fake-codex.sh" \
    KIPI_NOTIFY="$WORK/notify.sh" TEST_NOTIFY_LOG="$NOTIFY_LOG" \
    bash "$WORKER" --apply --limit 2 > "$WORK/tick$TICK.out" 2>&1
  echo "tick $TICK: worker rc=$?"
done
PICKUPS_OUTAGE="$(grep -c 'Picked up by the autonomous worker' "$WORK/comments.log" 2>/dev/null)"
# The runner is back. Tick 6 runs the attempt whose note is already on the issue
# (no new note); tick 7 is a NEW attempt and must say so.
for TICK in 6 7; do
  mk "$WORK/t$TICK"
  PATH="$STUB:$PATH" KIPI_SKEL="$WORK/t$TICK/kipi-system" KIPI_STATE_DIR="$STATE" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
    KIPI_CODEX_RUNNER="bash $WORK/fake-codex.sh" \
    KIPI_NOTIFY="$WORK/notify.sh" TEST_NOTIFY_LOG="$NOTIFY_LOG" TEST_CLAUDE_MODE=healthy \
    bash "$WORKER" --apply --limit 1 --issue ASK-811 > "$WORK/tick$TICK.out" 2>&1
  echo "tick $TICK (runner answers): worker rc=$?"
done


echo "=== 'Picked up' notes across 5 ticks of ONE outage: $PICKUPS_OUTAGE   (expected 1)"
echo "=== 'Picked up' notes after the runner answered twice: $(grep -c 'Picked up by the autonomous worker' "$WORK/comments.log" 2>/dev/null)   (expected 2)"
echo "--- pages fired across 5 runs (deduped): $(grep -c '^NOTIFY ' "$NOTIFY_LOG" 2>/dev/null || echo 0)"
echo "--- commentCreate calls carrying 'Not attempted' (deduped by env_alert_claim):"
grep -c 'Not attempted' "$WORK/comments.log" 2>/dev/null || echo 0
echo "--- commentCreate calls carrying 'Picked up by the autonomous worker' (NOT deduped):"
grep -c 'Picked up by the autonomous worker' "$WORK/comments.log" 2>/dev/null || echo 0
echo "--- TOTAL commentCreate calls on ASK-811 over 5 ticks of ONE outage:"
grep -c 'commentCreate' "$WORK/comments.log" 2>/dev/null || echo 0
echo "--- bodies:"
grep -o 'Picked up by the autonomous worker[^"]*' "$WORK/comments.log" | head -5
