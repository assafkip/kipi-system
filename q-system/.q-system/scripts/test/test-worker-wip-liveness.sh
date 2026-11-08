#!/usr/bin/env bash
# At the WIP ceiling every worker tick either works an issue, reworks a movable
# PR, or releases ONE unmovable PR through a coded exit (ASK-3866,
# RULE-2026-11-07-A). "Starting nothing" with no action named is the defect.
#
# THE DEFECT, MEASURED 2026-11-07. kipi-system held 9 open sana/ PRs against a
# ceiling of 5, and 1 was movable. After it, 8 PRs no worker round can move
# stay open, so the ceiling holds forever and the worker prints "Starting
# nothing" on every tick and tells no one. No tracked code closed a PR. The
# orchestrator cleared it by hand by closing 5 PRs. Diagnosis:
# q-system/output/rca/rca-worker-wip-deadlock-2026-11-07.md, Q3.
#
# THE FIXTURE IS THAT DAY'S 8 SHAPES (case L1, L2):
#   #543 cap, APPROVE, DIRTY                 -> cap            (close + requeue)
#   #559 cap, REQUEST CHANGES, alert ticket  -> alert          (close + comment)
#   #584 cap, APPROVE at an old head, Done   -> ticket-closed  (close + comment)
#   #606 #609 #614 lanes at the cap, #618 #621 lanes under it -> lane
#
# WHAT IS REAL AND WHAT IS STUBBED. The real linear-worker.sh, linear-sync.py,
# attempts-ledger.py and pr-verdict-lib.sh run against a fixture Linear server
# (KIPI_LINEAR_API_URL) and fixture review records under a scratch
# KIPI_STATE_DIR. Stubbed: gh (fixture answers, every call logged), claude,
# the reviewer, the notifier and the usage breaker. Nothing reaches real
# Linear, real GitHub or the live state dir.
#
# NEGATIVE SELF-TESTS: 5 movable PRs release nothing (L3); a PR approved at its
# head with CI pending and 1 hour old is not released by the backstop (L4); a
# live lane is never released (L6); a mutant without the wip_release call goes
# red (L12); the coverage lint goes red on a hold kind with no exit row (L11);
# the dispatcher hook goes red without its apply pass (L13).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$REPO_SCRIPTS/../../.." && pwd)"
WORKER="${KIPI_WORKER_UNDER_TEST:-$REPO_SCRIPTS/linear-worker.sh}"
TABLE="$REPO_SCRIPTS/../terminal-states.json"
DISPATCH="$REPO_ROOT/kipi-dispatch.sh"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT

# --- fixture Linear: reads answered from the board below, writes logged -----------
cat > "$WORK/fixture-server.py" <<'PY'
import json, os
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = os.environ["FIXTURE_LOG"]
NOW = datetime.now(timezone.utc)
NAMES = {"backlog": "Backlog", "started": "In Progress", "completed": "Done"}
ALERT = "\n<!-- kipi-alert-fingerprint: fixture-fp -->"


def ago(hours):
    return (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def issue(ident, state, started_hours=None, alert=False):
    return {"id": "uuid-" + ident, "identifier": ident, "title": "fixture " + ident,
            "description": "## Definition of Ready\nOutcome: x" + (ALERT if alert else ""),
            "state": {"name": NAMES[state], "type": state},
            "startedAt": ago(started_hours) if started_hours is not None else None,
            "project": {"name": "kipi-system"}, "team": {"id": "team-fixture"},
            "labels": {"nodes": [{"id": "lab-owner", "name": "owner:sana"}]}}


def pr(branch, n):
    return {"url": "https://github.com/x/kipi-system/pull/%d" % n,
            "metadata": {"status": "open", "branch": branch, "number": n}}


MONTH = 24 * 30
# ASK-900 FIRST: it is the fresh ready issue a tick under the ceiling names.
TICKETS = [issue("ASK-900", "backlog")]
TICKETS.append(issue("ASK-2810", "started", MONTH))               # PR 543
TICKETS.append(issue("ASK-2058", "started", MONTH, alert=True))   # PR 559
TICKETS.append(issue("ASK-3574", "completed", MONTH))             # PR 584
for n in (3823, 3821, 3827, 3830, 3829):                          # the 5 lanes
    TICKETS.append(issue("ASK-%d" % n, "backlog"))
TICKETS.append(issue("ASK-971", "started", 1))                    # a LIVE lane
for n in (901, 902, 903, 904, 905, 961, 962, 963, 964, 965):
    TICKETS.append(issue("ASK-%d" % n, "started", MONTH))
BOARD = {i["identifier"]: i for i in TICKETS}
ATTACH = {"uuid-ASK-2810": [pr("sana/ask-2810", 543)],
          "uuid-ASK-2058": [pr("sana/ask-2058", 559)]}
for n in (901, 902, 903, 904, 905, 961, 962, 963, 964, 965):
    ATTACH["uuid-ASK-%d" % n] = [pr("sana/ask-%d" % n, n)]


def find(ref):
    for i in BOARD.values():
        if ref in (i["id"], i["identifier"]):
            return i
    return None


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, payload):
        out = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode())
        q, v = req.get("query", ""), req.get("variables") or {}
        if q.lstrip().startswith("mutation"):
            with open(LOG, "a") as fh:
                fh.write(json.dumps({"mutation": q.split("(")[1].split("{")[-1].strip()
                                     if "(" in q else q[:40], "q": q[:120], "variables": v}) + "\n")
            if "commentCreate" in q:
                return self.reply({"data": {"commentCreate": {"success": True, "comment": {"id": "c1"}}}})
            if "issueUpdate" in q:
                return self.reply({"data": {"issueUpdate": {"success": True,
                                   "issue": {"id": v.get("id"), "identifier": "x"}}}})
            return self.reply({"errors": [{"message": "fixture: unknown mutation"}]})
        if "teams(" in q:
            return self.reply({"data": {"teams": {"nodes": [{"id": "team-fixture", "key": "ASK"}]}}})
        if "attachments(" in q:
            return self.reply({"data": {"issue": {"attachments": {"nodes": ATTACH.get(v.get("id"), [])}}}})
        if "issues(filter" in q:
            return self.reply({"data": {"issues": {"nodes": list(BOARD.values()),
                               "pageInfo": {"hasNextPage": False, "endCursor": None}}}})
        if "team(id" in q and "states" in q:
            return self.reply({"data": {"team": {"states": {"nodes": [
                {"id": "st-backlog", "name": "Backlog", "type": "backlog", "position": 0}]}}}})
        if "issue(id" in q:
            i = find(v.get("id", ""))
            return self.reply({"data": {"issue": i}})
        return self.reply({"errors": [{"message": "fixture: unknown query"}]})


