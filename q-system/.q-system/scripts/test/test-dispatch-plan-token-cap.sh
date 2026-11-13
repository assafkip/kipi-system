#!/usr/bin/env bash
# The dispatcher's plan token cap refuses new dispatches past the cap (ASK-4721).
#
# WHY: under the plan-billing override the API budget gate is skipped and the usage
# breaker reads a ledger with no worker rows, so on 2026-11-12 nothing but the
# 96-a-day count stood between the fleet and the founder's plan. The gate BLOCK is
# lifted out of kipi-dispatch.sh by its own anchors, so the case follows the shipped
# code; `say`, `page_once` and `page_clear` are recording stubs. The helper is the
# real run_tokens.py, against scratch ledgers and a scratch cap file only.
#   1. under the cap the tick goes on and says the reading;
#   2. over the cap the tick stops (exit 0, no dispatch) and pages plan-token-cap;
#   3. a broken cap file stops the tick under its OWN page;
#   4. key billing (KIPI_FLEET_API_KEYS unset) skips the gate entirely;
#   5. no ledger yet says UNMETERED and goes on.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DISPATCH="${KIPI_DISPATCH_UNDER_TEST:-$ROOT/kipi-dispatch.sh}"
PASS=0; FAIL=0
ok()  { PASS=$((PASS + 1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; [ -n "${2:-}" ] && printf '       %s\n' "$2"; }
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
GATE="$WORK/gate.sh"
awk '/^# --- PLAN TOKEN CAP/{on=1} on; on && /^# --- END PLAN TOKEN CAP ---/{exit}' "$DISPATCH" > "$GATE"
grep -q -- '--cap-check' "$GATE" || { echo "FATAL: plan token cap block not extracted from $DISPATCH"; exit 1; }
printf '{"weights":{"input":1,"cache_read":0.1,"cache_write":1.25,"output":5},"windows":[{"hours":24,"cap":100}]}\n' > "$WORK/cap.json"
NOW_TS="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"
row() { printf '{"ts":"%s","input_tokens":%s,"cache_read_tokens":0,"cache_write_tokens":0,"output_tokens":0}\n' "$NOW_TS" "$1"; }
run_gate() {  # $1 = ledger path, $2 = cap file, $3 = KIPI_FLEET_API_KEYS value ("" = unset)
  : > "$WORK/events"
  ( say() { echo "say $*" >> "$WORK/events"; }
    page_once() { echo "page $1" >> "$WORK/events"; echo "$1|$2" >> "$WORK/bodies"; }
    page_clear() { echo "clear $1" >> "$WORK/events"; }
    REPO="$ROOT"; KIPI_RUN_TOKENS_FILE="$1"; KIPI_RUN_TOKEN_CAP_FILE="$2"
    export KIPI_RUN_TOKENS_FILE KIPI_RUN_TOKEN_CAP_FILE
    if [ -n "$3" ]; then export KIPI_FLEET_API_KEYS="$3"; else unset KIPI_FLEET_API_KEYS; fi
    . "$GATE"
    echo "REACHED-DISPATCH" >> "$WORK/events" )
}
row 40 > "$WORK/under.jsonl"; row 100 > "$WORK/over.jsonl"

run_gate "$WORK/under.jsonl" "$WORK/cap.json" 0
grep -q REACHED-DISPATCH "$WORK/events" && grep -q 'say PLAN TOKENS: run_tokens cap: under' "$WORK/events" \
  && ok "1. under the cap the tick goes on and logs the reading" || bad "1. under the cap" "$(cat "$WORK/events")"

run_gate "$WORK/over.jsonl" "$WORK/cap.json" 0
! grep -q REACHED-DISPATCH "$WORK/events" && grep -q '^page plan-token-cap$' "$WORK/events" \
  && ok "2. over the cap: no dispatch, pages plan-token-cap" || bad "2. over the cap" "$(cat "$WORK/events")"

# Readings that PRINT differently (1.5M vs 2.5M): at a 100-token cap both print 0.0M,
# and a body carrying the reading would still look identical, a check that cannot fail.
printf '{"weights":{"input":1,"cache_read":0.1,"cache_write":1.25,"output":5},"windows":[{"hours":24,"cap":1000000}]}\n' > "$WORK/cap-m.json"
row 1500000 > "$WORK/overm1.jsonl"; row 2500000 > "$WORK/overm2.jsonl"; : > "$WORK/bodies"
run_gate "$WORK/overm1.jsonl" "$WORK/cap-m.json" 0; run_gate "$WORK/overm2.jsonl" "$WORK/cap-m.json" 0
[ "$(grep -c '^plan-token-cap|' "$WORK/bodies")" = 2 ] && [ "$(grep '^plan-token-cap|' "$WORK/bodies" | sort -u | wc -l | tr -d ' ')" = 1 ] \
  && ok "2b. the over-cap page body is identical across readings (page_once can dedupe it)" || bad "2b. page body carries the reading" "$(cat "$WORK/bodies")"
run_gate "$WORK/under.jsonl" "$WORK/cap.json" 0
! grep -q '^clear plan-token-cap$' "$WORK/events" \
  && ok "2c. an under-cap tick does not clear the over-cap page" || bad "2c. under-cap tick cleared the page" "$(cat "$WORK/events")"

echo 'not json' > "$WORK/broken.json"
run_gate "$WORK/under.jsonl" "$WORK/broken.json" 0
! grep -q REACHED-DISPATCH "$WORK/events" && grep -q '^page plan-token-cap-broken$' "$WORK/events" \
  && ok "3. a broken cap file stops the tick under its own page" || bad "3. broken cap" "$(cat "$WORK/events")"

run_gate "$WORK/over.jsonl" "$WORK/cap.json" ""
grep -q REACHED-DISPATCH "$WORK/events" && ! grep -q 'PLAN TOKENS' "$WORK/events" \
  && ok "4. key billing skips the plan cap" || bad "4. keyed skip" "$(cat "$WORK/events")"

run_gate "$WORK/absent.jsonl" "$WORK/cap.json" 0
grep -q REACHED-DISPATCH "$WORK/events" && grep -q 'UNMETERED' "$WORK/events" && grep -q '^page plan-token-cap-unmetered$' "$WORK/events" \
  && ok "5. no ledger: UNMETERED, tick goes on" || bad "5. no ledger" "$(cat "$WORK/events")"

echo "$PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
