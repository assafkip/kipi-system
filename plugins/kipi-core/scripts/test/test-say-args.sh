#!/usr/bin/env bash
# test-say-args.sh - Prove say-last-response.py rejects unknown args WITHOUT
# synthesizing. Regression test for the bug where `--help` (or any typo) fell
# through to a real paid OpenAI call. (2026-06-21)
#
# No network, no API key, no audio device needed: the arg guard runs before
# any transcript read or synthesis, so these cases exit at the guard.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAY="$SCRIPT_DIR/../say-last-response.py"
PASS=0
FAIL=0

ok()   { echo "  PASS: $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }

# Run the script in an EMPTY project dir so there is no transcript. If the guard
# is missing, the code would reach load_text() / synthesize() instead of exiting
# at the guard, and the "synthesizing" marker or a different message would show.
EMPTY_DIR="$(mktemp -d)"
trap 'rm -rf "$EMPTY_DIR"' EXIT
run() { CLAUDE_PROJECT_DIR="$EMPTY_DIR" OPENAI_API_KEY="" python3 "$SAY" "$@" 2>&1; }

echo "test-say-args: unknown args never synthesize"

# 1. --help prints usage, exit 0, no synthesis.
out="$(run --help)"; code=$?
[ "$code" -eq 0 ]                  && ok "--help exits 0"            || bad "--help exit ($code)"
echo "$out" | grep -q "usage:"     && ok "--help prints usage"      || bad "--help no usage"
echo "$out" | grep -q "synthesizing chunk"  && bad "--help synthesized (!!)" || ok "--help did not synthesize"

# 2. A bogus flag is rejected, exit non-zero, no synthesis.
if out="$(run --bogus)"; then code=0; else code=$?; fi
[ "$code" -ne 0 ]                       && ok "--bogus exits non-zero"   || bad "--bogus exit 0"
echo "$out" | grep -q "unrecognized"    && ok "--bogus reports unknown"  || bad "--bogus no message"
echo "$out" | grep -q "synthesizing chunk"       && bad "--bogus synthesized (!!)"|| ok "--bogus did not synthesize"

# 3. A known no-API flag still works (proves the guard didn't break valid args).
#    --dump-chunks needs a transcript; with none it should fail cleanly on the
#    transcript, NOT on the arg guard. Either way: no "unrecognized" message.
if out="$(run --dump-chunks)"; then :; fi
echo "$out" | grep -q "unrecognized" && bad "--dump-chunks wrongly rejected" || ok "--dump-chunks passes arg guard"

echo "test-say-args: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