srv = HTTPServer(("127.0.0.1", 0), H)
print(srv.server_port, flush=True)
srv.serve_forever()
PY
FIXLOG="$WORK/linear-writes.jsonl"; : > "$FIXLOG"
FIXTURE_LOG="$FIXLOG" python3 "$WORK/fixture-server.py" > "$WORK/port" 2> "$WORK/server.err" &
SRV_PID=$!
for _ in $(seq 1 100); do PORT="$(cat "$WORK/port" 2>/dev/null)"; [ -n "${PORT:-}" ] && break; sleep 0.1; done
[ -n "${PORT:-}" ] || { echo "fixture server did not start: $(cat "$WORK/server.err")"; exit 1; }

# --- a real git skeleton whose origin reads as github.com/x/kipi-system ------------
SKEL_PARENT="$WORK/run"; SKEL="$SKEL_PARENT/kipi-system"
mkdir -p "$SKEL_PARENT"
git init --quiet --bare "$SKEL_PARENT/origin.git" && git -C "$SKEL_PARENT/origin.git" symbolic-ref HEAD refs/heads/main
git init --quiet "$SKEL"
git -C "$SKEL" config user.email t@t; git -C "$SKEL" config user.name t
mkdir -p "$SKEL/.claude"; printf '{}\n' > "$SKEL/.claude/settings.json"
: > "$SKEL/seed"; git -C "$SKEL" add seed .claude/settings.json; git -C "$SKEL" commit --quiet -m seed
git -C "$SKEL" remote add origin "$SKEL_PARENT/origin.git"
git -C "$SKEL" push --quiet -u origin HEAD:main 2>/dev/null
git -C "$SKEL" config url."$SKEL_PARENT/origin.git".insteadOf "https://github.com/x/kipi-system.git"
git -C "$SKEL" remote set-url origin "https://github.com/x/kipi-system.git"
STATE="$WORK/state"; mkdir -p "$STATE/worktrees" "$STATE/pr-reviews"

# --- the attempts ledger: who the fleet has run (lanes have no row) ----------------
ledger_seed() {  # ledger_seed <path>
  python3 - "$1" <<'LEDGER'
import json, sys
rows = {"ASK-%d" % n: {"rounds": 1, "count": 1}
        for n in (2810, 2058, 901, 902, 903, 904, 905, 961, 962, 963, 964, 965)}
json.dump(rows, open(sys.argv[1], "w"), indent=2)
LEDGER
}
ledger_seed "$STATE/linear-worker-attempts.json"

# --- review records, keyed the way the worker keys them ----------------------------
# shellcheck disable=SC1091
. "$REPO_SCRIPTS/repo-slug-lib.sh"
# shellcheck disable=SC1091
. "$REPO_SCRIPTS/pr-verdict-lib.sh"
SLUG="$(slug_for_repo "$SKEL" "$SKEL/instance-registry.json")"
[ "$SLUG" = "x/kipi-system" ] \
  && ok "fixture self-test: the skeleton reads as GitHub repo x/kipi-system" \
  || bad "fixture self-test: the skeleton has a GitHub slug" "slug_for_repo gave '$SLUG'"
