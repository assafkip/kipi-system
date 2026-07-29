#!/usr/bin/env bash
# The autonomous worker: pick a ready Linear issue, do it, leave a trail, open a PR.
#
# WHAT IT IS
# ----------
# The engine is not new. open-loops-heartbeat.sh already runs `claude -p` headless
# under launchd with a timeout, Slack-on-failure and a step audit. This gives that
# same shape a better queue: Linear instead of a local JSON file.
#
# THE FOUR THINGS IT WILL NOT DO
# ------------------------------
# 1. It will not MERGE. It opens a PR and stops. Merging is the founder's.
# 2. It will not CLOSE an issue. Closing runs through /issue-verify and
#    /issue-closeout, which refuse without receipts. A worker that could close its
#    own work would route around the only gates that make the board trustworthy.
# 3. It will not touch an issue labelled `owner:assaf` -- that label exists to mark
#    a founder decision, and an agent resolving one is the failure it guards.
# 4. It will not touch an issue with no Definition of Ready. Without a DoR the
#    agent is guessing, and "agents produce plausible garbage in the background" is
#    the outcome this whole design exists to avoid. linear-dor-drafter.py fills
#    those in nightly; this worker consumes them.
#
# EXITS (audited against .claude/rules/loop-exits.md)
#   turn cap / no progress / budget  -> token-guard.py inside the claude run
#   wall clock                       -> TIMEOUT per issue, below
#   error threshold                  -> MAX_ATTEMPTS per issue with backoff, and
#                                       infra failures do NOT burn an issue's budget
#   human interrupt                  -> destructive-op-deny.sh; and it cannot merge
#   goal met                         -> the PR + the closeout gates, not this script
#
# EXIT CODES
#   0  ran (or had nothing to run). A caller may treat this as healthy.
#   1  usage error
#   9  INFRA: the environment is down (git fetch failed) and the run did NO
#      work. Paged on the way out. Distinct from 1 so a caller can tell a dead
#      environment from a bad invocation.
#
# WHY INFRA FAILURE IS COUNTED SEPARATELY
# ---------------------------------------
# An expired auth token or a Linear outage is not the issue's fault. Counting it
# against the issue would burn a real task's retry budget on an environment
# problem and mark good work STUCK. Same distinction self-healing-retry.md rule 5
# draws, and the same one OpenSwarm's scheduler makes.
#
# Usage:  linear-worker.sh [--apply] [--limit N] [--issue ASK-123]
# Dry by default: prints what it would pick and stops.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# KIPI_SKEL / KIPI_STATE_DIR are TEST-ISOLATION SEAMS, same discipline as
# KIPI_LINEAR_CLAIMS / KIPI_LINEAR_LEDGER / KIPI_LINEAR_QUEUE. Without them a
# suite that drives this script end-to-end would create real worktrees and real
# sana/* branches in the founder's checkout and stomp the live attempts ledger --
# so the ordering this script's whole correctness rests on could only ever be
# asserted by grepping its source. Unset in production; the defaults are the
# real skeleton and the real state dir.
SKEL="${KIPI_SKEL:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
CLAIM="$SCRIPT_DIR/linear-claim.py"
SYNC="$SCRIPT_DIR/linear-sync.py"
# Overridable so the suite can read back WHAT was paged without paging the
# founder, and so "did anyone get told?" is answered by a file instead of by a
# grep of this source. Same seam and same name converge.sh already uses -- one
# convention, not two. Default is always the real Slack sink.
NOTIFY="${KIPI_NOTIFY:-$SCRIPT_DIR/slack-notify.sh}"
# The reviewer is injectable for the SAME reason converge.sh injects its worker:
# "what does this script do when the REVIEWER is down" is a real 3am state, and
# it is the state PR #30's review round 2 found two defects in (an unbounded
# drift loop, and a run reporting CONVERGED off the stale record the same run had
# just refused to trust). Asserting it against the real reviewer would cost an
# adversarial review's model spend per case, so the branch would stay untested --
# which is how it shipped wrong. Default is always the real reviewer.
REVIEWER_CMD="${KIPI_PR_REVIEWER:-bash $SCRIPT_DIR/pr-review-agent.sh}"
STATE_DIR="${KIPI_STATE_DIR:-$HOME/.config/kipi}"
ATTEMPTS="$STATE_DIR/linear-worker-attempts.json"
LOG="$STATE_DIR/linear-worker.log"
REVIEWS_DIR="$STATE_DIR/pr-reviews"
# Verdict semantics shared with pr-review-agent.sh -- one extractor, one gate.
. "$SCRIPT_DIR/pr-verdict-lib.sh"

MAX_ATTEMPTS=3
# Conflict rounds are capped SEPARATELY from failed attempts (ASK-212).
# MAX_ATTEMPTS only counts runs where `claude` exits non-zero, and the cited
# failure mode is an agent that exits 0 having done the wrong thing -- so it
# would never bound a rebase that cannot succeed.
# 2: a rebase either works on the first honest attempt or the conflict needs a
# human. Round 3 has never been the one that lands it here.
#
# WHAT THIS CAP DOES *NOT* DO (PR #25 review, finding 4): it does not buy a
# converged PR an exemption from review. A rebase REWRITES the diff, so the
# stored APPROVE no longer describes what is on the branch, and the round below
# re-reviews it like any other push. Skipping that would ship a force-pushed
# diff nobody ever read under an approval earned by a different diff. What the
# separate counter buys is that a rebase cannot spend MAX_ATTEMPTS and cannot
# loop forever -- two budgets, two questions, neither one a licence to skip the
# reviewer. `rounds` therefore counts every review this worker triggered,
# rebases included, and `conflict_rounds` says how many of the current streak
# were rebases.
MAX_CONFLICT_ROUNDS=2
# Drift rounds (gate 40) are capped SEPARATELY again, for the reason
# pr-verdict-lib.sh already states about gate 30: "Making APPROVE non-terminal
# opens an unbounded rework path ... every round writes a permanent Linear
# comment on an object that cannot be deleted ... The caller caps conflict rounds
# on its own budget." Gate 40 ALSO makes APPROVE non-terminal, and when ASK-219
# first wired it this caller gave it no budget at all. Measured on that build:
# 5 scheduled runs against one persistently-failing reviewer spent 5 model
# rounds, wrote 10 permanent Linear comments, paged nobody, and left
# conflict_rounds -- the only budget in the file -- at 0.
#
# 2, matching the conflict cap: a drift clears the moment ANY review writes a
# record pinned to the current head, so two rounds that both failed to produce
# one means the reviewer is down or the head keeps moving under it. Neither is
# fixed by a third round; both need a human.
MAX_DRIFT_ROUNDS=2
# A FIFTH key (ASK-245, PR #43 review round 3), and the reason is the one the
# four above keep restating in different words: MAX_ATTEMPTS counts runs where
# `claude` exits NON-ZERO, and the rework path's normal failure is an agent that
# exits 0 having left the PR just as red as it found it. `bump_attempt` has one
# call site and it is on the non-zero branch, so on that path the ledger file is
# never even created and the same issue is re-announced at "attempt 1/3" every
# heartbeat, forever. The DoR anticipated exactly this -- "if MAX_ATTEMPTS does
# not cover this path, bound it here and say so" -- and the first cut of this
# issue did not.
#
# COUNTED PER DISPATCH, not per round and not per failed run: kipi-dispatch.sh
# records one against the issue at the moment it hands the candidate to converge
# (--rework-dispatched below). That is the unit that costs money -- one dispatch
# is up to MAX_ROUNDS agent+reviewer pairs.
#
# 2, matching the conflict and drift caps: two full converge runs that both
# failed to make the PR green means the next thing it needs is a human, not a
# third run. At MAX_ROUNDS=3 that is already up to 12 model sessions spent on one
# PR. LIFETIME, not consecutive -- unlike conflict/drift there is no state a
# reader could trust as "the streak ended": the rework dispatch itself moves the
# head, so a head-change clear would reset the budget on every single dispatch
# and cap nothing. So it stops, pages ONCE, and prints the one command that
# hands it back to the loop. Same contract MAX_ATTEMPTS already has: marked
# stuck, a human decides next.
MAX_REWORK_DISPATCHES=2
TIMEOUT_SECONDS=1800
LIMIT=1
APPLY=0
ONLY_ISSUE=""
REWORK_DISPATCHED=""

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --limit) shift; LIMIT="${1:-1}" ;;
    --issue) shift; ONLY_ISSUE="${1:-}" ;;
    --rework-dispatched) shift; REWORK_DISPATCHED="${1:-}" ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
  shift || true
done

export SCRIPT_DIR
mkdir -p "$STATE_DIR"
TS() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "$(TS) $*" | tee -a "$LOG"; }

