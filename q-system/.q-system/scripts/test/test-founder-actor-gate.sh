#!/bin/bash
# Pairs with: founder-actor-gate.py (ASK-310).
#
# The corpus is REAL. Every BLOCK case is text the assistant actually produced on
# 2026-08-02 in the session that found this defect; every PASS case is text from
# the same session that must not be blocked. A synthetic corpus would prove the
# regexes match themselves and nothing else.
#
# The PASS half matters more than the BLOCK half. A gate that fires on ordinary
# reporting is a gate the operator switches off, and "a permanently red gate
# teaches the operator to skim RED" is root cause #3 of the RCA this implements.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUT="$(cd "$HERE/.." && pwd)/founder-actor-gate.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0
ok()   { printf '  \033[0;32mPASS\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[0;31mFAIL\033[0m %s\n     %s\n' "$1" "${2:-}"; FAIL=$((FAIL+1)); }

# Build a one-message transcript and run the gate over it.
run_gate() {
  local text="$1" n="$2"
  python3 - "$WORK/t$n.jsonl" "$text" <<'PY'
import json, sys
path, text = sys.argv[1], sys.argv[2]
with open(path, "w", encoding="utf-8") as fh:
    fh.write(json.dumps({"message": {"role": "assistant",
                                     "content": [{"type": "text", "text": text}]}}) + "\n")
PY
  printf '{"transcript_path":"%s"}' "$WORK/t$n.jsonl" | python3 "$SUT" 2>"$WORK/err$n"
  echo $?
}

expect_block() {
  local rc; rc="$(run_gate "$2" "$RANDOM")"
  [ "$rc" = "2" ] && ok "BLOCKS: $1" || bad "should BLOCK: $1" "got exit $rc"
}
expect_pass() {
  local rc; rc="$(run_gate "$2" "$RANDOM")"
  [ "$rc" = "0" ] && ok "allows: $1" || bad "should ALLOW: $1" "got exit $rc"
}

echo "== must BLOCK (real assistant output from 2026-08-02) =="

expect_block "the PR-queue tasking" \
"**Next:** Clear the PR queue. 19 issues have an open PR and the worker never merges, so nothing here moves until you do."

expect_block "the five-item founder list heading" \
"**Five things waiting on you** (in the handoff, so they survive the session):

1. **19 open PRs on kipi-system.** The worker never merges by design."

expect_block "a what's-yours heading" \
"**What's yours**

1. Clear those 20 PRs. Biggest single hour on the board.
2. Decide the 5 stuck cole-GTM items."

expect_block "a command handed over to run" \
"kipi dispatch: paused, this checkout is behind origin/main.
Do: cd \$REPO && git merge --ff-only origin/main"

expect_block "system declaring itself blocked on the founder" \
"The board is fine but it is blocked on you until the queue is cleared."

echo
echo "== must PASS (ordinary work from the same session) =="

expect_pass "a plain status report with numbers" \
"79 open, 16 in flight, 38 closed in the last 30 days. Only 2 of 16 started items have gone quiet, the oldest at 5 days (ASK-210)."

expect_pass "describing what a script does" \
"linear-dor-drafter.py applies the ready label and sets the estimate from the Time Est it already writes into every DoR."

expect_pass "a genuinely founder-only decision that names its class" \
"This one is yours: rewriting published history is an irreversible-git operation and an agent must not force-push to main."

expect_pass "a spend decision, named" \
"Running the full fan-out costs real model budget, so this is a spend decision rather than something I should start on my own."

expect_pass "the explicit acknowledgement token" \
"**What's yours:** pick which of these two names you prefer. founder-actor-ack: a naming preference is taste, and no gate or script can derive it."

expect_pass "reporting that the system did the work itself" \
"Next: nothing. The sweeper merged it and the loop resumed on its own."

expect_pass "an empty message" ""

expect_pass "a question about the code, not a task" \
"Do you want the sweeper to run hourly or on every dispatch? Either is one line."

echo
echo "  passed: $PASS   failed: $FAIL"
[ "$FAIL" -eq 0 ] || exit 1
