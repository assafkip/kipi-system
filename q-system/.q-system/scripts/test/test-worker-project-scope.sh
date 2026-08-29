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
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

def issue(ident, project, labels, dor=True, state="backlog", alert=False):
    body = "## Definition of Ready\nOutcome: x" if dor else "no readiness heading here"
    # ASK-839: what alert-to-linear.py stamps into every ticket IT files. The
    # DoR text is deliberately present too -- the defect is precisely an alert
    # ticket the drafter had already made ready-shaped.
    if alert:
        body += "\n\n<!-- kipi-alert-fingerprint: deadbeefdeadbeef -->"
    return {
        "id": ident, "identifier": ident, "title": "fixture " + ident,
        "description": body,
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
    # codex PR #215, minor: founder-routed with NO project set. `in_this_repo`
    # calls unset "not this repo", which is correct for deciding what to WORK and
    # wrong for deciding what to REPORT -- no repo's worker claims it, so under
    # the narrow scope every worker in the fleet stays silent and the issue is
    # invisible everywhere. That is the refilling-queue-looks-like-an-empty-board
    # failure the reversal exists to close, so it must appear on the DEFECT line.
    issue("ASK-912", None, ["owner:assaf"]),
    # codex PR #215 round 4, minor: THE ONLY ISSUE THAT CAN FALSIFY 6e.
    # That case asserted the DEFECT line omits ASK-901 -- which carries
    # owner:sana, so `held_with("owner:assaf", ...)` never selects it no matter
    # how wide founder_scope gets. The assertion could not fail for the reason it
    # was written, which is the whole reason it exists. This one is founder-routed
    # AND sits in another repo's project, so widening founder_scope to every
    # project puts it on the DEFECT line and 6e goes red.
    issue("ASK-913", "accountant", ["owner:assaf"]),
    issue("ASK-905", "kipi-system", ["owner:sana"], dor=False),
    # ASK-841: the HELD counts. held_with() selected on label + project and never
    # looked at state, so a finished issue that still carries its refusal label was
    # counted as held forever. The live board read "2 issue(s) held at
    # blocked:capability (ASK-284 ASK-281)" while ASK-281 was Done.
    # One open + two terminal of each kind, so the expected count (1) cannot be
    # reached by an off-by-one or by dropping the wrong row.
    issue("ASK-906", "kipi-system", ["owner:sana", "blocked:capability"]),
    issue("ASK-907", "kipi-system", ["owner:sana", "blocked:capability"], state="completed"),
    issue("ASK-908", "kipi-system", ["owner:sana", "blocked:capability"], state="canceled"),
    issue("ASK-909", "kipi-system", ["owner:sana", "needs-scope"], state="completed"),
    # ASK-839: a fleet alert ticket the DoR drafter already made ready-shaped,
    # project-unset because the writer never set one. On the live board
    # 2026-08-15 there were 19 of exactly this, and they were 100% of the
    # ready-shaped unset population and 43% of the whole UNREACHABLE bucket.
    issue("ASK-910", None, ["owner:sana"], alert=True),
    # An alert ticket that DOES carry a project. It must still be excluded: the
    # decision is "an alert is not dispatch work", not "an alert is unroutable".
    # Without this case the exclusion could be implemented as a project test and
    # nothing here would notice.
    issue("ASK-911", "kipi-system", ["owner:sana"], alert=True),
]

# THE RECOVERY SEAM. The board is static, and the defect in codex PR #215 round 4
# is only visible ACROSS a change to it: an issue that is founder-routed, then
# recovered, then founder-routed again. A file of ids, re-read on every request,
# is what lets one long-lived server serve three different boards to three worker
# runs. Named ids are stripped of owner:assaf -- exactly what a re-label does --
# so the issue leaves the founder population without leaving the board.
RECOVERED = os.environ.get("FIXTURE_RECOVERED_FILE", "")


