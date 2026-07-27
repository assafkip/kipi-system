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
head_sha()      { gh pr view "$1" --json headRefOid -q .headRefOid 2>/dev/null; }

if [ "$DRY" = "1" ]; then
  PR="$(pr_for_branch)"
  V=""; [ -n "$PR" ] && V="$(verdict_from_record "$REVIEWS_DIR/pr-$PR.verdict.json")"
  say "[dry] branch=$BRANCH pr=${PR:-none} verdict=${V:-none} would run up to $MAX_ROUNDS round(s)"
  exit 0
fi

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
  SHA="$(head_sha "$PR")"

  rework_gate "$VERDICT"; GATE=$?
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

  # NO PROGRESS (exit 5). Same verdict AND the branch head never moved means the
  # rework pass changed nothing -- running it again re-reads the same review and
  # produces the same nothing. Requiring BOTH avoids a false stop: a real fix
  # that happens to draw the same verdict again still moves the sha, and that is
  # convergence in progress, not a stall.
  if [ "$VERDICT" = "$LAST_VERDICT" ] && [ -n "$LAST_SHA" ] && [ "$SHA" = "$LAST_SHA" ]; then
    say "STOP exit-5: round $ROUND changed no code and drew the same verdict '$VERDICT'. Not burning another round."
    bash "$NOTIFY" "converge $ISSUE: stalled at '$VERDICT', no code change in round $ROUND" 2>/dev/null || true
    exit 5
  fi
  LAST_VERDICT="$VERDICT"; LAST_SHA="$SHA"
  say "round $ROUND -> $VERDICT (head $SHA); reworking"
done

say "STOP exit-2: hit the $MAX_ROUNDS-round cap still at '$LAST_VERDICT'. A cap-out means the reviewer and Sana disagree persistently; read the last review before raising the cap."
bash "$NOTIFY" "converge $ISSUE: hit $MAX_ROUNDS-round cap, still $LAST_VERDICT" 2>/dev/null || true
exit 2
