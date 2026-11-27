#!/usr/bin/env bash
# pr-progress-watch.sh <pr> [-R owner/repo] [--stall-min N] [--deadline-min M] (ASK-5842)
#
# Wait on a PR and wake on a STALL, not only on merge.
#   exit 0  "PR<n> MERGED <oid>"  or  "PR<n> CLOSED"
#   exit 3  "PR<n> STALLED <reason>"   (nothing changed for N min, or the deadline hit)
#   exit 64 bad usage
#
# WHY: 2026-11-27 a session armed `while ...; gh pr view 903 ...; sleep 300; done`
# that woke only on merge. The PR sat on a reviewer nothing had started and the
# session idled about 5h. A watcher that has one exit (merged) hangs; this one has
# three (merged/closed, no progress for N min, deadline). The pr-progress-watch-guard
# PreToolUse hook refuses the hand-rolled loop and points here.
#
# Fingerprint = head SHA, review states, comment count, check names + conclusions,
# mergeable. Any change resets the stall clock. A failed `gh` call changes nothing,
# so a dead API accrues stall time and ends in STALLED (never an endless silent wait).
#
# Test seams (env): PR_WATCH_POLL_SEC (default 60) and PR_WATCH_MIN_SEC (seconds per
# "minute" for --stall-min/--deadline-min, default 60). `timeout` does not exist on
# this machine, so the deadline is a wall-clock compare, not a wrapper.
set -u

usage() {
  echo "usage: pr-progress-watch.sh <pr> [-R owner/repo] [--stall-min N] [--deadline-min M]" >&2
  exit 64
}

PR=""; REPO=""; STALL_MIN=30; DEADLINE_MIN=360
while [ "$#" -gt 0 ]; do
  case "$1" in
    -R) [ "$#" -ge 2 ] || usage; REPO="$2"; shift 2 ;;
    --stall-min) [ "$#" -ge 2 ] || usage; STALL_MIN="$2"; shift 2 ;;
    --deadline-min) [ "$#" -ge 2 ] || usage; DEADLINE_MIN="$2"; shift 2 ;;
    -*) usage ;;
    *) [ -z "$PR" ] || usage; PR="$1"; shift ;;
  esac
done
case "$PR" in ''|*[!0-9]*) usage ;; esac
case "$STALL_MIN$DEADLINE_MIN" in *[!0-9]*) usage ;; esac

POLL="${PR_WATCH_POLL_SEC:-60}"
MIN_SEC="${PR_WATCH_MIN_SEC:-60}"
STALL_SEC=$((STALL_MIN * MIN_SEC))
DEADLINE_SEC=$((DEADLINE_MIN * MIN_SEC))
FIELDS="state,mergeCommit,headRefOid,reviews,comments,statusCheckRollup,mergeable,reviewDecision"

# stdin: gh JSON. stdout line 1 = state, 2 = merge oid, 3 = fingerprint, 4 = reason.
# Reason priority: red checks, conflict, changes requested, no verdict at head, pending.
summarize() {
  python3 -I -c '
import json, sys
d = json.load(sys.stdin)
head = d.get("headRefOid") or ""
reviews = d.get("reviews") or []
checks = d.get("statusCheckRollup") or []
def cname(c): return c.get("name") or c.get("context") or "?"
def cres(c): return c.get("conclusion") or c.get("state") or c.get("status") or ""
RED = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
red = sorted(cname(c) + "=" + cres(c) for c in checks if cres(c) in RED)
pend = sorted(cname(c) for c in checks if cres(c) in ("", "PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED", "WAITING"))
rstates = sorted((r.get("author") or {}).get("login", "?") + ":" + r.get("state", "") + ":" + ((r.get("commit") or {}).get("oid") or "")[:7] for r in reviews)
fp = "|".join([head, ";".join(rstates), str(len(d.get("comments") or [])),
               ";".join(sorted(cname(c) + "=" + cres(c) for c in checks)), d.get("mergeable") or ""])
at_head = [r for r in reviews if (r.get("commit") or {}).get("oid") == head and r.get("state") in ("APPROVED", "CHANGES_REQUESTED")]
if red: why = "checks red: " + ", ".join(red)
elif d.get("mergeable") == "CONFLICTING": why = "merge conflict with base"
elif d.get("reviewDecision") == "CHANGES_REQUESTED": why = "changes requested"
elif not at_head: why = "no review or verdict at head " + head[:7] + " (nothing started a reviewer)"
elif pend: why = "checks pending: " + ", ".join(pend)
else: why = "verdict at head, checks green, not merged (auto-merge not armed?)"
print(d.get("state", "")); print((d.get("mergeCommit") or {}).get("oid") or ""); print(fp); print(why)
'
}

start=$(date +%s)
last_change=$start
last_fp=""
last_why="no successful gh read yet"
while :; do
  now=$(date +%s)
  if [ -n "$REPO" ]; then raw="$(gh pr view "$PR" -R "$REPO" --json "$FIELDS" 2>&1)"; else raw="$(gh pr view "$PR" --json "$FIELDS" 2>&1)"; fi
  rc=$?
  if [ "$rc" -eq 0 ] && out="$(printf '%s' "$raw" | summarize 2>/dev/null)" && [ -n "$out" ]; then
    state="$(printf '%s\n' "$out" | sed -n 1p)"
    oid="$(printf '%s\n' "$out" | sed -n 2p)"
    fp="$(printf '%s\n' "$out" | sed -n 3p)"
    last_why="$(printf '%s\n' "$out" | sed -n 4p)"
    case "$state" in
      MERGED) echo "PR$PR MERGED $oid"; exit 0 ;;
      CLOSED) echo "PR$PR CLOSED"; exit 0 ;;
    esac
    if [ "$fp" != "$last_fp" ]; then last_fp="$fp"; last_change=$now; fi
  else
    last_why="gh read failed: $(printf '%s' "$raw" | head -c 120 | tr '\n' ' ')"
  fi
  now=$(date +%s)
  if [ $((now - last_change)) -ge "$STALL_SEC" ]; then
    echo "PR$PR STALLED no change for ${STALL_MIN}min: $last_why"
    exit 3
  fi
  if [ $((now - start)) -ge "$DEADLINE_SEC" ]; then
    echo "PR$PR STALLED deadline ${DEADLINE_MIN}min reached, still moving: $last_why"
    exit 3
  fi
  sleep "$POLL"
done
