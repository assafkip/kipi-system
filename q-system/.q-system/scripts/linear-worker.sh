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
SKEL="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CLAIM="$SCRIPT_DIR/linear-claim.py"
SYNC="$SCRIPT_DIR/linear-sync.py"
NOTIFY="$SCRIPT_DIR/slack-notify.sh"
STATE_DIR="$HOME/.config/kipi"
ATTEMPTS="$STATE_DIR/linear-worker-attempts.json"
LOG="$STATE_DIR/linear-worker.log"

MAX_ATTEMPTS=3
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

  # 1. CLAIM. exit 3 = another session holds this tree; that is a skip, not an error.
  if ! python3 "$CLAIM" claim "$ISSUE" --agent "$AGENT" --session "$SESSION" >/dev/null 2>&1; then
    rc=$?
    if [ "$rc" = "3" ]; then say "skip $ISSUE: working tree is claimed by another session"; continue; fi
    say "INFRA: claim failed rc=$rc on $ISSUE (not counted against the issue)"; continue
  fi

  BRANCH="sana/$(echo "$ISSUE" | tr 'A-Z' 'a-z')"

  # WORKTREE, not the main checkout. Scar from this worker's own first live run
  # (ASK-150, 2026-07-26): it branched in place and left the founder's main
  # checkout sitting on sana/ask-150. The claim lock stopped a concurrent AGENT
  # from colliding, but it cannot stop the worker yanking the FOUNDER's working
  # tree out from under them mid-edit -- which is commit 53f2eeb, the exact scar
  # this whole line of work started from. A worktree makes the collision
  # impossible by construction instead of merely detected.
  TREE="$STATE_DIR/worktrees/$(echo "$ISSUE" | tr 'A-Z' 'a-z')"
  if [ ! -d "$TREE" ]; then
    mkdir -p "$(dirname "$TREE")"
    if ! git -C "$SKEL" worktree add -q -B "$BRANCH" "$TREE" origin/main 2>>"$LOG"; then
      say "INFRA: could not create worktree for $ISSUE (not counted against the issue)"
      python3 "$CLAIM" release "$ISSUE" --agent "$AGENT" --session "$SESSION" >/dev/null 2>&1 || true
      continue
    fi
  fi
  say "start $ISSUE on $BRANCH in $TREE (attempt $((N+1))/$MAX_ATTEMPTS)"
  python3 "$SYNC" progress "$ISSUE" \
    "Picked up by the autonomous worker. Branch \`$BRANCH\`. Attempt $((N+1)) of $MAX_ATTEMPTS." \
    --agent "$AGENT" >/dev/null 2>&1 || true

  PROMPT="You are Sana, the kipi Systems Engineer, working Linear issue $ISSUE.

You are in a DEDICATED GIT WORKTREE at $TREE, already on branch $BRANCH off origin/main.
Work here. Never `cd` to $SKEL and never switch this branch -- the founder may be using that checkout.

1. Read the issue: \`python3 $SYNC progress $ISSUE\` is for REPORTING; to read it use the Linear MCP or
   \`gh\`-style inspection. The issue carries a Definition of Ready: Outcome, Files, Check, Blast radius, Not doing.
2. Work ONLY what the DoR scopes. The 'Not doing' line is binding.
3. Follow this repo's discipline: reproducer first and observed RED before green, then the real command output.
4. Commit on branch $BRANCH with the issue id $ISSUE in the message (the commit-msg gate requires it).
5. Post progress with: bash $SKEL/kipi linear progress $ISSUE \"<what happened>\" --agent sana --evidence \"<command and its real output>\"
6. Open a PR. DO NOT MERGE. DO NOT close the issue - closeout runs through /issue-verify and /issue-closeout.
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
  if [ -n "$PR_NUM" ]; then
    say "review PR #$PR_NUM for $ISSUE"
    bash "$SCRIPT_DIR/pr-review-agent.sh" "$PR_NUM" --issue "$ISSUE" --post >>"$LOG" 2>&1 \
      || say "WARN: reviewer failed on PR #$PR_NUM (the PR stands, unreviewed)"
  else
    say "no PR found for $BRANCH; nothing to review"
  fi

  # 6. RELEASE at PR-open, not at close, so a reviewer can pick the tree up.
  python3 "$CLAIM" release "$ISSUE" --agent "$AGENT" --session "$SESSION" >/dev/null 2>&1 || true
  DONE=$((DONE+1))
done

say "worker: run complete"
exit 0
