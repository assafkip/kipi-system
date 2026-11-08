#!/usr/bin/env bash
# At 5 open fleet-own PRs in a repo, the worker reworks the oldest one it can
# move instead of starting a new issue (ASK-3826, RULE-2026-11-06-B).
#
# THE DEFECT, MEASURED 2026-11-06. No WIP limit existed in linear-worker.sh.
# kipi-system held 8 open sana/* PRs while the worker kept starting a fresh
# ready issue every tick: inflow 10 a day, and nothing made the oldest PR the
# next job. chief/cloud_worker.py:66 already had the rule (at 5 open own PRs,
# rework the oldest), added after 82 open sana/* PRs where "no fire went back
# to one". This suite is the port, held to the three traps the brief named:
#
#   1. LANE RACE. An orchestrated lane PR is fleet-own (sana/) but its ticket
#      was moved to In Progress by hand an hour ago and has no attempts-ledger
#      row. The ASK-3825 rule holds that ticket, so the rework pick must skip
#      its PR, never take it (case 2).
#   2. CAPPED PRs. A PR at the reviewer round cap gets no new review after a
#      push, so reworking it moves nothing. When every candidate is capped or
#      held, the worker starts no new issue and no rework round; it releases
#      the oldest one through its exit and names it in one line (ASK-3866,
#      RULE-2026-11-07-A; test-worker-wip-liveness.sh owns the release). It
#      never falls back to a new issue (case 3, dry and --apply).
#   3. ONLY FLEET-OWN PRs COUNT. lessons/weekly-* and a human fix/ branch do
#      not (case 4).
#
# WHAT IS REAL AND WHAT IS STUBBED. The real linear-worker.sh picker, the real
# linear-sync.py (started_hold_reason), the real pr-verdict-lib.sh (rework_gate,
# review_is_usable) run against a fixture Linear server (transport seam
# KIPI_LINEAR_API_URL) and a fixture review dir under KIPI_STATE_DIR. Stubbed:
# gh (answers from fixture files and logs every call), claude, codex, the
# reviewer, the notifier and the usage breaker. Nothing reaches real Linear,
# real GitHub or the live state dir.
#
# NEGATIVE SELF-TESTS (case 9). The cases run again against mutant copies of
# the scripts dir, one per rule, and each must go red.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_SCRIPTS="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKER="${KIPI_WORKER_UNDER_TEST:-$REPO_SCRIPTS/linear-worker.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; }

WORK="$(mktemp -d)"
trap 'kill "${SRV_PID:-}" 2>/dev/null; rm -rf "$WORK"' EXIT

# --- fixture Linear --------------------------------------------------------------
cat > "$WORK/fixture-server.py" <<'PY'
import json, os
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = os.environ["FIXTURE_LOG"]
# While this file exists the board has no queue-state ticket: the empty-queue world.
NO_FRESH = os.environ["NO_FRESH_FLAG"]
NOW = datetime.now(timezone.utc)
NAMES = {"backlog": "Backlog", "started": "In Progress"}


def ago(hours):
    return (NOW - timedelta(hours=hours)).isoformat().replace("+00:00", "Z")


def issue(ident, state, started_hours=None, labels=("owner:sana",)):
    return {"id": "uuid-" + ident, "identifier": ident, "title": "fixture " + ident,
            "description": "## Definition of Ready\nOutcome: x",
            "state": {"name": NAMES[state], "type": state},
            "startedAt": ago(started_hours) if started_hours is not None else None,
            "project": {"name": "kipi-system"}, "team": {"id": "team-fixture"},
            "labels": {"nodes": [{"id": "lab-" + l, "name": l} for l in labels]}}


def pr(branch, n):
    return {"url": "https://github.com/x/kipi-system/pull/%d" % n,
            "metadata": {"status": "open", "branch": branch, "number": n}}


MONTH = 24 * 30
# Board order is pick order before ASK-3826: ASK-900 FIRST, so the pre-change
# dry run (--limit 1) names it. It is the only queue-state ticket a run can pick.
TICKETS = [issue("ASK-900", "backlog")]
for n in (901, 902, 903, 904, 905, 907, 931, 932, 933, 941, 951, 952):
    TICKETS.append(issue("ASK-%d" % n, "started", MONTH))
TICKETS.append(issue("ASK-911", "started", 1))       # THE LANE RACE: an hour old, no ledger row
TICKETS.append(issue("ASK-921", "started", 1))       # a lane on a slug branch
TICKETS.append(issue("ASK-942", "started", MONTH, labels=("owner:sana", "needs-scope")))
BOARD = {i["identifier"]: i for i in TICKETS}
ATTACH = {"uuid-ASK-%d" % n: [pr("sana/ask-%d" % n, n)]
          for n in (901, 902, 903, 904, 905, 911, 931, 932, 933, 941, 942, 951, 952)}
