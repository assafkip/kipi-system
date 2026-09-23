#!/usr/bin/env bash
# OPUS STANDS IN WHEN CODEX IS DOWN (founder, 2026-09-23: "you dont need codex
# credits, you can use opus as a fallback - that has been recorded"). The
# reviewer already did this; the worker's second runner held the issue instead.
# Codex prints a REAL outage transcript (fixture run ASK-1126) and exits 1; the
# Opus stand-in is a stub run in three modes:
#   commit  -> it does the work: the issue is continued, not held, not parked
#   refuse  -> it writes the capability sentinel: parked with both refusals
#   limit   -> Claude is out too: only then is the issue held as an outage
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
FIX="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/fixtures/worker-env-halt/codex-outages-2026-09-23.json"
python3 - "$FIX" > "$WORK/codex-transcript.txt" <<'PYX'
import json, sys
fx = json.load(open(sys.argv[1]))
r = next(x for x in fx["runs"] if x["issue"] == "ASK-1126" and x["label"] == "outage")
print("\n".join(fx["banner"] + ["You are Codex, the SECOND runner on Linear issue ASK-811."] + r["tail"]))
PYX
cat > "$WORK/real-codex.sh" <<SH
#!/usr/bin/env bash
cat "$WORK/codex-transcript.txt"
exit 1
SH
cat > "$WORK/opus.sh" <<'SH'
#!/usr/bin/env bash
echo "OPUS-INVOKED" >> "$TEST_OPUS_LOG"
case "$TEST_OPUS_MODE" in
  commit) echo "fallback work" > opus-did-this.txt; git add opus-did-this.txt; git -c user.email=t@t -c user.name=t commit -qm "opus stand-in"; echo "Done." ;;
  refuse) printf '%s' "the harness refused the sensitive path .claude/settings.json" > .codex-blocked-capability; echo "Not equipped either." ;;
  limit)  echo "You've hit your weekly limit · resets Sep 29 at 2pm (America/Los_Angeles)" ;;
esac
exit 0
SH

mkrepo() { mkdir -p "$1"; git init --quiet --bare "$1/origin.git"; git init --quiet "$1/kipi-system"
  git -C "$1/kipi-system" config user.email t@t; git -C "$1/kipi-system" config user.name t
  : > "$1/kipi-system/seed"; git -C "$1/kipi-system" add seed
  git -C "$1/kipi-system" commit --quiet -m seed
  git -C "$1/kipi-system" remote add origin "$1/origin.git"
  git -C "$1/kipi-system" push --quiet -u origin HEAD:main 2>/dev/null; }

scenario() {  # scenario <mode>
  local mode="$1" st="$WORK/state-$1"; mkdir -p "$st"
  : > "$WORK/comments.log"; : > "$WORK/opus-$mode.log"
  mkrepo "$WORK/t-$mode"
  PATH="$STUB:$PATH" KIPI_SKEL="$WORK/t-$mode/kipi-system" KIPI_STATE_DIR="$st" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
    KIPI_CODEX_RUNNER="bash $WORK/real-codex.sh" \
    KIPI_SECOND_RUNNER_FALLBACK="bash $WORK/opus.sh" TEST_OPUS_MODE="$mode" TEST_OPUS_LOG="$WORK/opus-$mode.log" \
    KIPI_NOTIFY="$WORK/notify.sh" TEST_NOTIFY_LOG="$WORK/notify-$mode.log" \
    bash "$WORKER" --apply --limit 1 > "$WORK/run-$mode.out" 2>&1
  cnt() { local n; n="$(grep -c "$1" "$2" 2>/dev/null)"; printf '%s' "${n:-0}"; }
  printf '%s opus-calls=%s continued=%s parked=%s held=%s\n' "$mode" \
    "$(cnt OPUS-INVOKED "$WORK/opus-$mode.log")" \
    "$(cnt 'CONTINUED the work' "$WORK/run-$mode.out")" \
    "$(cnt 'labelled blocked:capability\|-- parking' "$WORK/run-$mode.out")" \
    "$(cnt 'second runner is unavailable' "$WORK/run-$mode.out")"
}
scenario commit
scenario refuse
scenario limit
