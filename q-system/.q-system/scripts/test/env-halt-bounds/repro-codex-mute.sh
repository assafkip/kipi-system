#!/usr/bin/env bash
# REPRO: the Codex-outage page claim is released ONLY when Codex CONTINUES work
# (commits). A Codex run that answers and honestly refuses leaves the claim held,
# so the NEXT Codex outage pages nobody.
#
# Three worker runs, one shared $STATE_DIR (the real shape: $STATE_DIR defaults
# to ~/.config/kipi and is shared by every dispatcher process on the machine).
#   run 1: Codex outage            -> expect 1 page
#   run 2: Codex healthy, honest refusal (the run-F fixture, already in the suite)
#   run 3: Codex outage again      -> expect 1 page.  ACTUAL: 0.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd)"
WORKER="$REPO/q-system/.q-system/scripts/linear-worker.sh"
WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null' EXIT

cat > "$WORK/fixture-server.py" <<'PY'
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
def issue(ident):
    return {"id": ident, "identifier": ident, "title": "fixture " + ident,
            "description": "## Definition of Ready\nOutcome: x",
            "state": {"name": "backlog", "type": "backlog"},
            "project": {"name": "kipi-system"},
            "labels": {"nodes": [{"name": "owner:sana"}]}}
BOARD = [issue("ASK-811"), issue("ASK-812"), issue("ASK-813")]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        b = self.rfile.read(int(self.headers["Content-Length"])).decode()
        d = ({"teams": {"nodes": [{"id": "t"}]}} if "teams(" in b else
             {"issues": {"nodes": BOARD,
                         "pageInfo": {"hasNextPage": False, "endCursor": None}}})
        o = json.dumps({"data": d}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(o)))
        self.end_headers()
        self.wfile.write(o)
s = HTTPServer(("127.0.0.1", 0), H)
print(s.server_port, flush=True)
s.serve_forever()
PY
python3 "$WORK/fixture-server.py" > "$WORK/port" 2>/dev/null &
SRV_PID=$!
for _ in $(seq 1 100); do
  PORT="$(cat "$WORK/port" 2>/dev/null)"; [ -n "${PORT:-}" ] && break; sleep 0.1
done

printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/gh"; chmod +x "$WORK/gh"
printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/fake-reviewer.sh"
cat > "$WORK/notify.sh" <<'SH'
#!/usr/bin/env bash
printf 'NOTIFY %s\n' "$*" >> "${TEST_NOTIFY_LOG:-/dev/null}"
exit 0
SH
chmod +x "$WORK/notify.sh"

LIMIT_LINE="You've hit your weekly limit - resets Aug 18 at 2pm (America/Los_Angeles)"

# Sana always refuses on capability, so Codex is always reached (run-E stub).
mkdir -p "$WORK/stub"
cp "$WORK/gh" "$WORK/stub/gh"
cat > "$WORK/stub/claude" <<'SH'
#!/usr/bin/env bash
printf '%s' "the harness refused the sensitive path .claude/settings.json" \
  > .sana-blocked-capability
printf 'Not equipped for this one; wrote the capability sentinel.\n'
exit 0
SH
chmod +x "$WORK/stub/claude"

cat > "$WORK/quota-codex.sh" <<SH
#!/usr/bin/env bash
printf '%s\n' "$LIMIT_LINE"
exit 0
SH
# The suite's OWN run-F fixture: Codex answers and honestly refuses.
cat > "$WORK/refusing-codex.sh" <<'SH'
#!/usr/bin/env bash
printf '%s' "codex has no browser and the DoR needs one" > .codex-blocked-capability
printf 'I am also not equipped for this.\n'
exit 0
SH

make_skel() {
  local parent="$1" skel="$1/kipi-system"
  mkdir -p "$parent"
  git init --quiet --bare "$parent/origin.git"
  git init --quiet "$skel"
  git -C "$skel" config user.email t@t; git -C "$skel" config user.name t
  : > "$skel/seed"; git -C "$skel" add seed; git -C "$skel" commit --quiet -m seed
  git -C "$skel" remote add origin "$parent/origin.git"
  git -C "$skel" push --quiet -u origin HEAD:main 2>/dev/null
  printf '%s' "$skel"
}

STATE="$WORK/state"        # ONE shared state dir for all three runs
mkdir -p "$STATE"

run() {  # run <tag> <issue> <codex-runner>
  local tag="$1" iss="$2" codex="$3"
  local skel; skel="$(make_skel "$WORK/$tag")"
  PATH="$WORK/stub:$PATH" \
    KIPI_SKEL="$skel" KIPI_STATE_DIR="$STATE" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
    KIPI_CODEX_RUNNER="bash $codex" KIPI_SECOND_RUNNER_FALLBACK="" \
    KIPI_NOTIFY="$WORK/notify.sh" \
    TEST_NOTIFY_LOG="$WORK/notify-$tag.log" \
    bash "$WORKER" --apply --limit 1 --issue "$iss" > "$WORK/$tag.out" 2>&1
  local n; n="$(grep -c 'second runner (Codex) is unavailable' "$WORK/notify-$tag.log" 2>/dev/null || echo 0)"
  local saw; saw="$(grep -ci 'second runner is unavailable' "$WORK/$tag.out" "$STATE/linear-worker.log" 2>/dev/null | awk -F: '{s+=$2} END{print s+0}')"
  printf '%-28s codex-outage-detected=%s  PAGES SENT=%s\n' "$tag" "$([ "${saw:-0}" -gt 0 ] && echo yes || echo no)" "$n"
}

run "run1-codex-outage"       ASK-811 "$WORK/quota-codex.sh"
run "run2-codex-honest-refuse" ASK-812 "$WORK/refusing-codex.sh"
echo "  run2 self-check (Codex ANSWERED, honest refusal, issue parked):"
grep -Ei 'ALSO not equipped|labelled blocked:capability' "$WORK/run2-codex-honest-refuse.out" | sed 's/^/    /' | head -3
echo "claim dir after run2: $([ -d "$STATE/codex-outage/env-alert.claim" ] && echo HELD || echo released)"
run "run3-codex-outage-again" ASK-813 "$WORK/quota-codex.sh"
echo "  run3 self-check (a REAL, fresh Codex outage was detected):"
grep -Ei 'second runner is unavailable' "$WORK/run3-codex-outage-again.out" | sed 's/^/    /' | head -2
echo "  run3 notify log lines: $(wc -l < "$WORK/notify-run3-codex-outage-again.log")"
echo
echo "EXPECTED: run1 PAGES=1, run3 PAGES=1 (two distinct outages, two pages)"
echo "workdir: $WORK"
