#!/usr/bin/env bash
# Reproducer + regression suite for the worker's READY filter (ASK-275).
#
# WHAT IT PROVES, AND WHY IT IS SHAPED THIS WAY
# ---------------------------------------------
# It drives the REAL linear-worker.sh picker -- the `python3 -` heredoc at
# linear-worker.sh:210 -- against a fixture Linear server, through the transport
# seam linear-sync.py:323 already exposes (KIPI_LINEAR_API_URL). It does NOT
# hand-feed a pool to a copy of ready().
#
# That distinction is the whole point. test-linear-worker-parallel.sh stubs
# `python3` on PATH, which intercepts `python3 -` and therefore REPLACES the
# picker wholesale -- a fixture fed to a stub cannot observe anything about
# ready(). The defect this suite exists for lived inside that stubbed-out block
# and was invisible to the entire suite for as long as it existed.
#
# The producer half of the contract (that Linear really returns project.name for
# every issue) was measured live against the real board on 2026-07-30 before this
# file was written: 29 ready issues, 15 distinct project names, 11 'kipi-system'.
# The GraphQL query at linear-worker.sh:218 already selected project{name}; the
# picker just never read it. So this suite tests a consumer whose producer is
# known-live, per lessons/a-gate-is-only-real-if-production-writes-what-it-reads.
#
# REF HATCH: KIPI_WORKER_UNDER_TEST points the suite at a different copy of
# linear-worker.sh, so the pre-fix worker can be checked out from a git ref and
# watched to FAIL. A regression case added after its own fix has never been
# observed red, and an unobserved-red case is an assertion about nothing.
#
#   git show <pre-fix-ref>:q-system/.q-system/scripts/linear-worker.sh > /tmp/old.sh
#   KIPI_WORKER_UNDER_TEST=/tmp/old.sh bash test-worker-project-scope.sh
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER="${KIPI_WORKER_UNDER_TEST:-$REPO_SCRIPTS/linear-worker.sh}"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT

# --- fixture Linear ---------------------------------------------------------
# Answers the two queries the picker makes. Distinguishes them by body content,
# the same way the real endpoint would route them.
#
# The board mirrors the real one's SHAPE: a mix of in-repo, foreign-project and
# unset-project issues, all otherwise identically ready. Every exclusion below
# is a case the live board actually contains.
cat > "$WORK/fixture-server.py" <<'PY'
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

def issue(ident, project, labels, dor=True, state="backlog"):
    return {
        "id": ident, "identifier": ident, "title": "fixture " + ident,
        "description": "## Definition of Ready\nOutcome: x" if dor else "no readiness heading here",
        "state": {"name": state, "type": state},
        "project": ({"name": project} if project else None),
        "labels": {"nodes": [{"name": n} for n in labels]},
    }

BOARD = [
    # the one that must survive every filter
    issue("ASK-900", "kipi-system", ["owner:sana"]),
    # A: foreign project -- the worker cuts every worktree from SKEL and cannot
    # check this repo out. 18 of 29 live ready issues look like this.
    issue("ASK-901", "accountant", ["owner:sana"]),
    # A: unset project -- target repo unknown, which is not the same as "this one"
    issue("ASK-902", None, ["owner:sana"]),
    # C: Sana already judged this one unexecutable; the label is that judgment
    # made machine-readable so it survives into the next run
    issue("ASK-903", "kipi-system", ["owner:sana", "needs-scope"]),
    # pre-existing rules, kept as regression guards
    issue("ASK-904", "kipi-system", ["owner:assaf", "owner:sana"]),
    issue("ASK-905", "kipi-system", ["owner:sana"], dor=False),
]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        if "teams(" in body:
            data = {"teams": {"nodes": [{"id": "team-fixture"}]}}
        else:
            data = {"issues": {"nodes": BOARD,
                               "pageInfo": {"hasNextPage": False, "endCursor": None}}}
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

# Its stderr goes to a FILE, never to the inherited one. A long-lived child that
# holds the suite's stderr open keeps the whole pipeline's write end open, so a
# caller doing `| tail` hangs forever after the script has already exited -- which
# looked exactly like the worker hanging, and cost a 120s timeout to tell apart.
python3 "$WORK/fixture-server.py" > "$WORK/port" 2> "$WORK/server.err" &
SRV_PID=$!
for _ in $(seq 1 100); do
  PORT="$(cat "$WORK/port" 2>/dev/null)"
  [ -n "${PORT:-}" ] && break
  sleep 0.1
done
[ -n "${PORT:-}" ] || { echo "fixture server did not start: $(cat "$WORK/server.err" 2>/dev/null)"; exit 1; }

# --- a real git repo for SKEL ------------------------------------------------
# The worker fetches origin before it picks (linear-worker.sh:203) and exits 9 if
# that fails, so the picker is unreachable without a real remote. The DIRECTORY
# NAME is load-bearing: repo identity is derived from it.
setup_skel() {
  local name="$1"
  local root="$WORK/$name"
  rm -rf "$root" "$WORK/origin-$name.git"
  git init --quiet --bare "$WORK/origin-$name.git"
  git init --quiet "$root"
  git -C "$root" config user.email t@t; git -C "$root" config user.name t
  : > "$root/seed"; git -C "$root" add seed
  git -C "$root" commit --quiet -m "seed"
  git -C "$root" remote add origin "$WORK/origin-$name.git"
  git -C "$root" push --quiet -u origin HEAD:main 2>/dev/null
  printf '%s' "$root"
}

