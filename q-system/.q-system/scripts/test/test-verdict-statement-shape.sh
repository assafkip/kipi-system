#!/usr/bin/env bash
# Pairs with extract_verdict() in pr-verdict-lib.sh (ASK-356).
#
# THE DEFECT. `codex exec` echoes the entire prompt to stdout, and the reviewer
# prompt carries its own grading rule:
#
#     - **VERDICT:** decided by THIS RULE, not by feel:
#         - any blocker or major finding      => REQUEST CHANGES
#
# extract_verdict anchored on the FIRST line matching `VERDICT` and took the
# first verdict token within 3 lines. In every codex review that first match is
# the echoed rule, so it returned REQUEST CHANGES no matter what the reviewer
# concluded. Measured 2026-08-03: 47 of 54 records carry stated=REQUEST CHANGES.
#
# Latent until ASK-312 made resolve_verdict take the HARSHER of stated/derived.
# After that, every codex-reviewed PR is held at REQUEST CHANGES regardless of
# the review, and kipi/reviewer-approved is REQUIRED on main -- so the whole
# merge pipeline stopped. PR #91 went three rounds and could not go green while
# its round-3 review said, in its own words, "VERDICT: APPROVE".
#
# WHY THIS IS A SHAPE RULE AND NOT A POSITION RULE. The obvious fix is "take the
# LAST match, not the first", copying findings_block. It was rejected on review:
# anchoring on position is what produced this bug, and a second position rule is
# a third thing to get wrong. The echo is not distinguished by WHERE it sits, it
# is distinguished by NOT BEING A VERDICT STATEMENT. A statement puts the token
# directly after the marker; the grading rule puts prose there.
#
# The review stream also contains THE DIFF OF THE PR, so a reviewer reading a
# change to this very loop sees `REQUEST CHANGES` in source strings and comments.
# Any rule that scans loose prose parses source code as a verdict.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
LIB_REL="q-system/.q-system/scripts/pr-verdict-lib.sh"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

# REF HATCH: point at a pre-fix commit and watch these cases fail against the
# code they were written for. A case added after its fix has never been proven.
LIB="$WORK/pr-verdict-lib.sh"
if [ -n "${REPRO_REF:-}" ]; then
  git -C "$REPO_ROOT" show "$REPRO_REF:$LIB_REL" > "$LIB" 2>/dev/null \
    || { echo "FATAL: $LIB_REL not at $REPRO_REF" >&2; exit 1; }
  echo "== verdict statement shape (LIB FROM REF $REPRO_REF) =="
else
  cp "$REPO_ROOT/$LIB_REL" "$LIB"
  echo "== verdict statement shape =="
fi
# shellcheck disable=SC1090
. "$LIB"

check() {   # check <label> <file> <want>
  local got; got="$(extract_verdict "$2")"
  if [ "$got" = "$3" ]; then ok "$1"; else bad "$1 -- got '${got:-<empty>}', want '${3:-<empty>}'"; fi
}

# --- the echoed prompt, verbatim from the real PR #91 round 3 payload --------
# Paths and any loaded-skill text are NOT reproduced: the captured stream carries
# the founder's home directory and skill bodies, and this repo is public
# (ASK-345). The grading rule itself is the load-bearing part and is exact.
PROMPT_ECHO='OpenAI Codex v0.146.0
--------
workdir: /tmp/review-trees/pr-91
--------
user
You are a SENIOR STAFF ENGINEER. Review pull request #91.

- **VERDICT:** decided by THIS RULE, not by feel:
    - any blocker or major finding      => REQUEST CHANGES (BLOCK only if merging
      would lose data)
    - only minor/nit findings           => APPROVE WITH NITS
    - no finding survived reproduction  => APPROVE
  A bar this high ALWAYS finds something; that is what APPROVE WITH NITS is for.
  Using REQUEST CHANGES to log minors wedges a PR that should have shipped.
'

# The stream also replays the DIFF, so the PR'"'"'s own source strings are in it.
DIFF_NOISE='
@@ -0,0 +1,4 @@
+REWORK_VERDICTS = {"REQUEST CHANGES", "BLOCK"}
+#   PR #82 -- a real review, one real major, REQUEST CHANGES.
+# The verdict does not separate them -- PR #80 recorded REQUEST CHANGES from the
+#              record ALSO says REQUEST CHANGES.               -> RE-REVIEW
'

