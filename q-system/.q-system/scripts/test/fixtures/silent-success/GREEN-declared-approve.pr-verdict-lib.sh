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

# findings_block <review-file>
# THE ONE READER of the machine-readable findings block. Prints the LAST COMPLETE
# block, or nothing. Every consumer of findings -- the verdict derivation, the
# minor capture, the reviewer's Linear comment -- goes through here.
#
# WHY IT EXISTS (sp-c0a9dac3). Three call sites each ran their own
# `sed -n '/^FINDINGS:/,/^END FINDINGS/p'`, which is wrong in two ways at once,
# and the fix had landed in only one of the three languages involved:
#
#   MULTIPLE BLOCKS CONCATENATE. sed RESTARTS the range after every `END
#   FINDINGS`, so a review containing two blocks yields both, glued together, and
#   a severity from a block that is not the verdict block sets the gate. Not
#   hypothetical: codex stdout is known to carry harness noise and A REPEATED
#   FINAL LINE (recorded on ASK-221 -- `hook: Stop`, `tokens used`, the last line
#   again), the reviewer prompt itself contains a literal `FINDINGS:` /
#   `END FINDINGS` template the model can echo, and from round 2 the prompt hands
#   the model the PREVIOUS round's findings to re-prove.
#
#   AN UNCLOSED BLOCK RUNS TO EOF. A stream that died one line into the block
#   printed a range with no severity lines, and no severities derives APPROVE --
#   a green gate for a review nobody read. pr-review-agent.sh defends that with
#   its own REVIEW_UNUSABLE flag, but the LIB still handed APPROVE to anyone else
#   who asked, so the safety lived in one caller instead of in the reader.
#
# LAST, NOT FIRST. The prompt says "Last, a machine-readable findings block", and
# a duplicated final line makes the last one the complete one. Taking the first
# would pick the echoed template.
#
# A BLOCK STILL OPEN AT EOF VOIDS THE WHOLE REVIEW, earlier complete blocks
# included. This is the case the first cut of this function got wrong, caught by
# its own reproducer: "last COMPLETE block" quietly falls back to a QUOTED
# prior-round block when the real trailing block is cut off mid-write, so a
# truncated review would derive a verdict from findings it had already withdrawn --
# and the completeness predicate built on it would call that review usable. An open
# block at EOF is evidence of truncation, so nothing in the stream is trustworthy.
#
# The cost of that strictness is a review whose PROSE happens to end with a line
# starting `FINDINGS:` reads as unstated. That is the safe direction and the same
# posture the rest of this file takes: unstated HOLDS a PR, green RELEASES it.
#
# awk, not sed, because the rule is stateful in two ways a range expression cannot
# express: opening a new block discards an unclosed one, and the end-of-input state
# decides whether any of it counts.
findings_block() {
  local f="$1"
  [ -s "$f" ] || return 0
  awk '
    /^FINDINGS:/            { buf = $0 "\n"; open = 1; next }
    open && /^END FINDINGS/ { last = buf $0 "\n"; open = 0; next }
    open                    { buf = buf $0 "\n" }
    END                     { if (open) exit 0; printf "%s", last }
  ' "$f" 2>/dev/null
}