ATTACH["uuid-ASK-921"] = [pr("sana/ask-921-lane-slug", 921)]
# Two open PRs on one ticket: its own and a lane PR. Reworking the own one
# would race the lane, so the hold is NOT excused.
ATTACH["uuid-ASK-907"] = [pr("sana/ask-907", 907), pr("sana/ask-907-lane", 9070)]


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
                fh.write(json.dumps({"mutation": q[:80], "variables": v}) + "\n")
            return self.reply({"errors": [{"message": "fixture: this suite allows no writes"}]})
        if "teams(" in q:
            return self.reply({"data": {"teams": {"nodes": [{"id": "team-fixture", "key": "ASK"}]}}})
        if "attachments(" in q:
            return self.reply({"data": {"issue": {"attachments": {"nodes": ATTACH.get(v.get("id"), [])}}}})
        if "issues(filter" in q:
            nodes = [i for i in BOARD.values()
                     if not (i["identifier"] == "ASK-900" and os.path.exists(NO_FRESH))]
            return self.reply({"data": {"issues": {"nodes": nodes,
                               "pageInfo": {"hasNextPage": False, "endCursor": None}}}})
        return self.reply({"errors": [{"message": "fixture: unknown query"}]})


srv = HTTPServer(("127.0.0.1", 0), H)
print(srv.server_port, flush=True)
srv.serve_forever()
PY
FIXLOG="$WORK/linear-writes.jsonl"; : > "$FIXLOG"
NO_FRESH="$WORK/no-fresh-issue"
FIXTURE_LOG="$FIXLOG" NO_FRESH_FLAG="$NO_FRESH" python3 "$WORK/fixture-server.py" > "$WORK/port" 2> "$WORK/server.err" &
SRV_PID=$!
for _ in $(seq 1 100); do PORT="$(cat "$WORK/port" 2>/dev/null)"; [ -n "${PORT:-}" ] && break; sleep 0.1; done
[ -n "${PORT:-}" ] || { echo "fixture server did not start: $(cat "$WORK/server.err")"; exit 1; }

# --- a real git skeleton, named for its project ----------------------------------
# Its origin reads as https://github.com/x/kipi-system.git, so the worker derives
# the slug x/kipi-system and asks for the open PRs scoped to it, the way every
# dispatch target is asked. insteadOf points that URL at a local bare repo, so
# the worker fetch never leaves the machine. make_skel <parent> local keeps the
# local-path origin: a repo with no GitHub slug (case 5b).
make_skel() {
  local parent="$1" skel="$1/kipi-system" mode="${2:-github}"
  mkdir -p "$parent"
  git init --quiet --bare "$parent/origin.git" && git -C "$parent/origin.git" symbolic-ref HEAD refs/heads/main
  git init --quiet "$skel"
  git -C "$skel" config user.email t@t; git -C "$skel" config user.name t
  mkdir -p "$skel/.claude"; printf '{}\n' > "$skel/.claude/settings.json"
  : > "$skel/seed"; git -C "$skel" add seed .claude/settings.json; git -C "$skel" commit --quiet -m seed
  git -C "$skel" remote add origin "$parent/origin.git"
  git -C "$skel" push --quiet -u origin HEAD:main 2>/dev/null
  if [ "$mode" = "github" ]; then
    git -C "$skel" config url."$parent/origin.git".insteadOf "https://github.com/x/kipi-system.git"
    git -C "$skel" remote set-url origin "https://github.com/x/kipi-system.git"
  fi
  printf '%s' "$skel"
}
SKEL="$(make_skel "$WORK/run")"
STATE="$WORK/state"; mkdir -p "$STATE/worktrees" "$STATE/pr-reviews"

# --- the attempts ledger: who the fleet has run ------------------------------------
# No row for ASK-911 and ASK-921: lane tickets the orchestrator moved by hand.
# ASK-941 has spent its 3 attempts.
python3 - "$STATE/linear-worker-attempts.json" <<'LEDGER'
import json, sys
rows = {"ASK-%d" % n: {"rounds": 1, "count": 1}
        for n in (901, 902, 903, 904, 905, 907, 931, 932, 933, 942, 951, 952)}
rows["ASK-941"] = {"rounds": 3, "count": 3, "why": "fixture: three failed runs"}
json.dump(rows, open(sys.argv[1], "w"), indent=2)
LEDGER

# --- review records, written with the SAME key derivation the worker uses ---------
# shellcheck disable=SC1091
. "$REPO_SCRIPTS/repo-slug-lib.sh"
# shellcheck disable=SC1091
. "$REPO_SCRIPTS/pr-verdict-lib.sh"
SLUG="$(slug_for_repo "$SKEL" "$SKEL/instance-registry.json")"
[ "$SLUG" = "x/kipi-system" ] \
  && ok "fixture self-test: the skeleton reads as GitHub repo x/kipi-system, so the PR count is scoped" \
  || bad "fixture self-test: the skeleton has a GitHub slug" "slug_for_repo gave '$SLUG'"
