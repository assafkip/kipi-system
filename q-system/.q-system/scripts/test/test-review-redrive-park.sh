#!/usr/bin/env bash
# Pairs with review-redrive.py + park_labels.py (ASK-872): the three labels that
# PARK an issue stop the fresh-pick path in linear-worker.sh and did not stop the
# redrive.
#
# THE DEFECT, measured 2026-08-16:
#   $ grep -n "owner:assaf\|needs-scope\|blocked:capability" review-redrive.py
#   (no output)
# A third consumer dispatching the same agents at the same issues, reading none
# of the vocabulary the other two use to say "not this one".
#
# THE PROPERTY UNDER TEST is the DISCRIMINATION, same posture as
# test-review-redrive.sh: a selector that skips everything passes any test that
# only checks the three parked fixtures, so the fourth fixture -- identical in
# every field except its labels -- must still be offered. Without it the fix
# "skip all PRs" is green.
#
# ISOLATION. The park check reads labels from Linear, so every case here points
# KIPI_LINEAR_API_URL at a fixture HTTP server on 127.0.0.1. No case reaches the
# real board and no case needs a real API key.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
SEL="$REPO_ROOT/q-system/.q-system/scripts/review-redrive.py"
[ -f "$SEL" ] || { echo "FATAL: review-redrive.py not found at $SEL" >&2; exit 1; }
SEL="${REVIEW_REDRIVE_UNDER_TEST:-$SEL}"

WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

RECORDS="$WORK/records"; mkdir -p "$RECORDS"
BIN="$WORK/bin"; mkdir -p "$BIN"

# --- the notify sink, stubbed for every case --------------------------------
# review-redrive escalates from inside `select`. With no stub that is the REAL
# slack-notify.sh: a live data path in a test suite, quiet only because no
# webhook resolves on this machine.
PAGES="$WORK/pages.txt"; : > "$PAGES"
cat > "$BIN/notify.sh" <<EOS
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$PAGES"
EOS
chmod +x "$BIN/notify.sh"

# --- the board, stubbed at the gh seam --------------------------------------
cat > "$BIN/gh" <<'EOS'
#!/usr/bin/env bash
cat "$BOARD"
EOS
chmod +x "$BIN/gh"

# --- fixture Linear: one label set per issue --------------------------------
# The four issues are byte-identical except for `labels`, which is the only
# field the park check may read.
cat > "$WORK/fixture-server.py" <<'PY'
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

LABELS = {
    "ASK-901": ["owner:sana", "owner:assaf"],
    "ASK-902": ["owner:sana", "needs-scope"],
    "ASK-903": ["owner:sana", "blocked:capability"],
    "ASK-904": ["owner:sana"],
}

def issue(ident):
    return {"id": ident, "identifier": ident,
            "labels": {"nodes": [{"name": n} for n in LABELS.get(ident, [])]}}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        req = json.loads(body)
        # The reader asks for a batch of aliased issues. Answer whichever
        # identifiers it named, under the alias it used, so the fixture cannot
        # accidentally teach the reader an ordering it does not have live.
        data = {}
        for alias, ident in _aliases(req.get("query") or ""):
            data[alias] = issue(ident)
        out = json.dumps({"data": data}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out))); self.end_headers()
        self.wfile.write(out)

def _aliases(query):
    # `i0: issue(id: "ASK-901") { ... }` -> ("i0", "ASK-901")
    import re
    return re.findall(r'(\w+)\s*:\s*issue\(\s*id\s*:\s*"([^"]+)"', query)

srv = HTTPServer(("127.0.0.1", 0), H)
print(srv.server_port, flush=True)
srv.serve_forever()
PY
python3 "$WORK/fixture-server.py" > "$WORK/port" 2> "$WORK/server.err" &
SRV_PID=$!
for _ in $(seq 1 100); do PORT="$(cat "$WORK/port" 2>/dev/null)"; [ -n "${PORT:-}" ] && break; sleep 0.1; done
[ -n "${PORT:-}" ] || { echo "fixture server did not start"; cat "$WORK/server.err"; exit 1; }

