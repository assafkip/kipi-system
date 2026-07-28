#!/usr/bin/env bash
# Drive one Linear issue to an APPROVED PR: dispatch Sana, review, repeat.
#
# WHY THIS EXISTS
# ---------------
# `linear-worker.sh` runs exactly ONE round: work, then review, then stop. So
# every subsequent round needed a human to type `kipi work --apply --issue X`
# again. That put a person in the loop for the one thing the loop was built to
# remove, and on PR #11 it meant four hand-dispatched rounds across an evening.
# Sana is a robot. She does not need a human to tell her to keep going.
#
# WHAT IT IS NOT
# --------------
# Not a scheduler. This is a foreground driver for ONE issue with a hard round
# cap. It never merges, never closes an issue, and inherits every refusal in
# linear-worker.sh because it drives that script rather than reimplementing it.
#
# EXITS (audited against .claude/rules/loop-exits.md)
#   1 goal met        -> verdict record reads APPROVE / APPROVE WITH NITS
#   2 turn cap        -> MAX_ROUNDS (default 4), the ceiling on rounds
#   5 no progress     -> same verdict AND no new commit on the branch two rounds
#                        running: the rework is not moving, stop burning rounds
#   7 error threshold -> no PR, or a review that produced no verdict
#   4 wall clock      -> inherited: each round is bounded inside the worker
#                        (1800s work) and the reviewer (2400s review)
#
# Usage: converge.sh --issue ASK-150 [--max-rounds 4] [--dry]
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKEL="$(cd "$SCRIPT_DIR/../../.." && pwd)"
# Overridable so the suite cannot page the founder. A test that Slacks "converge
# stalled" every run is exactly the cry-wolf failure this fleet keeps killing.
NOTIFY="${KIPI_NOTIFY:-$SCRIPT_DIR/slack-notify.sh}"
STATE_DIR="${KIPI_STATE_DIR:-$HOME/.config/kipi}"
REVIEWS_DIR="$STATE_DIR/pr-reviews"
LOG="$STATE_DIR/linear-worker.log"
. "$SCRIPT_DIR/pr-verdict-lib.sh"

# The worker command is injectable ONLY so the test suite can drive this loop
# against a fake that returns scripted verdicts. Testing convergence against the
# real worker would cost an hour and real model spend per case, so the loop
# logic would end up untested -- which is how a driver ships with an infinite
# loop in it. Default is always the real worker.
WORKER_CMD="${KIPI_CONVERGE_WORKER:-bash $SCRIPT_DIR/linear-worker.sh}"

ISSUE=""; MAX_ROUNDS=4; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --issue) shift; ISSUE="${1:-}" ;;
    --max-rounds) shift; MAX_ROUNDS="${1:-4}" ;;
    --dry) DRY=1 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
  shift || true
done
[ -n "$ISSUE" ] || { echo "usage: converge.sh --issue ASK-nnn [--max-rounds N] [--dry]" >&2; exit 1; }

TS() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "$(TS) converge[$ISSUE] $*" | tee -a "$LOG"; }

BRANCH="sana/$(echo "$ISSUE" | tr 'A-Z' 'a-z')"
pr_for_branch() { gh pr list --head "$BRANCH" --json number -q '.[0].number' 2>/dev/null; }
# The head sha comes from pr_head_sha in the shared lib, not a local copy of the
# same `gh pr view`: this driver and linear-worker.sh now BOTH compare it against
# the sha a review pinned, and two private readers of one input is how those two
# comparisons drift apart.

if [ "$DRY" = "1" ]; then
  PR="$(pr_for_branch)"
  V=""; [ -n "$PR" ] && V="$(verdict_from_record "$REVIEWS_DIR/pr-$PR.verdict.json")"
  say "[dry] branch=$BRANCH pr=${PR:-none} verdict=${V:-none} would run up to $MAX_ROUNDS round(s)"
  exit 0
fi