GHDIR="$WORK/gh"; mkdir -p "$GHDIR"
review() {  # review <pr> <verdict> <usable-rounds> <merge-state> [head-moved]
  local pr="$1" verdict="$2" rounds="$3" merge="$4" moved="${5:-}" key sha r
  key="$(artifact_key "$SLUG" "$pr")"
  sha="$(printf '%040d' "$pr")"
  printf '{"verdict": "%s", "head_sha": "%s", "degraded": false}\n' "$verdict" "$sha" \
    > "$STATE/pr-reviews/$key.verdict.json"
  # One mtime per round, as real rounds are written minutes apart. Written in
  # one clock tick, CI's filesystem gave the three files one mtime, `ls -t`
  # broke the tie by name, and the release read round 1's findings (L7b red on
  # PR #629 validate; green on macOS, whose mtimes differed by nanoseconds).
  for r in $(seq 1 "$rounds"); do
    printf 'VERDICT: %s\n\nFINDINGS:\nmajor|fixture finding %s on PR %s|x.sh:%s\nEND FINDINGS\n' \
      "$verdict" "$r" "$pr" "$r" > "$STATE/pr-reviews/$key-2026100${r}-000000.md"
    touch -t "2026100${r}0000" "$STATE/pr-reviews/$key-2026100${r}-000000.md"
  done
  printf '%s\n' "$merge" > "$GHDIR/merge-$pr"
  if [ -n "$moved" ]; then printf '%040d\n' "$((pr + 1))" > "$GHDIR/head-$pr"
  else printf '%s\n' "$sha" > "$GHDIR/head-$pr"; fi
}
review 543 "APPROVE" 3 DIRTY
review 559 "REQUEST CHANGES" 3 BLOCKED
review 584 "APPROVE" 3 BLOCKED moved
for n in 606 614; do review "$n" "REQUEST CHANGES" 3 DIRTY; done
review 609 "APPROVE WITH NITS" 3 BLOCKED
for n in 618 621; do review "$n" "REQUEST CHANGES" 2 DIRTY; done
review 971 "REQUEST CHANGES" 1 CLEAN
for n in 901 902 903 904 905; do review "$n" "REQUEST CHANGES" 1 CLEAN; done
for n in 961 962 963 964 965; do review "$n" "APPROVE" 1 BLOCKED; done   # CI pending

CAPPED=0
for f in "$STATE/pr-reviews/$(artifact_key "$SLUG" 543)-"*.md; do
  review_is_usable "$f" && CAPPED=$((CAPPED + 1))
done
[ "$CAPPED" = "3" ] \
  && ok "fixture self-test: PR #543 holds 3 rounds the reviewer counts as usable" \
  || bad "fixture self-test: PR #543 holds 3 usable rounds" "review_is_usable counted $CAPPED"
NEWEST="$(ls -t "$STATE/pr-reviews/$(artifact_key "$SLUG" 543)-"*.md | head -1)"
case "$NEWEST" in
  *-20261003-000000.md) ok "fixture self-test: by mtime the newest review of PR #543 is round 3" ;;
  *) bad "fixture self-test: the newest review of PR #543 is round 3" "ls -t gave $(basename "$NEWEST")" ;;
esac

# --- gh: fixture answers, every call logged ----------------------------------------
STUBS="$WORK/bin"; mkdir -p "$STUBS"
cat > "$STUBS/gh" <<'GH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$WIP_GH_DIR/calls.log"
A="$*"
case "$A" in
  *"pr list"*"--state open"*) cat "$WIP_PRS_FILE" 2>/dev/null; exit 0 ;;
  *"pr list"*"--state merged"*) cat "${WIP_MERGED_FILE:-/dev/null}" 2>/dev/null; exit 0 ;;
  *"pr close"*)
    [ "${WIP_GH_CLOSE_FAIL:-0}" = "1" ] && { echo "gh: HTTP 502" >&2; exit 1; }
    exit 0 ;;
  *"pr view"*)
    n="$(printf '%s' "$A" | grep -oE 'pr view [0-9]+' | grep -oE '[0-9]+')"
    case "$A" in
      *mergeStateStatus*) cat "$WIP_GH_DIR/merge-$n" 2>/dev/null ;;
      *headRefOid*)       cat "$WIP_GH_DIR/head-$n" 2>/dev/null ;;
    esac ;;
esac
exit 0
GH
printf '#!/usr/bin/env bash\nprintf "ran %%s\\n" "$*" >> "%s/claude-ran.log"\nexit 0\n' "$WORK" > "$STUBS/claude"
printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/fake-reviewer.sh"
printf '#!/usr/bin/env bash\nexit 0\n' > "$WORK/fake-codex.sh"
printf '#!/usr/bin/env bash\nprintf "NOTIFY %%s\\n" "$*" >> "%s/pages.log"\nexit 0\n' "$WORK" > "$WORK/notify.sh"
chmod +x "$STUBS/gh" "$STUBS/claude" "$WORK/fake-reviewer.sh" "$WORK/fake-codex.sh" "$WORK/notify.sh"

ago() { python3 -c 'import datetime,sys;print((datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=float(sys.argv[1]))).strftime("%Y-%m-%dT%H:%M:%SZ"))' "$1"; }
# prs <file> <number:branch:created-iso>...  The shape `gh pr list -q` prints.
prs() {
  local out="$1"; shift; : > "$out"
  local spec n br at
  for spec in "$@"; do
    n="${spec%%:*}"; br="${spec#*:}"; br="${br%%:*}"; at="${spec#*:*:}"
    printf '%s\t%s\t%s\thttps://github.com/x/kipi-system/pull/%s\n' "$n" "$br" "$at" "$n" >> "$out"
  done
}

run_worker() {  # run_worker <worker-script> <prs-file> <out-file> [worker args...]
  local w="$1" prsf="$2" out="$3"; shift 3
  : > "$GHDIR/calls.log"
  PATH="$STUBS:$PATH" \
    KIPI_SKEL="$SKEL" KIPI_STATE_DIR="${WIP_STATE:-$STATE}" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
    KIPI_CODEX_RUNNER="bash $WORK/fake-codex.sh" KIPI_SECOND_RUNNER_FALLBACK="" \
    KIPI_USAGE_BREAKER_CMD="true" KIPI_NOTIFY="$WORK/notify.sh" \
    WIP_GH_DIR="$GHDIR" WIP_PRS_FILE="$prsf" \
    bash "$w" "$@" > "$out" 2>&1
}
flat() { tr '\n' '|' < "$1" | cut -c1-1200; }
releases() { grep -oE '\[dry\] would release PR #[0-9]+ \([^)]*\)' "$1" | tr '\n' ';'; }
fresh_state() {  # fresh_state <dir>: a scratch state dir with the seed ledger and reviews
  mkdir -p "$1/worktrees"; ledger_seed "$1/linear-worker-attempts.json"
  ln -s "$STATE/pr-reviews" "$1/pr-reviews"
}

