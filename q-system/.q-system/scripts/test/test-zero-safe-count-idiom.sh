#!/usr/bin/env bash
# `grep -c ... || echo 0` is not a zero-safe count. Pins the corrected idiom
# and refuses the broken one from coming back (sp-762c7d6b).
#
# THE DEFECT. `grep -c` prints the count AND exits 1 when that count is zero.
# So `n=$(grep -c PATTERN FILE || echo 0)` appends a SECOND zero and n becomes
# the two-line string "0\n0". Measured:
#
#     file with 2 matches -> "2"      correct
#     file, zero matches  -> "0\n0"   BROKEN
#     missing file        -> "0"      correct (grep printed nothing)
#
# It only bites when the file EXISTS and is EMPTY, which is why six sites
# carried it unnoticed.
#
# WHY IT MATTERS, and it is not cosmetic. `[ "$n" -eq 1 ]` aborts with
# "integer expression expected", and `[ "$n" = "0" ]` -- a legitimate
# expect-zero assertion, e.g. test-severity-floor.sh's "no page was sent" case
# -- compares "0\n0" against "0" and FAILS on correct behaviour. A false
# failure in a test suite is worse than a missed one: it trains the reader to
# discount red.
#
# THE FIX. `{ grep -c ... || echo 0; } | head -1` keeps whichever zero arrived
# first, and the fallback still covers the missing-file case where grep prints
# nothing at all.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
TESTDIR="$ROOT/q-system/.q-system/scripts/test"
PASS=0; FAIL=0
ok()  { echo "PASS: $1"; PASS=$((PASS+1)); }
bad() { echo "FAIL: $1" >&2; FAIL=$((FAIL+1)); }

WORK="$(mktemp -d)"
trap 'python3 -c "import shutil,sys;shutil.rmtree(sys.argv[1],ignore_errors=True)" "$WORK"' EXIT
printf 'a\nb\n' > "$WORK/two.txt"
: > "$WORK/empty.txt"

count() { { grep -c . "$1" 2>/dev/null || echo 0; } | head -1; }

# --- 1. the idiom is correct on all three input states ---------------------
for case in "two.txt 2" "empty.txt 0" "missing.txt 0"; do
  set -- $case
  got="$(count "$WORK/$1")"
  [ "$got" = "$2" ] && ok "count($1) = $2" || bad "count($1) = '$got', want '$2'"
done

# --- 2. the result is ONE line, which is the whole defect ------------------
lines="$(count "$WORK/empty.txt" | wc -l | tr -d ' ')"
[ "$lines" = "1" ] && ok "zero count is a single line" \
  || bad "zero count spans $lines lines (the \"0\\n0\" defect)"

# --- 3. it survives the comparisons that the broken form breaks ------------
n="$(count "$WORK/empty.txt")"
if [ "$n" -eq 0 ] 2>/dev/null; then ok "numeric -eq works on a zero count"
else bad "numeric -eq still errors on a zero count"; fi
[ "$n" = "0" ] && ok "string = \"0\" works on a zero count" \
  || bad "expect-zero assertion still fails on correct behaviour"

# --- 4. the broken form really is broken (the check can fail) --------------
# Without this the suite above could pass against a no-op "fix".
broken="$(grep -c . "$WORK/empty.txt" 2>/dev/null || echo 0)"
[ "$(printf '%s' "$broken" | wc -l | tr -d ' ')" = "1" ] \
  && ok "control: the OLD idiom does produce a second line" \
  || bad "control failed -- grep here does not behave as the defect describes, "\
"so the rest of this file proves nothing"

# --- 5. no site regresses to the broken form ------------------------------
# The idiom is easy to retype from memory; this is what stops it returning.
residual="$(grep -rn 'grep -c [^|]* || echo 0' "$TESTDIR"/*.sh 2>/dev/null \
            | grep -v 'head -1' | grep -v 'test-zero-safe-count-idiom.sh' || true)"
if [ -z "$residual" ]; then ok "no test script carries the unguarded idiom"
else bad "unguarded \`grep -c ... || echo 0\` is back:
$residual"; fi

echo
echo "passed=$PASS failed=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