# RELEASE THE CLAIM IF THIS RUN IS KILLED.
#
# linear-claim.py deliberately does NOT pid-check the claim itself (only the
# critical-section guard) -- the claiming python process exits immediately, so
# its pid is meaningless, and the claim is meant to outlive it. Correct design,
# real operational hole: a SIGKILL, a harness timeout, a laptop sleeping, or a
# ctrl-c leaves the lock held with nothing to reclaim it.
#
# Observed 2026-07-27: this driver was killed mid-run on ASK-181 and left
# `ASK-181 claimed by sana (session worker-1785159359-39569)`. Because the lock
# is still repo-root scoped until ASK-188 lands, that one dead session blocked
# EVERY issue on the board until a human released it by hand. In an unattended
# loop, "a human notices and runs release" is not a recovery path -- nobody is
# watching, which is the entire premise.
#
# The trap cannot know the worker's session token (the worker mints its own), so
# it releases by the holder RECORDED IN THE LOCK, which is what the manual fix
# does. Best-effort by design: never let cleanup failure mask the real exit code.
release_stale_claim_for_issue() {
  local held
  held="$(python3 - "$ISSUE" <<'PY' 2>/dev/null || true
import json, os, subprocess, sys
issue = sys.argv[1]
override = os.environ.get("KIPI_LINEAR_CLAIMS")
if override:
    path = override
else:
    try:
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        raise SystemExit(0)
    path = os.path.join(root, ".linear-claims.json")
try:
    rec = json.load(open(path))
except Exception:
    raise SystemExit(0)
# Only speak up for THIS issue: never release a lock another issue legitimately holds.
if rec.get("issue") == issue:
    print("%s\t%s" % (rec.get("agent", ""), rec.get("session", "")))
PY
)"
  [ -n "$held" ] || return 0
  local agent session
  agent="$(printf '%s' "$held" | cut -f1)"
  session="$(printf '%s' "$held" | cut -f2)"
  [ -n "$session" ] || return 0
  python3 "$SCRIPT_DIR/linear-claim.py" release "$ISSUE" \
    --agent "$agent" --session "$session" >/dev/null 2>&1 \
    && say "released the claim this run left on $ISSUE (holder $session)" || true
}

# Exits 128+n directly rather than re-raising the signal at itself. Re-raising is
# the tidier convention, but `kill -TERM $$` from a backgrounded run reached the
# PARENT too and killed the caller: the test suite that drives this exited 143
# with its own later cases never run. A cleanup path that can take down its
# caller is worse than an unconventional exit code.
on_interrupt() {
  local sig="$1" code="$2"
  say "INTERRUPTED by $sig -- releasing any claim so the board is not wedged"
  release_stale_claim_for_issue
  exit "$code"
}
trap 'on_interrupt TERM 143' TERM
trap 'on_interrupt INT  130' INT
trap 'on_interrupt HUP  129' HUP