# The 8 shapes, oldest first.
TODAY=("543:sana/ask-2810:2026-10-22T12:00:00Z" "559:sana/ask-2058:2026-10-23T12:00:00Z"
       "584:sana/ask-3574:2026-10-24T12:00:00Z"
       "606:sana/ask-3823-promoter:2026-11-06T10:00:00Z" "609:sana/ask-3821-kipi-update:2026-11-06T11:00:00Z"
       "614:sana/ask-3827-slot-status:2026-11-06T12:00:00Z" "618:sana/ask-3830-live-receipt:2026-11-06T13:00:00Z"
       "621:sana/ask-3829-fragments:2026-11-06T14:00:00Z")
prs "$WORK/today.prs" "${TODAY[@]}"

echo "== worker WIP liveness (worker under test: $WORKER)"

# ============================================================================
# L1. THE DoR CHECK: today's 8 unmovable PRs, one dry tick
# ============================================================================
run_worker "$WORKER" "$WORK/today.prs" "$WORK/l1.out" --limit 1
if grep -q 'Starting nothing' "$WORK/l1.out" && ! grep -q '\[dry\] would release' "$WORK/l1.out"; then
  bad "L1 (DoR check): at the ceiling with nothing movable the tick names an action" \
      "THE DEFECT: 'Starting nothing' and no action named. $(grep 'WIP ceiling' "$WORK/l1.out" | head -1)"
else
  ok "L1 (DoR check): at the ceiling with nothing movable the tick names an action"
fi
REL="$(releases "$WORK/l1.out")"
[ "$REL" = "[dry] would release PR #543 (cap);" ] \
  && ok "L1b: exactly one release, the oldest: [dry] would release PR #543 (cap)" \
  || bad "L1b: one release, the oldest PR #543 as cap" "releases: ${REL:-none}. Output: $(flat "$WORK/l1.out")"
grep -q '\[dry\] would work' "$WORK/l1.out" \
  && bad "L1c: no new issue starts at the ceiling" "$(grep 'would work' "$WORK/l1.out")" \
  || ok "L1c: no new issue starts at the ceiling"

# ============================================================================
# L2. THE 10-TICK LOOP: the fixture applies each named release
# ============================================================================
cp "$WORK/today.prs" "$WORK/loop.prs"
MIN=8; REACHED=""; KINDS=""
for t in $(seq 1 10); do
  run_worker "$WORKER" "$WORK/loop.prs" "$WORK/loop-$t.out" --limit 1
  if grep -q '\[dry\] would work ASK-' "$WORK/loop-$t.out"; then REACHED="$t"; break; fi
  n="$(grep -oE '\[dry\] would release PR #[0-9]+' "$WORK/loop-$t.out" | head -1 | grep -oE '[0-9]+$')"
  k="$(grep -oE '\[dry\] would release PR #[0-9]+ \([^)]*\)' "$WORK/loop-$t.out" | head -1 | sed -E 's/.*\((.*)\)/\1/')"
  [ -n "$n" ] && { KINDS="$KINDS$k,"; grep -v "^$n	" "$WORK/loop.prs" > "$WORK/loop.next"; mv "$WORK/loop.next" "$WORK/loop.prs"; }
  c="$(grep -c . "$WORK/loop.prs")"; [ "$c" -lt "$MIN" ] && MIN="$c"
done
if [ -n "$REACHED" ] && [ "$REACHED" -le 5 ]; then
  ok "L2: the 10-tick loop reaches [dry] would work ASK-900 by tick 5 (tick $REACHED)"
else
  bad "L2: the 10-tick loop reaches a new issue by tick 5" \
      "reached: ${REACHED:-never}; open own PRs never dropped below $MIN"
fi
[ "$KINDS" = "cap,alert,ticket-closed,lane," ] \
  && ok "L2b: released oldest first, one per tick: cap, alert, ticket-closed, lane" \
  || bad "L2b: release order and kinds" "got: ${KINDS:-none}"

# ============================================================================
# L3. NEGATIVE: 5 movable PRs release nothing
# ============================================================================
prs "$WORK/movable.prs" "901:sana/ask-901:2026-10-01T12:00:00Z" "902:sana/ask-902:2026-10-02T12:00:00Z" \
    "903:sana/ask-903:2026-10-03T12:00:00Z" "904:sana/ask-904:2026-10-04T12:00:00Z" "905:sana/ask-905:2026-10-05T12:00:00Z"
run_worker "$WORKER" "$WORK/movable.prs" "$WORK/l3.out" --limit 1
if grep -q '\[dry\] would work ASK-901 .*rework PR #901' "$WORK/l3.out" && ! grep -q 'would release' "$WORK/l3.out"; then
  ok "L3 (negative): 5 movable PRs: the oldest is reworked and nothing is released"
