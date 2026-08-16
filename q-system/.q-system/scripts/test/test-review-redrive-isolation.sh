#!/usr/bin/env bash
# Pairs with test-review-redrive.sh and test-review-redrive-park.sh (ASK-872).
#
# THE PROPERTY: neither redrive suite talks to anything but its own fixtures.
#
# WHY IT NEEDS ITS OWN FILE. A suite cannot assert its own isolation from the
# inside -- the assertion runs in the same environment as the leak, so a case
# that reaches the real Linear passes exactly like one that reaches the fixture.
# The only thing that tells them apart is the endpoint, and the endpoint is set
# by whoever launches the suite. So the check is a launcher.
#
# THE DEFECT THIS PINS (PR #201 review round 3, major). `select` grew a Linear
# park read, and test-review-redrive.sh stubbed it at the API seam -- for the
# `select` call sites. Two `mark-dispatched` calls were written before
# `mark-dispatched` re-read the park, and were left as bare `env KIPI_ATTEMPTS=`
# invocations. When the claim started reading the park too, those two lines
# silently began calling the REAL Linear board with the founder's real key,
# asking about ASK-298 and ASK-301. The suite stayed green because those issues
# exist and are unparked. On a machine with no key, no network, or with either
# issue parked, the claim returns rc 3, nothing is claimed, and the cases that
# depend on the claim fail for a reason that has nothing to do with the code.
#
# Green-because-the-real-board-agreed is not isolation. Same class as the
# notify-sink leak that test-review-redrive.sh's own header documents: quiet
# because nothing was configured, not because nothing was called.
#
# HOW IT FAILS. The suites are run with the DEFAULT Linear endpoint pointed at a
# closed port. Every call site that passes its own fixture env overrides it and
# is unaffected; every call site that forgot one gets ECONNREFUSED, raises
# ParkUnavailable, and takes its case down with it. So a leak is loud here and
# nowhere else, and this file fails RED the moment a new call site forgets.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ok   - $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL - $1"; }

# Port 1 is never listening and refuses instantly, so a leaked call fails fast
# rather than hanging the suite on a connect timeout. The key is a real-looking
# string on purpose: an EMPTY key would make linear-sync fall back to
# ~/.config/kipi/linear-api-key, and on the founder's own machine that file
# exists -- the fallback would quietly restore the very leak being tested for.
DEAD_URL="http://127.0.0.1:1/graphql"
DEAD_KEY="isolation-probe-not-a-real-key"

run_isolated() {   # run_isolated <suite.sh> <outfile>
  env KIPI_LINEAR_API_URL="$DEAD_URL" KIPI_LINEAR_API_KEY="$DEAD_KEY" \
    bash "$HERE/$1" > "$2" 2>&1
}

for SUITE in test-review-redrive.sh test-review-redrive-park.sh; do
  [ -f "$HERE/$SUITE" ] || { bad "$SUITE is missing"; continue; }
  OUT="$(mktemp)"
  run_isolated "$SUITE" "$OUT"
  RC=$?
  TALLY="$(grep -E '^ *[0-9]+ passed, [0-9]+ failed' "$OUT" | tail -1)"

  # Asserted on the suite's own tally, not on its exit code alone: these suites
  # exit non-zero on failure, but a tally line saying "3 failed" with a stray
  # zero exit would otherwise read as a pass.
  case "$TALLY" in
    *" 0 failed") ok "$SUITE is green with the real Linear endpoint unreachable ($TALLY)" ;;
    "") bad "$SUITE printed no tally under an unreachable Linear -- it did not finish: $(tail -3 "$OUT")" ;;
    *)  bad "$SUITE leaks a live Linear call: $TALLY. Failing cases:
$(grep 'FAIL -' "$OUT")" ;;
  esac
  [ "$RC" = "0" ] && ok "$SUITE exited 0 under an unreachable Linear" \
    || bad "$SUITE exited $RC under an unreachable Linear"
  rm -f "$OUT"
done

# THE NEGATIVE SELF-TEST. Everything above passes trivially if the probe env is
# not actually reaching the code -- a typo'd variable name, a suite that stopped
# reading it, an `env` that dropped it. So a call is made that has NO fixture to
# override the default and MUST fail. If this one succeeds, the probe is inert
# and every "ok" above is worthless.
SEL="$(cd "$HERE/../../../.." && pwd)/q-system/.q-system/scripts/review-redrive.py"
PROBE_LEDGER="$(mktemp)"; echo '{}' > "$PROBE_LEDGER"
env KIPI_LINEAR_API_URL="$DEAD_URL" KIPI_LINEAR_API_KEY="$DEAD_KEY" \
    KIPI_ATTEMPTS="$PROBE_LEDGER" \
  python3 "$SEL" mark-dispatched --issue ASK-1 --action rework --pr 1 \
    --head-sha aaaa1111 >/dev/null 2>&1
PROBE_RC=$?
[ "$PROBE_RC" = "3" ] \
  && ok "the probe env is live: an unfixtured claim exits 3 (park unreadable)" \
  || bad "the probe env is INERT -- an unfixtured claim exited $PROBE_RC, want 3. Every check above is vacuous."
[ "$(cat "$PROBE_LEDGER")" = '{}' ] \
  && ok "and that refused claim spent no attempt" \
  || bad "the refused claim wrote to the ledger: $(cat "$PROBE_LEDGER")"
rm -f "$PROBE_LEDGER"

echo "  $PASS passed, $FAIL failed"
[ "$FAIL" = "0" ]