# --- the rework-dispatch ledger (ASK-245, PR #43 review round 3) -------------
# Deliberately defined HERE and not beside its four siblings 200 lines down: the
# --rework-dispatched short-circuit has to answer before the `git fetch` and the
# Linear query, because recording a dispatch that already happened must not
# depend on the network being up. Its siblings carry a pointer to this block.
#
# ONE WRITER. kipi-dispatch.sh is the only caller and it does not touch the JSON
# itself -- it shells this mode. Two processes hand-editing one ledger with
# different key conventions is the defect class this repo keeps closing, and the
# dispatcher had no business learning this file's schema.
rework_dispatches_for() { python3 -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: d={}
print(d.get(sys.argv[1],{}).get('rework_dispatches',0))" "$1"; }

bump_rework_dispatch() { python3 -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: d={}
e=d.setdefault(sys.argv[1],{}); e['rework_dispatches']=e.get('rework_dispatches',0)+1
e['last_rework_dispatch']=sys.argv[2]
json.dump(d,open('$ATTEMPTS','w'),indent=2)" "$1" "$(TS)"; }

if [ -n "$REWORK_DISPATCHED" ]; then
  bump_rework_dispatch "$REWORK_DISPATCHED" || {
    say "FATAL: could not record a rework dispatch against $REWORK_DISPATCHED in $ATTEMPTS"
    exit 1
  }
  say "recorded rework dispatch $(rework_dispatches_for "$REWORK_DISPATCHED")/$MAX_REWORK_DISPATCHES for $REWORK_DISPATCHED"
  exit 0
fi

# A distinct session token per run. The claim lock keys collisions on (agent,
# session), so without a unique token two overlapping runs would look like the
# same session and BOTH be granted -- the exact scar the lock exists to stop.
SESSION="worker-$(date +%s)-$$"
AGENT="sana"

# Wall clock, exit 4 of loop-exits.md. macOS ships NEITHER `timeout` nor `gtimeout`
# unless coreutils is installed, and the old fallback here was an empty string --
# i.e. silently no wall clock at all, which is the runaway-agent case this exit
# exists for. Never degrade a safety exit to a warning: implement it in bash.
run_bounded() {  # run_bounded <seconds> <cmd...>
  local secs="$1"; shift
  "$@" &
  local job=$!
  ( sleep "$secs"; kill -0 "$job" 2>/dev/null && {
      echo "$(TS) TIMEOUT after ${secs}s; killing pid $job" >>"$LOG"
      kill -TERM "$job" 2>/dev/null
      sleep 5
      kill -KILL "$job" 2>/dev/null
    } ) &
  local watchdog=$!
  wait "$job"; local rc=$?
  kill "$watchdog" 2>/dev/null   # cancel the watchdog if the job finished first
  wait "$watchdog" 2>/dev/null
  return "$rc"
}

# --- FETCH ONCE, BEFORE ANY WORKTREE EXISTS ---------------------------------
# ASK-211 (sp-28ced3d6). This script used to contain no `git fetch` at all: it
# cut every worktree from whatever local origin/main ref happened to be lying
# around, so the agent was dispatched against a base that could be arbitrarily
# old. Observed 2026-07-27 -- ASK-150 was sent to resolve a conflict against
# main, merged 3b60af0, and the conflict survived because main was already
# 72c782d. The agent did the right thing to the wrong target and two rounds
# were burned.
#
# ONCE PER RUN, not per issue: origin does not move meaningfully inside one run,
# and a 50-issue board would otherwise pay 50 network round-trips to learn the
# same thing. Placed above the picker so no code path can create a worktree
# before it.
#
# A fetch failure is environmental (self-healing-retry.md rule 5), so it stops
# on attempt 1 and is NOT counted against any issue. Continuing would be worse
# than stopping: the whole point is that a stale base silently produces
# plausible work aimed at the wrong target, and the run could not push or open
# a PR against an unreachable origin anyway.
#
# IT PAGES AND EXITS 9, it does not stop quietly (PR #22 review round 3,
# finding 1 -- major). The first version of this guard was `say` + `exit 0`,
# which made an expired credential at 3am byte-for-byte indistinguishable from a
# healthy run with nothing ready: same rc, no Slack, one line in a log nobody
# reads. The issue never became stuck either, because MAX_ATTEMPTS only counts
# DISPATCHED runs. Rule 5 says surface it IMMEDIATELY, and a log line is not
# surfacing.
#
# 9, not 1: 1 is the usage error above, and a caller has to be able to tell an
# environment that is down from a worker that was invoked wrong.
if ! git -C "$SKEL" fetch --quiet origin 2>>"$LOG"; then
  say "INFRA: git fetch failed in $SKEL. Stopping before any worktree is cut from a stale base."
  bash "$NOTIFY" "worker: git fetch failed in $SKEL -- the run did NO work. Check credentials/network." 2>/dev/null || true
  exit 9
fi

# --- pick ready issues ------------------------------------------------------
PICKED="$(python3 - "$ONLY_ISSUE" <<'PY'
import importlib.util, json, os, sys, pathlib
here = pathlib.Path(os.environ["SCRIPT_DIR"])
spec = importlib.util.spec_from_file_location("ls", here / "linear-sync.py")
ls = importlib.util.module_from_spec(spec); spec.loader.exec_module(ls)
only = (sys.argv[1] or "").strip()

Q = """query($t:ID!,$a:String){issues(filter:{team:{id:{eq:$t}}},first:250,after:$a){
 nodes{id identifier title description state{name type} project{name}
       labels{nodes{name}}} pageInfo{hasNextPage endCursor}}}"""
try:
    tid = ls.graphql('query{teams(filter:{key:{eq:"ASK"}}){nodes{id}}}',{})["teams"]["nodes"][0]["id"]
except Exception as exc:
    print(json.dumps({"infra_error": str(exc)[:200]})); raise SystemExit(0)

issues, after = [], None
while True:
    p = ls.graphql(Q, {"t": tid, "a": after})["issues"]
    issues += p["nodes"]
    if not p["pageInfo"]["hasNextPage"]: break
    after = p["pageInfo"]["endCursor"]

# The owner and spec filters are shared by BOTH sets, so they are ONE function
# rather than two copies. A rework candidate that skipped them would hand the
# loop the founder's own issues (owner:assaf) and issues with no spec to work
# against -- the two refusals `ready` has always encoded.
def mine(i):
    labels = {l["name"] for l in i["labels"]["nodes"]}
    if "owner:assaf" in labels:      return False   # founder decision, hands off
    if "owner:sana" not in labels:   return False
    d = i.get("description") or ""
    return "## Definition of Ready" in d or "Definition of Ready" in d

def ready(i):
    return mine(i) and i["state"]["type"] in ("backlog", "unstarted")

# REWORK CANDIDATES (ASK-245). An issue flips to `started` the moment a worker
# takes it, so `ready` -- backlog/unstarted only -- permanently excludes every
# issue the loop has ever touched. That is correct as a CONCURRENCY guard
# (kipi-dispatch.sh loop-exit 5) and wrong as a PERMANENT one: when the rounds
# run out or the converge process dies, the issue sits In Progress with a red PR
# and nothing picks it back up. Measured 2026-07-29: 5 PRs stranded that way.
#
# A SEPARATE SET, NEVER FOLDED INTO `ready`. The fresh-work path cuts a worktree
# from origin/main (the BASE block below), which for an issue that already has a
# PR would hand the agent a tree holding none of the PR's commits and then tell
# it to force-push. `started` and backlog/unstarted are disjoint state types, so
# an issue can never appear in both lists.
#
# LIVENESS IS NOT DECIDED HERE. "Has an open PR that is failing or unreviewed"
# and "has no live converge" are answers only `gh` and the process table can
# give; this block sees Linear rows and nothing else. It publishes the set that
# is ELIGIBLE by owner, spec and state -- the caller filters the rest.
def rework(i):
    return mine(i) and i["state"]["type"] == "started"

pool = [i for i in issues if ready(i)]
rew  = [i for i in issues if rework(i)]
if only:
    # An explicitly named issue bypasses classification entirely, exactly as
    # before: converge drives this path and has already decided. Emptying the
    # rework list keeps that path byte-identical to its pre-ASK-245 behaviour.
    pool = [i for i in issues if i["identifier"] == only]
    rew = []
def brief(i):
    return {"id": i["identifier"], "title": i["title"],
            "project": (i.get("project") or {}).get("name")}
print(json.dumps({"ready": [brief(i) for i in pool],
                  "rework": [brief(i) for i in rew],
                  "total_open": len(issues)}))
PY
)"

INFRA="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("infra_error",""))' 2>/dev/null)"
if [ -n "$INFRA" ]; then
  say "INFRA: linear unreachable ($INFRA). Not counted against any issue."
  exit 0
fi

READY_COUNT="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["ready"]))')"
say "worker: $READY_COUNT ready issue(s) (owner:sana, has a DoR, not owner:assaf)"

# `.get("rework", [])` and not `["rework"]`: the test suites stub this picker's
# stdout (test-linear-worker-fetch.sh feeds it a hand-written `{"ready":[...]}`),
# and a hard key would turn every one of those fixtures into a traceback.
REWORK_IDS="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;[print(i["id"]) for i in json.load(sys.stdin).get("rework",[])]' 2>/dev/null)"
REWORK_COUNT="$(printf '%s' "$REWORK_IDS" | grep -c . || true)"
# A POOL, NOT THE ANSWER (PR #43 review round 3, major). This count used to read
# "N rework candidate(s)", which is what the operator sees at 3am -- and it was
# wrong by exactly the population the review found: a started issue whose PR has
# already MERGED is in this pool and is not a candidate. Linear rows alone cannot
# tell those apart, so the honest line here is the pool, and the announcement
# block below (which can ask `gh`) reports what actually survived.
say "worker: $REWORK_COUNT started issue(s) in the rework pool (owner:sana, has a DoR). Eligibility -- an OPEN PR, a review verdict the apply loop will act on, budget left -- is decided at the announcement."

if [ "$READY_COUNT" = "0" ] && [ "$REWORK_COUNT" = "0" ]; then
  say "nothing ready. The DoR drafter feeds this queue; check kipi dor."
  exit 0
fi

attempts_for() { python3 -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: d={}
print(d.get(sys.argv[1],{}).get('count',0))" "$1"; }

bump_attempt() { python3 -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: d={}
e=d.setdefault(sys.argv[1],{'count':0}); e['count']+=1; e['last']=sys.argv[2]; e['why']=sys.argv[3]
json.dump(d,open('$ATTEMPTS','w'),indent=2)" "$1" "$(TS)" "$2"; }

# A FIFTH counter, `rework_dispatches`, lives with the same siblings but is
# DEFINED FAR ABOVE (search: rework-dispatch ledger) because kipi-dispatch.sh
# shells it via --rework-dispatched, which must answer before the fetch and the
# Linear query.

# --- conflict-round ledger (ASK-212) ----------------------------------------
# Its own counter in the same file, deliberately NOT `count` (failed attempts)
# and NOT `rounds` (review rounds). Three different budgets answering three
# different questions; sharing one would let a rebase attempt spend a review
# round, which is the thing the separate cap exists to prevent.
conflict_rounds_for() { python3 -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: d={}
print(d.get(sys.argv[1],{}).get('conflict_rounds',0))" "$1"; }

bump_conflict_round() { python3 -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: d={}
e=d.setdefault(sys.argv[1],{}); e['conflict_rounds']=e.get('conflict_rounds',0)+1
e['last_conflict']=sys.argv[2]
json.dump(d,open('$ATTEMPTS','w'),indent=2)" "$1" "$(TS)"; }

# CONSECUTIVE, NOT LIFETIME (PR #25 review, finding 3). Nothing used to clear
# these keys, so the cap counted every conflict the issue ever had -- including
# ones a rebase successfully fixed -- and the third conflict across an issue's
# life was permanently un-dispatchable AND silent, because `conflict_paged` was
# already true so it did not even page. A PR that merges cleanly again ended its
# streak, so the streak's counters go with it.
#
# Only on a STATED "CLEAN": empty means gh failed and UNKNOWN means GitHub is
# still computing, and refilling a budget from a state nobody actually read is
# how an unresolvable conflict gets infinite rounds. Clearing conflict_paged
# alongside is deliberate: a NEW conflict streak after the PR was healthy is new
# information, not a repeat of the page the founder already got.
clear_conflict_rounds() { python3 -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: raise SystemExit(0)
e=d.get(sys.argv[1])
if not e or not (e.get('conflict_rounds') or e.get('conflict_paged')): raise SystemExit(0)
for k in ('conflict_rounds','conflict_paged','last_conflict'): e.pop(k,None)
json.dump(d,open('$ATTEMPTS','w'),indent=2)" "$1"; }

# --- drift-round ledger (ASK-219, PR #30 review round 2) ---------------------
# A FOURTH key, deliberately not `count`, not `rounds`, not `conflict_rounds`.
# Four budgets, four questions. A drift round that spent the conflict budget
# would leave a real conflict un-dispatchable later; one that spent `count`
# would mark good work STUCK after three rounds that all ran fine.
drift_rounds_for() { python3 -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: d={}
print(d.get(sys.argv[1],{}).get('drift_rounds',0))" "$1"; }

bump_drift_round() { python3 -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: d={}
e=d.setdefault(sys.argv[1],{}); e['drift_rounds']=e.get('drift_rounds',0)+1
e['last_drift']=sys.argv[2]
json.dump(d,open('$ATTEMPTS','w'),indent=2)" "$1" "$(TS)"; }

# CONSECUTIVE, NOT LIFETIME -- the same scar clear_conflict_rounds carries (PR
# #25 finding 3). Without this the cap would count every drift in the issue's
# life, so the third genuine drift would be permanently un-dispatchable AND
# silent, because drift_paged was already true.
#
# Cleared on "the gate did not say 40", which is the ONE reader's own answer
# rather than a second sha comparison living out here. 40 is the only code that
# means drift, so anything else means there is none right now: a review has
# repinned the record to the head, or the verdict is no longer approving, or the
# record is gone. Re-deriving that comparison in this file is exactly the
# two-readers-of-one-input defect pr-verdict-lib.sh exists to close.
clear_drift_rounds() { python3 -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: raise SystemExit(0)
e=d.get(sys.argv[1])
if not e or not (e.get('drift_rounds') or e.get('drift_paged')): raise SystemExit(0)
for k in ('drift_rounds','drift_paged','last_drift'): e.pop(k,None)
json.dump(d,open('$ATTEMPTS','w'),indent=2)" "$1"; }

# Returns 0 the FIRST time <flag> is claimed for this issue and 1 every time
# after, so a page fires exactly once instead of once per scheduled run. A
# repeated "still stuck" every cycle is noise, and noise trains the reader to
# skim the real pages (founder-notifications.md). The flag is claimed in the
# same write that reports it, so two runs cannot both read "not paged yet".
# Takes the flag NAME so every once-only page in this script shares one
# mechanism instead of each stuck-state inventing its own convention.
claim_page_once() { python3 -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: d={}
e=d.setdefault(sys.argv[1],{})
first = not e.get(sys.argv[2])
e[sys.argv[2]]=True
json.dump(d,open('$ATTEMPTS','w'),indent=2)
raise SystemExit(0 if first else 1)" "$1" "$2"; }

# Pops the two auto-merge page flags the moment the PR is SEEN armed. Same scar
# clear_conflict_rounds and clear_drift_rounds both carry (PR #25 finding 3): a
# once-only page with no clear is a page that fires once in an issue's LIFE, so
# the second time the state is real it is silent -- and silent is the failure
# this whole issue exists to kill. Only ever called on a STATED "armed": clearing
# off a state nobody could read would refill the budget from a guess.
clear_automerge_pages() { python3 -c "
import json,sys
try: d=json.load(open('$ATTEMPTS'))
except Exception: raise SystemExit(0)
e=d.get(sys.argv[1])
if not e or not (e.get('automerge_unarmed_paged') or e.get('automerge_unknown_paged')):
    raise SystemExit(0)
for k in ('automerge_unarmed_paged','automerge_unknown_paged'): e.pop(k,None)
json.dump(d,open('$ATTEMPTS','w'),indent=2)" "$1"; }

# --- arm auto-merge (ASK-222) ------------------------------------------------
# arm_automerge <pr-number> <dir>: make GitHub own the merge, and publish what
# that attempt actually reached. Sets $AUTOMERGE to armed | unarmed | unknown.
#
# ONE FUNCTION, TWO CALLERS, and that is the whole of PR #33 round 3's major.
# This logic lived inline at step 5, which only runs when a ROUND is dispatched.
# The gate above `continue`s on an approved, clean, non-drifted PR -- a PR with
# nothing left to do but merge, which is precisely the population this issue is
# named for -- four hundred lines before step 5 exists. So the done PRs were the
# ones nothing ever armed, and converge.sh Slacked "no human merge needed" over
# that state off a comment claiming otherwise. A second copy at the gate would
# have been two arms with drifting semantics; this is one.
#
# BEFORE the review at step 5, never after. `--auto` is not "merge now": GitHub
# holds the PR until every REQUIRED context is green, and `kipi/reviewer-approved`
# is ABSENT until the reviewer posts it (ASK-217). Arming afterwards would need
# something to come back once the review lands -- the same gap wearing a coat.
#
# BLAST RADIUS -- READ THIS BEFORE TOUCHING BRANCH PROTECTION. With this function
# in place, code reaches main with no human in the path, on a repo that fans out
# fleet-wide through `kipi update`. The only thing between a diff and main is the
# set of REQUIRED contexts on the branch. Remove `kipi/reviewer-approved` from
# that set and this becomes an unreviewed-merge machine. It was made required
# FIRST, and watched refusing on ABSENT and on FAILURE (PRs #27, #30), before
# this was allowed to exist. This worker still never merges anything: GitHub
# merges, and only once the required checks pass.
#
# THE PROBE'S rc IS PART OF ITS ANSWER (PR #33 review round 1, finding 3). `gh pr
# view` says true/false when it answers at all and an EMPTY STRING when it could
# not -- a rate limit, a dropped connection, an unattended schedule against a
# live API. Reading that empty string as "not armed" is how an ARMED PR earns a
# warning saying it will sit green forever plus a command already run. Three
# states are kept apart, never two: armed / unarmed / could not tell.
AUTOMERGE=""
arm_automerge() {
  local pr="$1" dir="$2" probe
  AUTOMERGE="unknown"
  # `gh pr merge --auto --squash ''` acts on whatever branch the cwd is on, so an
  # empty number is not "arm nothing", it is "arm something else".
  [ -n "$pr" ] || { AUTOMERGE=""; return 0; }
  # ASKED FOR, not armed-and-forgiven. This runs on the same PR every rework
  # round AND on every scheduled run for as long as the PR sits approved, so a
  # warning per pass would train the operator to skim the one that matters -- and
  # which exit code `gh pr merge` returns for an already-armed PR varies by
  # version. Asking makes the no-op a real no-op.
  if ! probe="$( cd "$dir" && gh pr view "$pr" --json autoMergeRequest \
                   -q '.autoMergeRequest != null' 2>>"$LOG" )"; then
    probe="unknown"
  fi
  if [ "$probe" = "true" ]; then
    AUTOMERGE="armed"
  elif ( cd "$dir" && gh pr merge --auto --squash "$pr" ) >/dev/null 2>&1; then
    AUTOMERGE="armed"
    say "$ISSUE: auto-merge armed on PR #$pr (GitHub merges it once every required check is green)"
  else
    # ASK THE STATE AGAIN BEFORE CRYING WOLF. `gh pr merge --auto` refuses for
    # reasons that are not "unarmed", and an already-armed PR is one of them.
    # The refusal alone cannot tell an armed PR from a broken one, so the PR is
    # asked what it IS. Only ever runs on this path.
    if ! probe="$( cd "$dir" && gh pr view "$pr" --json autoMergeRequest \
                     -q '.autoMergeRequest != null' 2>>"$LOG" )"; then
      probe="unknown"
    fi
    if [ "$probe" = "true" ]; then
      # It was already armed and the refusal WAS the no-op. Silent on purpose:
      # this is the healthy state, reached through a blip.
      AUTOMERGE="armed"
    elif [ "$probe" = "unknown" ]; then
      AUTOMERGE="unknown"
      # STILL AUDIBLE, but claiming only what can be backed. gh refused the arm
      # AND refused the state, so "it will sit green and unmerged" is a sentence
      # nothing here knows to be true -- and this may equally be a PR that is
      # fine. It pages anyway: this is the branch where the PR may really be
      # unarmed, and quieting it would re-create the stall one layer down.
      say "WARN: could not arm auto-merge on PR #$pr for $ISSUE and could not read its state either -- gh answered neither. If it sits green: gh pr merge --auto --squash $pr"
      if claim_page_once "$ISSUE" automerge_unknown_paged; then
        bash "$NOTIFY" "worker: $ISSUE PR #$pr -- gh could neither arm auto-merge nor read its state, so whether this PR merges itself is unknown. Needs a human to check: gh pr merge --auto --squash $pr" 2>/dev/null || true
      fi
    else
      AUTOMERGE="unarmed"
      # LOUD MEANS $NOTIFY, NOT $LOG (PR #33 review round 1, finding 1 -- major).
      # This was `say` alone, and `say` is `tee -a "$LOG"`: under the launchd
      # heartbeat that is a file nobody opens at 3am. This worker's channel for
      # "a human must do something" is `bash "$NOTIFY"`, used at five other sites
      # in this file, and this state is exactly that -- the message ends in the
      # command a human has to run. An unarmed PR is invisible by construction
      # (everything green, nothing merges, no signal), so a log-only warning does
      # not kill the silent stall, it relocates it.
      say "WARN: could not arm auto-merge on PR #$pr for $ISSUE -- it will sit green and unmerged until someone runs: gh pr merge --auto --squash $pr"
      if claim_page_once "$ISSUE" automerge_unarmed_paged; then
        bash "$NOTIFY" "worker: $ISSUE PR #$pr is NOT armed -- it goes green and sits there forever. Needs a human: gh pr merge --auto --squash $pr" 2>/dev/null || true
      fi
    fi
  fi
  # ONCE PER ISSUE, NOT PER RUN -- and the comment that used to sit here claimed
  # the opposite while calling the approved-but-blocked pages above its precedent
  # (PR #33 review round 3, finding 3). All three of those go through
  # claim_page_once. So does this now, because the alternative is worse than an
  # inaccurate comment: the gate caller below re-reaches this state on EVERY
  # scheduled run for as long as the PR sits there, so per-run paging is a page
  # every cycle, forever, for one fact that has not changed.
  #
  # NOT fatal on any path: the PR still stands, the review still runs, the exit
  # code is unchanged. The `( ... ) >/dev/null 2>&1` around the arm inside an
  # `if` is what keeps a refusal out of `$?`.
  [ "$AUTOMERGE" = "armed" ] && clear_automerge_pages "$ISSUE"
  # PUBLISHED, so the second reporter reads instead of asserts. converge.sh has
  # to tell the operator who merges this PR and cannot re-probe without becoming
  # a second reader of one input; asserting instead is what put "no human merge
  # needed" on PRs nothing had armed.
  record_automerge "$REVIEWS_DIR/pr-$pr.automerge" "$AUTOMERGE"
  return 0
}

# --- worktree positioning (ASK-212, PR #25 review finding 1) -----------------
# tree_holds_pr_head <tree> <branch>: true when everything on origin/<branch> is
# already reachable from the tree's HEAD -- i.e. a push from this tree destroys
# nothing. Compared against origin/<branch> rather than the API's headRefOid on
# purpose: origin/<branch> is exactly what a force-push overwrites, and reading
# it costs no network call that could fail open.
tree_holds_pr_head() {
  # A remote branch that does not exist has nothing to lose, so the invariant
  # ("hold everything origin/<branch> has") is vacuously satisfied. Same
  # reasoning as the start-point fallback below; without this the check would
  # refuse every round on a PR whose head branch was already pruned.
  git -C "$1" rev-parse --verify -q "origin/$2" >/dev/null 2>&1 || return 0
  git -C "$1" merge-base --is-ancestor "origin/$2" HEAD 2>/dev/null
}

# position_tree_on_pr_head <tree> <branch>: move a tree onto the PR's head
# without discarding anything that exists only there. Refuses (1) on a dirty
# working tree, or on any commit not reachable from origin/<branch> or
# origin/main -- the two places work can legitimately live. An unattended job
# does not get to throw away commits nobody has seen; when it cannot prove the
# move is lossless it declines the round and leaves the tree for a human.
# Sets POSITION_REFUSAL to the REASON when it declines, because "cannot be moved
# safely" covers four different states and the operator reading this at 3am has
# to know which one they are looking at.
POSITION_REFUSAL=""
position_tree_on_pr_head() {
  local tree="$1" branch="$2" dirty extra
  POSITION_REFUSAL=""
  # `.linear-claims.json` is EXCLUDED: the claim taken two lines above this call
  # writes that file into the very tree being judged, so counting it as local
  # work made every inherited tree unrepositionable -- turning a destructive
  # round into a permanently stalled issue plus a page. It is this worker's own
  # lock, never a human's work.
  dirty="$(git -C "$tree" status --porcelain 2>/dev/null | grep -v '\.linear-claims\.json$')"
  if [ -n "$dirty" ]; then
    POSITION_REFUSAL="the tree has uncommitted changes"
    return 1
  fi
  extra="$(git -C "$tree" rev-list HEAD --not "origin/$branch" origin/main 2>/dev/null)"
  if [ -n "$extra" ]; then
    POSITION_REFUSAL="the tree holds $(printf '%s\n' "$extra" | grep -c .) commit(s) that exist nowhere else"
    return 1
  fi
  if ! git -C "$tree" checkout -q -B "$branch" "origin/$branch" 2>>"$LOG"; then
    POSITION_REFUSAL="git could not check out origin/$branch (see $LOG)"
    return 1
  fi
  if ! tree_holds_pr_head "$tree" "$branch"; then
    POSITION_REFUSAL="the tree still does not contain origin/$branch after the checkout"
    return 1
  fi
}

# --- ANNOUNCE THE REWORK CANDIDATES (ASK-245) -------------------------------
# DRY ONLY, and that is the whole design. `kipi work` in dry mode is what
# kipi-dispatch.sh reads to choose the next issue (deliberately not a second
# Linear query -- one source of truth, asked politely), so this line is the seam
# that lets the heartbeat re-enter an issue it already started. The APPLY loop
# below is untouched: it still works the fresh set only, and a rework round is
# reached the way it always was, through `--issue ASK-n` from converge.
#
# THE ATTEMPTS CAP IS APPLIED HERE, NOT LEFT TO THE DISPATCH (loop-exit 7).
# MAX_ATTEMPTS already stops the work loop from touching an issue that has burned
# its budget -- but a candidate announced to the dispatcher has already cost a
# daily budget slot and a converge launch by the time that refusal fires, every
# heartbeat, forever. A permanently-red PR would eat the whole day's allowance
# doing nothing. Filtering the announcement is what makes the existing cap
# actually bound this path.
#
# AND THE CANDIDATE MUST HAVE AN OPEN PR (PR #43 review round 3, major -- and
# the DoR said so from the start: "has an open PR that is failing checks or
# unreviewed"). The first cut of this block asked Linear only. NOTHING in this
# repo moves an issue out of `started` when its PR merges -- the only stateId
# call sites are fleet-health-daily.py, linear-triage.py and
# linear-dor-drafter.py, none of them on the merge path -- so every issue the
# loop has ever FINISHED stays In Progress and was landing in this set forever.
# Worse than merely useless: with no open PR the apply loop's own
# `gh pr list --head` also comes back empty, so the whole severity-floor gate is
# skipped, BASE stays origin/main, and the agent is handed the FRESH-WORK prompt
# for work that is already on main. Observed live 2026-07-29: ASK-150, started,
# owner:sana, DoR, PR merged, no open PR -- one of 7 pool members that day.
#
# ONE READER OF "does this branch have an open PR": open_pr_for below is the same
# call the apply loop makes, shared rather than copied, because two readers of
# that question with drifting semantics is the exact thing the picker comment
# above refuses to do to `ready`.
open_pr_for() {  # open_pr_for <branch> -> prints the number, rc from gh
  gh pr list --head "$1" --state open --json number -q '.[0].number' 2>/dev/null
}
branch_for() { printf 'sana/%s' "$(echo "$1" | tr 'A-Z' 'a-z')"; }

# --- ONE READER OF "what would the severity floor say about this PR?" -------
# read_rework_gate <pr-number>
#   Sets GATE, GATE_NOTE, PR_VERDICT, MERGE_STATE, REVIEWED_SHA, CURRENT_SHA.
#   Reads only -- no ledger write, no page, no arm -- so the DRY announcement and
#   the APPLY loop can both ask, and only the apply loop acts.
#
# WHY THIS EXISTS (PR #43 review round 4, major). The announcement decided
# eligibility on owner, DoR, `started`, the two caps and an open PR. The apply
# loop the dispatch BUYS then applies a further gate thirty lines down
# (rework_gate): exits 10 (approved -- nothing to rework) and 20 (no recorded
# verdict -- no spec to rework against) both `continue` with no agent and no
# work. So a candidate could clear the announcement and still be a GUARANTEED
# no-op, having spent a daily budget slot, a rework budget slot and a converge
# launch. With MAX_REWORK_DISPATCHES lifetime and never cleared, two of those
# no-ops locked the issue out of the loop permanently and paged "its PR is still
# not green" about a PR that was, in one of the two cases, approved. Observed on
# live state the same day: of the five PRs this issue was filed to rescue, #34
# had no verdict record (gate 20) and #23 read APPROVE WITH NITS (gate 10).
#
# A SHARED READER, NOT A SECOND COPY. Two callers computing "the verdict, the
# merge state and the two shas" from their own `gh` calls is two readers of one
# input with drifting semantics -- the defect class pr-verdict-lib.sh exists to
# close, and the same argument round 3 used to make open_pr_for one function.
#
# FAIL-TOWARD-TERMINAL IS INHERITED, NOT RE-DECIDED. pr_merge_state and
# pr_head_sha return empty when gh cannot answer, and rework_gate documents what
# it does with that (a missed conflict costs one human diagnosis; a manufactured
# one costs the whole fleet). The dry path gets exactly that behaviour because it
# is the same function -- a hard gh failure has already broken the loop at
# open_pr_for above, which is the one place that refuses rather than degrades.
read_rework_gate() {  # read_rework_gate <pr-number>
  local pr="$1" latest
  PR_VERDICT="$(verdict_from_record "$REVIEWS_DIR/pr-$pr.verdict.json")"
  if [ -z "$PR_VERDICT" ]; then
    # Fallback for PRs reviewed before the verdict record existed: extract from
    # the newest review .md with the SAME extractor the reviewer uses.
    latest="$(ls -t "$REVIEWS_DIR/pr-$pr-"*.md 2>/dev/null | head -1)"
    [ -n "$latest" ] && PR_VERDICT="$(extract_verdict "$latest")"
  fi
  # MERGEABILITY IS HALF THE GATE (ASK-212). Read once, through the shared lib,
  # so the worker and the driver cannot drift on what "still merges" means.
  MERGE_STATE="$(pr_merge_state "$pr")"
  # THE VERDICT IS BOUND TO A SHA, NOT A PR NUMBER (ASK-216, armed by ASK-219).
  # This worker reuses ONE branch and ONE PR across every rework round, so before
  # the sha was passed, each push landing after an approval inherited that
  # approval silently. APPENDED, NEVER INSERTED: $MERGE_STATE keeps argument 2.
  REVIEWED_SHA="$(head_sha_from_record "$REVIEWS_DIR/pr-$pr.verdict.json")"
  CURRENT_SHA="$(pr_head_sha "$pr")"
  GATE_NOTE="$(rework_gate "$PR_VERDICT" "$MERGE_STATE" "$REVIEWED_SHA" "$CURRENT_SHA")"; GATE=$?
  return 0
}

# round_budget_exhausted <issue> <gate> -> rc 0 = this gate has no round left
# The OTHER half of "would the apply loop actually do work". Gates 30 and 40
# carry their own per-issue round budgets, and at the cap the apply loop skips
# exactly like gates 10 and 20 do -- so an announcement blind to them buys the
# same guaranteed no-op the review found, just two rungs further down. ONE owner
# of each comparison, called from both paths, for the same reason
# read_rework_gate is one function.
round_budget_exhausted() {
  case "$2" in
    30) [ "$(conflict_rounds_for "$1")" -ge "$MAX_CONFLICT_ROUNDS" ] ;;
    40) [ "$(drift_rounds_for "$1")"    -ge "$MAX_DRIFT_ROUNDS" ] ;;
    *)  return 1 ;;   # gate 0 spends the review-round budget, capped elsewhere
  esac
}

if [ "$APPLY" = "0" ] && [ -n "$REWORK_IDS" ]; then
  REWORK_ANNOUNCED=0
  while IFS= read -r RID; do
    [ -n "$RID" ] || continue
    RBRANCH="$(branch_for "$RID")"
    RPR="$(open_pr_for "$RBRANCH")"; GHRC=$?
    if [ "$GHRC" != "0" ]; then
      # NOT the same statement as "there is no PR". Falling through on a gh
      # failure would announce the whole pool -- merged issues included -- on
      # exactly the run where nothing can be verified. Refuse the path and SAY
      # so; kipi-dispatch.sh echoes this line into its own log so the quiet is
      # visible where the operator actually looks.
      say "[dry] rework: gh could not be asked which PRs are open, so NO rework candidate is announced this run (fresh work is unaffected)"
      break
    fi
    if [ -z "$RPR" ]; then
      say "[dry] skip rework $RID: no OPEN PR on $RBRANCH -- it is In Progress with nothing to rework (merged and never closed, or the PR was closed). Not fresh work either; a human moves it off In Progress."
      continue
    fi

    # THE SEVERITY FLOOR, ASKED HERE AND NOT LEFT TO THE ROUND WE PAID FOR
    # (PR #43 review round 4, major). See read_rework_gate above for why. A
    # dispatch is only ever spent on a PR the apply loop will actually work.
    read_rework_gate "$RPR"
    if [ "$GATE" = "10" ]; then
      # Approved, still merges, pinned to its own head: there is nothing to
      # rework. It waits on the merge, not on an agent.
      #
      # WHAT GOT QUIETER, SAID OUT LOUD: the apply loop's gate-10 branch also
      # ARMS auto-merge (PR #33's catch-up for PRs approved before that code
      # existed), and refusing the dispatch means nothing arms this one. Arming
      # from a DRY run is not the answer -- this block's one write is a page
      # claim, and the thing that lands code on main is not a side effect a dry
      # run may have. So the line names the arm state and the command instead,
      # and kipi-dispatch.sh echoes it into dispatch.log. The missing automated
      # arm for this population is captured, not swallowed: sp-fba8d194.
      RARM="$(automerge_from_record "$REVIEWS_DIR/pr-$RPR.automerge")"
      if [ "$RARM" = "armed" ]; then
        say "[dry] skip rework $RID: PR #$RPR verdict is '$PR_VERDICT' -- nothing to rework; auto-merge is armed, GitHub lands it once every required check is green."
      else
        say "[dry] skip rework $RID: PR #$RPR verdict is '$PR_VERDICT' -- nothing to rework; it waits on the merge. Nothing here records it as armed, so if it sits green: gh pr merge --auto --squash $RPR"
      fi
      continue
    fi
    if [ "$GATE" = "20" ]; then
      # No verdict means no spec. The DoR calls an "unreviewed" PR a candidate
      # and the apply loop refuses one -- that disagreement is real, and the
      # apply loop is right: a rework prompt with no review to rework against is
      # a guess. What the issue actually needs is a REVIEW, which is a different
      # dispatch kind than this one and is not in this issue's scope. So the
      # announcement stops paying a converge launch to rediscover it every
      # heartbeat and prints the one command that closes it. Captured so the
      # missing trigger is a ledger item rather than a comment: sp-ccdf677f.
      say "[dry] skip rework $RID: PR #$RPR has no recorded review verdict -- with no review there is no spec to rework against. Do: kipi review $RPR --issue $RID --post"
      continue
    fi
    if round_budget_exhausted "$RID" "$GATE"; then
      # Gates 30 and 40 are real work, but each has its own per-issue round
      # budget and the apply loop skips at the cap exactly as it does at 10 and
      # 20. PAGED FROM HERE, with the apply loop's OWN claim keys: refusing the
      # dispatch would otherwise take the page down with it, which is the
      # "silence bought by a fix" this round is about. One claim, whichever path
      # reaches it first, so the two can never double-page one fact.
      if [ "$GATE" = "30" ]; then
        say "[dry] skip rework $RID: PR #$RPR is '$PR_VERDICT' but $MERGE_STATE after $MAX_CONFLICT_ROUNDS rebase round(s) -- the apply loop refuses it, so no dispatch is spent rediscovering that. A human resolves this one."
        if claim_page_once "$RID" conflict_paged; then
          bash "$NOTIFY" "worker: $RID PR #$RPR is approved but still $MERGE_STATE after $MAX_CONFLICT_ROUNDS rebase round(s) - needs a human" 2>/dev/null || true
        fi
      else
        say "[dry] skip rework $RID: PR #$RPR is '$PR_VERDICT' at $REVIEWED_SHA but its head $CURRENT_SHA is still unreviewed after $MAX_DRIFT_ROUNDS re-review round(s) -- the apply loop refuses it, so no dispatch is spent rediscovering that. A human resolves this one."
        if claim_page_once "$RID" drift_paged; then
          bash "$NOTIFY" "worker: $RID PR #$RPR is approved at $REVIEWED_SHA but its head $CURRENT_SHA is still unreviewed after $MAX_DRIFT_ROUNDS re-review round(s) - unreviewed code sits at the head, needs a human" 2>/dev/null || true
        fi
      fi
      continue
    fi

    # THE CAPS COME AFTER THE GATE, and the order is the point (round 4). Both
    # cap lines make a claim about the PR -- "still not green", "marked stuck" --
    # and the rework cap PAGES it. Read before the gate, they fired on a PR that
    # had since been approved, so the operator's page said the opposite of the
    # truth. Asking the gate first costs a few `gh` calls per capped candidate
    # per heartbeat and buys a page that is true when it fires.
    RN="$(attempts_for "$RID")"
    if [ "$RN" -ge "$MAX_ATTEMPTS" ]; then
      say "[dry] skip rework $RID: $RN/$MAX_ATTEMPTS attempts already. Marked stuck; a human decides next."
      continue
    fi
    # LOOP-EXIT 7 FOR THIS PATH, and it is the announcement that has to apply it
    # for the same reason MAX_ATTEMPTS is applied here: a candidate announced to
    # the dispatcher has already cost a daily budget slot and a converge launch
    # by the time any later refusal fires.
    RD="$(rework_dispatches_for "$RID")"
    if [ "$RD" -ge "$MAX_REWORK_DISPATCHES" ]; then
      say "[dry] skip rework $RID: $RD/$MAX_REWORK_DISPATCHES rework dispatch(es) already and PR #$RPR still reads '$PR_VERDICT'. Marked stuck; a human decides next. To hand it back to the loop: python3 -c \"import json;p='$ATTEMPTS';d=json.load(open(p));d['$RID'].pop('rework_dispatches',None);d['$RID'].pop('rework_paged',None);json.dump(d,open(p,'w'),indent=2)\""
      # ONCE, not every 15 minutes (founder-notifications.md). Same mechanism the
      # conflict and drift caps use. This is the ONLY write a dry run makes, and
      # it exists so that going quiet is announced rather than merely happening:
      # a candidate that silently stops being dispatched is the failure this
      # whole issue is named for.
      if claim_page_once "$RID" rework_paged; then
        bash "$NOTIFY" "worker: $RID has had $MAX_REWORK_DISPATCHES rework dispatch(es) and PR #$RPR still reads '$PR_VERDICT' - the loop has stopped picking it up, it needs a human" 2>/dev/null || true
      fi
      continue
    fi
    say "[dry] would rework $RID (PR #$RPR, gate $GATE, attempt $((RN+1))/$MAX_ATTEMPTS, rework dispatch $((RD+1))/$MAX_REWORK_DISPATCHES)"
    REWORK_ANNOUNCED=$((REWORK_ANNOUNCED + 1))
  done <<EOF
$REWORK_IDS
EOF
  say "worker: $REWORK_ANNOUNCED of $REWORK_COUNT rework candidate(s) announced"
fi

DONE=0
printf '%s' "$PICKED" | python3 -c 'import json,sys;[print(i["id"]) for i in json.load(sys.stdin)["ready"]]' | \
while IFS= read -r ISSUE; do
  [ "$DONE" -ge "$LIMIT" ] && break

  N="$(attempts_for "$ISSUE")"
  if [ "$N" -ge "$MAX_ATTEMPTS" ]; then
    say "skip $ISSUE: $N/$MAX_ATTEMPTS attempts already. Marked stuck; a human decides next."
    continue
  fi

  if [ "$APPLY" = "0" ]; then
    say "[dry] would work $ISSUE (attempt $((N+1))/$MAX_ATTEMPTS)"
    DONE=$((DONE+1)); continue
  fi

  BRANCH="$(branch_for "$ISSUE")"

  # SEVERITY FLOOR GATE (deterministic, before any side effect). Only REQUEST
  # CHANGES or BLOCK starts another rework round: an approved PR waits on the
  # founder, and an unreviewed PR has no spec to rework against. The gate runs
  # BEFORE the claim and the Linear progress note on purpose -- a "Picked up"
  # note on a permanent Linear object followed by an immediate skip is a false
  # alarm, and false alarms train the reader to ignore the real notes.
  # SHARED with the rework announcement (open_pr_for), not a second copy of the
  # same `gh` call. Behaviour is unchanged: `gh pr list` already defaulted to
  # --state open, the flag is now just written down.
  EXISTING_PR="$(open_pr_for "$BRANCH")"
  REWORK=""
  CONFLICT_ROUND=""
  DRIFT_ROUND=""
  if [ -n "$EXISTING_PR" ]; then
    # THE SAME READER THE DRY ANNOUNCEMENT USES (PR #43 review round 4). The
    # verdict, the merge state and the two shas used to be gathered inline here
    # and nowhere else; the announcement now has to ask the identical question,
    # and two callers computing it from their own `gh` calls is the
    # two-readers-of-one-input defect pr-verdict-lib.sh exists to close. Sets
    # PR_VERDICT / MERGE_STATE / REVIEWED_SHA / CURRENT_SHA / GATE / GATE_NOTE
    # and writes nothing -- every side effect below stayed here, on the apply
    # path, which is the only path allowed to have them.
    read_rework_gate "$EXISTING_PR"
    # The streak ends the moment the PR merges cleanly again -- see
    # clear_conflict_rounds. Placed before the gate so it runs on every verdict,
    # not just the approving ones: a rework round that also resolves the
    # conflict ended the streak just as much.
    [ "$MERGE_STATE" = "CLEAN" ] && clear_conflict_rounds "$ISSUE"
    # THE NOTE IS SAID ON THE APPLY PATH ONLY. It explains a fallback the gate
    # took (a record with no head sha, a merge state gh would not answer) and it
    # is worth a line on the run that acts. The dry announcement runs on every
    # candidate every 15 minutes and its skip lines already carry the verdict and
    # both shas, so repeating the note there is heartbeat noise, not signal.
    [ -n "$GATE_NOTE" ] && say "$GATE_NOTE"
    # THE DRIFT STREAK ENDS ON A STATED NON-DRIFT, and nothing less. Two halves,
    # both of them scars:
    #
    # It sits ABOVE the branches because gates 10 and 20 both `continue`, so a
    # clear placed with the gate-40 block would never run on the one path that
    # matters most -- the review came back, repinned the record, the PR is
    # healthy again. (Observed RED as P5: drift_rounds stayed at 2 through a
    # full heal.)
    #
    # And it requires BOTH shas to have been read, because "the gate did not say
    # 40" is not the same statement as "there is no drift". `pr_head_sha` returns
    # empty on any `gh` failure and the gate then falls toward terminal and
    # returns 10 -- so the bare `!= 40` form treated a head NOBODY COULD READ as
    # proof the drift was over: it reset the streak AND popped `drift_paged`, and
    # one hiccup every other run was enough to make the cap unreachable and the
    # page never fire. clear_conflict_rounds 190 lines up refuses the identical
    # move for the identical reason -- "refilling a budget from a state nobody
    # actually read is how an unresolvable conflict gets infinite rounds"
    # (PR #30 review round 3, major 1; observed RED as P8: 9 runs, 6 rounds, 0
    # pages).
    #
    # This is a readability check on the gate's INPUTS, not a second sha
    # comparison: 40 is still the one reader's own answer to "is this drift?".
    # What it costs, stated: a blind run no longer refills the budget, so a drift
    # that quietly resolved during a blind window can reach the cap one round
    # early. That direction pages ("unreviewed code sits at the head, needs a
    # human") on a run where the gate really did say 40, so the page is true when
    # it fires -- louder, never quieter, which is the only safe way to be wrong
    # about a budget guarding unreviewed code.
    if [ "$GATE" != "40" ] && [ -n "$REVIEWED_SHA" ] && [ -n "$CURRENT_SHA" ]; then
      clear_drift_rounds "$ISSUE"
    fi
    if [ "$GATE" = "10" ]; then
      # ARM BEFORE THE SKIP (PR #33 review round 3, finding 1 -- major). This
      # branch is the population the issue is named for: approved, clean, pinned
      # to its own head, nothing left to do but merge. And it `continue`d four
      # hundred lines ABOVE the arm at step 5, so it was the one population
      # nothing armed -- while converge.sh paged "auto-merge lands it, no human
      # merge needed" across exactly this state. Arming here does not turn a done
      # PR into a round: no agent, no reviewer, no Linear comment. The skip stays
      # a skip; only the arm is new.
      arm_automerge "$EXISTING_PR" "$SKEL"
      # AND THE LINE SAYS WHO MERGES IT (round 3, finding 2 -- minor). Round 2
      # fixed this sentence at the closing line and at converge's and left this
      # third site saying "waiting on founder merge". For a PR armed a round ago,
      # nobody is waiting. Three outcomes, three sentences: a hedge covering all
      # of them would make the healthy case -- which is most of them -- unreadable.
      case "$AUTOMERGE" in
        armed)
          say "skip $ISSUE: PR #$EXISTING_PR verdict is '$PR_VERDICT' -- nothing to rework; auto-merge is armed, GitHub merges it once every required check is green" ;;
        unarmed)
          say "skip $ISSUE: PR #$EXISTING_PR verdict is '$PR_VERDICT' -- nothing to rework, but it is NOT armed and will sit green: gh pr merge --auto --squash $EXISTING_PR" ;;
        *)
          say "skip $ISSUE: PR #$EXISTING_PR verdict is '$PR_VERDICT' -- nothing to rework; gh could not read its auto-merge state this run, so check it landed: gh pr merge --auto --squash $EXISTING_PR" ;;
      esac
      continue
    fi
    if [ "$GATE" = "20" ]; then
      say "skip $ISSUE: PR #$EXISTING_PR has no recorded review verdict -- run: kipi review $EXISTING_PR --issue $ISSUE --post"
      continue
    fi
    if [ "$GATE" = "40" ]; then
      # STALE. The record approves a commit that is no longer the head, so nobody
      # has read the code that is actually there. Dispatch a RE-REVIEW round on
      # its OWN budget: the round ends in a review (step 5 below), and THAT review
      # writes a record pinned to the current head, which is the only thing that
      # clears this. When the reviewer is the thing that is down, nothing clears
      # it -- so the budget below is what stops a dead reviewer at 3am from
      # becoming an unbounded loop of model rounds and undeletable Linear
      # comments with nobody told (PR #30 review round 2, major 2).
      #
      # CONFLICT_ROUND stays empty on purpose even when the PR is also DIRTY. A
      # drift round is a review round, not a rebase round; spending the rebase
      # budget on it would leave a real conflict un-dispatchable later, and the
      # rebase prompt would tell the agent to force-push a diff nobody reviewed.
      DR="$(drift_rounds_for "$ISSUE")"
      # THE COMPARISON HAS ONE OWNER (round 4). The dry announcement refuses this
      # same state so the dispatch is never spent on it; a second copy of
      # `-ge $MAX_DRIFT_ROUNDS` here is how the two would drift apart and put the
      # guaranteed no-op back.
      if round_budget_exhausted "$ISSUE" 40; then
        say "skip $ISSUE: PR #$EXISTING_PR is '$PR_VERDICT' recorded at $REVIEWED_SHA but the head is $CURRENT_SHA, still never reviewed after $DR/$MAX_DRIFT_ROUNDS drift round(s) -- a human resolves this one."
        if claim_page_once "$ISSUE" drift_paged; then
          bash "$NOTIFY" "worker: $ISSUE PR #$EXISTING_PR is approved at $REVIEWED_SHA but its head $CURRENT_SHA is still unreviewed after $MAX_DRIFT_ROUNDS re-review round(s) - unreviewed code sits at the head, needs a human" 2>/dev/null || true
        fi
        continue
      fi
      # PLANNED, NOT SPENT (same discipline as CONFLICT_ROUND below). Everything
      # between here and the dispatch can still decline the run -- another
      # session's claim, a worktree that cannot be created, a tree that cannot be
      # positioned. Spending the budget here would let two runs skipped by a stale
      # claim burn it having re-reviewed nothing, then page a round count that
      # never happened.
      DRIFT_ROUND=$((DR + 1))
      say "$ISSUE: PR #$EXISTING_PR reads '$PR_VERDICT', but that verdict was recorded at $REVIEWED_SHA and the head is now $CURRENT_SHA -- the code at the head was never reviewed. Dispatching a round so it gets re-reviewed."
    fi
    if [ "$GATE" = "30" ]; then
      # Approved on content, but it no longer merges. Dispatch a REBASE round on
      # its own budget -- and stop dead once that budget is spent, because an
      # unresolvable conflict would otherwise rework forever and write a
      # permanent Linear comment on every round.
      CR="$(conflict_rounds_for "$ISSUE")"
      # ONE OWNER OF THE COMPARISON, same reason as the drift cap above.
      if round_budget_exhausted "$ISSUE" 30; then
        say "skip $ISSUE: PR #$EXISTING_PR is '$PR_VERDICT' but $MERGE_STATE after $CR/$MAX_CONFLICT_ROUNDS conflict round(s) -- a human resolves this one."
        if claim_page_once "$ISSUE" conflict_paged; then
          bash "$NOTIFY" "worker: $ISSUE PR #$EXISTING_PR is approved but still $MERGE_STATE after $MAX_CONFLICT_ROUNDS rebase round(s) - needs a human" 2>/dev/null || true
        fi
        continue
      fi
      # THE ROUND IS NOT SPENT HERE, only planned (PR #25 review, finding 2).
      # Everything between this line and the dispatch can still decline the run:
      # another session's claim, a worktree that cannot be created, a tree that
      # cannot be positioned on the PR's head. Spending the budget up here meant
      # two runs skipped by a stale claim -- converge.sh's own documented
      # 2026-07-27 scar, a SIGKILL or a sleeping laptop leaving a lock nobody
      # reclaims -- burned the whole budget having dispatched ZERO rebases, then
      # paged the founder a round count that never happened and locked the issue
      # out until someone hand-edited the ledger. The bump and the log line both
      # live at the dispatch site below, where the round actually happens.
      CONFLICT_ROUND=$((CR + 1))
    fi
  fi

  # 1. WORKTREE FIRST, and only then the claim -- in that order, because the
  # claim has to be taken from INSIDE the tree it protects.
  #
  # Scar from this worker's own first live run (ASK-150, 2026-07-26): it branched
  # in place and left the founder's main checkout sitting on sana/ask-150. The
  # claim lock stopped a concurrent AGENT from colliding, but it cannot stop the
  # worker yanking the FOUNDER's working tree out from under them mid-edit --
  # commit 53f2eeb, the scar this whole line of work started from. A worktree
  # makes that collision impossible by construction instead of merely detected.
  TREE="$STATE_DIR/worktrees/$(echo "$ISSUE" | tr 'A-Z' 'a-z')"
  # WHERE A NEW TREE STARTS DEPENDS ON WHETHER A PR ALREADY EXISTS (PR #25
  # review, finding 1 -- major). `worktree add -B` RESETS the branch to the
  # start point. origin/main is correct for fresh work and destructive for a PR
  # that is already open: the agent gets a tree holding NONE of the PR's
  # commits, and the rebase prompt below then tells it to
  # `git push --force-with-lease`, which deletes the approved diff from the
  # remote branch. The lease does not catch it -- the fetch above just
  # refreshed origin/$BRANCH, so the lease sees no surprise and allows the
  # push. The PR's head is origin/$BRANCH; when there is a PR, that is the
  # only defensible start point.
  BASE="origin/main"
  if [ -n "$EXISTING_PR" ]; then
    if git -C "$SKEL" rev-parse --verify -q "origin/$BRANCH" >/dev/null 2>&1; then
      BASE="origin/$BRANCH"
    else
      # gh named a PR whose head branch is not on the remote (deleted after a
      # merge, pruned by hand). Cutting from main is safe HERE and only here:
      # there is no remote branch left for a force-push to destroy. Said out
      # loud rather than fallen through silently, because an unexplained
      # origin/main is the exact behaviour this block exists to stop -- and
      # refusing instead would stall the issue every cycle with one INFRA line
      # nobody reads.
      say "$ISSUE: PR #$EXISTING_PR is recorded but origin/$BRANCH does not exist; cutting from origin/main (nothing on the remote to overwrite)"
    fi
  fi
  if [ ! -d "$TREE" ]; then
    mkdir -p "$(dirname "$TREE")"
    if ! git -C "$SKEL" worktree add -q -B "$BRANCH" "$TREE" "$BASE" 2>>"$LOG"; then
      # A concurrent worker on the SAME issue can create this tree between the
      # test above and this line. That is the collision the claim below exists to
      # adjudicate, not an infra failure -- so fall through and let it, rather
      # than reporting a phantom outage and burning nothing.
      if [ ! -d "$TREE" ]; then
        say "INFRA: could not create worktree for $ISSUE (not counted against the issue)"
        continue
      fi
    fi
  fi

  # 2. CLAIM, from INSIDE $TREE. exit 3 = another session holds THIS tree; that
  # is a skip, not an error.
  #
  # ASK-188: the claim used to run here at step 1, BEFORE the worktree existed,
  # so its cwd was the skeleton. `linear-claim.py::claims_path()` resolves the
  # lock from `git rev-parse --show-toplevel` OF THE CALLER'S CWD, which meant
  # every issue on the board contended for one file at the skeleton root -- one
  # lock, whole repo, total serialization. Measured 2026-07-27: 50+ ready issues
  # behind a queue that could only ever run one. Inside a worktree that same
  # command returns THAT worktree's path, so the lock lands in the tree it
  # actually protects, which is what the function's own docstring says it is for.
  # Two workers on the SAME issue still share one worktree and still collide, so
  # the mutex is unweakened -- that is case 4 of test-linear-worker-parallel.sh.
  #
  # `rc=$?` cannot live under `if ! cmd`: bash sets $? from the NEGATION there, so
  # it read 0 on every failure and the collision branch was unreachable -- a real
  # collision reported as "INFRA: claim failed rc=0". Capture the status directly.
  #
  # --holder-pid IS THIS SCRIPT'S OWN PID (ASK-189). The claiming python3 exits
  # within milliseconds, so its pid means nothing -- but THIS shell lives for the
  # entire run, and until now that fact was simply never written down. With it
  # recorded, a claim left behind by a killed run is reclaimable on read instead
  # of wedging the tree until a human runs `release --holder`. Measured twice
  # 2026-07-27; the kills were SIGKILL, which converge.sh's TERM/INT/HUP trap
  # cannot ever catch.
  #
  # `$$` and not `$BASHPID`: this line runs inside a subshell inside the pipeline
  # subshell of the `while` loop, and `$$` stays the SCRIPT's pid through both
  # (verified). `$BASHPID` would be the innermost subshell, dead on the next line
  # -- and it does not exist at all in the bash 3.2 macOS ships.
  #
  # RESIDUAL, stated rather than papered over: if this shell alone is killed and
  # its backgrounded `claude` child is orphaned, the holder reads dead while work
  # continues. That needs a targeted kill of this pid only; a timeout, a killed
  # process group, a slept laptop or a reboot -- every case actually observed --
  # takes the whole tree down together.
  #
  # STDERR IS KEPT. With `>/dev/null 2>&1` a tree CHANGING HANDS left this log
  # showing a normal `start ASK-xxx` and nothing else, so the one line an
  # operator has while debugging a two-workers-one-tree collision was the one
  # line thrown away -- the fix landing on the detector and not on the report
  # (PR #31 review, finding 2). Only the RECLAIMED line is echoed: an ordinary
  # refusal already gets its own `skip ... claimed by another session` below, and
  # repeating that here would trade a missing signal for a duplicated one.
  CLAIM_ERR="$(mktemp)"
  ( cd "$TREE" && python3 "$CLAIM" claim "$ISSUE" --agent "$AGENT" --session "$SESSION" \
      --holder-pid "$$" ) >/dev/null 2>"$CLAIM_ERR"
  rc=$?
  while IFS= read -r claim_line; do
    case "$claim_line" in RECLAIMED:*) say "$claim_line" ;; esac
  done < "$CLAIM_ERR"
  rm -f "$CLAIM_ERR"
  if [ "$rc" != "0" ]; then
    if [ "$rc" = "3" ]; then say "skip $ISSUE: working tree is claimed by another session"; continue; fi
    say "INFRA: claim failed rc=$rc on $ISSUE (not counted against the issue)"; continue
  fi
  # 3. THE TREE MUST STAND ON THE PR'S HEAD before a round that will push over
  # it. A tree left by an earlier round, or cut by the version of this script
  # that always used origin/main, can be missing every commit the PR is made of
  # -- and the round would then force-push that emptiness over the approved
  # diff. Repositioning happens HERE, after the claim, because it mutates the
  # tree and the claim is what says this session owns it.
  if [ -n "$EXISTING_PR" ] && ! tree_holds_pr_head "$TREE" "$BRANCH"; then
    if ! position_tree_on_pr_head "$TREE" "$BRANCH"; then
      say "skip $ISSUE: $TREE is missing PR #$EXISTING_PR's commits and cannot be moved onto them -- $POSITION_REFUSAL. Refusing a round that would force-push over the PR. A human resolves this one: $TREE"
      if claim_page_once "$ISSUE" tree_paged; then
        bash "$NOTIFY" "worker: $ISSUE worktree does not hold PR #$EXISTING_PR's commits and has local work - $TREE needs a human" 2>/dev/null || true
      fi
      # Release before skipping: a claim held by a run that did nothing wedges
      # this issue for every later run, which is the failure this refusal exists
      # to avoid, one layer out.
      ( cd "$TREE" && python3 "$CLAIM" release "$ISSUE" --agent "$AGENT" --session "$SESSION" ) >/dev/null 2>&1 || true
      continue
    fi
  fi

  # 4. SPEND THE CONFLICT ROUND, at the dispatch and nowhere earlier. Every
  # decline above this line left the budget intact (PR #25 review, finding 2),
  # so the counter and the log line below both describe rounds that really ran.
  if [ -n "$CONFLICT_ROUND" ]; then
    bump_conflict_round "$ISSUE"
    say "$ISSUE: PR #$EXISTING_PR is '$PR_VERDICT' but $MERGE_STATE -- dispatching rebase round $CONFLICT_ROUND/$MAX_CONFLICT_ROUNDS"
  fi
  if [ -n "$DRIFT_ROUND" ]; then
    bump_drift_round "$ISSUE"
    say "$ISSUE: PR #$EXISTING_PR is '$PR_VERDICT' at $REVIEWED_SHA but the head is $CURRENT_SHA -- dispatching re-review round $DRIFT_ROUND/$MAX_DRIFT_ROUNDS"
  fi
  say "start $ISSUE on $BRANCH in $TREE (attempt $((N+1))/$MAX_ATTEMPTS)"
  python3 "$SYNC" progress "$ISSUE" \
    "Picked up by the autonomous worker. Branch \`$BRANCH\`. Attempt $((N+1)) of $MAX_ATTEMPTS." \
    --agent "$AGENT" >/dev/null 2>&1 || true

  # REWORK: if a PR already exists for this branch, the worker is not starting
  # fresh -- it is answering a review. Without this the prompt would say "do the
  # DoR" to an agent whose work is already written and already criticised, and it
  # would plausibly start over. The review is the spec for this pass.
  # EXISTING_PR was discovered above, before the claim; reaching this line means
  # the severity-floor gate already ruled the verdict REQUEST CHANGES or BLOCK,
  # or ruled it approved-but-unmergeable (gate 30, the conflict branch below).
  #
  # A CONFLICT ROUND IS NOT A REVIEW ROUND, so it does not get the review prompt.
  # The review APPROVED this diff -- handing the agent "the review is the spec,
  # answer every finding" against a review with no findings is how ASK-208's
  # rounds 1 and 2 both did code polish while the conflict went untouched. The
  # spec for this pass is the conflict and nothing else.
  if [ -n "$CONFLICT_ROUND" ]; then
    REWORK="

## THIS IS A REBASE ROUND. THE CONFLICT IS THE ONLY TASK.

PR #$EXISTING_PR on this branch was already REVIEWED AND APPROVED ('$PR_VERDICT').
GitHub now reports its merge state as $MERGE_STATE: main moved underneath it and
it no longer merges. This is round $CONFLICT_ROUND of $MAX_CONFLICT_ROUNDS; at the cap the
worker stops and pages a human, so do not spend this round on anything else.

Do exactly this:

  git fetch origin
  git rebase origin/main        # or merge origin/main, whichever this repo prefers
  # resolve the conflicts, keeping BOTH intents: yours and whatever landed on main
  bash <the tests this PR already ships>   # they must still pass after the rebase
  git push --force-with-lease origin $BRANCH

DO NOT redesign, refactor, polish, or 'improve' the approved diff. DO NOT re-open
the design. Any change beyond what resolving the conflict requires costs the PR
its approval and starts the review over.

If the conflict cannot be resolved without a real decision (the two sides changed
the same behaviour on purpose), say so on the issue via progress and STOP:
  bash $SKEL/kipi linear progress $ISSUE \"<the conflict and the decision it needs>\" --agent sana

Push to the SAME branch $BRANCH. Do not open a second PR."
  elif [ -n "$DRIFT_ROUND" ]; then
    # A DRIFT ROUND IS NOT A REVIEW ROUND EITHER, and for the same reason the
    # rebase round is not: the stored review APPROVED, so it carries no findings
    # to answer. Handing it the rework prompt below said "the review is the spec,
    # for EACH finding either fix it or reply why it is not a defect" against a
    # review with no findings -- ASK-208's failure shape exactly, and the most
    # common producer of this drift is a HUMAN (a founder push, GitHub's "Update
    # branch" button), so that prompt sent an agent to invent work on top of
    # someone else's commit and push it to the same branch (PR #30 review, major
    # 1).
    #
    # What actually clears the drift is step 5's review, not this round's edits.
    # So the honest instruction is: read the unreviewed commits, change NOTHING
    # unless they are broken, and let the review run. Doing nothing is a correct
    # outcome here and is stated as one -- otherwise an agent handed a round with
    # no task will manufacture one.
    REWORK="

## THIS IS A RE-REVIEW ROUND. THE CODE AT THE HEAD HAS NEVER BEEN REVIEWED.

PR #$EXISTING_PR on this branch carries a stored verdict of '$PR_VERDICT', but that
verdict was recorded against commit $REVIEWED_SHA. The head of the branch is now
$CURRENT_SHA. Whatever landed in between has never been read by any reviewer.

This is round $DRIFT_ROUND of $MAX_DRIFT_ROUNDS; at the cap the worker stops and pages a human.

THERE ARE NO FINDINGS TO ANSWER. The stored review approved. Do not read it as a
spec, do not re-open the design, and do not restart the task.

The re-review at the end of this round is what clears the drift, not your edits.
So:

  git log --oneline $REVIEWED_SHA..$CURRENT_SHA     # what nobody has reviewed
  git diff $REVIEWED_SHA..$CURRENT_SHA

  1. If those commits are coherent and complete, CHANGE NOTHING. Say so via
     progress and stop. That is a correct and expected outcome for this round --
     the review runs next either way. Inventing work here is the failure mode.
  2. Only if they are actually broken -- a partial push, a botched merge, a WIP
     commit, tests that no longer pass -- fix exactly that, and nothing else.
     Run this PR's tests before you push.

Someone else may have pushed those commits (a founder push, GitHub's 'Update
branch'). Treat them as work you did not write and must not silently rewrite.

Push to the SAME branch $BRANCH. Do not open a second PR."
  elif [ -n "$EXISTING_PR" ]; then
    REWORK="

## THIS IS A REWORK, NOT A FRESH START

PR #$EXISTING_PR already exists for this branch and has been reviewed by an
adversarial senior-staff reviewer. Read the review before touching anything:

  gh pr view $EXISTING_PR --comments

## FIRST, STAND ON CURRENT main

This branch may have been cut from a stale base. Measured 2026-07-29 (ASK-245):
origin/main was 17 commits behind local main, so five open PRs were all built on
a base that no longer existed -- one of them already CONFLICTING, the rest with a
red validate check for the same reason. Reworking on top of that reproduces the
conflict instead of fixing it.

  git fetch origin
  git rebase origin/main    # or merge origin/main, whichever this repo prefers

If it rebases cleanly, carry on with the findings below. If it conflicts, resolve
the conflict FIRST and keep both intents (yours and whatever landed on main); a
finding fixed on a base that no longer exists is not fixed. If the conflict needs
a real decision, say so via progress and STOP:
  bash $SKEL/kipi linear progress $ISSUE \"<the conflict and the decision it needs>\" --agent sana

THE REVIEW IS THE SPEC FOR THIS PASS. Do not restart the task and do not
re-litigate the design. For EACH finding, either:
  - fix it, and add a test that FAILS without the fix (observed red, then green), or
  - reply on the PR with why it is not a defect, citing the code.

Findings you disagree with are answered, never silently ignored -- a finding that
gets no response reads as a finding nobody read.

The reviewer's own bar applies to your fixes too: a fix with no test that could
have caught the bug is not a fix, it is a patch. Re-read what the reviewer said it
tried and could NOT break, and do not regress those.

## CHECK THE LAYER ABOVE YOUR FIX

Observed on BOTH review rounds of this PR, so treat it as the likely failure mode
rather than a hypothetical:

  round 1: the detector had no update path      -> you added one
  round 2: the update path rewrites a CLOSED issue and never reopens it,
           so the detector goes permanently dark after the operator does the
           right thing -- WORSE than before the fix
  round 2 also: 'the fix landed on the detector and not on the report'

A local fix that is correct in isolation can create a worse failure one layer out.
Before you call a finding fixed, walk the value you changed to its CONSUMERS and
ask what each now does with it:

- who READS the thing I just started writing? what if it is in a state I did not
  consider (closed, empty, stale, concurrent)?
- does the REPORT (Slack line, counts, dry-run output) still tell the truth after
  this change, or does it now claim something that is not happening?
- is there a SECOND code path doing the same job that I did not touch? Two readers
  of the same input with different semantics is a defect even when each is
  individually defensible.
- what does the operator SEE when this fires at 3am, and is that signal or noise?

If a fix makes any downstream thing quieter, say so explicitly on the PR and
justify it. Silence bought by a fix is the most expensive kind.

Push to the SAME branch $BRANCH. Do not open a second PR."
  fi

  PROMPT="You are Sana, the kipi Systems Engineer, working Linear issue $ISSUE.$REWORK

You are in a DEDICATED GIT WORKTREE at $TREE, already on branch $BRANCH off origin/main.
Work here. Never `cd` to $SKEL and never switch this branch -- the founder may be using that checkout.

1. Read the issue: \`python3 $SYNC progress $ISSUE\` is for REPORTING; to read it use the Linear MCP or
   \`gh\`-style inspection. The issue carries a Definition of Ready: Outcome, Files, Check, Blast radius, Not doing.
2. Work ONLY what the DoR scopes. The 'Not doing' line is binding.
3. Follow this repo's discipline: reproducer first and observed RED before green, then the real command output.
4. Commit on branch $BRANCH with the issue id $ISSUE in the message (the commit-msg gate requires it).
5. Post progress with: bash $SKEL/kipi linear progress $ISSUE \"<what happened>\" --agent sana --evidence \"<command and its real output>\"
6. Open a PR. DO NOT MERGE. DO NOT close the issue - closeout runs through /issue-verify and /issue-closeout.
   OPEN IT BEFORE YOUR TURN ENDS. Never finish on \"I'll open the PR once X finishes\" -- your turn
   ends there and the PR never exists, so the review never runs and the work is stranded (observed
   on ASK-184). If a check is still running, open the PR FIRST and post the result as a comment.
7. If the DoR turns out to be wrong or impossible, say so on the issue via progress and STOP. Do not improvise a different task.

Anything real you find and are not fixing: capture it, never just mention it:
  python3 $SKEL/plugins/prd-os/scripts/prd_runner.py spillover add --source $ISSUE --desc \"...\""

  if run_bounded "$TIMEOUT_SECONDS" bash -c "cd '$TREE' && KIPI_AGENT='$AGENT' claude -p \"\$1\" </dev/null >>'$LOG' 2>&1" _ "$PROMPT"; then
    say "ok $ISSUE"
    python3 "$SYNC" progress "$ISSUE" "Worker run completed. See the branch/PR for the diff." \
      --agent "$AGENT" >/dev/null 2>&1 || true
  else
    rc=$?
    bump_attempt "$ISSUE" "claude run failed rc=$rc"
    N2="$(attempts_for "$ISSUE")"
    say "fail $ISSUE rc=$rc ($N2/$MAX_ATTEMPTS)"
    python3 "$SYNC" progress "$ISSUE" \
      "Worker run FAILED (attempt $N2 of $MAX_ATTEMPTS, rc=$rc). Log: ~/.config/kipi/linear-worker.log" \
      --agent "$AGENT" >/dev/null 2>&1 || true
    if [ "$N2" -ge "$MAX_ATTEMPTS" ]; then
      bash "$NOTIFY" "worker: $ISSUE stuck after $MAX_ATTEMPTS attempts - needs a human" 2>/dev/null || true
    fi
  fi

  # 5. REVIEW. Every PR this worker opens gets the adversarial reviewer, with no
  # human having to remember to ask. The author of the PR and the author of the
  # review must not be the same mind: the worker's `claude -p` wrote the diff, so
  # a reviewer inside that same session would re-derive its blind spots rather
  # than find them. This is a separate process with fresh eyes and no memory of
  # why the code looks the way it does.
  PR_NUM="$(cd "$TREE" && gh pr list --head "$BRANCH" --json number -q '.[0].number' 2>/dev/null)"

  # OPEN THE PR IN CODE, not on the agent remembering to. Observed on ASK-184
  # (2026-07-27): Sana pushed two good commits with an observed red-then-green
  # reproducer, then ended her turn on "bar 4 is in flight -- I'll report its
  # exit code, then open the PR". The turn ended; no PR existed; the review
  # never ran and the driver stopped with nothing to look at. Good work
  # stranded on an unopened PR is the most expensive possible failure here,
  # and "tell the agent to remember" is not enforcement.
  # Only fires when there is something to open a PR FOR: commits ahead of
  # origin/main. A branch with no commits still yields no PR, which is a real
  # failure the driver should still see.
  if [ -z "$PR_NUM" ]; then
    AHEAD="$(cd "$TREE" && git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)"
    if [ "${AHEAD:-0}" -gt 0 ]; then
      say "$ISSUE: $AHEAD commit(s) pushed but no PR; opening it (the agent left it unopened)"
      (cd "$TREE" && git push -u origin "$BRANCH" >/dev/null 2>&1
       gh pr create --head "$BRANCH" --base main \
         --title "$(git log -1 --pretty=%s)" \
         --body "Autonomous worker (Sana) on $ISSUE. Opened by the worker because the run ended without opening it.

Commits on this branch:
$(git log --oneline origin/main..HEAD)

Review runs next. Do not merge without it." >/dev/null 2>&1) || true
      PR_NUM="$(cd "$TREE" && gh pr list --head "$BRANCH" --json number -q '.[0].number' 2>/dev/null)"
      [ -n "$PR_NUM" ] && say "$ISSUE: opened PR #$PR_NUM"
    fi
  fi

  if [ -n "$PR_NUM" ]; then
    # ARM AUTO-MERGE, on BOTH paths that resolve $PR_NUM above: the PR the agent
    # opened, and the PR this worker opened because the agent did not. Until this
    # line, arming was a hand-typed `gh pr merge --auto --squash <n>` plus a
    # watcher loop inside an interactive session -- and both die when the terminal
    # closes, so a PR opened after that sat green forever with nobody left to
    # merge it. A human remembering is not enforcement.
    #
    # THE SAME FUNCTION the approved-PR gate calls, not a second copy: one arm,
    # one set of semantics, one place the three-state probe lives. The rationale,
    # the blast radius, and the paging discipline are all stated at its
    # definition. $AUTOMERGE is what it reached, and the closing line below reads
    # it -- without that, the arm landed here and the REPORT two lines down still
    # told the operator a founder owed this PR a merge (PR #33 review round 1,
    # finding 2), which is the pre-fix picture printed underneath the fix.
    arm_automerge "$PR_NUM" "$TREE"
    # Count review ROUNDS per issue, distinct from failed ATTEMPTS. A run that
    # succeeds but comes back REQUEST CHANGES is not a failure, so the attempts
    # counter never sees it -- yet rounds-to-approve is the number that actually
    # decides whether this worker can be trusted unattended. Without it the
    # question "does it converge or oscillate?" is answered by memory, and memory
    # is what this whole system exists to replace.
    ROUNDS="$(python3 -c "
import json
try: d=json.load(open('$ATTEMPTS'))
except Exception: d={}
e=d.setdefault('$ISSUE',{}); e['rounds']=e.get('rounds',0)+1
json.dump(d,open('$ATTEMPTS','w'),indent=2); print(e['rounds'])" 2>/dev/null || echo "?")"
    say "review PR #$PR_NUM for $ISSUE (round $ROUNDS)"
    $REVIEWER_CMD "$PR_NUM" --issue "$ISSUE" --post >>"$LOG" 2>&1 \
      || say "WARN: reviewer failed on PR #$PR_NUM (the PR stands, unreviewed)"
    # Read back the verdict RECORD the reviewer just wrote (never re-grep the
    # review prose) and state what happens next in plain terms. Rework itself
    # fires on the NEXT run, through the severity-floor gate above.
    FINAL_VERDICT="$(verdict_from_record "$REVIEWS_DIR/pr-$PR_NUM.verdict.json")"
    # RE-GATE THE RECORD BEFORE REPORTING ON IT (PR #30 review round 2, major 3).
    # The reviewer above can fail -- it is a `|| say WARN` line, not a hard stop --
    # and when it does, this read returns the SAME record the gate at the top of
    # this run already refused to trust. Reporting "converged ... waits on founder
    # merge" off it put that line two lines below "the code at the head was never
    # reviewed", and the closing line is the one an operator scans. Unreachable
    # before ASK-219 (gate 10 skipped the issue before step 5 could run), which is
    # why arming exit 40 is what exposed it.
    #
    # Both shas are re-read rather than reused: a round that pushed moved the head,
    # so the values from the top of the loop describe a state that no longer
    # exists. The gate is the ONE reader of the comparison -- deriving it here
    # would be a second reader with drifting semantics.
    FINAL_REVIEWED_SHA="$(head_sha_from_record "$REVIEWS_DIR/pr-$PR_NUM.verdict.json")"
    FINAL_CURRENT_SHA="$(pr_head_sha "$PR_NUM")"
    # AND THE GATE'S NOTE IS SAID, NOT SWALLOWED (PR #30 review round 3, minor 2).
    # converge.sh's own call site states the rule this line broke: "Swallowing it
    # would silently grandfather the blind spot it announces." The reviewer always
    # writes head_sha and writes it EMPTY when its own `gh pr view` could not
    # answer, and a fresh issue reaches step 5 with no prior PR -- so the
    # top-of-run gate, the one that does `say` its NOTE, never ran. The run then
    # closed on "converged ... waits on founder merge" with nothing anywhere
    # saying the approval is pinned to no commit, which is the one thing that
    # separates it from a verified one. The BEHAVIOUR is right and settled
    # (absent is not drift, fail toward terminal); the missing thing was the
    # sentence. Adds no per-run noise: the gate is silent whenever both shas were
    # read, which is every healthy round.
    FINAL_GATE_NOTE="$(rework_gate "$FINAL_VERDICT" "" "$FINAL_REVIEWED_SHA" "$FINAL_CURRENT_SHA")"; FINAL_GATE=$?
    [ -n "$FINAL_GATE_NOTE" ] && say "$FINAL_GATE_NOTE"
    # NO PAGE HERE, deliberately, and it is the one place in this pass that buys
    # silence: the NEXT scheduled run gates this same PR at 40, spends a drift
    # round, and pages once at the cap. Paging here too would double-page the same
    # unreviewed head on every round. What this line owes the operator is the
    # truth, not a second alarm.
    #
    # It reports and falls THROUGH to the release at step 6 rather than
    # `continue`-ing: a claim held by a run that already finished wedges this
    # issue for every later run, which is worse than the wrong log line this
    # replaces.
    if [ "$FINAL_GATE" = "40" ]; then
      say "$ISSUE NOT converged: PR #$PR_NUM still reads '$FINAL_VERDICT' recorded at $FINAL_REVIEWED_SHA while the head is $FINAL_CURRENT_SHA -- this round's review wrote no record, so the code at the head is still unreviewed. Re-review next run ($(drift_rounds_for "$ISSUE")/$MAX_DRIFT_ROUNDS drift round(s) spent)."
    else
    case "$FINAL_VERDICT" in
      "APPROVE"|"APPROVE WITH NITS")
        # WHO MERGES IT (PR #33 review, finding 2). This line closed every approved
        # run with "waits on founder merge" -- two lines under the same run's
        # "auto-merge armed on PR #N". Nobody waits; GitHub merges it. The closing
        # line is the one an operator scans, so it reports the state the arm above
        # actually reached instead of the one that was true before this worker
        # armed anything. Three outcomes, three sentences: a hedge that covered all
        # of them would make the healthy case unreadable.
        case "$AUTOMERGE" in
          armed)
            say "$ISSUE converged: $FINAL_VERDICT after $ROUNDS round(s); PR #$PR_NUM has auto-merge armed -- GitHub merges it once every required check is green, no human merge needed" ;;
          unarmed)
            say "$ISSUE converged: $FINAL_VERDICT after $ROUNDS round(s); PR #$PR_NUM is NOT armed and waits on a human merge: gh pr merge --auto --squash $PR_NUM" ;;
          *)
            say "$ISSUE converged: $FINAL_VERDICT after $ROUNDS round(s); PR #$PR_NUM -- gh could not read its auto-merge state this run, so check it landed; if it sits green: gh pr merge --auto --squash $PR_NUM" ;;
        esac ;;
      "REQUEST CHANGES"|"BLOCK")
        say "$ISSUE: $FINAL_VERDICT (round $ROUNDS) -- rework via: kipi work --apply --issue $ISSUE" ;;
      *)
        say "$ISSUE: no verdict recorded for PR #$PR_NUM (round $ROUNDS) -- review may have died; see $REVIEWS_DIR" ;;
    esac
    fi
  else
    say "no PR found for $BRANCH; nothing to review"
  fi

  # 6. RELEASE at PR-open, not at close, so a reviewer can pick the tree up.
  # From INSIDE $TREE, matching the claim above. A claim taken in one cwd and
  # released in another does not error: release reads a DIFFERENT lock file,
  # finds nothing, prints "not held" and exits 0 while the real lock sits in the
  # worktree forever, wedging that issue permanently. Asserted by case 3 of
  # test-linear-worker-parallel.sh, which reads the lock files back after the run.
  ( cd "$TREE" && python3 "$CLAIM" release "$ISSUE" --agent "$AGENT" --session "$SESSION" ) >/dev/null 2>&1 || true
  DONE=$((DONE+1))
done

say "worker: run complete"
exit 0