def board():
    if not RECOVERED or not os.path.exists(RECOVERED):
        return BOARD
    ids = {ln.strip() for ln in open(RECOVERED) if ln.strip()}
    if not ids:
        return BOARD
    # Deep-copied per request: mutating BOARD in place would make the recovery
    # permanent and the third run below could never see the recurrence.
    out = json.loads(json.dumps(BOARD))
    for i in out:
        if i["identifier"] in ids:
            i["labels"]["nodes"] = [n for n in i["labels"]["nodes"]
                                    if n["name"] != "owner:assaf"]
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        if "teams(" in body:
            data = {"teams": {"nodes": [{"id": "team-fixture"}]}}
        else:
            data = {"issues": {"nodes": board(),
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
# Starts EMPTY, so every case above sees the unmodified board. Only case 6g
# writes to it, and it truncates the file again when it is done.
RECOVER_FILE="$WORK/recovered-ids"
: > "$RECOVER_FILE"
FIXTURE_RECOVERED_FILE="$RECOVER_FILE" \
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
#
# KIPI_NOTIFY is part of the isolation, not a nicety. Case 3 deliberately drives
# the worker into MISCONFIG, and MISCONFIG pages the founder (linear-worker.sh:384).
# Without this line the suite reaches the real slack-notify.sh and rings the
# founder's actual phone on every run -- which it did, twice on 2026-08-01, during
# ASK-281 verification and again under `kipi check`. A test that fires a real
# outbound channel is not isolated no matter how good its assertions are.
# The assertion is unaffected: case 3 greps the worker's own stdout for MISCONFIG,
# and that line is written by $LOG, not by $NOTIFY.
run_worker() {  # run_worker <skel-dir> [extra env assignments...]
  local skel="$1"; shift
  env KIPI_SKEL="$skel" \
      KIPI_STATE_DIR="$WORK/state" \
      KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
      KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
      KIPI_NOTIFY="/usr/bin/true" \
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
            "ASK-905:no Definition of Ready" \
            "ASK-906:blocked:capability" \
            "ASK-907:blocked:capability and completed" \
            "ASK-908:blocked:capability and canceled" \
            "ASK-909:needs-scope and completed" \
            "ASK-910:fleet alert ticket, project-unset (ASK-839)" \
            "ASK-911:fleet alert ticket, project set (ASK-839)"; do
  id="${pair%%:*}"; why="${pair#*:}"
  if printf '%s\n' "$PICKED" | grep -q "$id"; then
    bad "excludes $id -- $why" "it was picked"
  else
    ok "excludes $id -- $why"
  fi
done

# --- case 1b: owner:assaf is an ERROR PATH, and the run says so (ASK-353) -----
# Founder directive 2026-08-03 ("nothing should be on me") reversed the archived
# PRD, which called owner:assaf the one place routing to a person is by design.
# Excluding the issue is NOT the whole behaviour any more and asserting only the
# exclusion above would pass for the old silent filter: that is exactly the
# failure being closed, because a refilling founder queue looked identical to an
# empty board. ASK-904 carries the label and sits in this repo, so a run that
# does not name it as a DEFECT has not implemented the reversal.
if printf '%s\n' "$OUT" | grep -q "DEFECT: owner:assaf"; then
  ok "names owner:assaf as a DEFECT, not a silent exclusion"
else
  bad "names owner:assaf as a DEFECT" \
      "no DEFECT line in the run output (the old silent-filter behaviour)"
fi
if printf '%s\n' "$OUT" | grep "DEFECT: owner:assaf" | grep -q "ASK-904"; then
  ok "names the offending issue (ASK-904) on the DEFECT line"
else
  bad "names the offending issue on the DEFECT line" \
      "the count is there but not the id, so nobody can find what routed it"
fi
# NEGATIVE SELF-TEST. The two assertions above are greps for a string, and a grep
# that can never fail is decoration -- the whole point of this issue is refusing
# checks that cannot go red. ASK-900 is the issue this run PICKED, so it is by
# construction not founder-routed; if the DEFECT line named it, the count is
# reporting the wrong population and the two passes above mean nothing.
if printf '%s\n' "$OUT" | grep "DEFECT: owner:assaf" | grep -q "ASK-900"; then
  bad "negative self-test: the DEFECT line names ONLY founder-routed issues" \
      "it named ASK-900, which was picked and worked"
else
  ok "negative self-test: the DEFECT line names ONLY founder-routed issues"
fi

# --- case 2: the filter reports what it dropped, it does not drop silently ---
# A queue that quietly shrinks from 29 to 11 is indistinguishable from a broken
# query. The count has to be visible in the run's own output or nobody can tell
# a working filter from an empty board.
if printf '%s\n' "$OUT" | grep -qi "out-of-repo\|other project\|not this repo"; then
  ok "names the out-of-repo issues it dropped"
else
  bad "names the out-of-repo issues it dropped" "no line accounting for the drops in: $(printf '%s' "$OUT" | tr '\n' '|' | cut -c1-300)"
fi

# --- case 2b: the HELD counts describe OPEN work only (ASK-841) --------------
# held_with() selected on label + project and never read state, so a Done issue
# still carrying its refusal label was counted as held on every run, forever.
# Measured on the live board 2026-08-15: "2 issue(s) held at blocked:capability
# (ASK-284 ASK-281)" while ASK-281 was Done (completed). The real number was 1.
#
# Why the number matters and not just the label: this count is the ONLY signal
# that the loop is starving on a capability nobody granted (linear-worker.sh:596
# says so at the reporting site). A count that can only rise, because finished
# work never leaves it, cannot report starvation -- it reports the same alarm
# whether or not anything is actually blocked. Hand-clearing the label on the
# closed issue would have made the line read 1 without fixing that.
#
# Asserted on the reported LINE, not on a re-derived pool: the line is what an
# operator reads at 3am, and it is the artifact that was wrong.
CAP_LINE="$(printf '%s\n' "$OUT" | grep 'held at blocked:capability' | head -1)"
case "$CAP_LINE" in
  *"worker: 1 issue(s) held at blocked:capability"*)
    ok "blocked:capability count excludes closed issues (reports 1, not 3)" ;;
  "") bad "blocked:capability count excludes closed issues" "no held-at-blocked:capability line at all in the run output" ;;
  *)  bad "blocked:capability count excludes closed issues" "line reads: $CAP_LINE" ;;
