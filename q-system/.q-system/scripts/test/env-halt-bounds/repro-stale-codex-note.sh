#!/usr/bin/env bash
# PR #421 round 11, minor. codex_outage_noted was cleared only when Codex
# answered for the issue, so an issue noted in an OLD Codex outage kept the mark
# through healthy Sana runs, and any later, unrelated Codex outage held it for
# up to a day with no run. Tick 1: the old outage is over (no claim) and Sana
# runs the issue normally. Tick 2: another issue's fresh Codex outage claim is
# live. The issue must still run: its note belonged to an outage that ended.
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
cat > "$STUB/claude" <<'SH'
#!/usr/bin/env bash
echo SANA-RUN >> "${TEST_SANA_LOG:-/dev/null}"
if [ "${TEST_CLAUDE_MODE:-}" = "healthy" ]; then echo "done, nothing to change"; exit 0; fi
printf '%s' "the harness refused the sensitive path .claude/settings.json" > .sana-blocked-capability
printf 'Not equipped for this one; wrote the capability sentinel.\n'
exit 0
SH
chmod +x "$STUB/claude"
cat > "$WORK/quota-codex.sh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "You've hit your weekly limit - resets Sep 22 at 2pm (America/Los_Angeles)"
exit 0
SH

mkrepo() { mkdir -p "$1"; git init --quiet --bare "$1/origin.git"; git init --quiet "$1/kipi-system"
  git -C "$1/kipi-system" config user.email t@t; git -C "$1/kipi-system" config user.name t
  : > "$1/kipi-system/seed"; git -C "$1/kipi-system" add seed
  git -C "$1/kipi-system" commit --quiet -m seed
  git -C "$1/kipi-system" remote add origin "$1/origin.git"
  git -C "$1/kipi-system" push --quiet -u origin HEAD:main 2>/dev/null; }

STATE="$WORK/state"; NOTIFY_LOG="$WORK/notify.log"; : > "$NOTIFY_LOG"
mkdir -p "$STATE"
printf '{"ASK-811": {"codex_outage_noted": true}}\n' > "$STATE/linear-worker-attempts.json"
# PR #421 round 14, minor: a DRY run (no --apply) must not write the ledger.
# D1: a live claim, so the hold fires; it must not record env_halt.
# D2: no claim, so the note is stale; a dry run must not clear it.
dry() {
  mkrepo "$WORK/t$1"
  PATH="$STUB:$PATH" KIPI_SKEL="$WORK/t$1/kipi-system" KIPI_STATE_DIR="$STATE" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
    KIPI_CODEX_RUNNER="bash $WORK/quota-codex.sh" KIPI_SECOND_RUNNER_FALLBACK="" \
    KIPI_NOTIFY="$WORK/notify.sh" TEST_NOTIFY_LOG="$NOTIFY_LOG" TEST_SANA_LOG="$WORK/sana.log" \
    bash "$WORKER" --limit 1 > "$WORK/tick$1.out" 2>&1
}
flag() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("ASK-811",{}).get(sys.argv[2],""))' "$STATE/linear-worker-attempts.json" "$1" 2>/dev/null; }
mkdir -p "$STATE/codex-outage/env-alert.claim"
printf 'pid=1 claimed_at=now epoch=%s\n' "$(date +%s)" > "$STATE/codex-outage/env-alert.claim/holder"
dry D1
echo "=== dry run under a live claim wrote env_halt: $( [ -n "$(flag env_halt)" ] && echo yes || echo no)   (expected no)"
mv "$STATE/codex-outage/env-alert.claim" "$WORK/claim-aside"
dry D2
echo "=== dry run with no claim cleared the note: $( [ "$(flag codex_outage_noted)" = "True" ] && echo no || echo yes)   (expected no)"
for TICK in 1 2; do
  if [ "$TICK" = 2 ]; then
    mkdir -p "$STATE/codex-outage/env-alert.claim"
    printf 'pid=1 claimed_at=now epoch=%s\n' "$(date +%s)" > "$STATE/codex-outage/env-alert.claim/holder"
  fi
  mkrepo "$WORK/t$TICK"
  PATH="$STUB:$PATH" KIPI_SKEL="$WORK/t$TICK/kipi-system" KIPI_STATE_DIR="$STATE" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
    KIPI_CODEX_RUNNER="bash $WORK/quota-codex.sh" KIPI_SECOND_RUNNER_FALLBACK="" \
    KIPI_NOTIFY="$WORK/notify.sh" TEST_NOTIFY_LOG="$NOTIFY_LOG" TEST_SANA_LOG="$WORK/sana.log" \
    TEST_CLAUDE_MODE=healthy \
    bash "$WORKER" --apply --limit 1 > "$WORK/tick$TICK.out" 2>&1
  echo "tick $TICK rc=$? sana-runs-so-far=$(grep -c SANA-RUN "$WORK/sana.log" 2>/dev/null || echo 0)"
done
echo "=== Sana runs across a healthy tick and a tick during an unrelated Codex outage: $(grep -c SANA-RUN "$WORK/sana.log" 2>/dev/null || echo 0)   (expected 2)"
