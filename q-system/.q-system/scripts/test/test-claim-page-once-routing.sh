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

# LIFT THE ROUTER ITSELF, DO NOT RE-WRITE IT (codex round 2 on PR #67, minor 2).
# Case 3 used to define a local `route()` that reimplemented the routing from the
# same mental model that wrote `page_once` -- and it happened to omit the very
# `set -e` that made the shipped function a major defect. A test that reimplements
# its subject asserts the author's intent, not the code. The function wired to six
# call sites had zero executed coverage and the suite was green anyway.
extract_page_once() {
  sed -n '/^page_once() {/,/^}/p' "$WORKER"
}

extract_ledger_fault() {
  sed -n '/^ledger_fault() {/,/^}/p' "$WORKER"
}

CLAIM_FN="$(extract_claim_page_once)"
[ -n "$CLAIM_FN" ] || fail "claim_page_once is no longer a one-line definition in $WORKER; this test has to be re-pointed"

PAGE_FN="$(extract_page_once)"
[ -n "$PAGE_FN" ] || fail "page_once is no longer a \`page_once() {\` .. \`}\` block in $WORKER; this test has to be re-pointed"

FAULT_FN="$(extract_ledger_fault)"
[ -n "$FAULT_FN" ] || fail "ledger_fault is no longer a \`ledger_fault() {\` .. \`}\` block in $WORKER; this test has to be re-pointed"

# page_once calls ledger_fault, which pages Slack through \$NOTIFY. Point it at a
# log inside the temp dir: unstubbed it would run the real slack-notify.sh.
NOTIFY="$WORK/notify.sh"
SLACKLOG="$WORK/slack.log"
printf '#!/usr/bin/env bash\necho "$*" >> "%s"\n' "$SLACKLOG" > "$NOTIFY"
chmod +x "$NOTIFY"
: > "$SLACKLOG"

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
# routing the worker actually performs, on the three answers it can get -- by
# running the WORKER'S OWN `page_once`, lifted above, not a copy of it.
SAYLOG="$WORK/say.log"
say() { echo "$*" >> "$SAYLOG"; }
LEDGER_FAULT_ALERTED=0
eval "$FAULT_FN"
eval "$PAGE_FN"

# `page_once` answers page/quiet with its exit code and distinguishes the third
# route by warning through `say`, so the observation has to read both.
route() {
  : > "$SAYLOG"
  LEDGER_FAULT_ALERTED=0
  if page_once "$@" 2>/dev/null; then
    if [ -s "$SAYLOG" ]; then echo page-and-warn; else echo page; fi
  else
    if [ -s "$SAYLOG" ]; then echo quiet-and-warn; else echo quiet; fi
  fi
}
echo '{}' > "$ATTEMPTS"
rm -f "$ATTEMPTS.lock"   # case 2 deliberately left a held lock behind
[ "$(route ASK-3 tree_paged)" = "page" ]  || fail "a first claim did not route to page"
[ "$(route ASK-3 tree_paged)" = "quiet" ] || fail "a repeat claim did not route to quiet"
# The third answer: the ledger could not run at all, so nothing was written and
# nothing was claimed. Stands in for exit 2 (usage) and exit 3 (contention) alike.
#
# THIS USED TO ASSERT `page-and-warn` AND THAT WAS THE ROUND-4 MAJOR. Returning
# 0 here tells the CALLER to write its artifact, and at the stuck site that
# artifact is a permanent Linear comment whose only dedup is the ledger flag we
# just failed to write. The route has to be distinguishable from plain `quiet`
# -- that is what finding 2 of round 1 was about, and it still holds -- but
# distinguishable via the WARN, not by driving a non-idempotent permanent write
# with its dedup switched off. Cases 7-9 below hold the consequence.
BROKEN_RC="$(LEDGER="$WORK/no-such-ledger.py" route ASK-3 tree_paged)"
[ "$BROKEN_RC" = "quiet-and-warn" ] || fail "THE DEFECT: the ledger did not run and the answer
routed to '$BROKEN_RC'. It must be 'quiet-and-warn': audible (a bare 'quiet' drops
the state silently) but WITHOUT returning 0, because returning 0 makes the caller
post a permanent Linear comment that nothing can de-duplicate."
ok "page / quiet / quiet-and-warn are three distinct routes, not one"

# --- 4. EVERY CALL SITE ACTUALLY USES THE ROUTING HELPER --------------------
# The routing is only real if no call site still writes the collapsing shape.
BARE="$(grep -cE '^\s*if claim_page_once ' "$WORKER" || true)"
if [ "$BARE" -ne 0 ]; then
  fail "THE DEFECT: $BARE call site(s) in linear-worker.sh still use