else
  bad "L3 (negative): 5 movable PRs release nothing" "releases: $(releases "$WORK/l3.out"). Output: $(flat "$WORK/l3.out")"
fi

# ============================================================================
# L4. NEGATIVE: approved at head, CI pending, 1 hour old -> the backstop waits
# ============================================================================
H1="$(ago 1)"
prs "$WORK/young.prs" "961:sana/ask-961:$H1" "962:sana/ask-962:$H1" "963:sana/ask-963:$H1" \
    "964:sana/ask-964:$H1" "965:sana/ask-965:$H1"
run_worker "$WORKER" "$WORK/young.prs" "$WORK/l4.out" --limit 1
if ! grep -q 'would release' "$WORK/l4.out" && ! grep -q '\[dry\] would work' "$WORK/l4.out"; then
  ok "L4 (negative): 5 PRs approved at head with CI pending, 1 hour old: nothing released, nothing started"
else
  bad "L4 (negative): the backstop does not release a 1-hour-old approved PR" "$(flat "$WORK/l4.out")"
fi
grep -q 'backstop releases PR #961' "$WORK/l4.out" \
  && ok "L4b: the wait is named with its expiry: the backstop releases PR #961 once it is old enough" \
  || bad "L4b: the wait names the backstop expiry" "$(grep 'WIP' "$WORK/l4.out" | tr '\n' '|')"

# ============================================================================
# L5. THE BACKSTOP: the same, but the oldest is 4 days old
# ============================================================================
prs "$WORK/old.prs" "961:sana/ask-961:$(ago 96)" "962:sana/ask-962:$H1" "963:sana/ask-963:$H1" \
    "964:sana/ask-964:$H1" "965:sana/ask-965:$H1"
run_worker "$WORKER" "$WORK/old.prs" "$WORK/l5.out" --limit 1
REL="$(releases "$WORK/l5.out")"
[ "$REL" = "[dry] would release PR #961 (backstop: approved);" ] \
  && ok "L5: nothing movable, no exit row fits, oldest past 3 days: [dry] would release PR #961 (backstop: approved)" \
  || bad "L5: the backstop releases the 4-day-old PR" "releases: ${REL:-none}. Output: $(flat "$WORK/l5.out")"

# L5b. THE p85 TERM: 6 merged own PRs that each took 1 day put the bar at 10
# days (10 x p85), so the same 4-day-old PR is NOT released. Read through
# work_item_age.py tail_seconds, the repo's one percentile definition.
: > "$WORK/merged.tsv"
for n in 1 2 3 4 5 6; do
  printf 'sana/ask-80%s\t2026-10-0%sT00:00:00Z\t2026-10-0%sT00:00:00Z\n' "$n" "$n" "$((n + 1))" >> "$WORK/merged.tsv"
done
WIP_MERGED_FILE="$WORK/merged.tsv" run_worker "$WORKER" "$WORK/old.prs" "$WORK/l5b.out" --limit 1
if ! grep -q 'would release' "$WORK/l5b.out" && grep -q 'open 240h, the larger of 10 x the merged p85' "$WORK/l5b.out"; then
  ok "L5b: a merged p85 of 1 day sets the bar at 240h, so the 4-day-old PR waits"
else
  bad "L5b: the p85 term of the age bar" "releases: $(releases "$WORK/l5b.out"). $(grep 'WIP ceiling' "$WORK/l5b.out" | head -2 | tr '\n' '|')"
fi

# ============================================================================
# L6. NEGATIVE: a live lane (ticket started an hour ago) is never released
# ============================================================================
prs "$WORK/live.prs" "971:sana/ask-971-live-lane:2026-10-01T12:00:00Z" \
    "606:sana/ask-3823-promoter:2026-11-06T10:00:00Z" "609:sana/ask-3821-kipi-update:2026-11-06T11:00:00Z" \
    "614:sana/ask-3827-slot-status:2026-11-06T12:00:00Z" "618:sana/ask-3830-live-receipt:2026-11-06T13:00:00Z"
run_worker "$WORKER" "$WORK/live.prs" "$WORK/l6.out" --limit 1
REL="$(releases "$WORK/l6.out")"
[ "$REL" = "[dry] would release PR #606 (lane);" ] \
  && ok "L6 (negative): the live lane #971 is passed over; the next oldest lane #606 is released" \
  || bad "L6 (negative): a live lane is never released" "releases: ${REL:-none}. Output: $(flat "$WORK/l6.out")"

# ============================================================================
# L7. --apply, close + requeue: PR #543 at the cap, ticket started
# ============================================================================
AST="$WORK/state-apply"; fresh_state "$AST"; : > "$FIXLOG"; rm -f "$WORK/claude-ran.log"
WIP_STATE="$AST" run_worker "$WORKER" "$WORK/today.prs" "$WORK/l7.out" --apply --limit 1
CLOSE="$(grep -c '^pr close 543 ' "$GHDIR/calls.log")"
if [ "$CLOSE" = "1" ] && grep -q '^pr close 543 -R x/kipi-system --comment ' "$GHDIR/calls.log"; then
  ok "L7: --apply closes PR #543 once, scoped to the repo, with a comment"
else
  bad "L7: --apply closes PR #543" "gh calls: $(tr '\n' '|' < "$GHDIR/calls.log" | cut -c1-600)"
