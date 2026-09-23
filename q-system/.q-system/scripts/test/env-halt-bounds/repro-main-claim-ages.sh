#!/usr/bin/env bash
# PR #421 round 12, minor. Since round 5 the main outage claim is released only
# by a run that hears the runner answer. After an outage, a queue that stays
# empty (or all skipped) never reaches the runner, so the claim outlived its
# outage and the NEXT outage paged nobody. The claim now ages out after a day,
# like the Codex one. A: a claim two days old, then a new outage: must page.
# B: a claim from minutes ago, same outage: must not.
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
            open(LOG, "a").write(b[:900].replace("\\\\n", " ") + "\n")
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
echo "CLAUDE-INVOKED" >> "${TEST_CLAUDE_LOG:-/dev/null}"
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

STATE="$WORK/state"; mkdir -p "$STATE"
NOTIFY_LOG="$WORK/notify.log"; : > "$NOTIFY_LOG"; : > "$WORK/comments.log"
CLAUDE_LOG="$WORK/claude.log"; : > "$CLAUDE_LOG"
cat > "$STATE/linear-worker-attempts.json" <<'J'
{"ASK-812": {"count": 3, "why": "three honest attempts, a real per-issue failure", "stuck_paged": "1"}}
J

tick() {
  local n="$1"; shift
  mk "$WORK/t$n"
  : > "$CLAUDE_LOG"
  PATH="$STUB:$PATH" KIPI_SKEL="$WORK/t$n/kipi-system" KIPI_STATE_DIR="$STATE" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
    KIPI_CODEX_RUNNER="bash $WORK/fake-codex.sh" \
    KIPI_NOTIFY="$WORK/notify.sh" TEST_NOTIFY_LOG="$NOTIFY_LOG" \
    TEST_CLAUDE_LOG="$CLAUDE_LOG" TEST_CLAUDE_MODE="${MODE:-limit}" \
    bash "$WORKER" --apply --limit 1 "$@" > "$WORK/tick$n.out" 2>&1
  local rc=$?
  printf 'tick %s (worker --apply --limit 1 %s): rc=%s  claude-invocations=%s  outage-claim-after=%s  pages-so-far=%s\n' \
    "$n" "$*" "$rc" "$(grep -c CLAUDE-INVOKED "$CLAUDE_LOG")" \
    "$([ -d "$STATE/env-alert.claim" ] && echo HELD || echo FREE)" \
    "$(grep -c '^NOTIFY ' "$NOTIFY_LOG")"
}

plant() { mkdir -p "$STATE/env-alert.claim"; printf 'pid=1 claimed_at=x epoch=%s\n' "$1" > "$STATE/env-alert.claim/holder"; }
: > "$STATE/linear-worker-attempts.json"; printf '{}\n' > "$STATE/linear-worker-attempts.json"
plant "$(( $(date +%s) - 172800 ))"
tick A
PA="$(grep -c '^NOTIFY ' "$NOTIFY_LOG")"
: > "$NOTIFY_LOG"
plant "$(( $(date +%s) - 120 ))"
tick B
PB="$(grep -c '^NOTIFY ' "$NOTIFY_LOG")"
echo "=== pages for a new outage under a claim two days old: $PA   (expected 1)"
echo "=== pages for the same outage under a claim two minutes old: $PB   (expected 0)"
