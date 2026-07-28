#!/usr/bin/env bash
# Ask the REAL kipi-dispatch.sh what one issue's file set is.
# The functions are taken by LINE RANGE out of the real file (everything above
# the liveness beacon, which is where the top-level flow starts), never copied,
# so this cannot drift from what the dispatcher actually does.
ISSUE="$1"; OUT="$2"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set --                      # the sourced head parses "$@" as dispatcher flags
# shellcheck disable=SC1090
source /dev/stdin <<< "$(sed -n '1,/^# --- LIVENESS BEACON/p' "$ROOT/kipi-dispatch.sh")"
fileset_known "$ISSUE" "$OUT"
