#!/usr/bin/env bash
# Pairs with: ASK-445, the re-review of the 2026-08-06 degraded batch.
#
# WHAT THIS PINS. ASK-445's Definition of Ready carries a hard ordering
# constraint: "ASK-287 / PR #86 must be on main before the first Codex run, or a
# restored reviewer can approve on an empty transcript with 19 PRs pre-armed to
# merge." PR #86 is still OPEN, and landing it is on ASK-445's "Not doing" line,
# so the constraint had to be discharged by measurement rather than by merging.
#
# The claim under test is narrow and is the only thing that matters for starting
# the re-review: an out-of-credits codex transcript, fed to main's own verdict
# predicates, must NOT derive APPROVE. If it ever does, the batch re-review is
# unsafe to run and this test goes red before any codex call is spent.
#
# WHY A REPRODUCER AND NOT THE ISSUE COMMENT. ASK-445 already carries a comment
# (2026-08-07) asserting main handles this correctly. An assertion in a comment
# decays -- that is precisely how ASK-287's own body came to drive an ordering
# constraint three hours after the guard that closed it landed. This runs.
#
# THE CONTROLS ARE THE POINT. Case 1 is a "no". A probe that can only say no is
# not a result, so cases 2-4 prove this harness can say yes: it derives
# REQUEST CHANGES, BLOCK and APPROVE from blocks that deserve them. Without them
# a broken sourcing path would report a green that means nothing.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HERE/../pr-verdict-lib.sh"

if [ ! -f "$LIB" ]; then
  echo "FAIL: pr-verdict-lib.sh not found at $LIB" >&2
  exit 1
fi
# shellcheck source=/dev/null
. "$LIB"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fails=0
pass() { echo "  PASS $1"; }
fail() { echo "  FAIL $1" >&2; fails=$((fails + 1)); }

# check <label> <file> <expected-usable yes|no> <expected-derived-verdict>
check() {
  local label="$1" f="$2" want_usable="$3" want_verdict="$4"
  local got_usable got_verdict
  if review_is_usable "$f"; then got_usable=yes; else got_usable=no; fi
  got_verdict="$(verdict_from_findings "$f")"
  if [ "$got_usable" = "$want_usable" ] && [ "$got_verdict" = "$want_verdict" ]; then
    pass "$label (usable=$got_usable verdict='${got_verdict}')"
  else
    fail "$label: want usable=$want_usable verdict='${want_verdict}'; got usable=$got_usable verdict='${got_verdict}'"
  fi
}

echo "ASK-445 ordering-constraint reproducer (pr-verdict-lib.sh as it stands on this tree)"

# --- Case 1: THE CONSTRAINT. A real out-of-credits codex transcript shape.
# Verbatim error string from the billed 2026-08-06 run recorded on ASK-445.
#
# The `workdir:` value is the ONE field neutralised rather than copied. The real
# transcript carries the absolute checkout path, and this repo is the public
# skeleton -- validate-separation.py's Full skeleton sweep bans `/Users/assafkip`
# anywhere under q-system/, and it caught this line on PR #255. Neutralising it
# is safe precisely because nothing reads it: review_is_usable keys off the
# usage-limit error string and the FINDINGS block, never the header rows. Every
# field the parser DOES look at is still verbatim.
cat > "$TMP/out-of-credits.txt" <<'EOF'
Reading additional input from stdin...
OpenAI Codex v0.147.0
--------
workdir: /path/to/checkout
model: gpt-5.6-sol
provider: openai
--------
ERROR: You've hit your usage limit. Upgrade to Pro (https://openai.com/chatgpt/pricing) or try again at Aug 9th, 2026 6:53 PM.
EOF
check "out-of-credits transcript is unusable and derives NO verdict" \
  "$TMP/out-of-credits.txt" no ""

# --- Case 1b: THE SHAPE THAT ACTUALLY MATTERS.
# Case 1 above is too thin on its own and saying so is the point: `codex exec`
# writes with `> file 2>&1`, so the transcript carries the ECHOED PROMPT as well
# as the error, and the prompt ends with a literal `FINDINGS:` template. That
# echo is the only complete block in the stream -- which is exactly what ASK-287
# measured deriving APPROVE before the sp-df1a458f placeholder guard landed.
#
# The template row is not hand-typed here. It is read out of the producer,
# pr-review-agent.sh, so this fixture cannot drift away from the prompt it is
# meant to imitate (a fixture you invent tests your assumption, not the code).
PROMPT_TEMPLATE_ROW="$(grep -m1 '^severity|' "$HERE/../pr-review-agent.sh" || true)"
if [ -z "$PROMPT_TEMPLATE_ROW" ]; then
  fail "could not read the FINDINGS template row out of pr-review-agent.sh"
else
  {
    printf 'Reading additional input from stdin...\nOpenAI Codex v0.147.0\n'
    printf -- '--------\nmodel: gpt-5.6-sol\n--------\nuser\n'
    printf 'Review this PR.\n\nFINDINGS:\n%s\nEND FINDINGS\n' "$PROMPT_TEMPLATE_ROW"
    printf "ERROR: You've hit your usage limit. Upgrade to Pro or try again at Aug 9th, 2026 6:53 PM.\n"
  } > "$TMP/out-of-credits-with-echo.txt"
  check "out-of-credits WITH the echoed prompt template still derives NO verdict" \
    "$TMP/out-of-credits-with-echo.txt" no ""
fi

# --- Case 2 (control): a real review with a major finding must derive REQUEST CHANGES.
cat > "$TMP/major.txt" <<'EOF'
Reviewed the diff.

FINDINGS:
major|the dry-run guard can never evaluate false|kipi-update.sh:212
END FINDINGS

VERDICT: REQUEST CHANGES
EOF
check "control: a major row derives REQUEST CHANGES" \
  "$TMP/major.txt" yes "REQUEST CHANGES"

# --- Case 3 (control): a blocker row must derive BLOCK.
cat > "$TMP/blocker.txt" <<'EOF'
FINDINGS:
blocker|restore writes outside the target tree|kipi-rollback.sh:88
END FINDINGS

VERDICT: BLOCK
EOF
check "control: a blocker row derives BLOCK" \
  "$TMP/blocker.txt" yes "BLOCK"

# --- Case 4 (control): the harness CAN say APPROVE, so case 1's "no" is a result.
# An empty-but-closed block deriving APPROVE is the deliberate round-2-refutes-
# everything contract documented in pr-verdict-lib.sh; it is quoted here as the
# yes-control, not as behaviour this test wants changed.
cat > "$TMP/approve.txt" <<'EOF'
Round 2. Every round-1 finding was refuted against the current head.

FINDINGS:
END FINDINGS

VERDICT: APPROVE
EOF
check "control: an empty closed block derives APPROVE (harness can say yes)" \
  "$TMP/approve.txt" yes "APPROVE"

echo
if [ "$fails" -eq 0 ]; then
  echo "RESULT: ordering constraint DISCHARGED -- an out-of-credits transcript cannot approve on this tree."
  exit 0
fi
echo "RESULT: $fails failure(s). Do NOT start the ASK-445 batch re-review." >&2
exit 1