\`if claim_page_once ...; then\`, which collapses exit 3 (wrote nothing) into the
same branch as exit 1 (already claimed). Those pages are silently dropped."
fi
ok "no call site uses the bare \`if claim_page_once\` shape that collapses exit 3"

# --- 5. page_once MUST LEAVE THE SHELL FLAGS IT FOUND ----------------------
# (codex round 2 on PR #67, major.) `page_once` bracketed its call in
# `set +e` .. `set -e`, which does not RESTORE errexit, it TURNS IT ON. The
# worker runs `set -uo pipefail` (line 47) and has never had `-e`, so the first
# page in a run silently re-flags the rest of the script.
#
# THIS CASE CANNOT RUN IN-PROCESS. This suite itself runs `set -euo pipefail`,
# so errexit is already on here and the leak is invisible. The observation only
# exists under the worker's REAL flags, which is why it forks.
cat > "$WORK/flags.sh" <<EOF
set -uo pipefail                       # the worker's flags at linear-worker.sh:47
LEDGER="$LEDGER_PY"
ATTEMPTS="$WORK/flags-attempts.json"
echo '{}' > "\$ATTEMPTS"
say() { echo "\$*" >&2; }
$CLAIM_FN
$PAGE_FN
BEFORE="\$-"
page_once ASK-FLAGS stuck_paged >/dev/null 2>&1
AFTER="\$-"
echo "\$BEFORE|\$AFTER"
EOF
FLAGS="$(bash "$WORK/flags.sh")"
FLAGS_BEFORE="${FLAGS%%|*}"
FLAGS_AFTER="${FLAGS##*|}"
if [ "$FLAGS_BEFORE" != "$FLAGS_AFTER" ]; then
  fail "THE DEFECT: page_once changed the caller's shell flags from '$FLAGS_BEFORE' to
'$FLAGS_AFTER'. \`set -e\` at the end of the function does not restore errexit, it
enables it, and linear-worker.sh never had it. Every command after the first page
in a run is now fatal."
fi
ok "page_once leaves the shell flags unchanged ($FLAGS_BEFORE -> $FLAGS_AFTER)"

# --- 6. THE 3AM CONSEQUENCE: A PARTIAL QUEUE DRAIN THAT EXITS 0 -------------
# Flags are only worth asserting because of what they do to the drain. The
# worker's queue is a pipeline into `while read`, and it ends by saying
# "run complete" and exiting 0 -- its header documents that as "a caller may
# treat this as healthy". With errexit leaked, the first benign non-zero after
# the first page kills the loop and the worker still reports healthy: issues
# silently never processed, which is the stall class this file exists to kill.
cat > "$WORK/drain.sh" <<EOF
set -uo pipefail
LEDGER="$LEDGER_PY"
ATTEMPTS="$WORK/drain-attempts.json"
echo '{}' > "\$ATTEMPTS"
say() { echo "\$*" >&2; }
$CLAIM_FN
$PAGE_FN
printf 'ASK-1\nASK-2\nASK-3\n' | while read -r I; do
  echo "processing \$I"
  page_once "\$I" stuck_paged >/dev/null 2>&1 || true
  # A benign non-zero the worker runs constantly: a grep that matches nothing.
  grep -q 'no-such-pattern' /dev/null || true
  [ -f "$WORK/no-such-file" ]        # unguarded, exits 1, harmless without -e
  echo "finished \$I"
done
echo "LOOP DONE"
EOF
DRAINED="$(bash "$WORK/drain.sh" 2>/dev/null | grep -c '^processing ' || true)"
if [ "$DRAINED" -ne 3 ]; then
  fail "THE DEFECT: the queue drained $DRAINED of 3 issues. page_once leaked errexit,
so the first benign non-zero after the first page killed the drain -- and the
worker still exits 0 and says 'run complete', which its own header tells callers
to treat as healthy. A partial drain reported healthy is a silent stall."
fi
ok "a 3-issue queue still drains all 3 after a page fires (drained $DRAINED)"

# --- 7-9. A PAGE THE LEDGER COULD NOT RECORD MUST NOT DRIVE A PERMANENT WRITE -
# (codex round 4 on PR #67, major.) Exit codes and warn-vs-quiet are internals;
# the thing that reaches a human is what the CALLER writes when page_once says 0.
# At the stuck site that is `linear-sync.py progress` -- a permanent Linear
# comment, and the ledger flag is its only dedup. So `return 0` on the two codes
# that mean THE LEDGER DID NOT ANSWER drove a non-idempotent write with its dedup
# switched off. These three cases assert the artifact count, not the exit code.
#
# A real worker RUN is a fresh process, so `LEDGER_FAULT_ALERTED` starts at 0.
# Modelling several runs in one shell means resetting it by hand.
PERMANENT="$WORK/linear-comments.log"
: > "$PERMANENT"
attempt_page() {
  if page_once "$1" stuck_paged 2>/dev/null; then
    echo "PERMANENT LINEAR COMMENT on $1" >> "$PERMANENT"
  fi
}
new_run() { LEDGER_FAULT_ALERTED=0; }

# --- 7. CONTENTION PAGES ONCE ACROSS TWO RUNS, NOT TWICE -------------------
# Run A meets a live holder (exit 3, wrote nothing); run B, one cycle later,
# finds the lock free and claims. The state is real and deserves exactly one
# comment. Contention DEFERS the page by a cycle -- it does not drop it, which
# is why staying quiet here is safe and posting is not.
echo '{}' > "$ATTEMPTS"
rm -f "$ATTEMPTS.lock"
python3 - "$ATTEMPTS.lock" <<'PY' &
import fcntl, sys, time
fh = open(sys.argv[1], "a")
fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
time.sleep(60)
PY
HOLDER=$!
sleep 1
new_run; KIPI_ATTEMPTS_LOCK_TRIES=2 attempt_page ASK-CONTEND
kill "$HOLDER" 2>/dev/null || true
wait "$HOLDER" 2>/dev/null || true
new_run; attempt_page ASK-CONTEND
CONTEND_COMMENTS="$(grep -c 'ASK-CONTEND' "$PERMANENT" || true)"
if [ "$CONTEND_COMMENTS" -ne 1 ]; then
  fail "THE DEFECT: one contended cycle plus one successful cycle posted
$CONTEND_COMMENTS permanent Linear comments for a single state, expected 1. The
contended run wrote no flag, so paging off it duplicates whatever the run that
DOES get the lock posts a cycle later."
fi
ok "a contended cycle followed by a claiming cycle posts exactly 1 comment"

# --- 8. AN UNWRITABLE LEDGER DOES NOT POST EVERY RUN FOREVER ---------------
# Exit 2 is NOT self-recovering: nothing is ever claimed, so "bounded by the
# retry budget" -- true of contention -- is false here. Five cycles stand in for
# the unbounded series. Repeating "still stuck" every 15 minutes forever is the
# cry-wolf failure the stuck site's own comment says this flag exists to prevent.
: > "$PERMANENT"; : > "$SLACKLOG"
for cycle in 1 2 3 4 5; do
  new_run
  LEDGER="$WORK/no-such-ledger.py" attempt_page ASK-BROKEN
done
BROKEN_COMMENTS="$(grep -c 'ASK-BROKEN' "$PERMANENT" || true)"
if [ "$BROKEN_COMMENTS" -ne 0 ]; then
  fail "THE DEFECT: an unwritable ledger posted $BROKEN_COMMENTS permanent Linear
comments over 5 cycles, and the series does not terminate -- nothing is ever
claimed, so every future run posts again. A read-only filesystem exits 2 forever."
fi
BROKEN_ALERTS="$(wc -l < "$SLACKLOG" | tr -d ' ')"
if [ "$BROKEN_ALERTS" -ne 5 ]; then
  fail "an unwritable ledger raised $BROKEN_ALERTS Slack alerts over 5 runs, expected 5
(one per run). Silence here would be the drop this whole file exists to prevent:
the notice moves channel, it does not disappear."
fi
ok "5 unwritable cycles post 0 permanent comments and 5 ephemeral alerts"

# --- 9. ONE BROKEN LEDGER, ONE ALERT -- NOT ONE PER QUEUED ISSUE -----------
# A broken ledger is a property of the WORKER, not of any issue. Alerting per
# issue re-creates cry-wolf inside the channel the notice was just moved into.
: > "$PERMANENT"; : > "$SLACKLOG"
new_run   # ONE run; the four issues below are its queue, not four runs
for i in ASK-Q1 ASK-Q2 ASK-Q3 ASK-Q4; do
  LEDGER="$WORK/no-such-ledger.py" attempt_page "$i"
done
QUEUE_ALERTS="$(wc -l < "$SLACKLOG" | tr -d ' ')"
if [ "$QUEUE_ALERTS" -ne 1 ]; then
  fail "THE DEFECT: a 4-issue queue against one broken ledger raised $QUEUE_ALERTS Slack
alerts in a single run, expected 1. The fault is the ledger, not the issue."
fi
[ ! -s "$PERMANENT" ] || fail "a broken ledger still posted permanent comments for a queued run"
ok "a 4-issue queue against a broken ledger raises 1 alert, not 4"

echo "PASS ($PASS checks)"
