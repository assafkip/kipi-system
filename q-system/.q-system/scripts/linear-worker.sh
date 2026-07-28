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
TIMEOUT_SECONDS=1800
LIMIT=1
APPLY=0
ONLY_ISSUE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --limit) shift; LIMIT="${1:-1}" ;;
    --issue) shift; ONLY_ISSUE="${1:-}" ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
  shift || true
done

export SCRIPT_DIR
mkdir -p "$STATE_DIR"
TS() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "$(TS) $*" | tee -a "$LOG"; }

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

def ready(i):
    labels = {l["name"] for l in i["labels"]["nodes"]}
    if "owner:assaf" in labels:      return False   # founder decision, hands off
    if "owner:sana" not in labels:   return False
    if i["state"]["type"] not in ("backlog", "unstarted"): return False
    d = i.get("description") or ""
    return "## Definition of Ready" in d or "Definition of Ready" in d

pool = [i for i in issues if ready(i)]
if only:
    pool = [i for i in issues if i["identifier"] == only]
print(json.dumps({"ready": [
    {"id": i["identifier"], "title": i["title"], "project": (i.get("project") or {}).get("name")}
    for i in pool], "total_open": len(issues)}))
PY
)"

INFRA="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("infra_error",""))' 2>/dev/null)"
if [ -n "$INFRA" ]; then
  say "INFRA: linear unreachable ($INFRA). Not counted against any issue."
  exit 0
fi

READY_COUNT="$(printf '%s' "$PICKED" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["ready"]))')"
say "worker: $READY_COUNT ready issue(s) (owner:sana, has a DoR, not owner:assaf)"