fi
grep -q 'fixture finding 3 on PR 543' "$GHDIR/calls.log" \
  && ok "L7b: the close comment carries the last FINDINGS block" \
  || bad "L7b: the close comment carries the last FINDINGS block" "$(grep -A3 'pr close' "$GHDIR/calls.log" | head -8 | tr '\n' '|')"
# The close comment is prose and says "a push gets no new review", so this reads
# only the arguments gh can delete with (the first draft grepped "push" and
# matched that sentence).
if grep -qE -- '--delete-branch|^api .*(-X|--method) *DELETE' "$GHDIR/calls.log"; then
  bad "L7c: the release never deletes a branch" "$(grep -E -- '--delete-branch|DELETE' "$GHDIR/calls.log")"
else
  ok "L7c: the release never deletes a branch (no --delete-branch, no DELETE call)"
fi
UPD="$(grep -c '"issueUpdate' "$FIXLOG")"; CMT="$(grep -c 'commentCreate' "$FIXLOG")"
[ "$UPD" = "1" ] && [ "$CMT" = "1" ] && grep -q 'Resume from branch sana/ask-2810' "$FIXLOG" \
  && ok "L7d: ASK-2810 goes back to Backlog with ONE comment naming the branch to resume from" \
  || bad "L7d: one requeue, one comment" "issueUpdate: $UPD, commentCreate: $CMT. Log: $(cut -c1-400 < "$FIXLOG")"
N2="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["ASK-2810"]["count"])' "$AST/linear-worker-attempts.json")"
[ "$N2" = "2" ] && ok "L7e: one attempt is charged to ASK-2810 (1 -> 2)" \
                || bad "L7e: one attempt charged" "count is $N2"
NREV="$(ls "$STATE/pr-reviews/$(artifact_key "$SLUG" 543)-"*.md 2>/dev/null | grep -c .)"
[ "$NREV" = "3" ] && ok "L7f: the review cap is not reset: PR #543 still holds its 3 review rounds" \
                  || bad "L7f: the review cap is not reset" "PR #543 review files: $NREV"
[ ! -e "$WORK/claude-ran.log" ] && ok "L7g: the release starts no agent run" \
                                || bad "L7g: no agent run" "$(cat "$WORK/claude-ran.log")"

# ============================================================================
# L8. --apply, close + comment: the oldest PR's ticket is Done
# ============================================================================
prs "$WORK/done.prs" "584:sana/ask-3574:2026-10-24T12:00:00Z" "606:sana/ask-3823-promoter:2026-11-06T10:00:00Z" \
    "609:sana/ask-3821-kipi-update:2026-11-06T11:00:00Z" "614:sana/ask-3827-slot-status:2026-11-06T12:00:00Z" \
    "618:sana/ask-3830-live-receipt:2026-11-06T13:00:00Z"
DST="$WORK/state-done"; fresh_state "$DST"; : > "$FIXLOG"
WIP_STATE="$DST" run_worker "$WORKER" "$WORK/done.prs" "$WORK/l8.out" --apply --limit 1
if grep -q '^pr close 584 ' "$GHDIR/calls.log" && [ "$(grep -c 'commentCreate' "$FIXLOG")" = "1" ] \
   && ! grep -q '"issueUpdate' "$FIXLOG"; then
  ok "L8: a Done ticket's PR is closed and the ticket gets one comment and no state change"
else
  bad "L8: close + comment, no requeue" "gh: $(grep 'pr close' "$GHDIR/calls.log" | cut -c1-80). Linear: $(cut -c1-300 < "$FIXLOG")"
fi
FLAG="$(python3 "$REPO_SCRIPTS/attempts-ledger.py" "$DST/linear-worker-attempts.json" get ASK-3574 wip_released_pr584 "")"
[ "$FLAG" = "True" ] && ok "L8b: the release writes one attempts-ledger row through the ledger writer" \
                     || bad "L8b: a ledger row for the release" "wip_released_pr584 is '$FLAG'"

# ============================================================================
# L9. --apply, the backstop pages once with its classification
# ============================================================================
BST="$WORK/state-backstop"; fresh_state "$BST"; : > "$WORK/pages.log"
WIP_STATE="$BST" run_worker "$WORKER" "$WORK/old.prs" "$WORK/l9a.out" --apply --limit 1
WIP_STATE="$BST" run_worker "$WORKER" "$WORK/old.prs" "$WORK/l9b.out" --apply --limit 1
P="$(grep -c 'WIP backstop' "$WORK/pages.log")"
if [ "$P" = "1" ] && grep -q 'PR #961' "$WORK/pages.log" && grep -q 'approved' "$WORK/pages.log"; then
  ok "L9: the backstop release pages once, naming the PR and its classification"
else
  bad "L9: one backstop page with the classification" "pages: $P. $(tr '\n' '|' < "$WORK/pages.log" | cut -c1-400)"
fi

# ============================================================================
# L10. A dry run stays dry
# ============================================================================
: > "$FIXLOG"; cp "$STATE/linear-worker-attempts.json" "$WORK/ledger.before"
run_worker "$WORKER" "$WORK/today.prs" "$WORK/l10.out" --limit 1
if ! grep -q 'pr close' "$GHDIR/calls.log" && [ ! -s "$FIXLOG" ] \
   && cmp -s "$WORK/ledger.before" "$STATE/linear-worker-attempts.json"; then
  ok "L10: a dry tick closes nothing, writes nothing to Linear and leaves the ledger alone"
else
  bad "L10: dry stays dry" "gh: $(grep 'pr close' "$GHDIR/calls.log" | head -1). Linear: $(head -c 200 "$FIXLOG")"