esac

# The ids on that same line, asserted separately. A count of 1 reached by
# counting the WRONG one is still broken, and only the id list can tell.
case "$CAP_LINE" in
  *"(ASK-906)"*) ok "names the open blocked issue (ASK-906) and no closed one" ;;
  *)             bad "names the open blocked issue (ASK-906) and no closed one" "line reads: $CAP_LINE" ;;
esac

# needs-scope goes through the SAME helper, so it carried the same defect. Its
# line has no id list, so this asserts the count only.
SCOPE_LINE="$(printf '%s\n' "$OUT" | grep 'held at needs-scope' | head -1)"
case "$SCOPE_LINE" in
  *"worker: 1 issue(s) held at needs-scope"*)
    ok "needs-scope count excludes closed issues (reports 1, not 2)" ;;
  "") bad "needs-scope count excludes closed issues" "no held-at-needs-scope line at all in the run output" ;;
  *)  bad "needs-scope count excludes closed issues" "line reads: $SCOPE_LINE" ;;
esac

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

# --- case 4b: the registry BEATS basename -----------------------------------
# instance-registry.json maps instance path -> name, and that name is the Linear
# project, while the directory usually is NOT: a registered instance named
# <Persona>_strategy lives at .../projects/strategy, one named for its product
# lives at .../projects/product, one named <Persona>_consultant lives at
# .../consulting. Shipping basename alone would reject every issue on those
# instances. The directory here is deliberately named something that is NOT a
# project, so a pass can only come from the registry being read.
SKEL_REG="$(setup_skel not-a-project-name)"
cat > "$SKEL_REG/instance-registry.json" <<JSON
[{"name": "accountant", "path": "$SKEL_REG", "type": "subtree"}]
JSON
OUT_REG="$(run_worker "$SKEL_REG")"
PICKED_REG="$(printf '%s\n' "$OUT_REG" | grep -o 'would work ASK-[0-9]*' | sed 's/would work //' | sort | tr '\n' ' ')"
case "$PICKED_REG" in
  "ASK-901 ") ok "instance-registry.json name beats the directory basename" ;;
  *)          bad "instance-registry.json name beats the directory basename" \
                  "picked: [$PICKED_REG] -- expected [ASK-901 ]; basename would have MISCONFIGed" ;;
esac

