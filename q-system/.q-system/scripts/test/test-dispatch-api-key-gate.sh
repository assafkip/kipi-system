#!/usr/bin/env bash
# The dispatcher's API-key gate pages the truth it was told (ASK-4311).
#
# WHY THIS EXISTS (PR #717 review round 2, finding 1). `fleet_api_key.py probe`
# answered green with nothing in the Keychain, so dispatch kept launching and
# every run died at exit 4 with no spend row and no event. probe now answers
# about key MATERIAL first and credit second, and it has two different red
# answers:
#
#   no key <slots>  nothing will ever run until the item is created
#   paused          both credits read as exhausted; tomorrow re-probes itself
#
# Those need different pages because they need different responses. One line
# claiming "both credits read as exhausted" for a fleet that simply has no key
# sends whoever reads it to look at billing.
#
# THE CASE THAT CAME FROM READING page_once RATHER THAN FROM THE REVIEW. It
# dedupes on a per-key marker file (`paged-<key>`), and the two keys are
# independent, so a gate that paged one condition and left the other's marker
# behind would go SILENT on the second condition for as long as that marker
# survived. Each branch therefore clears the other's marker, and case 5 flips
# the fleet from missing-key to paused to prove the pause still pages.
#
# WHAT IS PINNED, through the REAL helper and no stub of probe:
#   1. with a key and live credit the gate passes and pages nothing;
#   2. with no key it stops the tick, pages api-keys-missing, names the
#      Keychain rather than the credit, and leaves a no_key event;
#   3. with a key but both credits exhausted it pages api-keys-paused instead;
#   4. the two red answers never wear each other's page;
#   5. a flip from one condition to the other still pages (the marker clear);
#   6. a red gate does not consume the paused fleet's one daily re-probe;
#   7. a missing helper FILE (a checkout before the door) lets the tick go on;
#   8. a present but CRASHING helper stops the tick under its own page;
#   9. a spent day pages the budget; 10. an unconfirmed key and 11. no known
#      credit are red; 12. an unknown key 2 alone does not stop key 1.
#
# The gate BLOCK is lifted out of kipi-dispatch.sh by its own anchors, the way
# test-dispatch-disk-floor.sh lifts the reviewer's functions, so the case follows
# the shipped code. `say` and the real `page_once` / `page_clear` bodies are
# lifted too, so the marker behaviour under test is the shipped one. Everything
# else is the real helper under KIPI_TEST=1, which reads KIPI_FLEET_FAKE_KEY_*
# instead of the macOS Keychain. No real key, no network, no `claude`.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
DISPATCH="${KIPI_DISPATCH_UNDER_TEST:-$ROOT/kipi-dispatch.sh}"
PASS=0; FAIL=0
ok()  { PASS=$((PASS + 1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; [ -n "${2:-}" ] && printf '       %s\n' "$2"; }

[ -f "$DISPATCH" ] || { echo "FATAL: kipi-dispatch.sh not found at $DISPATCH"; exit 1; }
command -v python3 >/dev/null || { echo "FATAL: python3 not on PATH"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

GATE="$WORK/gate.sh"
awk '/^# --- API-CREDIT BUDGET GATE/{on=1} on && /^# --- MEMORY GATE/{exit} on' \
  "$DISPATCH" > "$GATE"
grep -q 'probe' "$GATE" || {
  echo "FATAL: the API-credit gate block was not extracted (anchors moved in $DISPATCH)"; exit 1; }

# The real paging helpers, by name, so the marker semantics are the shipped ones.
HELPERS="$WORK/helpers.sh"
# page_once writes its marker only when page_ok reports the notifier went out,
# and it reads PAGE_REPING_SECONDS. Both come from the shipped file: lifting
# page_once without them left it dying on `set -u` with the page silently
# unsent, which is how this harness found its own first bug.
printf 'PAGE_REPING_SECONDS="%s"\n' "$(sed -n 's/^PAGE_REPING_SECONDS="\${KIPI_PAGE_REPING_SECONDS:-\([0-9]*\)}"/\1/p' "$DISPATCH")" > "$HELPERS"
grep -qE '^PAGE_REPING_SECONDS="[0-9]+"$' "$HELPERS" || {
  echo "FATAL: could not read PAGE_REPING_SECONDS out of $DISPATCH"; exit 1; }
# page_ok is a one-liner, so it is lifted by its single line; the rest are
# brace-delimited blocks. A range match on a one-liner would run to EOF.
sed -n '/^page_ok() {.*}$/p' "$DISPATCH" >> "$HELPERS"
for fn in page_lock page_once page_clear; do
  sed -n "/^${fn}() {/,/^}/p" "$DISPATCH" >> "$HELPERS"
done
for fn in page_ok page_lock page_once page_clear; do
  grep -q "^${fn}() {" "$HELPERS" || {
    echo "FATAL: could not lift $fn out of $DISPATCH"; exit 1; }
done

echo "== dispatch API-key gate (under test: $DISPATCH)"

# run_gate <label> [state-file] -- runs the extracted block in a fresh page dir
# unless a state file is reused. Records every page, clear and say line.
run_gate() {
  local label="$1" state="${2:-$WORK/$1-state.json}"
  local pagedir="${GATE_PAGEDIR:-$WORK/$label-pages}"
  mkdir -p "$pagedir"
  ( set +e
    REPO="$ROOT"; BUDGET_DAY="2026-11-09"; RESET_HOUR=7
    LOG="$pagedir/dispatch.log"
    NOTIFY="$WORK/notify"
    . "$HELPERS"
    # THE REAL say, writing to the real $LOG. An override that diverted it to a
    # per-label file is how case 5b first passed against a live bug: page_once's
    # own "page suppressed" line goes through say, so a harness that redirects
    # say cannot see the suppression it is testing for.
    say() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }
    export KIPI_TEST=1
    export KIPI_FLEET_API_FACTS="${GATE_FACTS:-$WORK/facts.json}"
    export KIPI_FLEET_SPEND_LEDGER="${GATE_LEDGER:-$WORK/$label-spend.jsonl}"
    export KIPI_FLEET_EVENTS="${GATE_EVENTS:-$WORK/$label-events.jsonl}"
    export KIPI_FLEET_STATE="$state"
    export KIPI_DISPATCH_RESET_HOUR=7
    . "$GATE"
    echo through > "$WORK/$label.through" ) >"$WORK/$label.out" 2>&1
}
# The notifier records the page text and always succeeds: page_once writes its
# marker ONLY when page_ok reports the page went out, so a notifier that failed
# would leave every marker unset and every case green for the wrong reason.
cat > "$WORK/notify" <<NOTIFYEOF
#!/usr/bin/env bash
printf 'PAGE %s\n' "\$1" >> "$WORK/pages.txt"
exit 0
NOTIFYEOF
chmod +x "$WORK/notify"
paged() {  # paged <pagedir> <pattern>
  grep -q "$2" "$1/dispatch.log" 2>/dev/null
}
marker() { [ -f "$1/paged-$2" ]; }
through() { [ -f "$WORK/$1.through" ]; }
NOW12="$(python3 -c 'import datetime as d;print(int(d.datetime(2026,11,9,12).timestamp()))')"
# The per-key facts, shaped like ~/.config/kipi/fleet-api.json: both keys known
# and confirmed, so the green case is green for the right reason. Variants below
# null a credit or drop the auto-reload confirmation.
write_facts() {  # write_facts <path> <key2 credit or null> <confirm key1 yes|no>
  python3 - "$1" "$2" "$3" <<'FACTSPY'
import json, sys
EXP = "2026-11-26T15:00:00Z"
k1 = {"monthly_credit_usd": 100, "current_cycle_expires_utc": EXP}
if sys.argv[3] == "yes":
    k1["auto_reload_off_confirmed_at"] = "2026-11-10T21:00:00Z"
k2 = {"monthly_credit_usd": None if sys.argv[2] == "null" else int(sys.argv[2]),
      "current_cycle_expires_utc": None if sys.argv[2] == "null" else EXP,
      "auto_reload_off_confirmed_at": "2026-11-10T21:00:00Z"}
json.dump({"keys": {"1": k1, "2": k2}}, open(sys.argv[1], "w"))
FACTSPY
}
write_facts "$WORK/facts.json" 200 yes

# --- 1: a key and live credit -----------------------------------------------
KIPI_FLEET_FAKE_KEY_1=k1 KIPI_FLEET_FAKE_KEY_2=k2 KIPI_FLEET_NOW="$NOW12" run_gate green
if through green && ! marker "$WORK/green-pages" api-keys-missing \
   && ! marker "$WORK/green-pages" api-keys-paused; then
  ok "case 1: with a key and live credit the gate passes and pages nothing"
else
  bad "case 1: a healthy gate passes quietly" \
      "through=$(through green && echo yes || echo no) markers=$(ls "$WORK/green-pages" 2>/dev/null | tr '\n' ' ')"
fi

# --- 2: no key at all ---------------------------------------------------------
( unset KIPI_FLEET_FAKE_KEY_1 KIPI_FLEET_FAKE_KEY_2
  KIPI_FLEET_NOW="$NOW12" run_gate nokey )
if ! through nokey && marker "$WORK/nokey-pages" api-keys-missing; then
  ok "case 2: with no key the gate stops the tick and pages api-keys-missing"
else
  bad "case 2: no key stops the tick with its own page" \
      "through=$(through nokey && echo yes || echo no) markers=$(ls "$WORK/nokey-pages" 2>/dev/null | tr '\n' ' ') stderr: $(tr "\n" "|" < "$WORK/nokey.out" 2>/dev/null)"
fi
if paged "$WORK/nokey-pages" "nothing can run until that is fixed" \
   && ! paged "$WORK/nokey-pages" "credits read as exhausted"; then
  ok "case 2b: the log names the Keychain, and does not blame the credit"
else
  bad "case 2b: the missing-key line names the Keychain" \
      "$(cat "$WORK/nokey-pages/dispatch.log" 2>/dev/null)"
fi
if grep -q "no_key" "$WORK/nokey-events.jsonl" 2>/dev/null; then
  ok "case 2c: the gate leaves a no_key event, so the daily report cannot read quiet"
else
  bad "case 2c: a no_key event lands in the events ledger" \
      "$(cat "$WORK/nokey-events.jsonl" 2>/dev/null)"
fi
# The gate ticks every 15 minutes. One event a budget day, not 96.
( unset KIPI_FLEET_FAKE_KEY_1 KIPI_FLEET_FAKE_KEY_2
  GATE_PAGEDIR="$WORK/nokey-pages" GATE_EVENTS="$WORK/nokey-events.jsonl" \
    KIPI_FLEET_NOW="$NOW12" run_gate nokey2 )
NK="$(grep -c "no_key" "$WORK/nokey-events.jsonl" 2>/dev/null)"; NK="${NK:-0}"
[ "$NK" = "1" ] \
  && ok "case 2d: a second tick in the same budget day adds no second event" \
  || bad "case 2d: one no_key event a budget day" "rows=$NK"

# --- 3: a key, but both credits paused ---------------------------------------
PAUSED="$WORK/paused-state.json"
write_paused() {
  python3 - "$PAUSED" <<'PY'
import json, sys
json.dump({"active_slot": 1, "exhausted": {"1": "2026-11-26T15:00:00Z", "2": "2026-11-26T15:00:00Z"},
           "paused": True, "paused_since": "2026-11-09T08:00:00",
           "last_probe_day": "2026-11-09"}, open(sys.argv[1], "w"))
PY
}
write_paused
KIPI_FLEET_FAKE_KEY_1=k1 KIPI_FLEET_FAKE_KEY_2=k2 KIPI_FLEET_NOW="$NOW12" \
  run_gate paused "$PAUSED"
if ! through paused && marker "$WORK/paused-pages" api-keys-paused; then
  ok "case 3: with a key but both credits exhausted the gate pages api-keys-paused"
else
  bad "case 3: a paused fleet pages the pause" \
      "through=$(through paused && echo yes || echo no) markers=$(ls "$WORK/paused-pages" 2>/dev/null | tr '\n' ' ')"
fi
! marker "$WORK/paused-pages" api-keys-missing \
  && ok "case 4: a pause is never reported as a missing key" \
  || bad "case 4: the two red answers stay distinct"

# --- 5: the flip, which is what reading page_once turned up -------------------
# One page dir across both ticks, the way a real machine has one. The
# missing-key tick pages first; the paused tick must still page, which it can
# only do if the first branch's marker was cleared.
FLIP="$WORK/flip-pages"; mkdir -p "$FLIP"
( unset KIPI_FLEET_FAKE_KEY_1 KIPI_FLEET_FAKE_KEY_2
  GATE_PAGEDIR="$FLIP" KIPI_FLEET_NOW="$NOW12" run_gate flip1 )
write_paused
GATE_PAGEDIR="$FLIP" KIPI_FLEET_FAKE_KEY_1=k1 KIPI_FLEET_FAKE_KEY_2=k2 \
  KIPI_FLEET_NOW="$NOW12" run_gate flip2 "$PAUSED"
if marker "$FLIP" api-keys-paused && ! marker "$FLIP" api-keys-missing; then
  ok "case 5: a flip from missing-key to paused still pages, and drops the stale marker"
else
  bad "case 5: the flip pages the new condition" \
      "markers=$(ls "$FLIP" 2>/dev/null | tr '\n' ' ')"
fi

# --- 5b: the RECURRENCE, which is the half case 5 cannot see -----------------
# Case 5 passes even with one cross-clear removed, because the branch it lands
# on still clears the other marker. The damage only shows on a RETURN to the
# first condition: paused, then missing, then paused again. PAGE_REPING_SECONDS
# is 86400, so a marker left behind by tick 1 suppresses tick 3 for a full day
# and a real pause goes unpaged. Measured: without the clear in the missing
# branch, tick 3 logs "page suppressed (api-keys-paused ...)".
SEQ="$WORK/seq-pages"; mkdir -p "$SEQ"
write_paused
GATE_PAGEDIR="$SEQ" KIPI_FLEET_FAKE_KEY_1=k1 KIPI_FLEET_FAKE_KEY_2=k2 \
  KIPI_FLEET_NOW="$NOW12" run_gate seq1 "$PAUSED"
( unset KIPI_FLEET_FAKE_KEY_1 KIPI_FLEET_FAKE_KEY_2
  GATE_PAGEDIR="$SEQ" KIPI_FLEET_NOW="$NOW12" run_gate seq2 )
write_paused
GATE_PAGEDIR="$SEQ" KIPI_FLEET_FAKE_KEY_1=k1 KIPI_FLEET_FAKE_KEY_2=k2 \
  KIPI_FLEET_NOW="$NOW12" run_gate seq3 "$PAUSED"
if paged "$SEQ" "page suppressed (api-keys-paused"; then
  bad "case 5b: a pause recurring after a missing-key spell still pages" \
      "tick 2 left the paused marker behind, so tick 3 was suppressed for 24h"
else
  ok "case 5b: a pause recurring after a missing-key spell still pages (no stale marker)"
fi

# --- 6: the gate is still a reader -------------------------------------------
# last_probe_day is already today in the fixture. A gate that consumed the
# re-probe would rewrite the state; a 15-minute tick must not.
write_paused
BEFORE="$(cat "$PAUSED")"
KIPI_FLEET_FAKE_KEY_1=k1 KIPI_FLEET_FAKE_KEY_2=k2 KIPI_FLEET_NOW="$NOW12" \
  run_gate reader "$PAUSED"
[ "$BEFORE" = "$(cat "$PAUSED")" ] \
  && ok "case 6: a red gate leaves the key state untouched (it burns no re-probe)" \
  || bad "case 6: the gate stays a reader" "state now: $(cat "$PAUSED")"

# --- 7: a MISSING helper file is a pre-door checkout, not a crash ------------
# A checkout that predates ASK-4311 has no helper and a worker that still bills
# the plan, so there is nothing to gate and the tick goes on.
MISSING="$WORK/missing-gate.sh"
sed 's#^KEY_HELPER=.*#KEY_HELPER="/nonexistent/fleet_api_key.py"#' "$GATE" > "$MISSING"
mkdir -p "$WORK/open-pages"
( set +e
  REPO="$ROOT"; BUDGET_DAY="2026-11-09"; RESET_HOUR=7
  LOG="$WORK/open-pages/dispatch.log"; NOTIFY="$WORK/notify"
  . "$HELPERS"
  say() { :; }
  export KIPI_TEST=1
  export KIPI_FLEET_API_FACTS="$WORK/facts.json"
  export KIPI_FLEET_SPEND_LEDGER="$WORK/open-spend.jsonl"
  export KIPI_FLEET_EVENTS="$WORK/open-events.jsonl"
  export KIPI_FLEET_STATE="$WORK/open-state.json"
  export KIPI_FLEET_NOW="$NOW12"
  . "$MISSING"
  echo through > "$WORK/open.through" ) >/dev/null 2>&1
through open \
  && ok "case 7: a missing helper file (a pre-door checkout) lets the tick go on" \
  || bad "case 7: the gate passes a checkout with no helper"

# --- 8: a PRESENT but BROKEN helper (PR #717 review round 3, major) ----------
# probe crashing used to fall into the paused branch: the tick stopped AND the
# page said "both credits read as exhausted ... Do: nothing" for a Python crash.
# Every run goes through the same helper, so the tick still stops, but under
# its own page that names the crash.
BROKEN_DIR="$WORK/broken"; mkdir -p "$BROKEN_DIR"
printf 'import sys\nsys.stderr.write("Traceback: ImportError: fleet_api_spend mid-rsync\\n")\nsys.exit(1)\n' \
  > "$BROKEN_DIR/fleet_api_key.py"
BROKEN="$WORK/broken-gate.sh"
sed "s#^KEY_HELPER=.*#KEY_HELPER=\"$BROKEN_DIR/fleet_api_key.py\"#" "$GATE" > "$BROKEN"
GATE_SAVED="$GATE"; GATE="$BROKEN"
KIPI_FLEET_FAKE_KEY_1=k1 KIPI_FLEET_FAKE_KEY_2=k2 KIPI_FLEET_NOW="$NOW12" run_gate broken
GATE="$GATE_SAVED"
if ! through broken && marker "$WORK/broken-pages" api-helper-broken; then
  ok "case 8: a crashed helper stops the tick under its own page"
else
  bad "case 8: a crashed helper pages api-helper-broken" \
      "through=$(through broken && echo yes || echo no) markers=$(ls "$WORK/broken-pages" 2>/dev/null | tr '\n' ' ')"
fi
if ! marker "$WORK/broken-pages" api-keys-paused \
   && ! paged "$WORK/broken-pages" "credit read as exhausted" \
   && paged "$WORK/broken-pages" "ImportError"; then
  ok "case 8b: the crash is never reported as a pause, and its stderr is named"
else
  bad "case 8b: a crash wears the crash page, not the pause page" \
      "$(cat "$WORK/broken-pages/dispatch.log" 2>/dev/null)"
fi

# --- 9: the day's allowance spent --------------------------------------------
printf '{"day": "2026-11-09", "slot": 1, "cost_usd": 50.0}\n' > "$WORK/spent-spend.jsonl"
GATE_LEDGER="$WORK/spent-spend.jsonl" KIPI_FLEET_FAKE_KEY_1=k1 KIPI_FLEET_FAKE_KEY_2=k2 \
  KIPI_FLEET_NOW="$NOW12" run_gate spent
if ! through spent && marker "$WORK/spent-pages" api-budget \
   && ! marker "$WORK/spent-pages" api-helper-broken; then
  ok "case 9: a spent day stops the tick under the budget page"
else
  bad "case 9: a spent day pages api-budget" \
      "through=$(through spent && echo yes || echo no) markers=$(ls "$WORK/spent-pages" 2>/dev/null | tr '\n' ' ')"
fi

# --- 10: auto-reload not confirmed off (orchestrator, 2026-11-10) ------------
write_facts "$WORK/unconfirmed.json" 200 no
GATE_FACTS="$WORK/unconfirmed.json" KIPI_FLEET_FAKE_KEY_1=k1 KIPI_FLEET_FAKE_KEY_2=k2 \
  KIPI_FLEET_NOW="$NOW12" run_gate unconfirmed
if ! through unconfirmed && marker "$WORK/unconfirmed-pages" api-keys-missing \
   && paged "$WORK/unconfirmed-pages" "auto-reload off not confirmed"; then
  ok "case 10: a key with auto-reload unconfirmed stops the tick and says why"
else
  bad "case 10: an unconfirmed key is red at the gate" \
      "$(cat "$WORK/unconfirmed-pages/dispatch.log" 2>/dev/null)"
fi

# --- 11: no key with a known credit ------------------------------------------
printf '{"keys": {}}' > "$WORK/nofacts.json"
GATE_FACTS="$WORK/nofacts.json" KIPI_FLEET_FAKE_KEY_1=k1 KIPI_FLEET_FAKE_KEY_2=k2 \
  KIPI_FLEET_NOW="$NOW12" run_gate nofacts
if ! through nofacts && marker "$WORK/nofacts-pages" api-keys-missing \
   && paged "$WORK/nofacts-pages" "known credit"; then
  ok "case 11: no known credit stops the tick and says so"
else
  bad "case 11: no known credit is red at the gate" \
      "$(cat "$WORK/nofacts-pages/dispatch.log" 2>/dev/null)"
fi

# --- 11b: the page names the fields the code reads (PR #717 round 4, minor 1)
# The missing-key page told the reader to set cycle_anchor_day, a field nothing
# reads since the cycle end moved to current_cycle_expires_utc. Followed
# verbatim, it left probe red and the fleet stopped.
if grep -q "current_cycle_expires_utc" "$WORK/pages.txt" 2>/dev/null \
   && grep -q "auto_reload_off_confirmed_at" "$WORK/pages.txt" 2>/dev/null \
   && ! grep -q "cycle_anchor_day" "$GATE"; then
  ok "case 11b: the missing-key page names the fields the helper reads"
else
  bad "case 11b: the missing-key page names a field no code reads" \
      "$(grep -o 'Do: what the line names[^"]*' "$GATE" | head -1)"
fi

# --- 12: an unknown key 2 does not stop a fleet that has key 1 ---------------
write_facts "$WORK/k2null.json" null yes
( unset KIPI_FLEET_FAKE_KEY_2
  GATE_FACTS="$WORK/k2null.json" KIPI_FLEET_FAKE_KEY_1=k1 KIPI_FLEET_NOW="$NOW12" run_gate k2null )
through k2null \
  && ok "case 12: key 2 with an unknown credit is skipped, key 1 carries the fleet" \
  || bad "case 12: an unknown key 2 stopped the tick" "$(cat "$WORK/k2null-pages/dispatch.log" 2>/dev/null)"

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" = "0" ]
