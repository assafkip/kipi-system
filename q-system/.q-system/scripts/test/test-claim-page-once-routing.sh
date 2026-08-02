#!/usr/bin/env bash
# Reproducer + acceptance criterion for how linear-worker.sh routes the ledger's
# exit codes (ASK-286, codex round 1 on PR #67, finding 2).
#
# THE DEFECT
# ----------
# `claim_page_once` is the once-only page gate for six states in linear-worker.sh
# (stuck, drift, conflict, tree, and both auto-merge shapes). Every call site is
# `if claim_page_once "$ISSUE" <flag>; then <page>; fi`, and bash `if` only ever
# asks "was the exit 0". So THREE different answers collapse into one branch:
#
#   0  claimed, this is the first time     -> page          (correct)
#   1  already claimed on an earlier run   -> stay quiet     (correct)
#   3  the ledger could not be written     -> stay quiet     (WRONG)
#   2  unknown op / bad usage              -> stay quiet     (WRONG)
#
# Exit 3 means NOTHING WAS CLAIMED. Reading it as "already claimed" suppresses a
# page for a state no file records, so it will not be retired by a later run
# either -- it is simply gone. That is the silent-stall failure class this whole
# worker exists to kill, re-created inside the mechanism built to kill it.
#
# WHICH DIRECTION IS SAFE
# -----------------------
# A duplicate page is noise; a suppressed page is a stall nobody sees. Under
# contention nothing was claimed, so the state is still true and still unpaged:
# the worker pages. Lock contention is bounded (the retry budget), so this is
# a page or two during a collision, not a page every cycle forever -- the first
# run that gets the lock claims the flag and every run after it is quiet again.
#
# ISOLATION: runs against a temp ledger. Never touches linear-worker-attempts.json.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
WORKER="$ROOT/q-system/.q-system/scripts/linear-worker.sh"
LEDGER_PY="$ROOT/q-system/.q-system/scripts/attempts-ledger.py"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Lift the one function under test out of the worker rather than sourcing the
# whole script, which runs a dispatch loop against live Linear on load.
extract_claim_page_once() {
  awk '/^claim_page_once\(\)/{print; exit}' "$WORKER"
}

CLAIM_FN="$(extract_claim_page_once)"
[ -n "$CLAIM_FN" ] || fail "claim_page_once is no longer a one-line definition in $WORKER; this test has to be re-pointed"

LEDGER="$LEDGER_PY"
ATTEMPTS="$WORK/attempts.json"
echo '{}' > "$ATTEMPTS"
eval "$CLAIM_FN"

# --- 1. THE FIRST CLAIM PAGES, THE SECOND DOES NOT -------------------------
if claim_page_once "ASK-1" stuck_paged 2>/dev/null; then :; else
  fail "the first claim of a flag did not page"
fi
if claim_page_once "ASK-1" stuck_paged 2>/dev/null; then
  fail "the second claim of the same flag paged again, so the page is not once-only"
fi
ok "the first claim pages and the second stays quiet"

# --- 2. A LEDGER WRITE THAT FAILED MUST NOT READ AS 'ALREADY CLAIMED' -------
# Hold the lock from a live process so the claim exits 3 (wrote nothing). The
# call site's `if` must not treat that as "quiet": nothing was claimed, so the
# state is unpaged and still true.
python3 - "$ATTEMPTS.lock" <<'PY' &
import fcntl, sys, time
fh = open(sys.argv[1], "a")
fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
sys.stdout.write("held\n"); sys.stdout.flush()
time.sleep(60)
PY
HOLDER=$!
# Also stamp the pre-flock token shape, so this case is meaningful against both
# the old hand-rolled lock and the flock one.
printf '%s\n' "$$:0:0" > "$ATTEMPTS.lock" 2>/dev/null || true
sleep 1

set +e
KIPI_ATTEMPTS_LOCK_TRIES=2 claim_page_once "ASK-2" conflict_paged >/dev/null 2>&1
CONTENDED_RC=$?
set -e
kill "$HOLDER" 2>/dev/null || true
wait "$HOLDER" 2>/dev/null || true

[ "$CONTENDED_RC" -ne 0 ] || fail "the contended claim exited 0, so it reported a claim it never made"

if [ "$CONTENDED_RC" -eq 1 ]; then
  fail "THE DEFECT: the ledger could not be written and the claim answered 1 -- the same
answer as 'already claimed on an earlier run'. Every call site is
\`if claim_page_once ...; then page; fi\`, so the page is silently dropped for a
state no file records and no later run will retire. rc=$CONTENDED_RC"
fi
ok "a failed ledger write is distinguishable from 'already claimed' (rc=$CONTENDED_RC)"

# --- 3. THE CALL-SITE SHAPE ROUTES THE THREE ANSWERS TO TWO BRANCHES --------
# The exit code only matters if the six call sites read it. This asserts the
# routing the worker actually performs, on the three answers it can get.
route() {
  set +e
  claim_page_once "$@" >/dev/null 2>&1
  local rc=$?
  set -e
  case "$rc" in
    0) echo page ;;
    1) echo quiet ;;
    *) echo page-and-warn ;;
  esac
}
echo '{}' > "$ATTEMPTS"
rm -f "$ATTEMPTS.lock"   # case 2 deliberately left a held lock behind
[ "$(route ASK-3 tree_paged)" = "page" ]  || fail "a first claim did not route to page"
[ "$(route ASK-3 tree_paged)" = "quiet" ] || fail "a repeat claim did not route to quiet"
# The third answer: the ledger could not run at all, so nothing was written and
# nothing was claimed. Stands in for exit 2 (usage) and exit 3 (contention)
# alike -- what matters is that neither lands on the "quiet" branch.
BROKEN_RC="$(LEDGER="$WORK/no-such-ledger.py" route ASK-3 tree_paged)"
[ "$BROKEN_RC" = "page-and-warn" ] || fail "THE DEFECT: the ledger did not run and the answer
routed to '$BROKEN_RC'. Nothing was claimed, so a 'quiet' here drops the page for
a state no file records and no later run will retire."
ok "page / quiet / page-and-warn are three distinct routes, not one"

# --- 4. EVERY CALL SITE ACTUALLY USES THE ROUTING HELPER --------------------
# The routing is only real if no call site still writes the collapsing shape.
BARE="$(grep -cE '^\s*if claim_page_once ' "$WORKER" || true)"
if [ "$BARE" -ne 0 ]; then
  fail "THE DEFECT: $BARE call site(s) in linear-worker.sh still use
\`if claim_page_once ...; then\`, which collapses exit 3 (wrote nothing) into the
same branch as exit 1 (already claimed). Those pages are silently dropped."
fi
ok "no call site uses the bare \`if claim_page_once\` shape that collapses exit 3"

echo "PASS ($PASS checks)"