# has_complete_findings_block <review-file>
# True when the review carries a usable block. DEFINED IN TERMS OF findings_block
# so the predicate and the extractor cannot answer differently -- it lives here,
# next to the reader, for exactly that reason.
#
# It used to be `grep -q '^FINDINGS:' && grep -q '^END FINDINGS'` inside
# pr-review-agent.sh: two markers, anywhere, in any order. That passes a review
# whose only COMPLETE block is a quoted prior round while its real trailing block
# is truncated -- so the unusable flag stays off, the gate goes green, and the
# verdict is derived from findings the review had already withdrawn. Two
# definitions of "complete" in one script is the drift this file exists to stop.
#
# DELIBERATELY STRUCTURAL, NOT ROW-COUNTING (ASK-312). Requiring at least one
# severity row here looks like the obvious hardening and is wrong: a round-2 review
# that refutes every round-1 finding closes with a legitimately EMPTY block, and
# `test-findings-block-reader.sh` case 2 pins that shape. Rejecting it would route
# a real review to the fallback engine and mark the status DEGRADED for finding
# nothing, which is the opposite of what finding nothing means.
#
# "Reviewed, found nothing" and "never started" are byte-identical inside the
# block. The discriminator is OUTSIDE it -- the reviewer's own STATED verdict --
# so the fix lives at that comparison, not in this predicate. See
# verdict_from_findings below and the decline-to-start guard in pr-review-agent.sh.
has_complete_findings_block() {
  [ -n "$(findings_block "${1:-}")" ]
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
# Empty when there is no COMPLETE FINDINGS block, so the caller falls back to
# prose. An unclosed block is now "no block" rather than "an empty block": empty
# reads as unstated, which holds a PR, where APPROVE released it.
verdict_from_findings() {
  local f="$1" block
  [ -s "$f" ] || return 0
  block="$(findings_block "$f")"
  printf '%s' "$block" | grep -q '^FINDINGS:' || return 0
  if   printf '%s' "$block" | grep -qE '^blocker\|';    then printf 'BLOCK'
  elif printf '%s' "$block" | grep -qE '^major\|';      then printf 'REQUEST CHANGES'
  elif printf '%s' "$block" | grep -qE '^(minor|nit)\|'; then printf 'APPROVE WITH NITS'
  # An empty block deriving APPROVE is a DELIBERATE contract, pinned by name in
  # test-severity-floor.sh: a round 2 that refutes everything must be able to land,
  # or approved PRs wedge forever. ASK-312 tried removing it and collided with that
  # contract plus test-findings-block-reader.sh case 2. The decline-to-start defect
  # is not fixed here -- see resolve_verdict below, where the discriminator lives.
  else printf 'APPROVE'
  fi
}

# resolve_verdict <stated> <derived>
# The ONE place a stated and a derived verdict become the verdict that gets posted.
#
# WHY THIS FAILS CLOSED (ASK-312). pr-review-agent.sh used to prefer the derived
# verdict whenever it existed, printing a NOTE about any disagreement and
# proceeding. On 2026-08-02 that silently converted a reviewer's own
# "REQUEST CHANGES" into APPROVE, twice, and posted kipi/reviewer-approved=success
# on the head SHA of a PR nobody had read. The reviewer had answered "Reply `OK`
# and I'll run the review exactly as planned" and echoed the prompt's TEMPLATE
# back: a structurally perfect block with zero rows, which the severity ladder
# reads as "nothing was wrong" when it meant "nothing was examined".
#
# The rule: a disagreement may never resolve TOWARD approval. Deriving a harsher
# verdict than the reviewer stated is fine and stays -- that is the severity floor
# doing its job against a reviewer that logged a blocker and then said APPROVE.
# Deriving a SOFTER one means the two signals contradict each other about whether
# the PR is safe, and the only safe reading of a contradiction is the harsher side.
#
# Ranked least to most permissive; a disagreement resolves to the lower rank.
verdict_rank() {   # verdict_rank <verdict>
  case "$1" in
    BLOCK)                printf '0' ;;
    "REQUEST CHANGES")    printf '1' ;;
    "APPROVE WITH NITS")  printf '2' ;;
    APPROVE)              printf '3' ;;
    *)                    printf '9' ;;   # unknown/empty: not a verdict
  esac
}

resolve_verdict() {   # resolve_verdict <stated> <derived>
  local stated="${1:-}" derived="${2:-}" sr dr
  [ -n "$derived" ] || { printf '%s' "$stated"; return 0; }
  [ -n "$stated" ]  || { printf '%s' "$derived"; return 0; }
  sr="$(verdict_rank "$stated")"
  dr="$(verdict_rank "$derived")"
  # An unrecognised stated verdict cannot vouch for anything, so the derived one
  # stands alone rather than being averaged with noise.
  [ "$sr" = "9" ] && { printf '%s' "$derived"; return 0; }
  if [ "$dr" -le "$sr" ]; then printf '%s' "$derived"; else printf '%s' "$stated"; fi
}