GHDIR="$WORK/gh"; mkdir -p "$GHDIR"
review() {  # review <pr> <verdict> <usable-rounds>
  local pr="$1" verdict="$2" rounds="$3" key sha r
  key="$(artifact_key "$SLUG" "$pr")"
  sha="$(printf '%040d' "$pr")"
  printf '{"verdict": "%s", "head_sha": "%s", "degraded": false}\n' "$verdict" "$sha" \
    > "$STATE/pr-reviews/$key.verdict.json"
  for r in $(seq 1 "$rounds"); do
    printf 'VERDICT: %s\n\nFINDINGS:\nmajor|fixture finding %s|x.sh:%s\nEND FINDINGS\n' \
      "$verdict" "$r" "$r" > "$STATE/pr-reviews/$key-2026100${r}-000000.md"
  done
  printf 'CLEAN\n' > "$GHDIR/merge-$pr"; printf '%s\n' "$sha" > "$GHDIR/head-$pr"
}
for n in 901 902 903 904 905 907 911 921 941 942 952; do review "$n" "REQUEST CHANGES" 1; done
for n in 931 932 933; do review "$n" "REQUEST CHANGES" 3; done   # at the round cap
review 951 "APPROVE" 1                                            # approved at its head
rm -f "$STATE/pr-reviews/$(artifact_key "$SLUG" 952).verdict.json" \
      "$STATE/pr-reviews/$(artifact_key "$SLUG" 952)-"*.md        # never reviewed

# Positive self-test of the fixture: the capped PR really reads as 3 usable rounds
# to the reviewer's own predicate, or case 3 would pass for the wrong reason.
CAPPED_ROUNDS=0
for f in "$STATE/pr-reviews/$(artifact_key "$SLUG" 931)-"*.md; do
  review_is_usable "$f" && CAPPED_ROUNDS=$((CAPPED_ROUNDS + 1))
done
[ "$CAPPED_ROUNDS" = "3" ] \
  && ok "fixture self-test: PR #931 holds 3 rounds the reviewer counts as usable" \
  || bad "fixture self-test: PR #931 holds 3 usable rounds" "review_is_usable counted $CAPPED_ROUNDS"

# --- gh: answers from fixture files, logs every call --------------------------------
STUBS="$WORK/bin"; mkdir -p "$STUBS"
cat > "$STUBS/gh" <<'GH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$WIP_GH_DIR/calls.log"
A="$*"
case "$A" in
  *"pr list"*"--state open"*)
    if [ "${WIP_GH_FAIL:-0}" = "1" ]; then echo "gh: HTTP 502: Bad Gateway" >&2; exit 1; fi
    cat "$WIP_PRS_FILE" 2>/dev/null; exit 0 ;;
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

# One line per open PR, the shape `gh pr list ... -q` prints: number, head
# branch, created, url. Oldest first by created date regardless of line order.
prs() {  # prs <file> <number:branch:created-day>...
  local out="$1"; shift; : > "$out"
  local spec n br day
  for spec in "$@"; do
    n="${spec%%:*}"; br="${spec#*:}"; br="${br%:*}"; day="${spec##*:}"
    printf '%s\t%s\t2026-10-%sT12:00:00Z\thttps://github.com/x/kipi-system/pull/%s\n' "$n" "$br" "$day" "$n" >> "$out"
  done
}

run_worker() {  # run_worker <worker-script> <prs-file> <out-file> [worker args...]
  local w="$1" prsf="$2" out="$3"; shift 3
  : > "$GHDIR/calls.log"
  PATH="$STUBS:$PATH" \
    KIPI_SKEL="${WIP_SKEL:-$SKEL}" KIPI_STATE_DIR="${WIP_STATE:-$STATE}" \
    KIPI_LINEAR_API_URL="http://127.0.0.1:$PORT/graphql" \
    KIPI_LINEAR_API_KEY="fixture-key-not-a-secret" \
    KIPI_PR_REVIEWER="bash $WORK/fake-reviewer.sh" \
    KIPI_CODEX_RUNNER="bash $WORK/fake-codex.sh" KIPI_SECOND_RUNNER_FALLBACK="" \
    KIPI_USAGE_BREAKER_CMD="true" KIPI_NOTIFY="$WORK/notify.sh" \
    WIP_GH_DIR="$GHDIR" WIP_PRS_FILE="$prsf" \
    bash "$w" "$@" > "$out" 2>&1
}
flat() { tr '\n' '|' < "$1" | cut -c1-900; }
picks() { grep -oE '\[dry\] would work ASK-[0-9]+' "$1" | grep -oE 'ASK-[0-9]+' | tr '\n' ' '; }

# Scenario PR sets.
prs "$WORK/s1.prs"  "905:sana/ask-905:15" "901:sana/ask-901:01" "902:sana/ask-902:02" \
                    "903:sana/ask-903:03" "904:sana/ask-904:04"
prs "$WORK/s2.prs"  "911:sana/ask-911:01" "902:sana/ask-902:02" "903:sana/ask-903:03" \
                    "904:sana/ask-904:04" "905:sana/ask-905:05"
prs "$WORK/s3.prs"  "931:sana/ask-931:01" "932:sana/ask-932:02" "933:sana/ask-933:03" \
                    "941:sana/ask-941:04" "942:sana/ask-942:05" "921:sana/ask-921-lane-slug:06"
prs "$WORK/s4.prs"  "960:lessons/weekly-2026-10-01:01" "961:fix/a-human-branch:01" \
                    "902:sana/ask-902:02" "903:sana/ask-903:03" "904:sana/ask-904:04" "905:sana/ask-905:05"
prs "$WORK/s4b.prs" "921:sana/ask-921-lane-slug:01" "902:sana/ask-902:02" "903:sana/ask-903:03" \
                    "904:sana/ask-904:04" "905:sana/ask-905:05"
prs "$WORK/s7.prs"  "951:sana/ask-951:01" "952:sana/ask-952:02" "907:sana/ask-907:03" \
                    "903:sana/ask-903:04" "904:sana/ask-904:05"

