#!/usr/bin/env bash
# The review gate must not go green on a review that never ran (ASK-312).
#
# WHY THIS EXISTS. On 2026-08-02, PR #74 twice received
# `kipi/reviewer-approved=success` from a reviewer that had explicitly declined to
# start. codex answered "Reply `OK` and I'll run the review exactly as planned",
# echoing the prompt's findings TEMPLATE back -- header, column legend,
# END FINDINGS, and zero data rows. `verdict_from_findings` fell through its
# severity ladder to `else APPROVE`, and pr-review-agent.sh preferred that derived
# APPROVE over the reviewer's own STATED "REQUEST CHANGES".
#
# That is the single required check standing in for human review across this
# fleet, and it failed OPEN: posted on the exact head SHA, where it looks
# maximally legitimate, on a loop that merges its own PRs.
#
# THE FIXTURES ARE THE REAL ARTIFACTS, byte for byte, not hand-written imitations.
# A fixture I invent tests my model of the bug; these three files are what the
# producer actually emitted, so they test the parser. Copied verbatim from
# ~/.config/kipi/pr-reviews/codex/pr-74-20260802-*.md:
#
#   real-review-request-changes.md  345 KB, 3 finding rows, ~8 min  -> must stay usable
#   declined-to-start-short.md        8 KB, 0 rows, ~20 s          -> must NOT approve
#   declined-to-start-long.md        38 KB, 0 rows, ~57 s          -> must NOT approve
#
# THE NEGATIVE HALF IS THE POINT. A gate that can only fail is as useless as one
# that can only pass, so the real 345 KB review must still derive a usable verdict.
# Without that case this test would pass against a parser hard-wired to refuse.
#
# Isolation: reads fixtures only. Touches no live review directory and posts no
# commit status.

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HERE/../pr-verdict-lib.sh"
FX="$HERE/fixtures/pr-verdict"

# shellcheck source=/dev/null
. "$LIB"

PASS=0
FAIL=0

check() {  # check <description> <condition-result>
  if [ "$2" = "0" ]; then
    echo "  ok: $1"
    PASS=$((PASS + 1))
  else
    echo "  FAIL: $1"
    FAIL=$((FAIL + 1))
  fi
}

echo "=== ASK-312: a review that did not run cannot go green ==="

for f in real-review-request-changes.md declined-to-start-short.md declined-to-start-long.md; do
  [ -f "$FX/$f" ] || { echo "  FAIL: missing fixture $f"; FAIL=$((FAIL + 1)); }
done
[ "$FAIL" = "0" ] || { echo; echo "FAIL: fixtures missing ($FAIL)"; exit 1; }

# --- the two declines must not resolve to an approving verdict ----------------
#
# NOTE ON LAYER, because the first attempt at this fix got it wrong. The obvious
# move is to make an empty findings block stop deriving APPROVE. That collides
# with a deliberate contract -- test-severity-floor.sh pins "an empty findings
# block must derive APPROVE" by name, and test-findings-block-reader.sh case 2
# depends on it so a round 2 that refutes everything can still land. Two existing
# suites went red; the change was wrong, not the suites.
#
# "Reviewed, found nothing" and "never started" are byte-identical INSIDE the
# block. The discriminator is outside it: what the reviewer itself said. So the
# assertions below are on resolve_verdict, where the two signals meet.
# UPSTREAM MOVED UNDER THIS LOOP, TWICE, AND BOTH MOVES WERE FIXES LANDING.
# These two fixtures no longer reproduce the original stated/derived shape:
#
#   derived: ASK-274 (6fe7a3c) added review_is_usable, and sp-df1a458f made
#            findings_block skip the prompt's own echoed template, so both files
#            now derive NOTHING where they historically derived APPROVE.
#   stated:  ASK-356. The "REQUEST CHANGES" these fixtures used to state was
#            never the reviewer -- it was the prompt's grading rule, echoed to
#            stdout by `codex exec` and read back as the answer. The fixture's
#            premise WAS the defect.
#
# Measured on this base 2026-08-03, both files: usable NO, stated '', derived ''.
#
# A test pinned to a bug's fingerprint dies with the bug and takes the gate with
# it, and weakening it to "derived is whatever it is" would make it vacuous. So
# what is asserted here is the SAFETY PROPERTY this suite exists for: A REVIEW
# THAT NEVER RAN MUST NEVER PRODUCE AN APPROVAL -- at every point the pipeline
# could leak one, each input signal SEPARATELY and then the resolved output,
# because "stated is safe OR derived is safe" passes on the weak half and never
# tests the other. The fidelity burden for reproducing a LIVE disagreement sits
# on the fixture further down, which still does.
approving() {   # approving <verdict> -- exit 0 when this verdict releases a PR
  # The same two values post_reviewer_status maps to state=success. Anything
  # else, unstated included, posts failure and HOLDS the PR.
  case "${1:-}" in APPROVE|"APPROVE WITH NITS") return 0 ;; *) return 1 ;; esac
}
for f in declined-to-start-short.md declined-to-start-long.md; do
  stated="$(extract_verdict "$FX/$f")"
  derived="$(verdict_from_findings "$FX/$f")"
  final="$(resolve_verdict "$stated" "$derived")"

  check "$f: the reviewer's own words do not approve (stated '${stated:-<unstated>}')" \
        "$(approving "$stated" && echo 1 || echo 0)"
  check "$f: the severity ladder does not approve either (derived '${derived:-<unstated>}')" \
        "$(approving "$derived" && echo 1 || echo 0)"
  # THE TWO USABILITY RULES ARE ASSERTED SEPARATELY, AND THAT IS NOT REDUNDANCY.
  # review_is_usable is an OR: a complete non-template block AND no decline. On
  # these two fixtures BOTH rules fire, so each one masks the other and the
  # roll-up cannot be killed by breaking either alone. Measured 2026-08-03: a
  # mutant that makes review_declined_to_start never fire left the roll-up GREEN,
  # because the block rule was still carrying it. An assertion no single mutation
  # can turn red is not testing anything. The roll-up stays as the integration
  # check -- it is the predicate pr-review-agent.sh actually calls -- but the two
  # halves below are what give it teeth.
  check "$f: the prompt's echoed template is not accepted as a findings block" \
        "$(has_complete_findings_block "$FX/$f" && echo 1 || echo 0)"
  check "$f: the plan-and-wait answer is detected as a decline" \
        "$(review_declined_to_start "$FX/$f" && echo 0 || echo 1)"
  check "$f: the stream is classified unusable" \
        "$(review_is_usable "$FX/$f" && echo 1 || echo 0)"
  check "$f resolves to a non-approving verdict (got '${final:-<unstated>}')" \
        "$(approving "$final" && echo 1 || echo 0)"