# pr_merge_state <pr-number>
# GitHub's mergeStateStatus for a PR: CLEAN | DIRTY | BEHIND | BLOCKED |
# UNSTABLE | DRAFT | HAS_HOOKS | UNKNOWN, or empty when gh cannot answer.
# ONE reader of this state, for the same reason this file exists at all: the
# worker and the driver both need it, and two callers each shelling their own
# `gh pr view` is two readers of one input with drifting semantics. Empty on any
# failure, which the gate treats as "still merges" -- see rework_gate.
pr_merge_state() {
  gh pr view "$1" --json mergeStateStatus -q .mergeStateStatus 2>/dev/null | tr -d '[:space:]'
}

# pr_head_sha <pr-number>
# The commit at the tip of the PR's head branch RIGHT NOW (GitHub's headRefOid),
# or empty when gh cannot answer. ONE reader, for the same reason pr_merge_state
# is one: both drivers have to agree on what "the current head" means before they
# can compare it to the sha a review pinned, and two callers each shelling their
# own `gh pr view` is two readers of one input with drifting semantics -- the
# defect class this file exists to close. Empty on any failure, which rework_gate
# reads as "unknown, fall back and say so", never as drift.
pr_head_sha() {
  gh pr view "$1" --json headRefOid -q .headRefOid 2>/dev/null | tr -d '[:space:]'
}

# --- the arm-state record (ASK-222, PR #33 review round 3, finding 1) --------
# record_automerge <path> <armed|unarmed|unknown>   -- written by the ONE reader
# automerge_from_record <path>                      -- read by everyone else
#
# WHY A RECORD AND NOT A SECOND PROBE. linear-worker.sh asks GitHub whether a PR
# has auto-merge on. converge.sh reports on the same PR minutes later and has to
# say who merges it. Giving converge its own `gh pr view --json autoMergeRequest`
# would be two readers of one input with drifting semantics -- the defect class
# this whole file exists to close, and converge's own call sites refuse it
# elsewhere. The alternative it reached for instead was an ASSERTION: a comment
# claiming "the worker arms every PR it touches", which was false for every PR
# the worker skipped as done, so the founder's phone got "no human merge needed"
# on PRs nothing had armed. A record is neither: it is the one reader's own
# answer, published, exactly like the verdict record two functions up.
#
# STALENESS, STATED. The record is rewritten every time the worker reaches the
# PR. A run that never got there (another session's claim, a worktree that could
# not be made) leaves the previous run's word standing. That is safe in the
# direction that matters: "armed" only goes false if a human turns auto-merge
# off, and "unarmed"/"unknown" both point the operator at the fallback command,
# which is a no-op on a PR that is in fact armed. Absent means absent -- the
# reader gets an empty string and must claim nothing.
record_automerge() {
  printf '%s\n' "$2" > "$1" 2>/dev/null || true
}

automerge_from_record() {
  [ -s "$1" ] || return 0
  tr -d '[:space:]' < "$1" 2>/dev/null
}

# _sha_norm <sha>
# Whitespace-stripped, lower-cased sha for comparison. Hex case and a stray
# newline are not drift. A PREFIX is deliberately NOT treated as a match: both
# sides of the comparison come from GitHub's full 40-char headRefOid, so a short
# sha means something unexpected wrote the record, and reading that as "same
# commit" would be a guess in the never-merge direction's favour.
_sha_norm() { printf '%s' "${1:-}" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]'; }

