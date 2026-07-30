#!/usr/bin/env bash
# Reproducer for sp-b418be32: a codex review is too large for a GitHub comment,
# so `--post` never delivered the review to the PR.
#
# Pairs with: review_comment_body() in pr-verdict-lib.sh, and the --post call
# site in pr-review-agent.sh.
#
# WHY THE REF HATCH. Every case here must be watched FAIL before it is trusted.
# KIPI_TEST_REVIEWER_REF loads the lib from a pre-fix git ref, where
# review_comment_body does not exist at all -- so the harness asserts the
# ABSENCE is what fails, not a rewritten assertion. Same hatch and same reason
# as test-review-tree-guard.sh case 5.
#
#   KIPI_TEST_REVIEWER_REF=f277389 bash test-review-comment-body.sh   -> FAIL
#   bash test-review-comment-body.sh                                  -> PASS
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$(cd "$HERE/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

# ---- load the lib under test (live tree, or a pre-fix ref) -------------------
LIB="$SCRIPTS/pr-verdict-lib.sh"
if [ -n "${KIPI_TEST_REVIEWER_REF:-}" ]; then
  # Resolve the repo from the SCRIPT's own location, never from $PWD: a refuse-path
  # test that asks the checkout it is running in proves nothing about the caller.
  REPO="$(cd "$SCRIPTS" && git rev-parse --show-toplevel)"
  REL="$(cd "$SCRIPTS" && git ls-files --full-name pr-verdict-lib.sh)"
  LIB="$WORK/lib-at-ref.sh"
  git -C "$REPO" show "$KIPI_TEST_REVIEWER_REF:$REL" >"$LIB" 2>/dev/null \
    || { echo "cannot load pr-verdict-lib.sh at ref $KIPI_TEST_REVIEWER_REF"; exit 1; }
  echo "== lib loaded from ref $KIPI_TEST_REVIEWER_REF (expect FAILs) =="
fi
# shellcheck disable=SC1090
. "$LIB"

# GitHub's hard limit on an issue-comment body. The thing the defect violated.
GH_LIMIT=65536

# ---- the fixture IS the real payload ----------------------------------------
# A synthesized 500KB blob would not carry the properties that broke this: the
# codex header, a transcript that echoes the diff (so MULTIPLE FINDINGS: blocks),
# typographic quotes that a blind byte cut can split, and the real trailing
# block. Prefer the captured review; fall back to a shaped stand-in so the test
# still runs on a machine that never ran a review.
REAL="$HOME/.config/kipi/pr-reviews/codex/pr-34-20260729-210606.md"
BIG="$WORK/big-review.md"
if [ -s "$REAL" ]; then
  cp "$REAL" "$BIG"; echo "== fixture: captured review $(wc -c <"$BIG" | tr -d ' ') bytes =="
else
  {
    echo "Reading additional input from stdin..."
    echo "OpenAI Codex v0.145.0"
    # A quoted PRIOR block, so "take the last complete block" is under test too.
    echo "FINDINGS:"; echo "major|a quoted prior-round finding that must NOT win|a.sh:1"; echo "END FINDINGS"
    # Bulk, with typographic quotes so a blind byte cut could split a sequence.
    for _ in $(seq 1 12000); do echo "transcript line with a \xe2\x80\x99 curly quote and padding to make this long"; done
    echo "## VERDICT"; echo "APPROVE WITH NITS."
    echo "FINDINGS:"
    echo "minor|the real trailing finding the human has to act on|q-system/.q-system/scripts/pr-review-agent.sh:660"
    echo "END FINDINGS"
  } >"$BIG"
  echo "== fixture: synthesized $(wc -c <"$BIG" | tr -d ' ') bytes =="
fi

echo
echo "== 1. the defect itself: the raw file cannot be a comment =="
RAW_BYTES="$(wc -c <"$BIG" | tr -d ' ')"
# NEGATIVE SELF-TEST. This is the assertion the fix has to satisfy, aimed at the
# UNFIXED input. If it ever passes, the fixture stopped reproducing the defect and
# every result below is meaningless.
if [ "$RAW_BYTES" -gt "$GH_LIMIT" ]; then
  ok "fixture reproduces the defect: raw review is $RAW_BYTES bytes > $GH_LIMIT"
else
  bad "fixture no longer reproduces the defect ($RAW_BYTES <= $GH_LIMIT); every case below is void"
fi

echo
echo "== 2. the rendered body fits a GitHub comment =="
if ! type review_comment_body >/dev/null 2>&1; then
  bad "THE DEFECT: no review_comment_body exists, so --post can only send the raw $RAW_BYTES-byte file"
else
  BODY="$WORK/body.md"
  review_comment_body "$BIG" "APPROVE WITH NITS" "codex" 0 >"$BODY" 2>/dev/null
  B="$(wc -c <"$BODY" | tr -d ' ')"
  [ "$B" -le "$GH_LIMIT" ] \
    && ok "rendered body is $B bytes <= $GH_LIMIT" \
    || bad "rendered body is $B bytes, still over the $GH_LIMIT limit"
  [ "$B" -gt 200 ] \
    && ok "rendered body is not empty ($B bytes)" \
    || bad "rendered body is $B bytes, effectively empty"

  echo
  echo "== 3. truncation cannot drop the verdict or the findings =="
  grep -q 'APPROVE WITH NITS' "$BODY" \
    && ok "verdict survives truncation" \
    || bad "verdict is missing from the rendered body"
  grep -q '^FINDINGS:' "$BODY" && grep -q '^END FINDINGS' "$BODY" \
    && ok "a complete findings block survives truncation" \
    || bad "no complete findings block in the rendered body"

  echo
  echo "== 4. the findings come from the ONE READER, not from the cut text =="
  # The fixture's FIRST block is a decoy. If the rendered block carries it, the
  # renderer grew its own extractor instead of going through findings_block.
  EXPECTED="$(findings_block "$BIG")"
  RENDERED="$(awk '/^FINDINGS:/{f=1} f{print} /^END FINDINGS/{if(f) exit}' "$BODY")"
  [ -n "$EXPECTED" ] && [ "$RENDERED" = "$EXPECTED" ] \
    && ok "rendered block is byte-identical to findings_block output" \
    || bad "rendered block differs from findings_block (a second reader)"

  echo
  echo "== 5. the full artifact is still reachable =="
  grep -q "$BIG" "$BODY" \
    && ok "body names the on-disk review path" \
    || bad "body does not name the full review path, so the transcript is unreachable"

  echo
  echo "== 6. the body says which engine reviewed =="
  grep -q 'codex' "$BODY" \
    && ok "body names the engine" \
    || bad "body does not name the reviewing engine"

  echo
  echo "== 7. a DEGRADED review says so in the body =="
  review_comment_body "$BIG" "APPROVE" "codex" 1 >"$WORK/deg.md" 2>/dev/null
  grep -qi 'DEGRADED' "$WORK/deg.md" \
    && ok "degraded review is marked in the body" \
    || bad "degraded review is not marked, so a fallback reads as a second opinion"

  echo
  echo "== 8. a small review is passed through whole, not truncated =="
  SMALL="$WORK/small.md"
  { echo "## VERDICT"; echo "APPROVE"; echo "a short narrative line";
    echo "FINDINGS:"; echo "END FINDINGS"; } >"$SMALL"
  review_comment_body "$SMALL" "APPROVE" "codex" 0 >"$WORK/small-body.md" 2>/dev/null
  grep -q 'a short narrative line' "$WORK/small-body.md" \
    && ok "small review keeps its narrative" \
    || bad "small review lost its narrative"

  echo
  echo "== 9. valid UTF-8 after the cut =="
  if iconv -f UTF-8 -t UTF-8 "$BODY" >/dev/null 2>&1; then
    ok "rendered body is valid UTF-8 (the byte cut did not split a sequence)"
  else
    bad "rendered body is invalid UTF-8: the byte cut split a multi-byte sequence"
  fi

  echo
  echo "== 10. an unusable review does not render a fake findings block =="
  TRUNC="$WORK/trunc.md"
  { echo "## VERDICT"; echo "REQUEST CHANGES"; echo "FINDINGS:";
    echo "major|a block that never closes|x.sh:1"; } >"$TRUNC"
  review_comment_body "$TRUNC" "REQUEST CHANGES" "codex" 0 >"$WORK/trunc-body.md" 2>/dev/null
  # findings_block VOIDS a review whose block is open at EOF, so the renderer must
  # say "no complete block" rather than print the withdrawn one as if it counted.
  grep -q 'no complete findings block' "$WORK/trunc-body.md" \
    && ok "truncated review renders as 'no complete findings block'" \
    || bad "truncated review rendered a findings block findings_block had voided"
fi

echo
echo "== 11. THE CALL SITE actually uses the renderer =="
# Codex round 1 on PR #47, minor 2: every case above tests the LIBRARY. Mutate
# pr-review-agent.sh back to `gh pr comment --body-file "$REVIEW"` and all ten
# still pass, because none of them ever asks what the reviewer posts. A renderer
# nothing calls is the same dead code as a hook nothing wires -- this repo's
# load-path lesson, applied to its own test.
#
# Structural, not behavioural: driving the real --post path would need a live PR
# and a real gh. So assert the two things a revert would break, on the file the
# scripts dir actually holds.
AGENT="$SCRIPTS/pr-review-agent.sh"
if [ ! -f "$AGENT" ]; then
  bad "no pr-review-agent.sh next to the lib, so the call site cannot be checked"
else
  POST_BLOCK="$WORK/post-block.txt"
  # From the `--post` guard to the end: the only region that comments on a PR.
  awk '/^if \[ "\$POST" = "1" \]; then/,0' "$AGENT" > "$POST_BLOCK"
  if grep -q 'review_comment_body' "$POST_BLOCK"; then
    ok "the --post path calls review_comment_body"
  else
    bad "THE DEFECT: the --post path does not call review_comment_body, so the raw review is still what gets posted"
  fi
  # The mutation this case exists to catch: --body-file pointed straight at $REVIEW.
  if grep -qE '(gh|GH) pr comment[^|]*--body-file[[:space:]]*"?\$REVIEW"?([[:space:]]|$)' "$POST_BLOCK"; then
    bad "THE DEFECT: gh pr comment still posts --body-file \$REVIEW (the raw transcript)"
  else
    ok "gh pr comment does not post the raw \$REVIEW file"
  fi
fi

echo
echo "== 13. a LARGE findings block cannot overrun the limit (codex round 5, minor) =="
# The header reservation was a flat 5,000 bytes while the findings block inside
# it is unbounded, so a review with many findings blew past the cap this function
# exists to guarantee. Build a block bigger than the old reservation and assert
# the body still fits AND still carries every finding.
BIGF="$WORK/big-findings.md"
{
  echo "## VERDICT"; echo "REQUEST CHANGES"
  # The padding must push the review PAST the byte budget, or the renderer takes
  # the "small review, pass it through whole" branch and the reservation is never
  # exercised. My first fixture was ~30KB, so case 13 passed against the OLD flat
  # reservation too -- it proved nothing until the negative self-test said so.
  for _ in $(seq 1 3000); do echo "narrative padding line to give the tail something to eat and push this review well past the sixty-thousand-byte budget"; done
  echo "FINDINGS:"
  for i in $(seq 1 90); do
    printf 'major|finding %s with a deliberately long claim string so the block alone exceeds the old flat five-thousand-byte header reservation|q-system/.q-system/scripts/some-file-%s.sh:%s\n' "$i" "$i" "$i"
  done
  echo "END FINDINGS"
} >"$BIGF"
BLOCK_BYTES="$(findings_block "$BIGF" | wc -c | tr -d ' ')"
review_comment_body "$BIGF" "REQUEST CHANGES" "codex" 0 >"$WORK/bigf-body.md" 2>/dev/null
BB="$(wc -c <"$WORK/bigf-body.md" | tr -d ' ')"
[ "${BLOCK_BYTES:-0}" -gt 5000 ] \
  && ok "fixture reproduces the case: findings block alone is $BLOCK_BYTES bytes > the old 5000 reservation" \
  || bad "fixture too small ($BLOCK_BYTES bytes); case 13 proves nothing"
[ "$BB" -le "$GH_LIMIT" ] \
  && ok "body with a $BLOCK_BYTES-byte findings block still fits ($BB <= $GH_LIMIT)" \
  || bad "THE DEFECT: body is $BB bytes, over the $GH_LIMIT limit the renderer guarantees"
RENDERED_N="$(awk '/^FINDINGS:/{f=1} f&&/^major\|/{n++} /^END FINDINGS/{if(f){print n; exit}}' "$WORK/bigf-body.md")"
[ "${RENDERED_N:-0}" -eq 90 ] \
  && ok "all 90 findings survive (narrative is sacrificed first, never a finding)" \
  || bad "only ${RENDERED_N:-0} of 90 findings rendered -- truncation ate a finding"

echo
echo "== 12. no BSD-only mktemp form (portability, caught by CI not by me) =="
# `mktemp -t name` appends a random suffix on BSD (macOS) and is REJECTED by GNU
# mktemp (the Linux runner) unless the template carries three or more X's. My
# first cut used the BSD form: 14/14 here, `validate` red on the PR, because the
# body file was never created and --body-file got an empty path.
#
# A grep, deliberately. The behavioural test cannot see this -- it passes on the
# developer's OS by construction, and the only machine that disagrees is the one
# nobody runs the suite on by hand.
if [ -f "$AGENT" ]; then
  # Per LINE, not per line-ending. The first cut anchored the template with `$`,
  # which never matched because the real line continues with `)" || ...` -- so the
  # guard passed with the BSD form reintroduced. Caught by running the negative
  # self-test, which is the entire reason for running it: a check that cannot
  # fail is not a check, and this one could not.
  BAD="$(grep -n 'mktemp' "$AGENT" | grep -E 'mktemp[^|;)]*-t[[:space:]]' | grep -v 'XXX' || true)"
  if [ -z "$BAD" ]; then
    ok "no BSD-only 'mktemp -t' form in the reviewer"
  else
    bad "THE DEFECT: BSD-only mktemp form, fails on the GNU/Linux runner: $BAD"
  fi
  # And the positive: every mktemp here must carry an explicit template.
  MKT="$(grep -c 'mktemp' "$AGENT" || true)"
  MKX="$(grep -c 'mktemp.*XXXXXX' "$AGENT" || true)"
  if [ "${MKT:-0}" -eq 0 ] || [ "${MKX:-0}" -ge 1 ]; then
    ok "mktemp calls carry an explicit XXXXXX template ($MKX of $MKT)"
  else
    bad "mktemp used without an XXXXXX template ($MKX of $MKT)"
  fi
fi

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: review_comment_body keeps a codex review inside a GitHub comment, and the reviewer uses it"
