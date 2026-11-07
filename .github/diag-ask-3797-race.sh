#!/usr/bin/env bash
# Case 11 of test-dispatch-stale-checkout.sh in a tight loop, with xtrace kept
# for every iteration that pages twice.
# usage: race.sh <dispatch.sh> <iterations>
set -uo pipefail
DISPATCH="$1"; N="${2:-200}"
W="$(mktemp -d)"
PH="$W/prim.sh"
{
  echo 'set -uo pipefail'
  echo 'say() { printf "SAY %s\n" "$*" >&2; }'
  echo 'page_ok() { printf "PAGE %s\n" "$1"; return 0; }'
  echo 'PAGE_REPING_SECONDS=86400'
  awk '/^page_lock\(\) \{/,/^\}/'  "$DISPATCH"
  awk '/^page_clear\(\) \{/,/^\}/' "$DISPATCH"
  awk '/^page_once\(\) \{/,/^\}/'  "$DISPATCH"
  echo 'page_once "$@"'
} > "$PH"
dup=0
for i in $(seq 1 "$N"); do
  PC="$W/pc-$i"; mkdir -p "$PC"
  ( LOG="$PC/dispatch.log" bash -x "$PH" kconc "same line" 2>"$PC/t1" > "$PC/c1.out" ) &
  ( LOG="$PC/dispatch.log" bash -x "$PH" kconc "same line" 2>"$PC/t2" > "$PC/c2.out" ) &
  wait
  T=$(( $(grep -c '^PAGE ' "$PC/c1.out" || true) + $(grep -c '^PAGE ' "$PC/c2.out" || true) ))
  if [ "$T" -gt 1 ]; then
    dup=$((dup+1))
    if [ "$dup" -le 2 ]; then
      echo "=== iteration $i paged $T times"
      echo "--- trace 1"; grep -vE '^\+ (say|printf "SAY)' "$PC/t1" | tail -40
      echo "--- trace 2"; grep -vE '^\+ (say|printf "SAY)' "$PC/t2" | tail -40
    fi
  fi
done
echo "iterations=$N duplicates=$dup"
