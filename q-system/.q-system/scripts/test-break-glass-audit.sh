#!/usr/bin/env bash
# Regression test: the break-glass hatch may never open without a trace.
#
# THE DEFECT (Codex major, PR #159): with the ledger unwritable AND the notifier
# failing, `off` disabled main's protection and exited 0 -- no row, no Slack, no
# trace. The hatch's entire justification is that the override is VISIBLE, so a
# silent success is not a rough edge, it is the guarantee being absent.
#
# THE FIX IS ORDERING, not just error handling. The audit row is written FIRST and
# its failure REFUSES the override. Writing it afterwards means you learn the
# ledger is dead when protection is already off, and by then there is nothing
# useful to do.
#
# Every case runs against a COPY with the two `gh api` calls stubbed against a
# state file, so live branch protection is never touched. The stubs are asserted
# to have applied before any result is trusted -- a sed that silently did not
# match would otherwise make every case pass for the wrong reason.
#
# Run: bash test_break_glass_audit.sh

set -uo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/break-glass-main-protection.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

COPY="$WORK/bg.sh"
STATE="$WORK/state"

sed \
  -e "s|gh api \"\$API\" -q '.enabled' 2>/dev/null|cat '$STATE'|" \
  -e "s|gh api -X DELETE \"\$API\" >/dev/null 2>&1|echo false > '$STATE'|" \
  -e "s|gh api -X POST \"\$API\" >/dev/null 2>&1|echo true > '$STATE'|" \
  "$SRC" > "$COPY"
chmod +x "$COPY"

# Negative self-test on the harness itself.
for needle in "cat '$STATE'" "echo false > '$STATE'" "echo true > '$STATE'"; do
  grep -qF "$needle" "$COPY" || { echo "HARNESS BROKEN: stub not applied: $needle" >&2; exit 2; }
done

OK_NOTIFY="$WORK/notify-ok.sh";   printf '#!/bin/bash\nexit 0\n' > "$OK_NOTIFY";   chmod +x "$OK_NOTIFY"
BAD_NOTIFY="$WORK/notify-bad.sh"; printf '#!/bin/bash\nexit 1\n' > "$BAD_NOTIFY"; chmod +x "$BAD_NOTIFY"
# A path whose parent is a FILE: mkdir -p and append both fail.
BLOCKER="$WORK/blocker"; : > "$BLOCKER"
DEAD_LEDGER="$BLOCKER/sub/ledger.jsonl"
# A SECOND kind of dead ledger, and the distinction is not cosmetic. Above, the
# parent is a file so `mkdir -p` fails and the append is never reached. Here the
# path IS a directory, so mkdir succeeds and the APPEND is what fails. Mutation
# proved the first fixture alone could not tell those apart: restoring `|| true`
# on the append line survived, because no case ever got that far.
APPEND_ONLY_DEAD="$WORK/ledger-is-a-directory"; mkdir -p "$APPEND_ONLY_DEAD"

FAILURES=0
CHECKS=0

fail() { FAILURES=$((FAILURES + 1)); echo "  FAIL: $1"; }
ck()   { CHECKS=$((CHECKS + 1)); }

run_off() {
  # run_off <state> <ledger> <notify> <reason>
  echo "$1" > "$STATE"
  BREAK_GLASS_LEDGER="$2" KIPI_NOTIFY="$3" bash "$COPY" off "$4" >"$WORK/out" 2>"$WORK/err"
  echo $?
}
run_on() {
  echo "$1" > "$STATE"
  BREAK_GLASS_LEDGER="$2" KIPI_NOTIFY="$3" bash "$COPY" on >"$WORK/out" 2>"$WORK/err"
  echo $?
}

echo "1. ledger dead + notifier dead -> REFUSE, protection untouched"
ck; RC="$(run_off true "$DEAD_LEDGER" "$BAD_NOTIFY" "both audit paths down")"
[ "$RC" = "2" ] || fail "expected rc=2, got $RC"
ck; [ "$(cat "$STATE")" = "true" ] || fail "protection was disabled anyway (state=$(cat "$STATE"))"
ck; grep -q "REFUSING to open the hatch" "$WORK/err" || fail "no refusal message on stderr"