echo "== worker WIP ceiling (worker under test: $WORKER)"

# ============================================================================
# 1. THE DoR CHECK: 5 open fleet-own PRs and a ready issue
# ============================================================================
run_worker "$WORKER" "$WORK/s1.prs" "$WORK/s1.out" --limit 1
if grep -q '\[dry\] would work ASK-900 ' "$WORK/s1.out"; then
  bad "case 1 (DoR check): at 5 open own PRs the fresh issue ASK-900 is NOT started" \
      "THE DEFECT: the worker started a new issue at the ceiling. Output: $(flat "$WORK/s1.out")"
else
  ok "case 1 (DoR check): at 5 open own PRs the fresh issue ASK-900 is NOT started"
fi
if grep -qE '\[dry\] would work ASK-901 \(attempt 2/3\) -- WIP ceiling: rework PR #901, the oldest movable of 5 open own PRs \(ceiling 5\)' "$WORK/s1.out"; then
  ok "case 1b (DoR check): the pick is the OLDEST own PR, #901 (ASK-901), named on the dry line"
else
  bad "case 1b (DoR check): the pick names the oldest own PR #901" "picks: $(picks "$WORK/s1.out"). Output: $(flat "$WORK/s1.out")"
fi
NEXT="$(grep -oE '\[dry\] would work ASK-[0-9]+' "$WORK/s1.out" | grep -oE 'ASK-[0-9]+' | head -1)"
[ "$NEXT" = "ASK-901" ] \
  && ok "case 1c: kipi-dispatch.sh's own grep reads the rework pick as ASK-901 (converge reworks sana/ask-901)" \
  || bad "case 1c: the dispatcher grep reads the rework pick" "it read '${NEXT:-nothing}'"
grep -q 'WIP ceiling: 5 open own PRs in .* (ceiling 5). No new issue starts' "$WORK/s1.out" \
  && ok "case 1d: the run says the ceiling is why no new issue starts" \
  || bad "case 1d: the ceiling line" "$(grep -i 'wip' "$WORK/s1.out" | head -3 | tr '\n' '|')"

# 1e. THE EMPTY QUEUE (PR #613 review round 1, major 2). With nothing ready the
# run used to end at "nothing ready" above the WIP block, so a pile at the
# ceiling waited on DoR inflow and no fire went back to one.
: > "$NO_FRESH"
run_worker "$WORKER" "$WORK/s1.prs" "$WORK/s1e.out" --limit 1
rm -f "$NO_FRESH"
if grep -q 'worker: 0 ready issue' "$WORK/s1e.out" \
   && grep -q '\[dry\] would work ASK-901 .*-- WIP ceiling: rework PR #901' "$WORK/s1e.out"; then
  ok "case 1e: with an empty queue, a pile at the ceiling still drains: the oldest own PR #901 is the pick"
else
  bad "case 1e: an empty queue still drains the pile" "picks: $(picks "$WORK/s1e.out"). Output: $(flat "$WORK/s1e.out")"
fi

# 1f. THE SET-ASIDE LIST REACHES THE REWORK PICK (ASK-3993, PR #651 round 1,
# major). The dispatcher sets an issue aside for a day after a branch refusal.
# At the ceiling the rework feed replaces the fresh pool, so without this the
# set-aside ASK-901 came straight back as the pick and was refused every tick.
KIPI_PICK_EXCLUDE="ASK-901" run_worker "$WORKER" "$WORK/s1.prs" "$WORK/s1f.out" --limit 1
if [ "$(picks "$WORK/s1f.out")" = "ASK-902 " ] && ! grep -q 'would work ASK-901' "$WORK/s1f.out"; then
  ok "case 1f: at the ceiling a set-aside issue is passed over; the next oldest own PR #902 is the pick"
else
  bad "case 1f: the rework pick honours the set-aside list" "picks: $(picks "$WORK/s1f.out"). Output: $(flat "$WORK/s1f.out")"
fi

# ============================================================================
# 2. TRAP 1, THE LANE RACE: the oldest own PR's ticket was started an hour ago
# ============================================================================
run_worker "$WORKER" "$WORK/s2.prs" "$WORK/s2.out" --limit 1
if grep -q '\[dry\] would work ASK-911 ' "$WORK/s2.out"; then
  bad "case 2 (trap 1): the PR of a ticket started 1 hour ago is skipped" \
      "THE DEFECT: the rework pick took ASK-911 and would race a live lane"
else
  ok "case 2 (trap 1): the PR of a ticket started 1 hour ago (no ledger row) is skipped"
fi
grep -q '\[dry\] would work ASK-902 .*-- WIP ceiling: rework PR #902' "$WORK/s2.out" \
  && ok "case 2b: the pick moves on to the next oldest, #902 (ASK-902)" \
  || bad "case 2b: the pick is #902" "picks: $(picks "$WORK/s2.out"). Output: $(flat "$WORK/s2.out")"
grep -q '#911 (ASK-911): ticket held: started 1.0h ago, inside the 24h window' "$WORK/s2.out" \
  && ok "case 2c: the passed-over line names #911 and the ASK-3825 24h window" \
  || bad "case 2c: the skip reason for #911" "$(grep 'passed over' "$WORK/s2.out")"