done

# --- the shape that IS still live on this base --------------------------------
#
# A review that PASSES review_is_usable, files only nits, and whose author still
# said stop. ASK-274 cannot catch this one: the review is real, so the usability
# gate correctly lets it through, and the severity ladder correctly derives an
# APPROVING verdict from nits alone. resolve_verdict is the ONLY thing left
# between that and kipi/reviewer-approved=success on a PR the reviewer rejected.
#
# Without this case the suite would pass on a base where every remaining fixture
# is intercepted upstream, and the fix under test would ship never having been
# exercised end to end. That is the failure this file exists to prevent.
LIVE=usable-review-states-changes-derives-nits.md
stated="$(extract_verdict "$FX/$LIVE")"
derived="$(verdict_from_findings "$FX/$LIVE")"
final="$(resolve_verdict "$stated" "$derived")"

check "$LIVE: passes the usability gate (ASK-274 does not catch it)" \
      "$(review_is_usable "$FX/$LIVE" >/dev/null 2>&1 && echo 0 || echo 1)"

# The precondition. If this goes red the fixture stopped reproducing and every
# assertion under it is worthless, so it is checked explicitly rather than assumed.
check "$LIVE: still reproduces a LIVE disagreement (stated '$stated' vs derived '$derived')" \
      "$([ "$stated" = "REQUEST CHANGES" ] && { [ "$derived" = "APPROVE" ] || [ "$derived" = "APPROVE WITH NITS" ]; } && echo 0 || echo 1)"

check "$LIVE: resolves to the harsher stated verdict, not the derived green (got '$final')" \
      "$([ "$final" = "REQUEST CHANGES" ] && echo 0 || echo 1)"

# --- the floor still overrides a reviewer that is too soft on itself ----------
#
# The rule is "never resolve toward approval", not "always take the stated one".
# A reviewer that logs a blocker and then writes APPROVE must still be overridden
# by its own findings, which is the severity floor's original job. Without this,
# the fix would be a one-way ratchet that disarms the floor.
check "a stated APPROVE is still overridden by a derived BLOCK" \
      "$([ "$(resolve_verdict 'APPROVE' 'BLOCK')" = "BLOCK" ] && echo 0 || echo 1)"
check "a stated APPROVE is still overridden by derived REQUEST CHANGES" \
      "$([ "$(resolve_verdict 'APPROVE' 'REQUEST CHANGES')" = "REQUEST CHANGES" ] && echo 0 || echo 1)"
check "agreement passes through unchanged" \
      "$([ "$(resolve_verdict 'APPROVE' 'APPROVE')" = "APPROVE" ] && echo 0 || echo 1)"