# --- case 1: THE BUG. A review whose own answer is APPROVE ------------------
printf '%s%s\ncodex\n\nVERDICT: APPROVE\n\nMost important thing to fix first: nothing in the reviewed code.\n\nFINDINGS:\nEND FINDINGS\n' \
  "$PROMPT_ECHO" "$DIFF_NOISE" > "$WORK/pr91.md"
check "the reviewer said APPROVE, so the record says APPROVE" "$WORK/pr91.md" "APPROVE"

# --- case 2: no answer at all is UNSTATED, never the prompt's rule ----------
# A stream that died, or a model that never answered. Unstated posts state=failure
# and HOLDS the PR, which is the safe direction. What it must never do is read a
# verdict out of the prompt and pretend a reviewer said it.
printf '%s%s\n' "$PROMPT_ECHO" "$DIFF_NOISE" > "$WORK/echo-only.md"
check "prompt echo + diff, no answer -> unstated" "$WORK/echo-only.md" ""

# --- case 3: the diff alone must not be parsed as a verdict ----------------
printf '%s\n' "$DIFF_NOISE" > "$WORK/diff-only.md"
check "source strings in the diff are not a verdict" "$WORK/diff-only.md" ""

# --- cases 4-8: every shape that already worked MUST keep working -----------
# Taken from test-severity-floor.sh, which holds them against real captured
# payloads from PR #11 rounds 1, 2 and 4. Regression guard: a shape rule that
# fixes the echo by rejecting real verdict lines has traded one silence for
# another.
printf '## VERDICT: REQUEST CHANGES\n\nFix first: **BLOCKER 1**. Add state to the update path.\n' > "$WORK/r2.md"
check "r2: '## VERDICT: TOKEN' with BLOCKER prose after" "$WORK/r2.md" "REQUEST CHANGES"

printf '## VERDICT: **REQUEST CHANGES**\n\n**Fix first: finding #1.**\n' > "$WORK/r1.md"
check "r1: bold token on the verdict line" "$WORK/r1.md" "REQUEST CHANGES"

printf 'Attacks that would BLOCK a lesser change all failed against this one.\n\n## VERDICT: APPROVE WITH NITS\n' > "$WORK/nits.md"
check "nits: BLOCK prose BEFORE the verdict line does not win" "$WORK/nits.md" "APPROVE WITH NITS"

printf '## VERDICT\n\n**REQUEST CHANGES** (not BLOCK - nothing here writes an unrecoverable object).\n' > "$WORK/r4.md"
check "r4: bare heading, verdict on the next line, self-qualifying" "$WORK/r4.md" "REQUEST CHANGES"

printf '## VERDICT: APPROVE\n\nFINDINGS:\nmajor|silently drops every finding|a.py:10\nEND FINDINGS\n' > "$WORK/liar.md"
check "liar: prose APPROVE still extracted (derivation overrides it elsewhere)" "$WORK/liar.md" "APPROVE"

: > "$WORK/empty.md"
check "empty review file -> unstated" "$WORK/empty.md" ""

# --- case 9: the self-referential case, which is THIS PR --------------------
# The stream replays the diff, and the diff of this very file contains literal
# `## VERDICT: REQUEST CHANGES` fixture lines. A shape rule alone matches them:
# they ARE statement-shaped, because they are quoted statements. Shape rejects
# the prompt's grading rule; only order separates the reviewer's own answer from
# a verdict it is quoting. The reviewer answers last, which is the same reason
# findings_block takes the LAST complete block.
printf '%s\n@@ test-verdict-statement-shape.sh @@\n+printf %s > "$WORK/r2.md"\n+## VERDICT: REQUEST CHANGES\n+## VERDICT: APPROVE WITH NITS\n\ncodex\n\nVERDICT: APPROVE\n\nNothing in the reviewed code.\n' \
  "$PROMPT_ECHO" "'## VERDICT: REQUEST CHANGES'" > "$WORK/selfref.md"
check "a verdict QUOTED in the diff loses to the reviewer's own answer" "$WORK/selfref.md" "APPROVE"

# --- case 10: a bare heading followed by prose, not a token ------------------
# The heading look-ahead must not grab a verdict token out of a sentence. This is
# the same failure as the prompt rule, one line further down.
printf '## VERDICT\n\nI could not complete the review; REQUEST CHANGES would be premature.\n' > "$WORK/heading-prose.md"
check "bare heading followed by a SENTENCE is not a verdict" "$WORK/heading-prose.md" ""

echo "  $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