# ============================================================================
# 3. TRAP 2: every candidate is capped or held -> start NOTHING, say why
# ============================================================================
run_worker "$WORKER" "$WORK/s3.prs" "$WORK/s3.out" --limit 1
if grep -q '\[dry\] would work' "$WORK/s3.out"; then
  bad "case 3 (trap 2): with every candidate capped or held, nothing starts" \
      "THE DEFECT: picks: $(picks "$WORK/s3.out")"
else
  ok "case 3 (trap 2): with every candidate capped or held, nothing starts (no new issue, no capped PR)"
fi
# Since ASK-3866 the stop names its action: the oldest PR goes through its exit.
STOP="$(grep 'WIP ceiling: 6 open own PRs' "$WORK/s3.out" | grep 'No new issue starts, and none of the 6')"
if [ "$(printf '%s\n' "$STOP" | grep -c .)" = "1" ] && grep -q 'releases the oldest one through its exit: PR #931 (cap)' <<<"$STOP" \
   && grep -q '3 at the review round cap' <<<"$STOP" && grep -q '\[dry\] would release PR #931 (cap)' "$WORK/s3.out"; then
  ok "case 3b: ONE line names the count (6), the 3 capped PRs and the release of the oldest, PR #931 (cap)"
else
  bad "case 3b: one stop line naming the count and the release" "stop line(s): ${STOP:-none}. Output: $(flat "$WORK/s3.out")"
fi
grep -q '#931 (ASK-931): at the review round cap (3 of 3 usable rounds)' "$WORK/s3.out" \
  && ok "case 3c: the capped PR is named with the reviewer's own count" \
  || bad "case 3c: #931 named as capped" "$(grep 'passed over' "$WORK/s3.out")"
grep -q '#941 (ASK-941): 3/3 attempts spent' "$WORK/s3.out" \
  && grep -q '#942 (ASK-942): ticket labelled needs-scope' "$WORK/s3.out" \
  && grep -q '#921 (sana/ask-921-lane-slug): lane branch' "$WORK/s3.out" \
  && ok "case 3d: the held PRs are named: attempt cap, needs-scope, lane branch" \
  || bad "case 3d: held PRs named" "$(grep 'passed over' "$WORK/s3.out")"

# The same world under --apply: nothing may run, nothing may be written.
rm -f "$WORK/claude-ran.log"; : > "$FIXLOG"
run_worker "$WORKER" "$WORK/s3.prs" "$WORK/s3-apply.out" --apply --limit 1
if [ ! -e "$WORK/claude-ran.log" ] && ! grep -q '^.* start ASK-' "$WORK/s3-apply.out" \
   && grep -q 'release PR #931 (cap): closed' "$WORK/s3-apply.out"; then
  ok "case 3e: under --apply the ceiling starts no agent run either"
else
  bad "case 3e: --apply at the ceiling starts nothing" \
      "claude ran: $(cat "$WORK/claude-ran.log" 2>/dev/null | head -2). Output: $(flat "$WORK/s3-apply.out")"
fi
[ ! -s "$FIXLOG" ] && ok "case 3f: the --apply stop wrote nothing to Linear" \
                   || bad "case 3f: no Linear writes" "$(cat "$FIXLOG")"

# 3g. THE FIRST LIVE DRY RUN'S SCAR. Its state dir linked pr-reviews as a
# symlink, plain BSD find did not descend it, #543 read as 0 rounds instead of
# 3, and the capped PR was picked. The reviewer counts with a glob, which
# follows the link, so the worker must count the same set either way.
LSTATE="$WORK/state-linked"; mkdir -p "$LSTATE"
cp "$STATE/linear-worker-attempts.json" "$LSTATE/"
ln -s "$STATE/worktrees" "$LSTATE/worktrees"; ln -s "$STATE/pr-reviews" "$LSTATE/pr-reviews"
WIP_STATE="$LSTATE" run_worker "$WORKER" "$WORK/s3.prs" "$WORK/s3g.out" --limit 1
if ! grep -q '\[dry\] would work' "$WORK/s3g.out" && grep -q '3 at the review round cap' "$WORK/s3g.out"; then
  ok "case 3g: a symlinked reviews dir still reads the capped PRs as capped"
else
  bad "case 3g: a symlinked reviews dir reads the cap" "picks: $(picks "$WORK/s3g.out"). Output: $(flat "$WORK/s3g.out")"
fi

# ============================================================================
# 4. TRAP 3: only fleet-own PRs count
# ============================================================================
run_worker "$WORKER" "$WORK/s4.prs" "$WORK/s4.out" --limit 1
grep -q '\[dry\] would work ASK-900 ' "$WORK/s4.out" \
  && ok "case 4 (trap 3): 4 sana/ PRs plus a lessons and a human PR is under the ceiling; ASK-900 is picked" \
  || bad "case 4 (trap 3): lessons and human PRs do not count" "picks: $(picks "$WORK/s4.out"). Output: $(flat "$WORK/s4.out")"
grep -q 'WIP: 4 open own PRs in .* (ceiling 5)' "$WORK/s4.out" \
  && ok "case 4b: the run reports 4 open own PRs, not 6" \
  || bad "case 4b: the count line" "$(grep -i 'wip' "$WORK/s4.out" | head -3 | tr '\n' '|')"