if [ "$READY_COUNT" = "0" ]; then
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

  BRANCH="sana/$(echo "$ISSUE" | tr 'A-Z' 'a-z')"

  # SEVERITY FLOOR GATE (deterministic, before any side effect). Only REQUEST
  # CHANGES or BLOCK starts another rework round: an approved PR waits on the
  # founder, and an unreviewed PR has no spec to rework against. The gate runs
  # BEFORE the claim and the Linear progress note on purpose -- a "Picked up"
  # note on a permanent Linear object followed by an immediate skip is a false
  # alarm, and false alarms train the reader to ignore the real notes.
  EXISTING_PR="$(gh pr list --head "$BRANCH" --json number -q '.[0].number' 2>/dev/null)"
  REWORK=""
  CONFLICT_ROUND=""
  if [ -n "$EXISTING_PR" ]; then
    PR_VERDICT="$(verdict_from_record "$REVIEWS_DIR/pr-$EXISTING_PR.verdict.json")"
    if [ -z "$PR_VERDICT" ]; then
      # Fallback for PRs reviewed before the verdict record existed: extract
      # from the newest review .md with the SAME extractor the reviewer uses.
      LATEST_REVIEW="$(ls -t "$REVIEWS_DIR/pr-$EXISTING_PR-"*.md 2>/dev/null | head -1)"
      [ -n "$LATEST_REVIEW" ] && PR_VERDICT="$(extract_verdict "$LATEST_REVIEW")"
    fi
    # MERGEABILITY IS HALF THE GATE (ASK-212). Read once, through the shared lib,
    # so the worker and the driver cannot drift on what "still merges" means.
    MERGE_STATE="$(pr_merge_state "$EXISTING_PR")"
    # The streak ends the moment the PR merges cleanly again -- see
    # clear_conflict_rounds. Placed before the gate so it runs on every verdict,
    # not just the approving ones: a rework round that also resolves the
    # conflict ended the streak just as much.
    [ "$MERGE_STATE" = "CLEAN" ] && clear_conflict_rounds "$ISSUE"
    # THE VERDICT IS BOUND TO A SHA, NOT A PR NUMBER (ASK-216, armed here by
    # ASK-219, sp-a27722e7). This worker reuses ONE branch and ONE PR across every
    # rework round, so before this call passed a sha, each push landing after an
    # approval inherited that approval silently. The reviewed sha is the one the
    # reviewer pinned into the record; the current head goes through the same
    # shared lib as the merge state so the worker and converge.sh cannot drift on
    # what "the current head" means.
    #
    # APPENDED, NEVER INSERTED: $MERGE_STATE keeps argument 2. Reordering it would
    # silently stop ASK-212's rebase rounds from ever firing again.
    REVIEWED_SHA="$(head_sha_from_record "$REVIEWS_DIR/pr-$EXISTING_PR.verdict.json")"
    CURRENT_SHA="$(pr_head_sha "$EXISTING_PR")"
    GATE_NOTE="$(rework_gate "$PR_VERDICT" "$MERGE_STATE" "$REVIEWED_SHA" "$CURRENT_SHA")"; GATE=$?
    [ -n "$GATE_NOTE" ] && say "$GATE_NOTE"
    if [ "$GATE" = "10" ]; then
      say "skip $ISSUE: PR #$EXISTING_PR verdict is '$PR_VERDICT' -- nothing to rework, waiting on founder merge"
      continue
    fi
    if [ "$GATE" = "20" ]; then
      say "skip $ISSUE: PR #$EXISTING_PR has no recorded review verdict -- run: kipi review $EXISTING_PR --issue $ISSUE --post"
      continue
    fi
    if [ "$GATE" = "40" ]; then
      # STALE. The record approves a commit that is no longer the head, so nobody
      # has read the code that is actually there. Fall through to the dispatch:
      # the round ends in a review (step 5 below), and THAT review writes a record
      # pinned to the current head, which is the only thing that clears this.
      #
      # CONFLICT_ROUND stays empty on purpose even when the PR is also DIRTY. A
      # drift round is a review round, not a rebase round; spending the rebase
      # budget on it would leave a real conflict un-dispatchable later, and the
      # rebase prompt would tell the agent to force-push a diff nobody reviewed.
      say "$ISSUE: PR #$EXISTING_PR reads '$PR_VERDICT', but that verdict was recorded at $REVIEWED_SHA and the head is now $CURRENT_SHA -- the code at the head was never reviewed. Dispatching a round so it gets re-reviewed."
    fi
    if [ "$GATE" = "30" ]; then
      # Approved on content, but it no longer merges. Dispatch a REBASE round on
      # its own budget -- and stop dead once that budget is spent, because an
      # unresolvable conflict would otherwise rework forever and write a
      # permanent Linear comment on every round.
      CR="$(conflict_rounds_for "$ISSUE")"
      if [ "$CR" -ge "$MAX_CONFLICT_ROUNDS" ]; then
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
  ( cd "$TREE" && python3 "$CLAIM" claim "$ISSUE" --agent "$AGENT" --session "$SESSION" ) >/dev/null 2>&1
  rc=$?
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
  elif [ -n "$EXISTING_PR" ]; then
    REWORK="

## THIS IS A REWORK, NOT A FRESH START

PR #$EXISTING_PR already exists for this branch and has been reviewed by an
adversarial senior-staff reviewer. Read the review before touching anything:

  gh pr view $EXISTING_PR --comments

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
    bash "$SCRIPT_DIR/pr-review-agent.sh" "$PR_NUM" --issue "$ISSUE" --post >>"$LOG" 2>&1 \
      || say "WARN: reviewer failed on PR #$PR_NUM (the PR stands, unreviewed)"
    # Read back the verdict RECORD the reviewer just wrote (never re-grep the
    # review prose) and state what happens next in plain terms. Rework itself
    # fires on the NEXT run, through the severity-floor gate above.
    FINAL_VERDICT="$(verdict_from_record "$REVIEWS_DIR/pr-$PR_NUM.verdict.json")"
    case "$FINAL_VERDICT" in
      "APPROVE"|"APPROVE WITH NITS")
        say "$ISSUE converged: $FINAL_VERDICT after $ROUNDS round(s); PR #$PR_NUM waits on founder merge" ;;
      "REQUEST CHANGES"|"BLOCK")
        say "$ISSUE: $FINAL_VERDICT (round $ROUNDS) -- rework via: kipi work --apply --issue $ISSUE" ;;
      *)
        say "$ISSUE: no verdict recorded for PR #$PR_NUM (round $ROUNDS) -- review may have died; see $REVIEWS_DIR" ;;
    esac
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