# And the env override still outranks the registry, or an instance whose registry
# entry is wrong has no way out.
OUT_OVR="$(run_worker "$SKEL_REG" KIPI_LINEAR_PROJECT="kipi-system")"
PICKED_OVR="$(printf '%s\n' "$OUT_OVR" | grep -o 'would work ASK-[0-9]*' | sed 's/would work //' | sort | tr '\n' ' ')"
case "$PICKED_OVR" in
  "ASK-900 ") ok "KIPI_LINEAR_PROJECT still outranks the registry" ;;
  *)          bad "KIPI_LINEAR_PROJECT still outranks the registry" "picked: [$PICKED_OVR] -- expected [ASK-900 ]" ;;
esac

# --- case 4c: alert tickets leave the UNREACHABLE bucket too (ASK-839) -------
# Excluding them from ready() alone would be half a fix: they would stop being
# WORKED and keep being COUNTED, so the same 19-issue UNREACHABLE line would run
# every night describing work the loop has already decided it will never take.
# Run against SKEL_REG because it is the only skel here carrying a registry, and
# without one reachability is UNKNOWN and the whole classification collapses.
#
# The expected number is 2, not 0, and that is deliberate. ASK-902 is a genuine
# non-alert unset issue and ASK-900 is a foreign project with no checkout -- both
# are really unreachable and must keep being reported. Only the two alert tickets
# leave. An assertion of 0 would pass for a worker that stopped reporting at all.
OUT_ALERT="$(run_worker "$SKEL_REG")"
UNREACH_N="$(printf '%s\n' "$OUT_ALERT" | sed -n 's/.*worker: \([0-9]*\) ready-shaped issue(s) UNREACHABLE.*/\1/p' | head -1)"
case "${UNREACH_N:-none}" in
  2)    ok "alert tickets leave the UNREACHABLE bucket (2 left, not 4)" ;;
  4)    bad "alert tickets leave the UNREACHABLE bucket" \
            "still 4 -- ASK-910/ASK-911 are counted as unreachable dispatch work" ;;
  none) bad "alert tickets leave the UNREACHABLE bucket" \
            "no UNREACHABLE line at all: $(printf '%s' "$OUT_ALERT" | tr '\n' '|' | cut -c1-300)" ;;
  *)    bad "alert tickets leave the UNREACHABLE bucket" "count reads '$UNREACH_N', expected 2" ;;
esac

# --- case 6: the founder DEFECT page (codex PR #215, major + minor) ---------
# Everything above reads the worker's STDOUT. The page is a different channel and
# has its own failure mode, so it needs its own stub: /usr/bin/true swallows the
# call and proves only that it did not crash. This records every page to a file,
# one line per invocation, so "how many times" becomes an assertion instead of an
# assumption.
# THE FOUNDER CASES RUN AGAINST A SKELETON, NOT AN INSTANCE (codex PR #215
# round 6, major). founder_scope only takes the UNSET population when this
# checkout is the one instance-registry.json declares as `skeleton` -- otherwise
# all 23 workers page about the same unrouted issue into one Linear queue, each
# with its own ledger, so nothing can collapse them. SKEL_KIPI carries no
# registry, which is exactly what an INSTANCE looks like (linear-worker.sh: an
# instance carries no instance-registry.json), so it is the wrong fixture for a
# rule about who owns the unset queue.
#
# Repo identity comes from the registry here, not the basename, so this can live
# in a directory named anything. Only the founder cases use it; every case above
# keeps SKEL_KIPI so their reachability assertions are untouched.
SKEL_SKELETON="$(setup_skel skeleton-checkout)"
python3 - "$SKEL_SKELETON" <<'REGPY'
import json, sys
root = sys.argv[1]
json.dump({
    "skeleton": {"path": root, "linear_project": "kipi-system"},
    "instances": [{"name": "kipi-system", "linear_project": "kipi-system",
                   "path": root}],
}, open(root + "/instance-registry.json", "w"), indent=2)
REGPY

PAGES="$WORK/pages.log"
PAGER="$WORK/recording-notify.sh"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "%s"\n' "$PAGES" > "$PAGER"
chmod +x "$PAGER"