# rework_gate <verdict> [merge-state] [reviewed-head-sha] [current-head-sha]
# The deterministic slice of the severity floor: whether another rework round
# is allowed to start. Exit codes, not prose:
#   0  = rework      (REQUEST CHANGES or BLOCK -- the review is the spec)
#   10 = approved    (APPROVE or APPROVE WITH NITS *and it still merges* --
#                     nothing to rework; the PR waits on the founder. Minors
#                     were captured, not wedged.)
#   20 = unreviewed  (no verdict -- with no review there is no spec; refuse and
#                     point at `kipi review <PR#> --post` instead of guessing)
#   30 = conflicted  (approved, but it no longer merges -- a REBASE round, not a
#                     review round. Distinct from 0 so the caller can cap it
#                     separately; see the caller-owned cap note below.)
#   40 = stale       (approving, but at a sha that is no longer the PR's head --
#                     re-review at the new sha. NEVER merge, never auto-approve.)
#
# WHY MERGEABILITY IS PART OF THE GATE (ASK-212, sp-71b63e62)
# ----------------------------------------------------------
# A verdict is a statement about a diff at a moment. The merge state is a
# statement about that diff against main NOW, and main moves underneath it. PR
# #11 was approved at 06:08Z; #16 landed at 17:30Z and broke it. Reading the
# verdict alone, both converge and a direct worker run skipped #11 in under two
# seconds and reported "waiting on founder merge only" -- so the loop could not
# dispatch the one thing actually blocking the merge, and a human had to
# diagnose it by hand. An approved PR that does not merge is not done.
#
# ONLY A STATED DIRTY OR BEHIND COUNTS. BLOCKED is a branch-protection state a
# rebase cannot fix, UNSTABLE is a failing non-required check, UNKNOWN is GitHub
# still computing, and empty is gh failing. Treating any of those as a conflict
# would manufacture rebase rounds on healthy PRs every time the API was slow --
# the wrong-refusal failure that would stall every instance's worker at once.
# Fail toward "terminal": a missed conflict costs one human diagnosis, a
# manufactured one costs unbounded model budget on every PR at once.
#
# 30 IS NOT 0, AND THE CAP IS THE CALLER'S (PR #22 round-3 review, finding 4)
# --------------------------------------------------------------------------
# Making APPROVE non-terminal opens an unbounded rework path: an unresolvable
# conflict yields infinite rounds, and every round writes a permanent Linear
# comment on an object that cannot be deleted. So this returns a DISTINCT code
# rather than folding into 0. The caller caps conflict rounds on its own budget,
# separate from the review-round budget -- a PR that has converged on content
# must not lose its review rounds to rebase attempts. The gate answers "is this
# a conflict?"; it does not answer "have we tried enough times?", because the
# round ledger lives with the caller that owns the dispatch.
#
# The ONE-ARGUMENT form keeps its original semantics exactly (no merge state
# supplied reads as "still merges"), because converge.sh calls it that way and a
# silent behaviour change on the short form is a fleet-wide bug.
#
# WHY THE SHA IS PART OF THE GATE (ASK-216, sp-12f99480)
# ------------------------------------------------------
# A verdict record keyed on a PR NUMBER says "this PR was approved", never "this
# CODE was approved". The worker reuses one branch and one PR across rework
# rounds (linear-worker.sh:328), so every push landing after an approval
# inherited that approval silently. Today that is a stale skip; under an
# integrator it is an auto-merge of code no reviewer ever read, on a repo whose
# main fans out fleet-wide through `kipi update`. pr-receipt-gate.py already
# reasons this way with --head-sha; a verdict is the same class of claim.
#
# ABSENT IS NOT DRIFT. Every record written before this change lacks the field,
# so absent falls back to verdict-only and SAYS SO on stdout -- reading
# absent-as-drift would re-review every converged PR on the board at once. Same
# posture when the CURRENT head cannot be read: fail toward terminal, exactly as
# an empty merge state does above. A manufactured re-review round costs the
# whole fleet at once; a missed one costs a single human diagnosis.
#
# DRIFT OUTRANKS THE MERGE STATE. When both fire, the sha wins: a rebase round
# dispatched on a diff nobody reviewed is the same unreviewed-code path wearing
# a rebase coat. Re-review first; the fresh record then decides.
#
# 40 IS NOT 10 AND NOT 30. Callers passing 1 or 2 arguments (converge.sh,
# linear-worker.sh -- neither touched by this issue) can never see it, and a
# caller that does not know 40 falls out of its if-chain into the rework path,
# which is the safe direction: not terminal, never a merge.
rework_gate() {
  local verdict="${1:-}" merge_state="${2:-}" reviewed_sha="${3:-}" current_sha="${4:-}"
  case "$verdict" in
    "REQUEST CHANGES"|"BLOCK")            return 0 ;;
    "APPROVE"|"APPROVE WITH NITS")
      # Silent unless a caller actually asked for the sha check, so the short
      # forms stay byte-identical and no line is printed on every worker run.
      if [ -n "$reviewed_sha" ] || [ -n "$current_sha" ]; then
        if [ -z "$reviewed_sha" ]; then
          echo "  NOTE: no head_sha in this verdict record (written before ASK-216) -- cannot tell an approval from one inherited by a later push; falling back to verdict-only"
        elif [ -z "$current_sha" ]; then
          echo "  NOTE: could not read the PR's current head_sha; not manufacturing a re-review round on an unreadable head"
        elif [ "$(_sha_norm "$reviewed_sha")" != "$(_sha_norm "$current_sha")" ]; then
          return 40
        fi
      fi
      case "$merge_state" in
        "DIRTY"|"BEHIND")                 return 30 ;;
        *)                                return 10 ;;
      esac ;;
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
  findings_block "$f" | grep -E '^minor\|' || true
}

