#!/usr/bin/env bash
# PR #421 round 8, two majors, both on the Codex branch.
#
# A. A REAL Codex outage was never read as one. `codex exec` prints a banner, the
#    echoed prompt and hook lines before its "ERROR: ..." line, so the every-line
#    rule could not match, and the issue was parked blocked:capability for a
#    condition of the machine. 17 real runs in the worker log went this way.
#    The Codex stub here prints a real transcript from the fixture and exits 1,
#    the rc the worker logged for every one of them.
# B. The Codex page claim is released only when Codex answers, and Codex is
#    reached only on a rare capability refusal. A claim from an outage long over
#    stayed held and the next outage paged nobody. The claim now expires.
# C. The dedupe that remains: a FRESH claim still suppresses a second page, and
#    the "Not parked" note is per issue, so an issue the earlier outage never
#    touched still gets its note.
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
# Codex prints a REAL outage transcript (fixture run ASK-1126) and exits 1.
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

mkrepo() { mkdir -p "$1"; git init --quiet --bare "$1/origin.git"; git init --quiet "$1/kipi-system"
  git -C "$1/kipi-system" config user.email t@t; git -C "$1/kipi-system" config user.name t
  : > "$1/kipi-system/seed"; git -C "$1/kipi-system" add seed
  git -C "$1/kipi-system" commit --quiet -m seed
  git -C "$1/kipi-system" remote add origin "$1/origin.git"
  git -C "$1/kipi-system" push --quiet -u origin HEAD:main 2>/dev/null; }

# plant_claim <state> <epoch>: an earlier run of the fleet already paged a
# Codex outage and holds the claim, claimed at <epoch>.
plant_claim() {
  mkdir -p "$1/codex-outage/env-alert.claim"
  printf 'pid=1 claimed_at=earlier epoch=%s\n' "$2" > "$1/codex-outage/env-alert.claim/holder"
}

scenario() {  # scenario <name> [plant-epoch]
  local name="$1" st="$WORK/state-$1"; mkdir -p "$st"
  [ -n "${2:-}" ] && plant_claim "$st" "$2"
  : > "$WORK/comments.log"; : > "$WORK/notify-$name.log"
  mkrepo "$WORK/t-$name"
  PATH="$STUB:$PATH" KIPI_SKEL="$WORK/t-$name/kipi-system" KIPI_STATE_DIR="$st" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
    KIPI_CODEX_RUNNER="bash $WORK/real-codex.sh" \
    KIPI_NOTIFY="$WORK/notify.sh" TEST_NOTIFY_LOG="$WORK/notify-$name.log" \
    bash "$WORKER" --apply --limit 1 > "$WORK/run-$name.out" 2>&1
  local rc=$?
  # The mark converge.sh reads first (PR #421 round 13): without env_halt it
  # read refused_no_pr, logged a label never applied, and paged exit 7.
  printf '%s env_halt=%s\n' "$name" "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("ASK-811",{}).get("env_halt",""))' "$st/linear-worker-attempts.json" 2>/dev/null)"
  printf '%s rc=%s parked=%s unavailable=%s pages=%s not-parked-notes=%s\n' "$name" "$rc" \
    "$(grep -c 'labelled blocked:capability\|-- parking' "$WORK/run-$name.out")" \
    "$(grep -c 'second runner is unavailable' "$WORK/run-$name.out")" \
    "$(grep -c '^NOTIFY ' "$WORK/notify-$name.log")" \
    "$(grep -c 'Not parked: the second runner was unavailable' "$WORK/comments.log")"
}

NOW="$(date +%s)"
scenario A-real-transcript
scenario B-claim-two-days-old "$((NOW - 172800))"
scenario C-claim-fresh "$NOW"
