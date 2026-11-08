#!/usr/bin/env bash
# TEMPORARY ASK-3968 probe. A faithful copy of section H of
# test-worker-env-halt.sh, repeated <trials> times against <lib>, printing how
# many of the 8 racers won each trial. Usage: probe-h.sh <lib> <trials>
set -uo pipefail
LIB="$1"; N="$2"
OUT="$(mktemp)"
for _t in $(seq 1 "$N"); do
  WORK="$(mktemp -d)"
  CLAIM_STATE="$WORK/claim-race"; mkdir -p "$CLAIM_STATE"
  CLAIM_WINNERS="$WORK/claim-winners"; : > "$CLAIM_WINNERS"
  CLAIM_PIDS=""
  for _i in 1 2 3 4 5 6 7 8; do
    (
      . "$LIB" 2>/dev/null || exit 0
      _spins=0
      while [ ! -f "$WORK/claim-go" ] && [ "$_spins" -lt 2000000 ]; do _spins=$((_spins+1)); done
      if env_alert_claim "$CLAIM_STATE" 2>/dev/null; then printf 'win\n' >> "$CLAIM_WINNERS"; fi
    ) &
    CLAIM_PIDS="$CLAIM_PIDS $!"
  done
  : > "$WORK/claim-go"
  for _p in $CLAIM_PIDS; do wait "$_p" 2>/dev/null || true; done
  N_WIN="$(grep -c '^win$' "$CLAIM_WINNERS" 2>/dev/null)" || true
  echo "${N_WIN:-0}" >> "$OUT"
done
echo "histogram for $(basename "$LIB"), $N trials (winners -> trials):"
sort -n "$OUT" | uniq -c | awk '{printf "  winners=%s trials=%s\n", $2, $1}'