# A PR entry with a failing reviewer slot. Everything except pr/branch/sha is
# fixed, so a difference in outcome can only come from the issue's labels.
pr_entry() {   # pr_entry <number> <issue-lower> <sha>
  cat <<EOS
{"number": $1, "headRefName": "sana/$2", "headRefOid": "$3",
 "url": "https://example.invalid/pr/$1", "title": "work ($(echo "$2" | tr a-z A-Z))",
 "isDraft": false,
 "statusCheckRollup": [
   {"__typename": "StatusContext", "context": "kipi/reviewer-approved", "state": "FAILURE"},
   {"__typename": "CheckRun", "name": "validate", "status": "COMPLETED", "conclusion": "SUCCESS"}
 ]}
EOS
}

record() {   # record <pr> <issue> <sha>
  python3 - "$RECORDS/pr-$1.verdict.json" "$1" "$2" "$3" <<'PY'
import json, sys
out, pr, issue, sha = sys.argv[1:5]
json.dump({"pr": int(pr), "issue": issue, "verdict": "REQUEST CHANGES",
           "stated": "REQUEST CHANGES", "derived": "", "source": "findings",
           "engine": "codex", "round": 1, "review": "", "usable": True,
           "head_sha": sha, "ts": "now"}, open(out, "w"), indent=2)
PY
}

run_select() {   # run_select [extra env assignments via RR_URL]
  env PATH="$BIN:$PATH" BOARD="$WORK/board.json" KIPI_NOTIFY="$BIN/notify.sh" \
    KIPI_LINEAR_API_URL="${RR_URL:-http://127.0.0.1:$PORT/graphql}" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    python3 "$SEL" --repo-dir "$WORK" --records-dir "$RECORDS" select --all \
    > "$WORK/out.txt" 2> "$WORK/err.txt"
  echo $?
}

echo "== review-redrive park labels =="

printf '[%s,%s,%s,%s]\n' \
  "$(pr_entry 90 ask-901 aaaa1111)" "$(pr_entry 91 ask-902 bbbb2222)" \
  "$(pr_entry 92 ask-903 cccc3333)" "$(pr_entry 93 ask-904 dddd4444)" \
  > "$WORK/board.json"
record 90 ASK-901 aaaa1111
record 91 ASK-902 bbbb2222
record 92 ASK-903 cccc3333
record 93 ASK-904 dddd4444

RC="$(run_select)"
OUT="$(cat "$WORK/out.txt")"
ERR="$(cat "$WORK/err.txt")"

# --- the three parked issues --------------------------------------------------
for pair in "90:owner:assaf" "91:needs-scope" "92:blocked:capability"; do
  PR="${pair%%:*}"; LABEL="${pair#*:}"
  if printf '%s' "$OUT" | awk -F'\t' -v pr="$PR" '$3 == pr {found=1} END {exit !found}'; then
    bad "PR #$PR is parked by $LABEL and was still offered"
  else
    ok "PR #$PR is parked by $LABEL and is not offered"
  fi
  case "$ERR" in
    *"$LABEL"*) ok "the run names $LABEL as what stopped PR #$PR" ;;
    *) bad "nothing in stderr names $LABEL -- a silent skip is the same park, quieter" ;;
  esac
done

# --- the negative fixture: the fix must not be "skip everything" -------------
if printf '%s' "$OUT" | awk -F'\t' -v pr="93" '$3 == pr {found=1} END {exit !found}'; then
  ok "PR #93 carries none of the three and is still offered"
else
  bad "PR #93 carries none of the three and was dropped -- the fix skips everything"
fi

# --- an unreadable board is not an empty one ---------------------------------
# Same posture as GhUnavailable (rc 2): if the park state cannot be read, the
# run must not decide that nothing is parked. It refuses and says so.
#
# 127.0.0.1:1 is chosen over an unroutable address on purpose: a closed port on
# loopback refuses the connection immediately, so this case cannot hang on a
# 30s socket timeout.
RC2="$(RR_URL="http://127.0.0.1:1/graphql" run_select)"
OUT2="$(cat "$WORK/out.txt")"
[ "$RC2" = "2" ] && ok "an unreadable park state exits 2, not 0" \
  || bad "an unreadable park state exited '$RC2' -- the caller reads that as a verdict"
[ -z "$OUT2" ] && ok "an unreadable park state offers nothing" \
  || bad "an unreadable park state still offered: $OUT2"

echo
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