echo "1b. ledger APPEND fails (mkdir succeeds) -> REFUSE, protection untouched"
# Distinct from case 1 on purpose. There the parent is a file so `mkdir -p` fails
# and the append is never reached; here mkdir succeeds and the APPEND is what
# fails. Mutation proved case 1 alone could not tell them apart -- restoring
# `|| true` on the append line survived because no case ever got that far.
ck; RC="$(run_off true "$APPEND_ONLY_DEAD" "$BAD_NOTIFY" "append path is a directory")"
[ "$RC" = "2" ] || fail "expected rc=2, got $RC"
ck; [ "$(cat "$STATE")" = "true" ] || fail "protection disabled despite an unwritable ledger"

echo "2. ledger dead but notifier fine -> still REFUSE (the ledger is the precondition)"
ck; RC="$(run_off true "$DEAD_LEDGER" "$OK_NOTIFY" "ledger down only")"
[ "$RC" = "2" ] || fail "expected rc=2, got $RC"
ck; [ "$(cat "$STATE")" = "true" ] || fail "protection disabled without a ledger row"

echo "3. ledger fine but notifier dead -> hatch OPENS, exit 3, loud"
LEDGER3="$WORK/l3.jsonl"
ck; RC="$(run_off true "$LEDGER3" "$BAD_NOTIFY" "slack down")"
[ "$RC" = "3" ] || fail "expected rc=3 (opened, alert failed), got $RC"
ck; [ "$(cat "$STATE")" = "false" ] || fail "hatch did not open when only Slack was down"
ck; grep -q "Slack alert did NOT send" "$WORK/err" || fail "no loud warning about the alert"
ck; [ -s "$LEDGER3" ] || fail "ledger row missing on the happy-ledger path"

echo "4. both audit paths fine -> exit 0, intent + outcome rows"
LEDGER4="$WORK/l4.jsonl"
ck; RC="$(run_off true "$LEDGER4" "$OK_NOTIFY" "normal emergency")"
[ "$RC" = "0" ] || fail "expected rc=0, got $RC"
ck; [ "$(wc -l < "$LEDGER4" | tr -d ' ')" = "2" ] || fail "expected 2 rows (intent+outcome), got $(wc -l < "$LEDGER4" | tr -d ' ')"
ck; grep -q "off-intent" "$LEDGER4" || fail "no intent row -- the ordering guarantee is gone"

echo "5. closing is NEVER blocked by bookkeeping (asymmetry is deliberate)"
ck; RC="$(run_on false "$DEAD_LEDGER" "$BAD_NOTIFY")"
[ "$RC" = "3" ] || fail "expected rc=3 (closed, audit incomplete), got $RC"
ck; [ "$(cat "$STATE")" = "true" ] || fail "REFUSED TO CLOSE -- that leaves protection off, strictly worse"

echo "6. the reason survives into the ledger, quotes and newlines included"
LEDGER6="$WORK/l6.jsonl"
ck; RC="$(run_off true "$LEDGER6" "$OK_NOTIFY" 'he said "ship it"
and then a newline')"
[ "$RC" = "0" ] || fail "expected rc=0, got $RC"
ck; grep -q 'he said \\"ship it\\"' "$LEDGER6" || fail "quotes not escaped into the reason"
ck; python3 -c "
import json,sys
rows=[json.loads(l) for l in open('$LEDGER6') if l.strip()]
assert rows, 'no rows'
assert any('ship it' in (r.get('reason') or '') for r in rows), 'reason lost'
" 2>/dev/null || fail "ledger is not valid JSON, or the reason was dropped"

echo "7. no reason -> refuse, protection untouched"
LEDGER7="$WORK/l7.jsonl"
ck; RC="$(run_off true "$LEDGER7" "$OK_NOTIFY" "")"
[ "$RC" = "2" ] || fail "expected rc=2 for a missing reason, got $RC"
ck; [ "$(cat "$STATE")" = "true" ] || fail "opened the hatch with no reason"
ck; [ ! -s "$LEDGER7" ] || fail "wrote a row for a refused-before-anything call"

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "ok  $CHECKS/$CHECKS break-glass audit checks passed"
  exit 0
fi
echo "FAIL $FAILURES/$CHECKS"
exit 1