# A LONE DERIVED VERDICT STANDS ONLY WHEN IT IS NOT AN APPROVAL (ASK-1227).
#
# This check used to read `resolve_verdict '' 'APPROVE'` = APPROVE, and that
# assertion PINNED THE DEFECT rather than a contract. APPROVE is the only verdict
# the ladder can derive from a block with ZERO severity rows, so "derived APPROVE
# with nothing stated" is precisely: an empty block, and a reviewer that never
# said the PR was fine.
#
# Measured 2026-09-03 on PR #78: codex could not reach api.github.com, read no
# diff, said "VERDICT: NOT ISSUED", and closed an empty block. NOT ISSUED is not
# a verdict token, so stated was "" -- this exact call -- and the gate went green
# on a review that had read nothing. A worker merged on it.
#
# The harsher directions are untouched: a lone derived BLOCK or REQUEST CHANGES
# still stands alone, because failing closed needs no corroboration.
check "a lone derived APPROVE does NOT stand when nothing was stated" \
      "$([ -z "$(resolve_verdict '' 'APPROVE')" ] && echo 0 || echo 1)"
check "a lone derived BLOCK still stands when nothing was stated" \
      "$([ "$(resolve_verdict '' 'BLOCK')" = "BLOCK" ] && echo 0 || echo 1)"
check "a lone derived REQUEST CHANGES still stands when nothing was stated" \
      "$([ "$(resolve_verdict '' 'REQUEST CHANGES')" = "REQUEST CHANGES" ] && echo 0 || echo 1)"
check "a lone derived APPROVE WITH NITS still stands when nothing was stated" \
      "$([ "$(resolve_verdict '' 'APPROVE WITH NITS')" = "APPROVE WITH NITS" ] && echo 0 || echo 1)"
check "a lone stated verdict stands when nothing derived" \
      "$([ "$(resolve_verdict 'REQUEST CHANGES' '')" = "REQUEST CHANGES" ] && echo 0 || echo 1)"

# --- NEGATIVE SELF-TEST: the real review must still work ----------------------
#
# If this case ever fails, the fix has stopped being a gate and become a wall.
real="$FX/real-review-request-changes.md"
real_rows="$(findings_block "$real" | grep -cE '^(blocker|major|minor|nit)\|')"
check "the real 8-minute review still carries findings (got $real_rows rows)" \
      "$([ "$real_rows" -ge 1 ] && echo 0 || echo 1)"

real_derived="$(verdict_from_findings "$real")"
check "the real review still derives a usable verdict (got '${real_derived:-<empty>}')" \
      "$([ -n "$real_derived" ] && echo 0 || echo 1)"

check "the real review is still recognised as a complete findings block" \
      "$(has_complete_findings_block "$real" && echo 0 || echo 1)"

# A genuinely clean review -- one that ran and found nothing -- must still be able
# to approve. This is the case the zero-row rule could wrongly catch, so it is
# pinned here. Built in a tempfile, never a live path.
clean="$(mktemp)"
trap 'rm -f "$clean"' EXIT
{
  echo "VERDICT: APPROVE"
  echo "FINDINGS:"
  echo "severity|file|line|what"
  echo "nit|foo.py|1|trailing whitespace"
  echo "END FINDINGS"
} > "$clean"
clean_derived="$(verdict_from_findings "$clean")"
check "a real review with one nit still derives an approving verdict (got '$clean_derived')" \
      "$([ "$clean_derived" = "APPROVE WITH NITS" ] && echo 0 || echo 1)"

# --- WIRING: the script must actually USE the resolver -----------------------
#
# Everything above tests the lib function. None of it proves pr-review-agent.sh
# calls it, and a correct helper nobody invokes is the defect this whole issue is
# about, one layer up. Fable's mutation pass on ASK-122 found exactly this shape:
# two shipped fixes with zero coverage, because the tests pinned the helper and
# not the call site. So pin the call site.
AGENT="$HERE/../pr-review-agent.sh"
check "pr-review-agent.sh calls resolve_verdict" \
      "$(grep -q 'resolve_verdict "\$STATED_VERDICT" "\$DERIVED_VERDICT"' "$AGENT" && echo 0 || echo 1)"

# The pre-fix line, spelled out so a revert cannot pass silently. If someone puts
# this assignment back, the gate reopens and this check is what says so.
check "pr-review-agent.sh no longer assigns the raw derived verdict" \
      "$(grep -qE '^\s*VERDICT="\$DERIVED_VERDICT"\s*$' "$AGENT" && echo 1 || echo 0)"

check "the lib defines resolve_verdict exactly once" \
      "$([ "$(grep -c '^resolve_verdict()' "$LIB")" = "1" ] && echo 0 || echo 1)"

echo
if [ "$FAIL" = "0" ]; then
  echo "PASS: $PASS/$((PASS + FAIL)) review-gate checks"
  exit 0
fi
echo "FAIL: $FAIL of $((PASS + FAIL)) review-gate checks failed"
exit 1
