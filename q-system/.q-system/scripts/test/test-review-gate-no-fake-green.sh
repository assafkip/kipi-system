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
for f in declined-to-start-short.md declined-to-start-long.md; do
  stated="$(extract_verdict "$FX/$f")"
  derived="$(verdict_from_findings "$FX/$f")"
  final="$(resolve_verdict "$stated" "$derived")"

  # The exact shape of the defect: the reviewer said stop, the ladder said go.
  check "$f: still reproduces the shape (stated '$stated' vs derived '$derived')" \
        "$([ "$stated" = "REQUEST CHANGES" ] && [ "$derived" = "APPROVE" ] && echo 0 || echo 1)"

  case "$final" in
    APPROVE|"APPROVE WITH NITS")
      check "$f resolves to a non-approving verdict (got '$final')" 1 ;;
    *)
      check "$f resolves to a non-approving verdict (got '$final')" 0 ;;
  esac
done

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
check "a lone derived verdict stands when nothing was stated" \
      "$([ "$(resolve_verdict '' 'APPROVE')" = "APPROVE" ] && echo 0 || echo 1)"
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