# A lane PR on a sana/ slug branch IS fleet-own, so it counts, but the worker
# commits only onto sana/<id> (converge.sh:123), so it is never the pick.
run_worker "$WORKER" "$WORK/s4b.prs" "$WORK/s4b.out" --limit 1
grep -q '\[dry\] would work ASK-902 .*-- WIP ceiling: rework PR #902' "$WORK/s4b.out" \
  && ! grep -q '\[dry\] would work ASK-900 ' "$WORK/s4b.out" \
  && ok "case 4c: a sana/ lane PR counts toward the ceiling but is never the rework pick" \
  || bad "case 4c: lane PR counts, is not picked" "picks: $(picks "$WORK/s4b.out"). Output: $(flat "$WORK/s4b.out")"

# ============================================================================
# 5. An uncounted pile is not a pile under the ceiling
# ============================================================================
WIP_GH_FAIL=1 run_worker "$WORKER" "$WORK/s1.prs" "$WORK/s5.out" --limit 1
if ! grep -q '\[dry\] would work' "$WORK/s5.out" \
   && grep -q 'WIP ceiling: could not count the open own PRs' "$WORK/s5.out"; then
  ok "case 5: when gh cannot list PRs, nothing starts and the run says why"
else
  bad "case 5: a failed PR count starts nothing" "picks: $(picks "$WORK/s5.out"). Output: $(flat "$WORK/s5.out")"
fi

# 5c. A STOP NOBODY IS TOLD ABOUT IS A SILENT HALT (PR #613 review round 1,
# major 1). The failed count pages ONCE per outage, carries gh's own words,
# keeps them off stdout (kipi-dispatch.sh greps it for "authentication"), and a
# good count re-arms the page for the next outage.
GSTATE="$WORK/state-gh"; mkdir -p "$GSTATE"
cp "$STATE/linear-worker-attempts.json" "$GSTATE/"
ln -s "$STATE/worktrees" "$GSTATE/worktrees"; ln -s "$STATE/pr-reviews" "$GSTATE/pr-reviews"
: > "$WORK/pages.log"
WIP_STATE="$GSTATE" WIP_GH_FAIL=1 run_worker "$WORKER" "$WORK/s1.prs" "$WORK/s5c-1.out" --limit 1
WIP_STATE="$GSTATE" WIP_GH_FAIL=1 run_worker "$WORKER" "$WORK/s1.prs" "$WORK/s5c-2.out" --limit 1
P1="$(grep -c 'could not count the open PRs' "$WORK/pages.log")"
if [ "$P1" = "1" ] && grep -q 'gh said: gh: HTTP 502: Bad Gateway' "$WORK/pages.log"; then
  ok "case 5c: two failed counts in one outage page once, and the page carries gh's own words"
else
  bad "case 5c: one page per outage, with gh's words" "pages: $P1. Log: $(tr '\n' '|' < "$WORK/pages.log" | cut -c1-500)"
fi
if grep -q 'HTTP 502' "$WORK/s5c-1.out"; then
  bad "case 5c-b: gh's words stay off stdout" "stdout carried them: $(grep 'HTTP 502' "$WORK/s5c-1.out")"
else
  ok "case 5c-b: gh's words stay off stdout, where kipi-dispatch.sh greps for a Linear outage"
fi
WIP_STATE="$GSTATE" run_worker "$WORKER" "$WORK/s1.prs" "$WORK/s5c-3.out" --limit 1
WIP_STATE="$GSTATE" WIP_GH_FAIL=1 run_worker "$WORKER" "$WORK/s1.prs" "$WORK/s5c-4.out" --limit 1
P2="$(grep -c 'could not count the open PRs' "$WORK/pages.log")"
[ "$P2" = "2" ] \
  && ok "case 5c-c: a good count ends the outage, so the next failure pages again" \
  || bad "case 5c-c: a good count re-arms the page" "pages after outage, recovery, outage: $P2"
# The empty queue too: the uncounted pile still pages with nothing ready.
GSTATE2="$WORK/state-gh2"; mkdir -p "$GSTATE2"; cp "$STATE/linear-worker-attempts.json" "$GSTATE2/"
: > "$WORK/pages.log"; : > "$NO_FRESH"
WIP_STATE="$GSTATE2" WIP_GH_FAIL=1 run_worker "$WORKER" "$WORK/s1.prs" "$WORK/s5c-5.out" --limit 1
rm -f "$NO_FRESH"
[ "$(grep -c 'could not count the open PRs' "$WORK/pages.log")" = "1" ] \
  && ok "case 5c-d: with an empty queue a failed count still pages" \
  || bad "case 5c-d: empty queue, failed count, page" "$(flat "$WORK/s5c-5.out")"

# 5b. A repo with no GitHub slug: an unscoped gh call would bind to the cwd and
# count SOME OTHER repo (the first run of test-worker-project-scope.sh counted
# the real kipi-system PRs for a fixture). Not asked, and the run says so.
NOSLUG_SKEL="$(make_skel "$WORK/noslug" local)"
WIP_SKEL="$NOSLUG_SKEL" run_worker "$WORKER" "$WORK/s1.prs" "$WORK/s5b.out" --limit 1
if grep -q '\[dry\] would work ASK-900 ' "$WORK/s5b.out" && ! grep -q -- '--state open' "$GHDIR/calls.log" \
   && grep -q 'has no GitHub slug, so its open PRs are not counted' "$WORK/s5b.out"; then
  ok "case 5b: a repo with no GitHub slug takes no unscoped PR count and says why"