# --limit 99, ALWAYS. The first version of this suite ran at the default limit of
# 1 and asserted on which issue got worked -- which passed against the UNFIXED
# picker, because the loop breaks after one issue and the three that should have
# been filtered were simply never reached. The budget was doing the filter's job
# and the assertion could not tell the two apart. Assert on the pool, then, not
# on the truncated tail of it: `ready_count` below reads the picker's own number.
run_worker() {  # run_worker <skel-dir> [extra env assignments...]
  local skel="$1"; shift
  env KIPI_SKEL="$skel" \
      KIPI_STATE_DIR="$WORK/state" \
      KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
      KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
      "$@" bash "$WORKER" --limit 99 2>&1
}

ready_count() { printf '%s\n' "$1" | sed -n 's/.*worker: \([0-9]*\) ready issue(s).*/\1/p' | head -1; }

SKEL_KIPI="$(setup_skel kipi-system)"

echo "== worker READY filter (worker under test: $WORKER)"

# --- case 1: only the in-repo, un-rejected, DoR-bearing issue is picked ------
OUT="$(run_worker "$SKEL_KIPI")"
PICKED="$(printf '%s\n' "$OUT" | grep -o 'would work ASK-[0-9]*' | sed 's/would work //' | sort | tr '\n' ' ')"
COUNT="$(ready_count "$OUT")"

# The pool size, asserted separately from the pool contents. This is the number
# that was 4 against the unfixed picker while the contents assertion read clean.
if [ "${COUNT:-x}" = "1" ]; then
  ok "READY pool is 1 (the count the picker reports, not the truncated worklist)"
else
  bad "READY pool is 1" "picker reported '$COUNT' ready"
fi

case "$PICKED" in
  "ASK-900 ") ok "picks only the in-repo issue (ASK-900)" ;;
  *)          bad "picks only the in-repo issue" "picked: [$PICKED] -- expected [ASK-900 ]" ;;
esac

# Each exclusion asserted BY NAME. A single count assertion would pass for the
# wrong reason the moment two bugs cancel out.
for pair in "ASK-901:foreign project (accountant)" \
            "ASK-902:unset project" \
            "ASK-903:needs-scope (Sana already rejected it)" \
            "ASK-904:owner:assaf" \
            "ASK-905:no Definition of Ready"; do
  id="${pair%%:*}"; why="${pair#*:}"
  if printf '%s\n' "$PICKED" | grep -q "$id"; then
    bad "excludes $id -- $why" "it was picked"
  else
    ok "excludes $id -- $why"
  fi
done

# --- case 2: the filter reports what it dropped, it does not drop silently ---
# A queue that quietly shrinks from 29 to 11 is indistinguishable from a broken
# query. The count has to be visible in the run's own output or nobody can tell
# a working filter from an empty board.
if printf '%s\n' "$OUT" | grep -qi "out-of-repo\|other project\|not this repo"; then
  ok "names the out-of-repo issues it dropped"
else
  bad "names the out-of-repo issues it dropped" "no line accounting for the drops in: $(printf '%s' "$OUT" | tr '\n' '|' | cut -c1-300)"
fi

# --- case 3: FAIL LOUD on a repo identity that matches no project -----------
# The dangerous failure mode of this whole change. If the derived name matches
# nothing, ready() returns 0 for every issue and the loop goes permanently quiet
# while reporting a healthy "nothing ready" -- strictly worse than the bug being
# fixed, because a silent queue looks like a finished one.
OUT_BAD="$(run_worker "$SKEL_KIPI" KIPI_LINEAR_PROJECT="no-such-project-anywhere")"
if printf '%s\n' "$OUT_BAD" | grep -qi "MISCONFIG"; then
  ok "fails loud when repo identity matches no Linear project"
else
  bad "fails loud when repo identity matches no Linear project" \
      "expected a MISCONFIG line, got: $(printf '%s' "$OUT_BAD" | tr '\n' '|' | cut -c1-300)"
fi
if printf '%s\n' "$OUT_BAD" | grep -qi "nothing ready"; then
  bad "does NOT report a misconfig as a healthy empty board" "it said 'nothing ready'"
else
  ok "does NOT report a misconfig as a healthy empty board"
fi

# --- case 4: repo identity follows the checkout, not a hardcoded name -------
# The worker runs from other skeletons. A literal "kipi-system" would make every
# other instance's queue empty (or, worse, make this filter a no-op there).
SKEL_OTHER="$(setup_skel accountant)"
OUT_OTHER="$(run_worker "$SKEL_OTHER")"
PICKED_OTHER="$(printf '%s\n' "$OUT_OTHER" | grep -o 'would work ASK-[0-9]*' | sed 's/would work //' | sort | tr '\n' ' ')"
case "$PICKED_OTHER" in
  "ASK-901 ") ok "repo identity derives from the checkout (accountant picks ASK-901)" ;;
  *)          bad "repo identity derives from the checkout" "from accountant/ picked: [$PICKED_OTHER] -- expected [ASK-901 ]" ;;
esac

# --- case 5: NEGATIVE SELF-TEST ---------------------------------------------
# Proves this suite can go red. Without it, every assertion above is compatible
# with a picker that emits nothing at all, or a grep that never matches.
FAKE="$WORK/never-picks.sh"
printf '#!/usr/bin/env bash\necho "worker: 0 ready issue(s)"\necho "nothing ready."\n' > "$FAKE"
NEG="$(KIPI_WORKER_UNDER_TEST="$FAKE" bash "$FAKE" 2>&1)"
if printf '%s\n' "$NEG" | grep -q 'would work ASK-900'; then
  bad "negative self-test" "a worker that picks nothing satisfied the ASK-900 assertion -- the check is inert"
else
  ok "negative self-test: case 1's assertion rejects a worker that picks nothing"
fi

echo
echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