fi
CST="$WORK/state-cf"; fresh_state "$CST"; : > "$FIXLOG"
WIP_GH_CLOSE_FAIL=1 WIP_STATE="$CST" run_worker "$WORKER" "$WORK/today.prs" "$WORK/l10b.out" --apply --limit 1
grep -q 'could not close PR #543' "$WORK/l10b.out" && ! grep -q '"issueUpdate' "$FIXLOG" \
  && ok "L10b: a failed close is said and writes nothing to Linear" \
  || bad "L10b: a failed close is said" "$(grep -i 'release\|close' "$WORK/l10b.out" | head -3 | tr '\n' '|')"

# ============================================================================
# L11. THE COVERAGE LINT: every hold kind has an exit row, and no row is stale
# ============================================================================
lint() {  # lint <worker> <table> -> prints problems, exit 1 on any
  python3 - "$1" "$2" <<'PY'
import json, re, sys
src = open(sys.argv[1]).read()
emitted = set(re.findall(r'hold\("([a-z][a-z-]*)"', src))
emitted |= set(re.findall(r"printf '([a-z][a-z-]*)\|", src))
try:
    rows = json.load(open(sys.argv[2]))["wip_release"]["kinds"]
except Exception as exc:
    print("no wip_release.kinds table: %s" % exc); sys.exit(1)
vocab = {"close-requeue", "close-comment", "wait"}
bad = []
if len(emitted) < 10:
    bad.append("only %d hold kinds found in the worker; the lint is not reading it" % len(emitted))
bad += ["kind %r has no exit row" % k for k in sorted(emitted - set(rows))]
bad += ["row %r names no kind the worker emits" % k for k in sorted(set(rows) - emitted)]
bad += ["row %r has exit %r, not one of %s" % (k, v.get("exit"), sorted(vocab))
        for k, v in rows.items() if v.get("exit") not in vocab]
bad += ["row %r names no consumer" % k for k, v in rows.items() if not str(v.get("consumer") or "").strip()]
print("\n".join(bad))
sys.exit(1 if bad else 0)
PY
}
if OUT="$(lint "$WORKER" "$TABLE")"; then
  ok "L11: every hold kind the picker and wip_move_why emit has an exit row, and every row is live"
else
  bad "L11: the coverage lint" "$OUT"
fi
cp "$TABLE" "$WORK/table-minus.json"
python3 - "$WORK/table-minus.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
try:
    d["wip_release"]["kinds"].pop("alert", None)
except Exception:
    pass
json.dump(d, open(sys.argv[1], "w"))
PY
lint "$WORKER" "$WORK/table-minus.json" >/dev/null \
  && bad "L11b (negative): the lint goes red when a kind loses its row" "a table without 'alert' passed" \
  || ok "L11b (negative): the lint goes red when the alert kind loses its exit row"
sed "s/printf 'drift|/printf 'drift-new|/" "$WORKER" > "$WORK/worker-newkind.sh"
lint "$WORK/worker-newkind.sh" "$TABLE" >/dev/null \
  && bad "L11c (negative): the lint goes red on a new kind with no row" "a worker emitting drift-new passed" \
  || ok "L11c (negative): the lint goes red on a new hold kind with no row"

# ============================================================================
# L12. MUTANT: the wip_release call deleted
# ============================================================================
MUT="$WORK/mut/scripts"; mkdir -p "$WORK/mut"
cp -R "$REPO_SCRIPTS" "$MUT"; cp "$TABLE" "$WORK/mut/terminal-states.json"
if python3 - "$MUT/linear-worker.sh" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
old = '    wip_release "$WIP_REL_PR"'
assert s.count(old) == 1, "mutation anchor not found exactly once"
open(p, "w").write(s.replace(old, '    : "$WIP_REL_PR"'))
PY
then
  run_worker "$MUT/linear-worker.sh" "$WORK/today.prs" "$WORK/m12.out" --limit 1
  grep -q 'would release' "$WORK/m12.out" \
    && bad "mutant L12 survived" "a release was named with the call cut out" \
    || ok "mutant killed: without the wip_release call nothing is released, so L1 can go red"
else
  bad "mutant L12: anchor" "the wip_release call site moved"
fi

# L12b. MUTANT: a close with --delete-branch must turn L7c red.
cp "$REPO_SCRIPTS/linear-worker.sh" "$MUT/linear-worker.sh"
if python3 - "$MUT/linear-worker.sh" <<'PY2'
import sys
p = sys.argv[1]
s = open(p).read()
old = 'gh pr close "$pr" $KIPI_GH_REPO_ARGS --comment'
assert s.count(old) == 1, "mutation anchor not found exactly once"
open(p, "w").write(s.replace(old, 'gh pr close "$pr" $KIPI_GH_REPO_ARGS --delete-branch --comment'))
PY2
then
  MST="$WORK/state-m12b"; fresh_state "$MST"
  WIP_STATE="$MST" run_worker "$MUT/linear-worker.sh" "$WORK/today.prs" "$WORK/m12b.out" --apply --limit 1
  grep -qE -- '--delete-branch|^api .*(-X|--method) *DELETE' "$GHDIR/calls.log" \
    && ok "mutant killed: a release that deletes its branch is caught by the L7c check" \
    || bad "mutant L12b survived" "the --delete-branch close was not seen: $(grep 'pr close' "$GHDIR/calls.log" | head -1 | cut -c1-120)"
