#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
for t in test-dispatch-rework test-dispatch-liveness test-linear-worker-fetch test-converge test-linear-worker-parallel; do
  printf '=== %s\n' "$t"
  bash "q-system/.q-system/scripts/test/$t.sh" 2>&1 | tail -4
done