# A state dir of its OWN. The dedup lives in the attempts ledger under
# KIPI_STATE_DIR, and every run above shares one -- reusing it would mean run 1
# here is not actually the first claim, and the test would pass on leftovers.
: > "$PAGES"
P_STATE="$WORK/state-pager"; mkdir -p "$P_STATE"
p_run() {
  env KIPI_SKEL="$SKEL_SKELETON" \
      KIPI_STATE_DIR="$P_STATE" \
      KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
      KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
      KIPI_NOTIFY="$PAGER" \
      bash "$WORKER" --limit 99 2>&1
}

P_OUT1="$(p_run)"; P1="$(wc -l < "$PAGES" | tr -d ' ')"
P_OUT2="$(p_run)"; P2="$(wc -l < "$PAGES" | tr -d ' ')"

# 6a. It must page AT ALL on the first run. Asserted before the dedup, because a
# worker that never pages satisfies "does not repeat" perfectly.
if [ "$P1" -ge 1 ]; then
  ok "the founder DEFECT pages on the first run ($P1 page(s))"
else
  bad "the founder DEFECT pages on the first run" "no page recorded at $PAGES"
fi

# 6b. THE REPRODUCER. The worker ticks every 15 minutes and this alert asks for a
# human relabel, so an unguarded page repeats ~96x/day until he acts -- cry-wolf
# by construction, and a muted channel is the silent board this reversal exists
# to kill, wearing a different coat.
if [ "$P2" = "$P1" ]; then
  ok "REPRODUCER: a second run with the SAME founder queue pages 0 more times (still $P2)"
else
  bad "REPRODUCER: the founder DEFECT page is deduplicated across runs" \
      "run 1 left $P1 page(s), run 2 left $P2 -- it repeats every tick"
fi

# 6c. NEGATIVE SELF-TEST for 6b. A dedup keyed on a state dir is indistinguishable
# from a worker that stopped paging entirely, or from a fixture board that lost
# its owner:assaf issues. A FRESH state dir must page again -- that is the same
# input with only the memory removed, so it isolates the dedup from the detector.
: > "$PAGES"
env KIPI_SKEL="$SKEL_SKELETON" KIPI_STATE_DIR="$WORK/state-pager-fresh" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_NOTIFY="$PAGER" bash "$WORKER" --limit 99 >/dev/null 2>&1
if [ "$(wc -l < "$PAGES" | tr -d ' ')" -ge 1 ]; then
  ok "negative self-test: a fresh state dir pages again -- 6b is the dedup, not a dead detector"
else
  bad "negative self-test: a fresh state dir pages again" \
      "still silent with no ledger, so the 'no repeat' in 6b proves nothing"
fi

# 6d. THE UNSET-PROJECT POPULATION (codex minor). ASK-912 carries owner:assaf with
# no project. Under `in_this_repo` it is neither this repo nor anyone else's, so
# every worker in the fleet stayed silent about it.
if printf '%s\n' "$P_OUT1" | grep "DEFECT: owner:assaf" | grep -q "ASK-912"; then
  ok "the DEFECT line names the unset-project founder issue (ASK-912)"
else
  bad "the DEFECT line names the unset-project founder issue (ASK-912)" \
      "$(printf '%s\n' "$P_OUT1" | grep 'DEFECT: owner:assaf' | head -1)"
fi

# 6e. NEGATIVE SELF-TEST for 6d: widening the scope must not swallow ANOTHER
# repo's issues. If the widened scope reported them, every worker in the fleet
# would page about every other repo's founder queue, which is the same cry-wolf
# failure 6b just fixed.
#
# THE FIXTURE IS THE ASSERTION (codex PR #215 round 4, minor). This case used to
# name ASK-901, which carries owner:sana -- and founder_routed is
# `held_with("owner:assaf", founder_scope)`, so the LABEL filter drops ASK-901
# before founder_scope is ever consulted. Set founder_scope to `return True` and
# the case still passed: it was structurally incapable of observing the widening
# it exists to catch. ASK-913 is the same foreign project (`accountant`) and IS
# founder-routed, so it clears the label filter and the only thing left holding
# it off the DEFECT line is the scope predicate. Verified by mutation before this
# comment was written: `def founder_scope(i): return True` takes this case red and
# leaves 6d green.
if printf '%s\n' "$P_OUT1" | grep "DEFECT: owner:assaf" | grep -q "ASK-913"; then
  bad "negative self-test: the widened scope excludes OTHER repos' projects" \
      "the DEFECT line names ASK-913 (owner:assaf, project=accountant) -- unset was widened to everything"
