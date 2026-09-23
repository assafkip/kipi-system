#!/usr/bin/env bash
# REPRO: a CODEX outage dedupes its PAGE but not its per-issue Linear COMMENT.
# Same shape as the round-1 Sana finding, on the Codex branch added in round 2.
# 3 ticks of one Codex outage -> how many "Not parked: the second runner" comments?
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd)"
WORKER="$ROOT/q-system/.q-system/scripts/linear-worker.sh"

WORK="$(mktemp -d)"
cleanup() { kill "${SRV_PID:-}" 2>/dev/null; /bin/rm -rf "$WORK"; }
trap cleanup EXIT

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
BOARD = [mk("ASK-811")]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        b = self.rfile.read(int(self.headers["Content-Length"])).decode()
        if "commentCreate" in b:
            open(LOG, "a").write(b[:400].replace("\\\\n", " ") + "\n")
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
cat > "$WORK/notify.sh" <<'SH'
#!/usr/bin/env bash
printf 'NOTIFY %s\n' "$*" >> "${TEST_NOTIFY_LOG:-/dev/null}"
exit 0
SH
chmod +x "$WORK/notify.sh"

STUB="$WORK/stub"; mkdir -p "$STUB"; cp "$WORK/gh" "$STUB/gh"
# Sana refuses on capability (healthy runner, honest refusal) -> Codex is reached.
cat > "$STUB/claude" <<'SH'
#!/usr/bin/env bash
printf '%s' "the harness refused the sensitive path .claude/settings.json" > .sana-blocked-capability
printf 'Not equipped for this one; wrote the capability sentinel.\n'
exit 0
SH
chmod +x "$STUB/claude"
# Codex is the one that is out of quota.
cat > "$WORK/quota-codex.sh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "You've hit your weekly limit · resets Sep 22 at 2pm (America/Los_Angeles)"
exit 0
SH

mkrepo() { mkdir -p "$1"; git init --quiet --bare "$1/origin.git"; git init --quiet "$1/kipi-system"
  git -C "$1/kipi-system" config user.email t@t; git -C "$1/kipi-system" config user.name t
  : > "$1/kipi-system/seed"; git -C "$1/kipi-system" add seed
  git -C "$1/kipi-system" commit --quiet -m seed
  git -C "$1/kipi-system" remote add origin "$1/origin.git"
  git -C "$1/kipi-system" push --quiet -u origin HEAD:main 2>/dev/null; }

STATE="$WORK/state"; NOTIFY_LOG="$WORK/notify.log"; : > "$NOTIFY_LOG"
for TICK in 1 2 3; do
  mkrepo "$WORK/t$TICK"
  PATH="$STUB:$PATH" KIPI_SKEL="$WORK/t$TICK/kipi-system" KIPI_STATE_DIR="$STATE" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
    KIPI_CODEX_RUNNER="bash $WORK/quota-codex.sh" \
    KIPI_NOTIFY="$WORK/notify.sh" TEST_NOTIFY_LOG="$NOTIFY_LOG" \
    bash "$WORKER" --apply --limit 1 > "$WORK/tick$TICK.out" 2>&1
  echo "=== tick $TICK rc=$? ==="
  grep -i 'second runner is unavailable' "$WORK/tick$TICK.out" | sed 's/^/  /'
done
echo
printf -- '--- pages fired across 3 ticks of ONE Codex outage (deduped): '
grep -c '^NOTIFY ' "$NOTIFY_LOG" 2>/dev/null || echo 0
printf -- "--- commentCreate calls carrying 'Not parked: the second runner was unavailable': "
grep -c 'Not parked: the second runner was unavailable' "$WORK/comments.log" 2>/dev/null || echo 0

echo
printf -- '--- commentCreate calls carrying "Picked up by the autonomous worker": '
grep -c 'Picked up by the autonomous worker' "$WORK/comments.log" 2>/dev/null || echo 0
echo '--- the pickup comments themselves:'
grep -o 'Picked up by the autonomous worker[^"]*' "$WORK/comments.log" | sed 's/^/    /'
