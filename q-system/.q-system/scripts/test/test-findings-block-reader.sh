#!/usr/bin/env bash
# Reproducer for sp-c0a9dac3: ONE reader of the machine-readable findings block.
# Pairs with findings_block() in pr-verdict-lib.sh.
#
# THE DEFECT. Three call sites each ran their own
# `sed -n '/^FINDINGS:/,/^END FINDINGS/p'`. sed RESTARTS that range after every
# closing line, so a review containing more than one block yields all of them
# glued together, and it runs to EOF when a block never closes. Two failure
# directions from one expression:
#
#   a refuted prior-round finding sets the gate -> an approved PR wedges forever
#   a stream that died mid-block derives APPROVE -> a green gate, review unread
#
# The multi-block shape is not invented. From round 2 the reviewer prompt hands
# the model the previous round's findings to re-prove, the prompt itself contains
# a literal FINDINGS:/END FINDINGS template, and codex stdout was recorded on
# ASK-221 carrying harness noise plus A REPEATED FINAL LINE.
#
# Point it at an older copy to watch it fail:
#   KIPI_TEST_LIB_REF=403bc0b bash test-findings-block-reader.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
REF="${KIPI_TEST_LIB_REF:-}"

PASS=0
ok()   { PASS=$((PASS+1)); echo "  ok: $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }

W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT

if [ -n "$REF" ]; then
  git -C "$ROOT" show "$REF:q-system/.q-system/scripts/pr-verdict-lib.sh" > "$W/lib.sh" \
    || fail "cannot read pr-verdict-lib.sh at ref $REF"
  echo "lib under test: ref $REF"
else
  cp "$SCRIPT_DIR/../pr-verdict-lib.sh" "$W/lib.sh" || fail "cannot copy the lib"
  echo "lib under test: working tree"
fi
LIB="$W/lib.sh"
# shellcheck disable=SC1090
. "$LIB"

# --- 1. the negative self-test FIRST -----------------------------------------
# A reader that returned nothing at all would pass every multi-block case below
# while breaking every real review. So the ordinary shape is asserted before any
# defect case: one block, two minors, APPROVE WITH NITS, both minors captured.
cat > "$W/normal.md" <<'EOF'
## VERDICT: APPROVE WITH NITS

FINDINGS:
minor|help text omits --engine|q-system/x.sh:9
minor|the retry loop drops the last error|q-system/x.sh:12
END FINDINGS
EOF
[ "$(verdict_from_findings "$W/normal.md")" = "APPROVE WITH NITS" ] \
  || fail "the reader broke the ORDINARY case: a single block with two minors derived
      '$(verdict_from_findings "$W/normal.md")'. Every case below would pass vacuously."
[ "$(extract_minor_findings "$W/normal.md" | grep -c .)" = "2" ] \
  || fail "the ordinary case captured $(extract_minor_findings "$W/normal.md" | grep -c .) of 2 minors"
ok "the ordinary single-block review still derives APPROVE WITH NITS and yields both minors"

# --- 2. a refuted prior-round block must not set the gate ---------------------
# The exact shape round 2 produces: the reviewer quotes what round 1 said, states
# that it could not reproduce it, and closes with its own empty block.
cat > "$W/multi.md" <<'EOF'
## THIS IS REVIEW ROUND 2 OF THIS PR

Round 1 raised:

FINDINGS:
blocker|deletes a production volume on a credential mismatch|q-system/x.sh:40
END FINDINGS

I re-ran that reproducer. It does not reproduce: the delete path is behind the
destructive-op hook, which exits 2 before the command is built. Nothing survived.

## VERDICT: APPROVE

FINDINGS:
END FINDINGS
EOF
GOT="$(verdict_from_findings "$W/multi.md")"
[ "$GOT" = "APPROVE" ] \
  || fail "THE DEFECT (sp-c0a9dac3): a review that explicitly REFUTED round 1's blocker derived
      '$GOT'. sed restarts the findings range after every 'END FINDINGS', so the quoted block is
      concatenated onto the real one and a severity the reviewer disproved sets the gate. An
      approved PR then wedges forever on a finding that does not exist."
ok "a quoted, refuted prior-round block does not set the verdict"

# AND IT STILL LANDS AFTER ASK-312. resolve_verdict now takes the harsher of the
# stated and derived verdicts, so this case is worth re-pinning at that layer: a
# clean round 2 agrees with itself (APPROVE/APPROVE) and must survive the new
# fail-closed rule. Without this, hardening the gate could silently wedge exactly
# the review shape sp-c0a9dac3 exists to let through.
[ "$(resolve_verdict "$(extract_verdict "$W/multi.md")" "$GOT")" = "APPROVE" ] \
  || fail "the fail-closed rule must not wedge a refuting round 2 that agrees with itself"
ok "a refuting round 2 still resolves to APPROVE under the fail-closed rule"

# --- 3. the minors captured must be the minors the verdict came from ----------
# extract_minor_findings feeds `spillover add`, which writes PERMANENT ledger
# items. Reading a different block than the verdict came from files follow-ups
# for findings that were withdrawn, and the standing gate then stays red on them.
cat > "$W/multi-minors.md" <<'EOF'
Round 1 raised:

FINDINGS:
minor|withdrawn: the fixture was wrong, not the code|q-system/x.sh:1
minor|withdrawn: duplicate of the line above|q-system/x.sh:2
END FINDINGS

Neither reproduced. One new nit did.

## VERDICT: APPROVE WITH NITS

FINDINGS:
minor|help text omits --engine|q-system/x.sh:9
END FINDINGS
EOF
N="$(extract_minor_findings "$W/multi-minors.md" | grep -c .)"
[ "$N" = "1" ] \
  || fail "THE LEDGER HALF OF THE DEFECT: $N minors were captured from a review with ONE live
      minor. The other $((N-1)) were WITHDRAWN in the same review and would each become a
      permanent spillover item holding the standing gate red. Captured:
$(extract_minor_findings "$W/multi-minors.md" | sed 's/^/        /')"
extract_minor_findings "$W/multi-minors.md" | grep -q 'help text omits' \
  || fail "the live minor was dropped while filtering the withdrawn ones"
ok "only the live block's minors are captured (withdrawn findings do not reach the ledger)"

# --- 4. an unclosed block is NOT an empty block ------------------------------
# The observed truncation shape. An unclosed range runs to EOF, contains no
# severity lines, and no severities derives APPROVE. pr-review-agent.sh defends
# this with its own REVIEW_UNUSABLE flag; the LIB handed APPROVE to anyone else
# who asked, so the safety lived in one caller instead of in the reader.
printf 'hook: Stop\n## VERDICT: APPROVE\n\nFINDINGS:\n' > "$W/truncated.md"
GOT="$(verdict_from_findings "$W/truncated.md")"
[ "$GOT" != "APPROVE" ] \
  || fail "THE DANGEROUS HALF: a stream that died one line into the findings block derived
      APPROVE. That is a green gate for a review nobody read -- the worst outcome available
      here, because unstated HOLDS a PR and green RELEASES it."
[ -z "$GOT" ] \
  || fail "an unclosed block derived '$GOT'. It must be EMPTY (unstated), so the caller falls
      back to prose or refuses, rather than inheriting a verdict from a truncated stream."
ok "an unclosed findings block reads as no block at all, never as an empty one"

# A block that opens, is abandoned, and is then opened again and CLOSED is the
# retry shape. The completed one is the answer.
printf 'FINDINGS:\nblocker|abandoned mid-write|a:1\nFINDINGS:\nminor|the real one|a:2\nEND FINDINGS\n' \
  > "$W/reopened.md"
[ "$(verdict_from_findings "$W/reopened.md")" = "APPROVE WITH NITS" ] \
  || fail "an abandoned block followed by a complete one derived
      '$(verdict_from_findings "$W/reopened.md")'; opening a new block must DISCARD the unclosed one"
ok "an abandoned block is discarded when a later block completes"

# --- 4b. the COMPLETENESS PREDICATE agrees with the reader --------------------
# The reviewer's REVIEW_UNUSABLE flag is what stops a truncated review from posting
# state=success on the required context. It used to ask its own question -- both
# markers, anywhere, in any order -- so this exact shape passed it: a complete
# QUOTED block from round 1, then the real trailing block cut off mid-write. The
# flag stayed off and the verdict came from findings the review had withdrawn.
if ! command -v has_complete_findings_block >/dev/null 2>&1 \
   && ! declare -F has_complete_findings_block >/dev/null 2>&1; then
  fail "the lib has no has_complete_findings_block, so pr-review-agent.sh is still asking its
      own question about what 'complete' means. Two definitions of complete in one flow is the
      drift this lib exists to stop."
fi
cat > "$W/quoted-then-truncated.md" <<'EOF'
Round 1 raised:

FINDINGS:
minor|withdrawn on re-run|q-system/x.sh:1
END FINDINGS

It did not reproduce. My own findings:

FINDINGS:
EOF
has_complete_findings_block "$W/quoted-then-truncated.md" \
  && fail "THE DRIFT: a review whose REAL findings block is TRUNCATED was called complete because
      a QUOTED prior-round block earlier in the body closed properly. The unusable flag stays off,
      so the required gate goes green on a review that was cut off, with a verdict derived from a
      finding the same review withdrew."
ok "a truncated real block is not laundered by a complete quoted one"

has_complete_findings_block "$W/normal.md" \
  || fail "the predicate rejects an ORDINARY complete review, which would mark every good review
      unusable and post state=failure on every PR in the repo"
has_complete_findings_block "$W/truncated.md" \
  && fail "the predicate accepted a review truncated one line into the block"
ok "the predicate accepts a complete review and rejects a truncated one"

# --- 5. no block at all stays empty, so the caller falls back to prose --------
printf '## VERDICT: APPROVE\n\nFreeform prose, no machine-readable block.\n' > "$W/prose.md"
[ -z "$(verdict_from_findings "$W/prose.md")" ] \
  || fail "a review with NO findings block derived a verdict from nothing"
ok "no findings block yields no derived verdict (the caller falls back to prose)"

# --- 6. STRUCTURAL: exactly one reader in the lib ----------------------------
# The criterion this whole file exists to hold. Two readers of one input with
# drifting semantics is the defect class the lib was created to close; it had
# grown two of them inside itself.
# Comment lines are excluded deliberately: the comment in findings_block QUOTES the
# expression it replaced, which is the scar the reader is anchored to. Stripping
# comments first is what makes this assert on code rather than on prose about code.
CODE="$W/lib-code.sh"
grep -v '^[[:space:]]*#' "$LIB" > "$CODE"
SEDS="$(grep -c "FINDINGS:/,/" "$CODE" | tr -d ' ')"
[ "$SEDS" = "0" ] \
  || fail "the lib still contains $SEDS sed findings-range extraction(s) in CODE. Every consumer
      must go through findings_block:
$(grep -n "FINDINGS:/,/" "$CODE" | sed 's/^/        /')"
AWKS="$(grep -c '^\s*/\^FINDINGS:/' "$LIB" | tr -d ' ')"
[ "$AWKS" = "1" ] \
  || fail "expected exactly ONE findings-block extractor in the lib, found $AWKS"
ok "the lib has exactly one findings-block reader"

echo "PASS: $PASS/$PASS findings-block-reader checks"
