#!/usr/bin/env bash
# TEMPORARY (ASK-3797 diagnosis). Loops test-dispatch-stale-checkout.sh and keeps
# every failing run. bad() is rewritten on a scratch copy so a failing case also
# prints the last harness output (stale_check's SAY lines and its verdict).
set -uo pipefail
RUNS="${1:-15}"
T=q-system/.q-system/scripts/test/test-dispatch-stale-checkout.sh
python3 - "$T" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
old = 'bad() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }'
new = ('bad() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; '
       'echo "    LAST-OUT: $(printf "%s" "${OUT:-}|${G:-}|${V:-}" | tr "\\n" " " | cut -c1-1500)"; }')
assert s.count(old) == 1, "bad() anchor not found exactly once"
open(p, "w").write(s.replace(old, new))
PY
grep -n '^bad()' "$T"
mkdir -p out; fails=0
for i in $(seq 1 "$RUNS"); do
  s=$(date +%s)
  bash "$T" > "out/run-$i.txt" 2>&1 < /dev/null; rc=$?
  echo "run $i rc=$rc $(( $(date +%s) - s ))s $(grep -- '-------- ' "out/run-$i.txt" | tail -1)"
  if [ "$rc" != 0 ]; then fails=$((fails+1)); grep -n -A1 'FAIL:' "out/run-$i.txt"; fi
done
echo "fails=$fails"
nproc; uptime; git --version
