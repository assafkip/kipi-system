#!/usr/bin/env bash
# Pairs with: pr-verdict-lib.sh findings_block (the ONE reader).
#
# WHY THIS TEST EXISTS. Two independent defences stop the reviewer's own echoed
# prompt template from filling a REQUIRED status with a fabricated APPROVE, and
# they landed on two branches that never saw each other:
#
#   ASK-287  (PR #86) -- the TRANSCRIPT-REGION SKIP. Rejects by WHERE the text
#                        sits: above the `codex` assistant-turn marker is the
#                        harness talking to itself, not the model's answer.
#   sp-df1a458f (PR #87) -- the PLACEHOLDER GUARD. Rejects by WHAT the rows are:
#                        a block whose rows are none of the four severities is
#                        the template, not findings.
#
# Merging #86 forward would have DELETED the second one (it forked at ea673e69,
# before #87 landed). Measured on the merge branch before resolution: the branch
# alone accepted the bare template AND an in-turn echo, deriving APPROVE from
# both. So this file pins BOTH mechanisms, and case 4 is the one that fails if
# either is quietly dropped later.
#
# NEITHER SUBSUMES THE OTHER, which is the whole reason both stay:
#   case 2/3 -- template rows, in-turn        -> only the placeholder guard sees it
#   case 4   -- REAL severity rows, harness   -> only the transcript skip sees it
# Case 4 is not hypothetical: from round 2 the prompt hands the model the PREVIOUS
# round's findings to re-prove, so the echoed region carries real severity rows
# that the placeholder guard is required to accept.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="${PR_VERDICT_LIB:-$HERE/../pr-verdict-lib.sh}"
# REF HATCH: point PR_VERDICT_LIB at a copy extracted from a pre-fix git ref to
# watch these cases FAIL. A case added after its own fix has never been seen red.
# shellcheck disable=SC1090
source "$LIB"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAILED=0

check() {   # check <name> <fixture-file> <expect-usable yes|no> <expect-verdict>
  local name="$1" f="$2" want_blk="$3" want_v="$4" blk="no" v
  has_complete_findings_block "$f" && blk="yes"
  v="$(verdict_from_findings "$f")"
  if [ "$blk" = "$want_blk" ] && [ "$v" = "$want_v" ]; then
    printf 'PASS  %-52s block=%-3s verdict=%s\n' "$name" "$blk" "${v:-<empty>}"
  else
    printf 'FAIL  %-52s block=%-3s verdict=%s  (wanted block=%s verdict=%s)\n' \
      "$name" "$blk" "${v:-<empty>}" "$want_blk" "${want_v:-<empty>}"
    FAILED=1
  fi
}

# ---- fixtures -------------------------------------------------------------
# The template exactly as the reviewer prompt prints it. `severity` is a literal
# placeholder word, not one of the four grades.
TEMPLATE=$'FINDINGS:\nseverity|one-sentence claim|file:line\nEND FINDINGS'

# 1. A real out-of-credits `codex exec` transcript. Trimmed from a live capture
#    (sha 934a8ab9..., 2026-08-03): banner, workdir, the echoed prompt carrying
#    the template, then the API refusing. The model never took a turn.
printf '%s\n' \
  'Reading additional input from stdin...' \
  'OpenAI Codex v0.146.0' \
  '--------' \
  'workdir: /repo' \
  'model: gpt-5.6-sol' \
  '--------' \
  'user' \
  'Review this PR.' \
  "$TEMPLATE" \
  "ERROR: You've hit your usage limit." \
  "ERROR: You've hit your usage limit." > "$TMP/oo-credits.txt"

# 2. The bare template with no transcript around it: the shape the placeholder
#    guard exists for, and the shape the transcript skip cannot see.
printf '%s\n' "$TEMPLATE" > "$TMP/bare-template.txt"

# 3. The template echoed INSIDE the model's own turn -- what a plan-instead-of-a-
#    review does when it quotes the block it was shown. Below the turn marker, so
#    the transcript skip is blind here by construction.
printf '%s\n' \
  'Reading additional input from stdin...' \
  'OpenAI Codex v0.146.0' \
  '--------' \
  'workdir: /x' \
  'model: m' \
  '--------' \
  'codex' \
  'Here is my plan. Reply OK and I will execute exactly that plan.' \
  "$TEMPLATE" > "$TMP/echo-in-turn.txt"

# 4. THE ROW THE PLACEHOLDER GUARD CANNOT SEE. Round 2 replays the previous
#    round's REAL findings into the prompt, so the harness region holds a block
#    of genuine severity rows -- which the placeholder guard must accept. The
#    model then dies before taking a turn. Only the transcript skip refuses this,
#    and without it the gate derives BLOCK from findings nobody re-examined.
printf '%s\n' \
  'Reading additional input from stdin...' \
  'OpenAI Codex v0.146.0' \
  '--------' \
  'workdir: /x' \
  'model: m' \
  '--------' \
  'user' \
  'Re-prove these round-1 findings:' \
  'FINDINGS:' \
  'blocker|round 1 said the ledger can be deleted|led.py:9' \
  'END FINDINGS' \
  "ERROR: You've hit your usage limit." > "$TMP/prior-round-echo.txt"

# 5. POSITIVE CONTROL, transcript: a real review below the turn marker still
#    parses, and the echoed template above it does not win. Without this the
#    suite would pass by refusing everything.
printf '%s\n' \
  'Reading additional input from stdin...' \
  'OpenAI Codex v0.146.0' \
  '--------' \
  'workdir: /x' \
  'model: m' \
  '--------' \
  'user' \
  "$TEMPLATE" \
  'codex' \
  'I read the diff.' \
  'FINDINGS:' \
  'major|the retry cap is never applied|run.sh:40' \
  'END FINDINGS' > "$TMP/real-transcript.txt"

# 6. POSITIVE CONTROL, plain: `claude -p` writes no banner, so the fallback's
#    output has no transcript to strip and is read whole. This is the row that
#    caught the first cut of the transcript rule (it wedged the fallback).
printf '%s\n' \
  'OpenAI Codex v0.146.0 was unreachable, so I reviewed it myself.' \
  'FINDINGS:' \
  'minor|a stale comment|x.sh:1' \
  'END FINDINGS' > "$TMP/fallback-plain.txt"

# 7. POSITIVE CONTROL: the legitimately EMPTY block. A round 2 that refutes
#    everything closes with one, and rejecting it would route a real review to
#    the fallback for finding nothing. Zero rows is not the template.
printf '%s\n' 'Every round-1 finding is refuted.' 'FINDINGS:' 'END FINDINGS' \
  > "$TMP/empty-block.txt"

# ---- the gate -------------------------------------------------------------
echo "== the echoed prompt is never a review =="
check "real out-of-credits artifact"          "$TMP/oo-credits.txt"       no  ""
check "bare prompt template"                  "$TMP/bare-template.txt"    no  ""
check "echo inside the model's own turn"      "$TMP/echo-in-turn.txt"     no  ""
check "prior-round findings, model never spoke" "$TMP/prior-round-echo.txt" no ""
echo "== a real review still lands =="
check "real review below the turn marker"     "$TMP/real-transcript.txt"  yes "REQUEST CHANGES"
check "plain fallback review (no transcript)" "$TMP/fallback-plain.txt"   yes "APPROVE WITH NITS"
check "legitimately empty round-2 block"      "$TMP/empty-block.txt"      yes "APPROVE"

if [ "$FAILED" = "0" ]; then echo "ALL PASS"; else echo "FAILURES PRESENT"; fi
exit "$FAILED"
