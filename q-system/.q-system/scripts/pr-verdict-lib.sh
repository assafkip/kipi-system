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
#
# TWO further real-payload corrections, both from PR #11 round 4 (2026-07-27):
#   - the verdict may sit on the line AFTER a bare `## VERDICT` heading, so the
#     anchor has to span a few lines (-A3), not just the matching line.
#   - the verdict line can QUALIFY itself: `**REQUEST CHANGES** (not BLOCK --
#     nothing here writes an unrecoverable object)`. Taking the last token on
#     that line records BLOCK for a review that said the opposite in the same
#     breath. The verdict is stated FIRST and qualified after, so take head -1.
# That misread actually reached the record: pr-11.verdict.json read BLOCK while
# the review said REQUEST CHANGES. Both route to rework so behavior survived,
# but "APPROVE (not BLOCK...)" would have reworked an approved PR forever.
extract_verdict() {
  local f="$1" v=""
  [ -s "$f" ] || return 0
  v="$(grep -A3 -E 'VERDICT' "$f" 2>/dev/null | sed 's/BLOCKERS\{0,1\}//g' \
        | grep -oE 'APPROVE WITH NITS|REQUEST CHANGES|APPROVE|BLOCK' | head -1)"
  [ -n "$v" ] || v="$(sed 's/BLOCKERS\{0,1\}//g' "$f" 2>/dev/null \
        | grep -oE 'APPROVE WITH NITS|REQUEST CHANGES|APPROVE|BLOCK' | head -1)"
  printf '%s' "$v"
}

# verdict_from_findings <review-file>
# Derive the verdict MECHANICALLY from the FINDINGS block severities. This is
# the enforcement half of the severity floor: a prompt telling the reviewer how
# to grade is not enforcement (no-prompt-only-enforcement), and PR #11 round 4
# proved the gap is real -- the model reasoned its way to the right call there,
# but nothing made it. Severity labels are structured data; the verdict is a
# function of them, so compute it instead of reading prose.
#   any blocker -> BLOCK            (anchor: unrecoverable if merged)
#   any major   -> REQUEST CHANGES  (recoverable, but a human must clean up)
#   minors/nits -> APPROVE WITH NITS (captured as follow-ups, never wedges)
#   none        -> APPROVE
# Empty when there is no FINDINGS block, so the caller falls back to prose.
verdict_from_findings() {
  local f="$1" block
  [ -s "$f" ] || return 0
  block="$(sed -n '/^FINDINGS:/,/^END FINDINGS/p' "$f" 2>/dev/null)"
  printf '%s' "$block" | grep -q '^FINDINGS:' || return 0
  if   printf '%s' "$block" | grep -qE '^blocker\|';    then printf 'BLOCK'
  elif printf '%s' "$block" | grep -qE '^major\|';      then printf 'REQUEST CHANGES'
  elif printf '%s' "$block" | grep -qE '^(minor|nit)\|'; then printf 'APPROVE WITH NITS'
  else printf 'APPROVE'
  fi
}

# pr_mergeable <pr-number>
# GitHub's mergeability for a PR: MERGEABLE | CONFLICTING | UNKNOWN, or empty
# when gh cannot answer. ONE reader of this state, for the same reason this file
# exists at all: the worker and the driver both need it, and two callers each
# shelling their own `gh pr view` is two readers of one input with drifting
# semantics. Empty on any failure, which the gate treats as "not a conflict".
pr_mergeable() {
  gh pr view "$1" --json mergeable -q .mergeable 2>/dev/null | tr -d '[:space:]'
}

# rework_gate <verdict> [mergeable]
# The deterministic slice of the severity floor: whether another rework round
# is allowed to start. Exit codes, not prose:
#   0  = rework      (REQUEST CHANGES or BLOCK -- the review is the spec; OR an
#                     approved PR that no longer merges -- the conflict is)
#   10 = approved    (APPROVE or APPROVE WITH NITS *and still mergeable* --
#                     nothing to rework; the PR waits on the founder. Minors
#                     were captured, not wedged.)
#   20 = unreviewed  (no verdict -- with no review there is no spec; refuse and
#                     point at `kipi review <PR#> --post` instead of guessing)
#
# WHY MERGEABILITY IS PART OF THE GATE (ASK-208, sp-71b63e62)
# ----------------------------------------------------------
# A verdict is a statement about a diff at a moment. Mergeability is a statement
# about that diff against main NOW, and main moves underneath it. PR #11 was
# approved at 06:08Z; #16 landed at 17:30Z and broke it. Reading the verdict
# alone, both converge and a direct worker run skipped #11 in under two seconds
# and reported "waiting on founder merge only" -- so the loop could not dispatch
# the one thing actually blocking the merge. An approved PR that does not merge
# is not done.
#
# Only a stated CONFLICTING counts. UNKNOWN is GitHub still computing, and empty
# is gh failing; treating either as a conflict would manufacture rework rounds on
# healthy PRs every time the API was slow, which is the wrong-refusal failure
# that would stall every instance's worker at once.
rework_gate() {
  local verdict="${1:-}" mergeable="${2:-}"
  case "$verdict" in
    "REQUEST CHANGES"|"BLOCK")            return 0 ;;
    "APPROVE"|"APPROVE WITH NITS")
      [ "$mergeable" = "CONFLICTING" ] && return 0
      return 10 ;;
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

# review_round <reviews-dir> <pr-number>
# Which round the NEXT review of this PR will be: existing review files + 1.
# Derived from disk, not from the worker's attempts json, because the reviewer
# also runs standalone (`kipi review 11`) where that counter is never bumped --
# it would report round 1 forever and the anti-re-litigation rule would never arm.
review_round() {
  local dir="$1" pr="$2" n
  n="$(ls "$dir/pr-$pr-"*.md 2>/dev/null | wc -l | tr -d ' ')"
  printf '%s' $(( ${n:-0} + 1 ))
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
