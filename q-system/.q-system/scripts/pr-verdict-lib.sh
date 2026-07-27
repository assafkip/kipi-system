#!/usr/bin/env bash
# Shared verdict semantics for the PR review loop (ASK-113, severity floor).
#
# WHY A LIB: the reviewer (pr-review-agent.sh) and the worker (linear-worker.sh)
# both need to know what a review concluded. Two scripts each grepping the review
# prose with their own regex is two readers of one input with different
# semantics -- the exact defect class review round 2 flagged on this PR line.
# One extractor, one gate, sourced by both.
#
# The DATA hand-off between them is the verdict record
# (~/.config/kipi/pr-reviews/pr-<N>.verdict.json), written once by the reviewer.
# The worker only falls back to re-extracting from the review .md for PRs
# reviewed before the record existed.

# extract_verdict <review-file>
# Prints APPROVE | APPROVE WITH NITS | REQUEST CHANGES | BLOCK, or nothing if
# the file states no verdict (empty file, killed run, freeform prose).
# Anchored on the VERDICT line first so prose like "this would BLOCK deploys"
# elsewhere in the review cannot win; whole-file grep is only the fallback.
# The sed strips BLOCKER/BLOCKERS before token matching: the REAL round-2
# review of PR #11 ends "Fix first: **BLOCKER 1**" after its verdict line, and
# a bare BLOCK token match reads that as verdict BLOCK. Found by using the
# captured payload as the fixture, which is the point of the fixture rule.
extract_verdict() {
  local f="$1" v=""
  [ -s "$f" ] || return 0
  v="$(grep -E 'VERDICT' "$f" 2>/dev/null | sed 's/BLOCKERS\{0,1\}//g' \
        | grep -oE 'APPROVE WITH NITS|REQUEST CHANGES|APPROVE|BLOCK' | tail -1)"
  [ -n "$v" ] || v="$(sed 's/BLOCKERS\{0,1\}//g' "$f" 2>/dev/null \
        | grep -oE 'APPROVE WITH NITS|REQUEST CHANGES|APPROVE|BLOCK' | tail -1)"
  printf '%s' "$v"
}

# rework_gate <verdict>
# The deterministic slice of the severity floor: whether another rework round
# is allowed to start. Exit codes, not prose:
#   0  = rework      (REQUEST CHANGES or BLOCK -- the review is the spec)
#   10 = approved    (APPROVE or APPROVE WITH NITS -- nothing to rework; the PR
#                     waits on the founder. Minors were captured, not wedged.)
#   20 = unreviewed  (no verdict -- with no review there is no spec; refuse and
#                     point at `kipi review <PR#> --post` instead of guessing)
rework_gate() {
  case "${1:-}" in
    "REQUEST CHANGES"|"BLOCK")            return 0 ;;
    "APPROVE"|"APPROVE WITH NITS")        return 10 ;;
    *)                                    return 20 ;;
  esac
}

# extract_minor_findings <review-file>
# Prints the `minor|claim|file:line` lines from the review's FINDINGS block
# (the machine-readable block the reviewer prompt requires after the verdict).
# Soft by design: an LLM that ignores the format yields zero lines, and the
# caller logs the zero -- capture can miss, it must never invent.
extract_minor_findings() {
  local f="$1"
  [ -s "$f" ] || return 0
  sed -n '/^FINDINGS:/,/^END FINDINGS/p' "$f" 2>/dev/null | grep -E '^minor\|' || true
}

# verdict_from_record <verdict-json>
# Reads the `verdict` field of a pr-<N>.verdict.json record. Empty on any
# parse failure -- a corrupt record reads as unreviewed, which fails closed.
verdict_from_record() {
  local f="$1"
  [ -s "$f" ] || return 0
  python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("verdict",""))
except Exception: pass' "$f" 2>/dev/null || true
}