else
  ok "negative self-test: the widened scope takes unset, not another repo's projects"
fi

# --- 6f. A FAILED SEND MUST NOT CONSUME THE ANNOUNCEMENT (codex round 3) -----
# The dedup flag was claimed BEFORE the send and the send's status was discarded
# by `|| true`. One failed file -- a 20s timeout, a Linear 500, no API key on a
# fresh machine -- marked the issue announced forever, so the next tick read the
# flag and stayed quiet. That is the silent founder queue this whole block exists
# to end, arrived at through the fix for it.
#
# Asserted on the page TEXT, not on a line count: other once-only pages may fire
# in the same run and a count cannot say which alert came back.
FAILPAGER="$WORK/failing-notify.sh"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> "%s"\nexit 1\n' "$PAGES" > "$FAILPAGER"
chmod +x "$FAILPAGER"

F_STATE="$WORK/state-pager-fail"; mkdir -p "$F_STATE"
f_run() {  # f_run <notifier>
  env KIPI_SKEL="$SKEL_SKELETON" \
      KIPI_STATE_DIR="$F_STATE" \
      KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
      KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
      KIPI_NOTIFY="$1" \
      bash "$WORKER" --limit 99 2>&1
}

: > "$PAGES"
F_OUT1="$(f_run "$FAILPAGER")"
if grep -q "owner:assaf" "$PAGES"; then
  ok "a failing notifier is still ATTEMPTED for the founder DEFECT"
else
  bad "a failing notifier is still ATTEMPTED for the founder DEFECT" \
      "nothing reached the notifier at all, so 6f below would pass on a dead detector"
fi

if printf '%s\n' "$F_OUT1" | grep -q "did NOT file"; then
  ok "the run says out loud that the owner:assaf alert did not file"
else
  bad "the run says out loud that the owner:assaf alert did not file" \
      "the notifier exited 1 and the log is silent about it"
fi

# THE REPRODUCER. Same state dir, working notifier. Before the fix the flag was
# already spent and this run said nothing.
: > "$PAGES"
f_run "$PAGER" >/dev/null 2>&1
if grep -q "owner:assaf" "$PAGES"; then
  ok "REPRODUCER: a founder page whose send FAILED is retried on the next run"
else
  bad "REPRODUCER: a founder page whose send FAILED is retried on the next run" \
      "the first run's failed send consumed the dedup flag, so this issue is muted forever"
fi

# NEGATIVE SELF-TEST for the reproducer. The retry above must come from the
# FAILURE, not from a release that fires on every run -- that would be the
# ~96-pages-a-day repeat 6b closed. Third run, notifier now working and the
# second run's send succeeded, so this one is silent.
: > "$PAGES"
f_run "$PAGER" >/dev/null 2>&1
if grep -q "owner:assaf" "$PAGES"; then
  bad "negative self-test: a SUCCESSFUL send still consumes the announcement" \
      "run 3 paged again, so the flag is being released unconditionally -- back to paging every tick"
else
  ok "negative self-test: after a successful send the founder page stays deduplicated"
fi

# --- 6g. A RECURRENCE AFTER RECOVERY MUST PAGE AGAIN (codex PR #215 round 4) -
# The announce flag was claimed on the first page and released on exactly one
# event: a send that FAILED (6f). Recovery released nothing. So an issue that was
# mis-routed, re-labelled, and mis-routed again hit `claim-flag` -> 1 (already
# announced) and the SECOND occurrence was swallowed, permanently, until someone
# hand-edited the ledger. A detector that stops detecting.
#
# 6b and 6f cannot see this. Both assert about the FIRST episode -- that it pages
# once, and that a failed send does not consume the claim. Neither ever changes
# the board, and this defect only exists across a change to it. That is what the
# recovery seam in the fixture server is for.
G_STATE="$WORK/state-recur"; mkdir -p "$G_STATE"
g_run() {
  env KIPI_SKEL="$SKEL_SKELETON" \
      KIPI_STATE_DIR="$G_STATE" \
      KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
      KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
      KIPI_NOTIFY="$PAGER" \
      bash "$WORKER" --limit 99 2>&1
}