# review_comment_body <review-file> <verdict> <engine> <degraded>
# Renders the review as something a GitHub comment can actually hold.
#
# WHY IT EXISTS (sp-b418be32). `--post` piped the raw review file straight into
# `gh pr comment --body-file`. A codex review is not a review-shaped document: it
# is the agent's whole stdout. Measured on PR #34: 435,280 and 519,377 bytes,
# against GitHub's 65,536-byte comment limit. So EVERY post failed, the caller
# logged `WARN: could not comment on PR` and carried on, and the commit status it
# then wrote had no target_url. A human opening the PR saw a bare green check with
# nothing behind it -- the reviewer ran, cost real spend, and left no readable trace.
#
# NOT A NOISE PROBLEM, so trimming is not the fix. The harness header is 14 lines
# of 10,130. The bulk is the codex agent's own transcript, INCLUDING the diff it
# read -- which is why that file carries 11 `FINDINGS:` markers instead of one.
# The reviewer's actual message is the last ~250 lines. A 500KB transcript is a
# debugging artifact; GitHub is not an artifact store, and splitting it across
# eight comments would put eight comments of transcript on the PR.
#
# THE VERDICT AND FINDINGS DO NOT COME FROM THE TRUNCATED TEXT. They are taken
# from the caller's already-derived verdict and from `findings_block` (THE ONE
# READER), then printed ABOVE the tail. That ordering is the whole safety
# property: truncation can drop narrative, never the two facts a human needs to
# act. Deriving them from a tail we just cut would be a second reader with its
# own semantics, the defect class this file exists to stop.
#
# The engine is named in the body, not just the status description, for the same
# reason post_reviewer_status names it: a review whose reader is unknown is worth
# little, and the point of this loop is that the checker is not Claude.
review_comment_body() {
  local f="$1" verdict="${2:-}" engine="${3:-}" degraded="${4:-0}"
  local limit="${KIPI_REVIEW_COMMENT_LIMIT:-60000}"
  local bytes head_bytes block block_bytes
  bytes="$(wc -c <"$f" 2>/dev/null | tr -d ' ')"; bytes="${bytes:-0}"
  block="$(findings_block "$f")"
  [ -n "$block" ] || block="(no complete findings block parsed from this review)"

  printf '## Verdict: %s\n\n' "${verdict:-unstated}"
  [ "$degraded" = "1" ] \
    && printf '**DEGRADED**: codex was down, this is the Opus fallback. Not an independent second opinion.\n\n'
  printf 'Reviewer engine: `%s`. Full review on disk: `%s` (%s bytes).\n\n' \
    "${engine:-unknown}" "$f" "$bytes"
  # `$(...)` strips the trailing newline off the block, so the closing fence needs
  # its own \n. Without it the fence glues onto `END FINDINGS`, which both breaks
  # the code block on GitHub and makes the rendered block differ from
  # findings_block's output -- caught by case 4, which is exactly what that
  # byte-identity assertion is for.
  printf '```\n%s\n```\n\n' "$block"

  # Byte-bounded, then snapped FORWARD to a line boundary. `tail -c` alone can
  # open mid-line and, worse, mid-UTF-8-sequence: these reviews contain typographic
  # quotes, so a blind byte cut can emit an invalid sequence. Dropping the first
  # partial line costs nothing and keeps the body valid text.
  # MEASURE THE HEADER, DO NOT ASSUME IT (codex round 5 on PR #47, minor). The
  # reservation used to be a flat 5,000 bytes, but the findings block inside the
  # header is UNBOUNDED -- a review with many findings, or one long claim string,
  # blows past it and the rendered body exceeds the very limit this function
  # exists to guarantee. A cap that a large input can overrun is not a cap.
  #
  # The block is already in hand ($block), so its size is a fact, not an estimate.
  # The fixed number stays only as the allowance for the surrounding prose.
  # BYTES, NOT CHARACTERS (codex round 7, minor). `${#block}` counts CHARACTERS,
  # and these reviews are full of typographic quotes and dashes that are 2-3 bytes
  # each in UTF-8. So the budget under-counted the block by exactly the amount that
  # matters, and a findings block of multi-byte text could push the body past both
  # the configured cap and GitHub's. The whole point of measuring the block instead
  # of reserving a flat 5,000 was to stop guessing; measuring it in the wrong unit
  # is still guessing.
  block_bytes="$(printf '%s' "$block" | wc -c | tr -d ' ')"
  head_bytes=$(( $(review_comment_body_header_size) + ${block_bytes:-0} ))
  local room=$(( limit - head_bytes ))
  # A findings block alone can now exceed the limit. Truncating findings would
  # drop the one thing a human must act on, so the narrative goes to zero first
  # and the block is still printed whole -- deliberately overrunning rather than
  # silently losing a finding. The caller's failure branch then reports it, which
  # is a loud failure instead of a quiet omission.
  [ "$room" -gt 512 ] || room=0
  if [ "${bytes:-0}" -gt "$room" ]; then
    printf -- '--- reviewer output, last %s bytes of %s (full review at the path above) ---\n\n' \
      "$room" "$bytes"
    tail -c "$room" "$f" 2>/dev/null | tail -n +2
  else
    printf -- '--- reviewer output ---\n\n'
    cat "$f"
  fi
}

# review_comment_body_header_size
# Byte budget reserved for everything review_comment_body prints ABOVE the tail.
# A fixed reservation, not a measurement: measuring would mean rendering the
# header twice and the two copies could disagree. Generous on purpose -- a
# findings block runs to a few KB at most, and over-reserving only shortens the
# narrative, while under-reserving overruns the limit and loses the whole comment.
review_comment_body_header_size() { printf '%s' 5000; }

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

# head_sha_from_record <verdict-json>
# Reads the `head_sha` field: the commit the review actually examined. EMPTY for
# every record written before ASK-216, for a corrupt record, and for a run where
# `gh` could not answer -- all three are the same thing to rework_gate, which
# reads empty as "unknown, fall back and say so", never as drift.
head_sha_from_record() {
  local f="$1"
  [ -s "$f" ] || return 0
  python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("head_sha","") or "")
except Exception: pass' "$f" 2>/dev/null || true
}