else
  bad "case 5b: no slug, no unscoped count" "picks: $(picks "$WORK/s5b.out"); gh calls: $(tr '\n' '|' < "$GHDIR/calls.log"). Output: $(flat "$WORK/s5b.out")"
fi

# ============================================================================
# 6. --issue is a driver override (converge, the redrives): no ceiling, no count
# ============================================================================
run_worker "$WORKER" "$WORK/s1.prs" "$WORK/s6.out" --issue ASK-900 --limit 1
if grep -q '\[dry\] would work ASK-900 ' "$WORK/s6.out" && ! grep -q -- '--state open' "$GHDIR/calls.log"; then
  ok "case 6: an explicit --issue is not second-guessed and no PR count is taken"
else
  bad "case 6: --issue bypasses the ceiling" "picks: $(picks "$WORK/s6.out"); gh calls: $(tr '\n' '|' < "$GHDIR/calls.log")"
fi

# ============================================================================
# 7. Movable means a worker round would change something
# ============================================================================
run_worker "$WORKER" "$WORK/s7.prs" "$WORK/s7.out" --limit 1
grep -q '\[dry\] would work ASK-903 .*-- WIP ceiling: rework PR #903' "$WORK/s7.out" \
  && ok "case 7: approved-at-head, never-reviewed and a ticket with a second open PR are passed over; #903 is picked" \
  || bad "case 7: the pick is #903" "picks: $(picks "$WORK/s7.out"). Output: $(flat "$WORK/s7.out")"
grep -q '#951 (ASK-951): approved at its head' "$WORK/s7.out" \
  && grep -q '#952 (ASK-952): no recorded review verdict' "$WORK/s7.out" \
  && grep -q '#907 (ASK-907): ticket held: open PR https://github.com/x/kipi-system/pull/' "$WORK/s7.out" \
  && ok "case 7b: each passed-over PR says why" \
  || bad "case 7b: reasons named" "$(grep 'passed over' "$WORK/s7.out")"

# ============================================================================
# 8. Dry runs write nothing
# ============================================================================
: > "$FIXLOG"
run_worker "$WORKER" "$WORK/s1.prs" "$WORK/s8.out" --limit 1
[ ! -s "$FIXLOG" ] && ok "case 8: a dry run at the ceiling wrote nothing to Linear" \
                   || bad "case 8: no Linear writes on a dry run" "$(cat "$FIXLOG")"

# ============================================================================
# 9. NEGATIVE SELF-TESTS: each rule above can fail
# ============================================================================
MUT="$WORK/mut/scripts"; mkdir -p "$WORK/mut"
cp -R "$REPO_SCRIPTS" "$MUT"
mutate() {  # mutate <old> <new>: one exact replacement in the mutant worker
  python3 - "$MUT/linear-worker.sh" "$1" "$2" <<'PY'
import sys
p, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(p).read()
assert s.count(old) == 1, "mutation anchor not found exactly once: " + old
open(p, "w").write(s.replace(old, new))
PY
}
restore() { cp "$REPO_SCRIPTS/linear-worker.sh" "$MUT/linear-worker.sh"; }

# 9a. no ceiling: case 1 must go red.
if mutate 'len(own) >= WIP_CEILING' 'len(own) >= 10 ** 6'; then
  run_worker "$MUT/linear-worker.sh" "$WORK/s1.prs" "$WORK/m.out" --limit 1
  grep -q '\[dry\] would work ASK-900 ' "$WORK/m.out" \
    && ok "mutant killed: without the ceiling the fresh issue ASK-900 starts, so case 1 can go red" \
    || bad "mutant 9a survived" "picks: $(picks "$WORK/m.out")"
else
  bad "mutant 9a: anchor" "the ceiling compare moved"
fi
restore

# 9b. no ticket rule: case 2 must go red.
if mutate 'r["kind"], r["hold"] = rework_hold(r["issue"], r["url"])' 'r["kind"], r["hold"] = "", ""'; then
  run_worker "$MUT/linear-worker.sh" "$WORK/s2.prs" "$WORK/m.out" --limit 1
  grep -q '\[dry\] would work ASK-911 ' "$WORK/m.out" \
    && ok "mutant killed: without the ASK-3825 ticket rule the lane PR #911 is picked, so case 2 can go red" \
    || bad "mutant 9b survived" "picks: $(picks "$WORK/m.out")"
else
  bad "mutant 9b: anchor" "the ticket rule call moved"
fi
restore

# 9c. no round-cap check: case 3 must go red.
if mutate '[ "$rounds" -ge "$REVIEW_MAX_ROUNDS" ]' '[ "$rounds" -ge 999 ]'; then
  run_worker "$MUT/linear-worker.sh" "$WORK/s3.prs" "$WORK/m.out" --limit 1
  grep -q '\[dry\] would work ASK-931 ' "$WORK/m.out" \
    && ok "mutant killed: without the round-cap check the capped PR #931 is picked, so case 3 can go red" \
    || bad "mutant 9c survived" "picks: $(picks "$WORK/m.out")"