else
  bad "mutant L12b: anchor" "the gh pr close call moved"
fi

# ============================================================================
# L13. THE LIVE PATH: the dispatcher applies a release its dry pick named
# ============================================================================
# kipi-dispatch.sh runs `kipi work` WITHOUT --apply to pick, then launches
# converge --issue, which never reaches the WIP block. So a release the dry pick
# names must be applied by the dispatcher itself, or it never happens live.
DROOT="$WORK/dispatch"; DREPO="$DROOT/repo"
mkdir -p "$DREPO" "$DROOT/home/.config/kipi" "$DROOT/bin"
printf '#!/bin/sh\nexit 0\n' > "$DROOT/bin/gh"; chmod +x "$DROOT/bin/gh"
printf '#!/bin/sh\nexit 0\n' > "$DROOT/notify.sh"; chmod +x "$DROOT/notify.sh"
make_kipi() {  # make_kipi <release|norelease>
  cat > "$DREPO/kipi" <<SH
printf '%s\n' "\$*" >> "$DROOT/kipi-calls.log"
case "\$1 \$*" in
  *--release-only*) printf 'apply-excl=[%s]\n' "\${KIPI_PICK_EXCLUDE:-}" >> "$DROOT/kipi-calls.log"; echo "release PR #543 (cap): closed" ;;
  work*) if [ "$1" = "release" ]; then echo "[dry] would release PR #543 (cap): close it"; else echo "nothing ready."; fi ;;
esac
exit 0
SH
  chmod +x "$DREPO/kipi"
}
run_dispatch() {  # run_dispatch <dispatch-script>
  rm -rf "$DROOT/home/.config/kipi"; mkdir -p "$DROOT/home/.config/kipi"
  date -u +%s > "$DROOT/home/.config/kipi/dispatch-lastbeat"; : > "$DROOT/kipi-calls.log"
  [ -z "${SEED_SET_ASIDE:-}" ] || printf '%s\t%s\n' "$SEED_SET_ASIDE" "$(date +%s)" \
    > "$DROOT/home/.config/kipi/dispatch-branch-refused.tsv"
  ( cd "$DREPO" && HOME="$DROOT/home" PATH="$DROOT/bin:$PATH" \
      KIPI_REPO="$DREPO" KIPI_NOTIFY="$DROOT/notify.sh" \
      KIPI_DISPATCH_DAILY_MAX=9 KIPI_DISPATCH_MAX=999 \
      bash "$1" >/dev/null 2>&1 )
}
make_kipi release; run_dispatch "$DISPATCH"
grep -q -- 'work --release-only --apply' "$DROOT/kipi-calls.log" \
  && ok "L13: a dry pick that names a release makes the dispatcher run kipi work --release-only --apply" \
  || bad "L13: the dispatcher applies the named release" "kipi calls: $(tr '\n' '|' < "$DROOT/kipi-calls.log")"
# L13c. THE APPLY PASS SEES THE SAME SET-ASIDE LIST AS THE DRY PICK (ASK-3993
# follow-up, PR #651 round 2, major). Without it the apply pass recomputes the
# hold kinds without the list and closes a different PR than the log names.
make_kipi release; SEED_SET_ASIDE="ASK-931" run_dispatch "$DISPATCH"
grep -q '^apply-excl=\[ASK-931\]$' "$DROOT/kipi-calls.log" \
  && ok "L13c: the release-apply pass carries the set-aside list the dry pick used" \
  || bad "L13c: the release-apply pass carries the set-aside list" "kipi calls: $(tr '\n' '|' < "$DROOT/kipi-calls.log")"
make_kipi norelease; run_dispatch "$DISPATCH"
grep -q -- '--release-only' "$DROOT/kipi-calls.log" \
  && bad "L13b (negative): no release named, no apply pass" "$(tr '\n' '|' < "$DROOT/kipi-calls.log")" \
  || ok "L13b (negative): a dry pick with no release runs no apply pass"
sed '/WIP-RELEASE-APPLY:BEGIN/,/WIP-RELEASE-APPLY:END/d' "$DISPATCH" > "$WORK/dispatch-mut.sh"
if cmp -s "$DISPATCH" "$WORK/dispatch-mut.sh"; then
  bad "mutant L13c: anchor" "kipi-dispatch.sh has no WIP-RELEASE-APPLY block to cut"
else
  make_kipi release; run_dispatch "$WORK/dispatch-mut.sh"
  grep -q -- '--release-only' "$DROOT/kipi-calls.log" \
    && bad "mutant L13c survived" "the apply pass ran with its block cut out" \
    || ok "mutant killed: without the dispatcher block the release is never applied live, so L13 can go red"
fi

# ============================================================================
# L14. --release-only stops before the issue loop
# ============================================================================
run_worker "$WORKER" "$WORK/movable.prs" "$WORK/l14.out" --release-only --limit 1; RC14=$?
if [ "$RC14" = "0" ] && ! grep -q '\[dry\] would work' "$WORK/l14.out" \
   && grep -q 'release-only: the run stops before the issue loop' "$WORK/l14.out"; then
  ok "L14: --release-only names no issue and no rework, and says why it stopped"
else
  bad "L14: --release-only stops before the issue loop" "$(flat "$WORK/l14.out")"
fi

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: at the WIP ceiling every tick works, reworks, or releases one unmovable PR through a coded exit"