# Occurrence 1: ASK-912 is founder-routed and this is a virgin ledger.
: > "$RECOVER_FILE"
: > "$PAGES"
g_run >/dev/null 2>&1
if grep -q "ASK-912" "$PAGES"; then
  ok "6g setup: the first occurrence of ASK-912 pages"
else
  bad "6g setup: the first occurrence of ASK-912 pages" \
      "nothing paged, so everything below would pass on a dead detector"
fi

# Recovery: the fixture strips owner:assaf, which is what a re-label does.
printf 'ASK-912\n' > "$RECOVER_FILE"
: > "$PAGES"
G_OUT2="$(g_run)"
if grep -q "ASK-912" "$PAGES"; then
  bad "6g: recovery itself does not page" \
      "leaving the population produced a page -- that is the re-page-on-departure shape the block rejects"
else
  ok "6g: recovery itself is silent (no page on leaving the population)"
fi
if printf '%s\n' "$G_OUT2" | grep -q "ASK-912 is no longer founder-routed"; then
  ok "6g: the run says out loud that it released ASK-912's announce flag"
else
  bad "6g: the run says out loud that it released ASK-912's announce flag" \
      "no release line -- the sweep did not run, or it did not see the flag"
fi

# THE REPRODUCER. Same ledger, same id, board back to founder-routed. Before the
# fix this run was silent: the flag from occurrence 1 was still held.
: > "$RECOVER_FILE"
: > "$PAGES"
g_run >/dev/null 2>&1
if grep -q "ASK-912" "$PAGES"; then
  ok "REPRODUCER: a SECOND occurrence after recovery pages again"
else
  bad "REPRODUCER: a SECOND occurrence after recovery pages again" \
      "the flag from occurrence 1 was never released, so every later recurrence of ASK-912 is muted"
fi

# NEGATIVE SELF-TEST for the reproducer. The page above must come from the
# RECOVERY, not from a sweep that releases on every tick -- that would be the
# ~96-pages-a-day repeat 6b closed, reintroduced by its own fix. Fourth run,
# board unchanged, so ASK-912 is still in the population and must stay quiet.
: > "$PAGES"
g_run >/dev/null 2>&1
if grep -q "ASK-912" "$PAGES"; then
  bad "negative self-test: the recurrence page comes from recovery, not from an unconditional release" \
      "run 4 paged with no recovery in between -- the sweep is clearing flags for ids still in the population"
else
  ok "negative self-test: with no recovery in between, the founder page stays deduplicated"
fi

# --- 6h. A KILL BETWEEN THE CLAIM AND THE SEND (codex PR #215 round 5) -------
# The claim is written first on purpose: a page whose dedup did not land repeats
# every 15 minutes forever. But that leaves a window. Kill the worker after
# claim-flag and before the notifier returns -- launchd stopping the job, a
# reboot, an OOM -- and the release path never runs, because it only runs when
# the notifier RETURNED non-zero. A kill returns nothing. The flag then stood
# with no ticket behind it, and the 6g sweep could not see it either: the issue
# is still founder-routed, so it never leaves the population.
#
# THE FIXTURE IS THE LEDGER STATE A KILL LEAVES, not a real kill. Killing the
# worker mid-run from inside its own notifier is racy and would make the suite
# flaky for a reason unrelated to the assertion. The post-kill state is exactly
# one fact -- founder-routed claimed, founder-routed-filed absent -- and the
# ledger's own CLI is what writes it, so the fixture cannot drift from what the
# worker would have written.
H_STATE="$WORK/state-killed"; mkdir -p "$H_STATE"
H_LEDGER="$H_STATE/linear-worker-attempts.json"
python3 "$REPO_SCRIPTS/attempts-ledger.py" "$H_LEDGER" claim-flag ASK-912 founder-routed >/dev/null

if python3 "$REPO_SCRIPTS/attempts-ledger.py" "$H_LEDGER" list-flagged founder-routed | grep -q "ASK-912"; then
  ok "6h setup: the post-kill ledger really holds an unfiled claim for ASK-912"
