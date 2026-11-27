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
# why each value alone: validating the concatenation let an empty one through as 0
# and declared an instant false stall (PR #904 review round 1).
for v in "$STALL_MIN" "$DEADLINE_MIN"; do
  case "$v" in ''|*[!0-9]*) usage ;; esac
done
# 10# forces base 10: "010" would read as octal 8 (round 2). Both must be at least 1 minute.
STALL_MIN=$((10#$STALL_MIN)); DEADLINE_MIN=$((10#$DEADLINE_MIN))
[ "$STALL_MIN" -ge 1 ] && [ "$DEADLINE_MIN" -ge 1 ] || usage

POLL="${PR_WATCH_POLL_SEC:-60}"
MIN_SEC="${PR_WATCH_MIN_SEC:-60}"
CALL_SEC="${PR_WATCH_CALL_SEC:-90}"   # per-gh-call bound, finding 1 of PR #907 round 2
STALL_SEC=$((STALL_MIN * MIN_SEC))
DEADLINE_SEC=$((DEADLINE_MIN * MIN_SEC))
FIELDS="state,mergeCommit,headRefOid,reviews,comments,statusCheckRollup,mergeable,reviewDecision"

# bounded <sec> cmd...: run cmd in its own process group, SIGKILL the group after <sec>, exit 124.
# why: the stall clock and the deadline are compared only BETWEEN polls, so one blocking `gh`
# (blackholed TLS, a proxy that never answers) hung the watcher forever (PR #907 review round 2,
# finding 1). macOS has no `timeout`; perl is on every Mac. Group kill, not just the child: a
# stub or wrapper that spawns `sleep` would otherwise keep running. Output goes to files, not a
# pipe, so a leftover grandchild cannot hold a $(...) open.
bounded() {
  perl -e '$t = shift; $p = fork; die unless defined $p;
    if (!$p) { setpgrp(0, 0); exec @ARGV or exit 127 }
    setpgrp($p, $p);
    $SIG{ALRM} = sub { kill "KILL", -$p; waitpid($p, 0); exit 124 };
    alarm $t; waitpid($p, 0); exit(($? & 127) ? 128 + ($? & 127) : $? >> 8)' "$@"
}

# stdin: gh JSON. stdout line 1 = state, 2 = merge oid, 3 = fingerprint, 4 = reason.
# Reason priority: red checks, conflict, changes requested, checks still running, no verdict
# at head. Running checks come BEFORE "no verdict": the reviewer job is itself a check, so
# blaming an absent reviewer mid-CI contradicted the rollup (PR #904 review round 1).
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
def roid(r): return (r.get("commit") or {}).get("oid") or ""
# a review with no commit oid cannot be tied to another head, so it counts as one here
mine = [r for r in reviews if roid(r) in (head, "")]
approved = d.get("reviewDecision") == "APPROVED" or any(r.get("state") == "APPROVED" for r in mine)
if red: why = "checks red: " + ", ".join(red)
elif d.get("mergeable") == "CONFLICTING": why = "merge conflict with base"
elif d.get("reviewDecision") == "CHANGES_REQUESTED": why = "changes requested"
elif pend: why = "checks still running: " + ", ".join(pend)
elif approved: why = "approved, auto-merge not armed?"
elif not mine: why = "no review or verdict at head " + head[:7] + " (nothing started a reviewer)"
else: why = "reviewed at head " + head[:7] + " but no verdict (comment only)"
print(d.get("state", "")); print((d.get("mergeCommit") or {}).get("oid") or ""); print(fp); print(why)
'
}

# why a separate stderr file: gh prints its upgrade notice to stderr, and folding it into the
# JSON made a MERGED PR read as "gh read failed" and exit 3 (PR #904 review round 1).
ERRF="$(mktemp "${TMPDIR:-/tmp}/pr-watch-err.XXXXXX")"
OUTF="$(mktemp "${TMPDIR:-/tmp}/pr-watch-out.XXXXXX")"
trap 'rm -f "$ERRF" "$OUTF"' EXIT
start=$(date +%s)
last_change=$start
last_fp=""
last_why="no successful gh read yet"
while :; do
  now=$(date +%s)
  # why remaining-time cap: a call allowed its full CALL_SEC could outlive the deadline by that much.
  budget=$((DEADLINE_SEC - (now - start))); [ "$budget" -gt "$CALL_SEC" ] && budget=$CALL_SEC; [ "$budget" -lt 1 ] && budget=1
  if [ -n "$REPO" ]; then bounded "$budget" gh pr view "$PR" -R "$REPO" --json "$FIELDS" >"$OUTF" 2>"$ERRF"; else bounded "$budget" gh pr view "$PR" --json "$FIELDS" >"$OUTF" 2>"$ERRF"; fi
  rc=$?
  raw="$(cat "$OUTF")"
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
  elif [ "$rc" -eq 124 ]; then
    # timed out = no change, so the stall clock and the deadline keep running (ASK-5842 round 2)
    last_why="gh read timed out after ${budget}s"
  else
    last_why="gh read failed: $( { cat "$ERRF"; printf '%s' "$raw"; } | head -c 120 | tr '\n' ' ')"
  fi
  now=$(date +%s)
  if [ $((now - last_change)) -ge "$STALL_SEC" ]; then
    echo "PR$PR STALLED no change for ${STALL_MIN}min: $last_why"
    exit 3
  fi
  if [ $((now - start)) -ge "$DEADLINE_SEC" ]; then
    echo "PR$PR STALLED deadline ${DEADLINE_MIN}min reached: $last_why"
    exit 3
  fi
  sleep "$POLL"
done