LAST_VERDICT=""; LAST_SHA=""; ROUND=0
while [ "$ROUND" -lt "$MAX_ROUNDS" ]; do
  ROUND=$((ROUND + 1))
  say "round $ROUND/$MAX_ROUNDS dispatching Sana"

  # One full round: work phase, then the adversarial review, both bounded inside
  # the worker. A nonzero rc is the worker's own failure handling (it already
  # bumped attempts and pinged); the verdict check below decides what to do.
  $WORKER_CMD --apply --limit 1 --issue "$ISSUE" >>"$LOG" 2>&1
  WRC=$?

  PR="$(pr_for_branch)"
  if [ -z "$PR" ]; then
    say "STOP exit-7: no PR on $BRANCH after round $ROUND (worker rc=$WRC). Sana could not open one; see $LOG"
    bash "$NOTIFY" "converge $ISSUE: stopped, no PR after round $ROUND" 2>/dev/null || true
    exit 7
  fi

  VERDICT="$(verdict_from_record "$REVIEWS_DIR/pr-$PR.verdict.json")"
  SHA="$(pr_head_sha "$PR")"
  REVIEWED_SHA="$(head_sha_from_record "$REVIEWS_DIR/pr-$PR.verdict.json")"

  # ARGUMENT 2 IS THE MERGE STATE, and this driver still does not read it: ASK-212
  # scoped mergeability to the worker, which runs first inside every round here.
  # "" is byte-identical to the one-argument form this call used before, so the
  # merge half of the gate behaves exactly as it did.
  #
  # ARGUMENTS 3 AND 4 ARM ASK-216 (ASK-219, sp-a27722e7). That drift exit shipped
  # with NO caller passing them -- this call site was the one-argument form named
  # in its own comment -- so exit 40 could never fire. Observed live 2026-07-28:
  # an approval recorded at bf641ad and a head of c063c3d converged in three
  # seconds as "waiting on founder merge only". The reviewed sha comes from the
  # record the reviewer wrote; the current head is the ONE `gh pr view` read on
  # the line above, reused rather than read a second time.
  #
  # The gate's NOTE goes through `say` so it lands in the run log with everything
  # else. Swallowing it would silently grandfather the blind spot it announces.
  GATE_NOTE="$(rework_gate "$VERDICT" "" "$REVIEWED_SHA" "$SHA")"; GATE=$?
  [ -n "$GATE_NOTE" ] && say "$GATE_NOTE"
  if [ "$GATE" = "10" ]; then
    say "DONE exit-1: PR #$PR verdict '$VERDICT' after $ROUND round(s). Waiting on founder merge only."
    bash "$NOTIFY" "converge $ISSUE: $VERDICT after $ROUND round(s), PR #$PR ready to merge" 2>/dev/null || true
    exit 1
  fi
  if [ "$GATE" = "20" ]; then
    say "STOP exit-7: PR #$PR has no verdict after round $ROUND -- the review died or timed out. Re-run: kipi review $PR --issue $ISSUE --post"
    bash "$NOTIFY" "converge $ISSUE: review produced no verdict on round $ROUND" 2>/dev/null || true
    exit 7
  fi

  # 40 = STALE. The verdict approves a commit that is no longer the head, so the
  # code sitting at the head has never been read. NOT terminal and never a merge:
  # another round runs, and the review at the end of it writes a record pinned to
  # the current head, which is the only thing that clears this.
  #
  # Deliberately falls THROUGH to the no-progress guard below rather than
  # `continue`-ing past it. If the head and the verdict both stop moving, that
  # guard stops the loop at exit 5; skipping it would re-review the same PR every
  # round to the cap, which is the cry-wolf failure this exit has to avoid.
  if [ "$GATE" = "40" ]; then
    say "round $ROUND: PR #$PR reads '$VERDICT', but that verdict was recorded at $REVIEWED_SHA and the head is now $SHA -- the code at the head was never reviewed. NOT done; re-reviewing."
  fi

  # NO PROGRESS (exit 5). Same verdict AND the branch head never moved means the
  # rework pass changed nothing -- running it again re-reads the same review and
  # produces the same nothing. Requiring BOTH avoids a false stop: a real fix
  # that happens to draw the same verdict again still moves the sha, and that is
  # convergence in progress, not a stall.
  if [ "$VERDICT" = "$LAST_VERDICT" ] && [ -n "$LAST_SHA" ] && [ "$SHA" = "$LAST_SHA" ]; then
    # THE PAGE HAS TO CARRY THE DRIFT, because it is the only thing that reaches
    # the founder's phone (PR #30 review round 2, minor 4). Gate 40 falls through
    # to this guard on purpose, so a stuck drift -- a held claim, a tree that
    # needs a human, a reviewer that is down -- exits here. The generic text read
    # "stalled at 'APPROVE WITH NITS', no code change in round N", which is a
    # benign stall on an approved PR. The gate-40 line above is in the run log;
    # the log is not what wakes anyone.
    STALL_LOG="STOP exit-5: round $ROUND changed no code and drew the same verdict '$VERDICT'. Not burning another round."
    STALL_PAGE="converge $ISSUE: stalled at '$VERDICT', no code change in round $ROUND"
    if [ "$GATE" = "40" ]; then
      STALL_LOG="STOP exit-5: round $ROUND changed no code, and PR #$PR is STILL approved at $REVIEWED_SHA with an unreviewed head of $SHA. Re-reviewing it is not working; not burning another round."
      STALL_PAGE="converge $ISSUE: PR #$PR is '$VERDICT' at $REVIEWED_SHA but its head $SHA was never reviewed, and round $ROUND changed nothing - unreviewed code is sitting at the head, needs a human"
    fi
    say "$STALL_LOG"
    bash "$NOTIFY" "$STALL_PAGE" 2>/dev/null || true
    exit 5
  fi
  LAST_VERDICT="$VERDICT"; LAST_SHA="$SHA"
  say "round $ROUND -> $VERDICT (head $SHA); reworking"
done

say "STOP exit-2: hit the $MAX_ROUNDS-round cap still at '$LAST_VERDICT'. A cap-out means the reviewer and Sana disagree persistently; read the last review before raising the cap."
bash "$NOTIFY" "converge $ISSUE: hit $MAX_ROUNDS-round cap, still $LAST_VERDICT" 2>/dev/null || true
exit 2