else
  bad "6h setup: the post-kill ledger really holds an unfiled claim for ASK-912" \
      "nothing claimed, so the reproducer below would pass against unfixed code"
fi

: > "$RECOVER_FILE"
: > "$PAGES"
H_OUT="$(env KIPI_SKEL="$SKEL_SKELETON" KIPI_STATE_DIR="$H_STATE" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_NOTIFY="$PAGER" bash "$WORKER" --limit 99 2>&1)"
if printf '%s\n' "$H_OUT" | grep -q "never filed"; then
  ok "6h: the run names ASK-912's claim as announced-but-never-filed"
else
  bad "6h: the run names ASK-912's claim as announced-but-never-filed" \
      "no release line -- an unfiled claim is indistinguishable from a filed one"
fi

# THE REPRODUCER. Second run, same ledger, ASK-912 still founder-routed. Before
# the fix the interrupted claim stood and this issue never paged again.
: > "$PAGES"
env KIPI_SKEL="$SKEL_SKELETON" KIPI_STATE_DIR="$H_STATE" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_NOTIFY="$PAGER" bash "$WORKER" --limit 99 >/dev/null 2>&1
if grep -q "ASK-912" "$PAGES"; then
  ok "REPRODUCER: a claim interrupted before its send pages on the next run"
else
  bad "REPRODUCER: a claim interrupted before its send pages on the next run" \
      "the interrupted claim stood, so ASK-912 is muted until someone hand-clears the ledger"
fi

# NEGATIVE SELF-TEST. The page above must come from the claim being UNFILED, not
# from a release that runs on every tick. The run just above filed one, so this
# one must be silent -- otherwise the fix is the ~96-pages-a-day repeat again.
: > "$PAGES"
env KIPI_SKEL="$SKEL_SKELETON" KIPI_STATE_DIR="$H_STATE" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_NOTIFY="$PAGER" bash "$WORKER" --limit 99 >/dev/null 2>&1
if grep -q "ASK-912" "$PAGES"; then
  bad "negative self-test: a FILED claim still suppresses the next tick" \
      "run 3 paged again, so the unfiled check is releasing every claim -- back to paging every tick"
else
  ok "negative self-test: once the alert has filed, the claim suppresses the next tick"
fi

# --- 6i. ONLY THE SKELETON OWNS THE UNSET QUEUE (codex PR #215 round 6) ------
# 6d widened founder_scope to include unset-project issues so an unrouted one is
# not invisible fleet-wide. Unqualified, that put the SAME issue in all 23
# instances at once: each keeps its own attempts ledger so the per-id dedup
# cannot collapse them, and alert-to-linear cannot either -- measured, two
# workers whose populations differ by one id fingerprint differently (d5547a63
# vs ff6479df). One mislabelled issue, one Linear ticket per instance, all by
# hand to close.
#
# SKEL_KIPI carries no instance-registry.json, which IS what an instance looks
# like. So this run must NOT claim ASK-912.
I_OUT="$(run_worker "$SKEL_KIPI")"
I_DEFECT="$(printf '%s\n' "$I_OUT" | grep 'DEFECT: owner:assaf' | head -1)"
if printf '%s' "$I_DEFECT" | grep -q "ASK-912"; then
  bad "REPRODUCER: an instance does not claim the unset founder queue" \
      "the instance run names ASK-912 -- every worker in the fleet pages about it: $I_DEFECT"
else
  ok "REPRODUCER: an instance (no registry) does not claim the unset founder queue"
fi

# NEGATIVE SELF-TEST. The narrowing must drop the UNSET issue only, never the
# instance own project founder issues -- silencing those would be a worse bug
# than the flood, and an assertion that only checks for absence passes just as
# well against a worker that stopped reporting the DEFECT line at all.
if printf '%s' "$I_DEFECT" | grep -q "ASK-904"; then
  ok "negative self-test: the instance still names its OWN founder-routed issue (ASK-904)"
else
  bad "negative self-test: the instance still names its OWN founder-routed issue (ASK-904)" \
      "the DEFECT line lost ASK-904 too, so 6i passes on a dead detector: $I_DEFECT"
fi

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