else
  bad "mutant 9c: anchor" "the round-cap compare moved"
fi
restore

# 9d. every open PR counts: case 4 must go red.
if mutate 'r["branch"].startswith(OWN_PREFIX)' 'True'; then
  run_worker "$MUT/linear-worker.sh" "$WORK/s4.prs" "$WORK/m.out" --limit 1
  grep -q '\[dry\] would work ASK-900 ' "$WORK/m.out" \
    && bad "mutant 9d survived" "counting every PR still picked ASK-900" \
    || ok "mutant killed: counting lessons and human PRs puts 6 at the ceiling, so case 4 can go red"
else
  bad "mutant 9d: anchor" "the own-branch filter moved"
fi
restore

# 9e. plain find on the reviews dir: case 3g must go red.
if mutate 'find -H "$REVIEWS_DIR"' 'find "$REVIEWS_DIR"'; then
  WIP_STATE="$LSTATE" run_worker "$MUT/linear-worker.sh" "$WORK/s3.prs" "$WORK/m.out" --limit 1
  grep -q '\[dry\] would work ASK-931 ' "$WORK/m.out" \
    && ok "mutant killed: without find -H a symlinked reviews dir hides the cap and #931 is picked, so case 3g can go red" \
    || bad "mutant 9e survived" "picks: $(picks "$WORK/m.out")"
else
  bad "mutant 9e: anchor" "the reviews-dir find moved"
fi
restore

# 9f. no slug guard: case 5b must go red (the unscoped count reads the stub pile).
if mutate 'if [ -z "$ONLY_ISSUE" ] && [ -z "$TARGET_SLUG" ]; then' 'if false; then'; then
  WIP_SKEL="$NOSLUG_SKEL" run_worker "$MUT/linear-worker.sh" "$WORK/s1.prs" "$WORK/m.out" --limit 1
  grep -q '\[dry\] would work ASK-900 ' "$WORK/m.out" \
    && bad "mutant 9f survived" "without the slug guard the slug-less repo still picked ASK-900" \
    || ok "mutant killed: without the slug guard an unscoped count reads another pile, so case 5b can go red"
else
  bad "mutant 9f: anchor" "the slug guard moved"
fi
restore

# 9g. no page on a failed count: case 5c must go red.
if mutate 'if env_alert_claim "$WIP_COUNT_CLAIM" "$ENV_OUTAGE_MAX_AGE"; then' 'if false; then'; then
  MG="$WORK/state-m9g"; mkdir -p "$MG"; cp "$STATE/linear-worker-attempts.json" "$MG/"; : > "$WORK/pages.log"
  WIP_STATE="$MG" WIP_GH_FAIL=1 run_worker "$MUT/linear-worker.sh" "$WORK/s1.prs" "$WORK/m.out" --limit 1
  grep -q 'could not count the open PRs' "$WORK/pages.log" \
    && bad "mutant 9g survived" "a page was sent with the page call cut out" \
    || ok "mutant killed: without the page a failed count is a silent halt, so case 5c can go red"
else
  bad "mutant 9g: anchor" "the page call moved"
fi
restore

# 9h. the early exit back above the ceiling: case 1e must go red.
if mutate 'if [ "$READY_COUNT" = "0" ] && [ "${WIP_HOLDS:-0}" != "1" ]; then' 'if [ "$READY_COUNT" = "0" ]; then'; then
  : > "$NO_FRESH"
  run_worker "$MUT/linear-worker.sh" "$WORK/s1.prs" "$WORK/m.out" --limit 1
  rm -f "$NO_FRESH"
  grep -q '\[dry\] would work ASK-901 ' "$WORK/m.out" \
    && bad "mutant 9h survived" "the empty queue still drained with the old early exit" \
    || ok "mutant killed: with the old early exit an empty queue never drains, so case 1e can go red"
else
  bad "mutant 9h: anchor" "the early exit moved"
fi
restore

# 9i. no release on a good count: case 5c-c must go red.
if mutate '[ "${WIP_COUNTED:-0}" = "1" ] && env_alert_release "$WIP_COUNT_CLAIM"' 'true'; then
  MI="$WORK/state-m9i"; mkdir -p "$MI"; cp "$STATE/linear-worker-attempts.json" "$MI/"; : > "$WORK/pages.log"
  WIP_STATE="$MI" WIP_GH_FAIL=1 run_worker "$MUT/linear-worker.sh" "$WORK/s1.prs" "$WORK/m.out" --limit 1
  WIP_STATE="$MI" run_worker "$MUT/linear-worker.sh" "$WORK/s1.prs" "$WORK/m.out" --limit 1
  WIP_STATE="$MI" WIP_GH_FAIL=1 run_worker "$MUT/linear-worker.sh" "$WORK/s1.prs" "$WORK/m.out" --limit 1
  [ "$(grep -c 'could not count the open PRs' "$WORK/pages.log")" = "2" ] \
    && bad "mutant 9i survived" "the second outage paged with the release cut out" \
    || ok "mutant killed: without the release the next outage pages nobody, so case 5c-c can go red"
else
  bad "mutant 9i: anchor" "the release moved"
fi
restore

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: at the WIP ceiling the worker reworks the oldest movable own PR, never a lane PR, never a capped one, and never starts a new issue"
