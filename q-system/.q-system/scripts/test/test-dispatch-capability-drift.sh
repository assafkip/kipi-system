#!/usr/bin/env bash
# Reproducer + acceptance criterion for ASK-355 (promoted from sp-d319d541).
#
# THE DEFECT
# ----------
# kipi-dispatch.sh runs from the founder's WORKING TREE, so which branch is
# checked out decides what the 15-minute heartbeat can do. During ASK-352 the
# reviewer-redrive selector drove the real loop from an unmerged branch; any
# branch switch in that checkout reverts the wiring mid-flight and the dispatcher
# keeps exiting 0 while doing strictly less than it did a minute earlier.
#
# It is a SILENT DOWNGRADE: additive loss, not corruption. No error, no red gate,
# no page. The capability manifest checks declared-vs-actual per TEST FILE; it
# never asks whether the RUNNING dispatcher still has a call site it had before.
# So the loop quietly does less and nothing anywhere says so.
#
# WHAT IS ASSERTED
# ----------------
# The dispatcher records, each run, which redrive selectors it RESOLVED (the
# script exists under $REPO *and* the running dispatcher still references it from
# a non-comment line), and pages ONCE on each transition -- loss and recovery
# both. An operator who never hears the recovery cannot tell a degraded loop from
# a healthy one, which is the posture note_degraded_transition already takes in
# pr-review-agent.sh.
#
# HOW IT IS ASSERTED
# ------------------
# By driving the REAL kipi-dispatch.sh against a sandbox repo (the same shape
# test-dispatch-liveness.sh uses) and reading pages off the NOTIFY STUB'S OWN
# RECORD -- a file the stub appends to -- never off stderr. stderr would pass
# vacuously against an empty string, and the dispatcher's say() does not write
# there anyway.
#
# ISOLATION: HOME, $REPO and $NOTIFY all point inside a temp dir. The real
# slack-notify.sh is never on any path this test can reach, and the belt below
# pins KIPI_NOTIFY for anything that shells out before the stub is wired.
set -uo pipefail

# The founder was paged BY TESTS three times on 2026-08-01. Belt, in addition to
# the per-run stub: nothing in this file may reach the real notifier.
export KIPI_NOTIFY=/usr/bin/true

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Derive the repo from the SCRIPT, never from $PWD -- a test that asks the
# checkout it happens to run in proves nothing about the caller.
REPO_ROOT="$(cd "$HERE" && git rev-parse --show-toplevel)"
DISPATCH="${KIPI_TEST_DISPATCH:-$REPO_ROOT/kipi-dispatch.sh}"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

[ -f "$DISPATCH" ] || { echo "FATAL: no kipi-dispatch.sh at $DISPATCH" >&2; exit 1; }

ROOT="$(mktemp -d)"
trap 'rm -rf -- "$ROOT" 2>/dev/null' EXIT

FAKE_REPO="$ROOT/repo"
SCRIPTS="$FAKE_REPO/q-system/.q-system/scripts"
mkdir -p "$SCRIPTS" "$ROOT/home/.config/kipi" "$ROOT/bin"

# gh must merely exist; the dispatcher only checks `command -v gh`.
printf '#!/bin/sh\nexit 0\n' > "$ROOT/bin/gh"; chmod +x "$ROOT/bin/gh"

# THE PAGE SINK. Every assertion about alerting reads THIS FILE, so a page is
# graded on the notifier's own record of what it was handed.
PAGES="$ROOT/pages.txt"
printf '#!/bin/sh\nprintf "%%s\\n" "$1" >> "%s"\n' "$PAGES" > "$ROOT/notify.sh"
chmod +x "$ROOT/notify.sh"

# A real git repo, because the page has to name the current branch and HEAD and a
# fixture that cannot produce one would grade that requirement vacuously. No
# `origin` remote: stale_check's fetch fails, which it treats as "no answer" and
# proceeds -- fail closed on staleness, fail open on not knowing.
( cd "$FAKE_REPO"
  git init -q -b sana/ask-355 .
  git config user.email t@e.com; git config user.name t ) >/dev/null 2>&1

# The two selectors under test. Stubs, not the real ones: this test must never
# reach gh or Linear. Both answer "nothing to redrive" (rc 1).
seed_selectors() {
  printf '#!/usr/bin/env python3\nraise SystemExit(1)\n' > "$SCRIPTS/ci-redrive.py"
  printf '#!/usr/bin/env python3\nraise SystemExit(1)\n' > "$SCRIPTS/review-redrive.py"
}
seed_selectors

# `kipi work` with nothing ready: the run reaches "nothing ready" and exits 0
# without claiming or dispatching anything.
cat > "$FAKE_REPO/kipi" <<'SH'
#!/usr/bin/env bash
case "$1" in
  work) printf '0 ready issues\n' ;;
esac
exit 0
SH
chmod +x "$FAKE_REPO/kipi"
( cd "$FAKE_REPO"; git add -A; git commit -qm seed ) >/dev/null 2>&1
HEAD_SHORT="$(git -C "$FAKE_REPO" rev-parse --short HEAD)"

# KIPI_DISPATCH_MAX is pinned high for the same reason test-dispatch-liveness.sh
# pins it: the concurrency cap counts converge runs from the GLOBAL process
# table, so an unrelated pair on this box would make the dispatcher skip before
# it reaches anything under test.
run_dispatch() {  # run_dispatch [dispatcher-path]
  ( cd "$FAKE_REPO" && HOME="$ROOT/home" PATH="$ROOT/bin:$PATH" \
      KIPI_REPO="$FAKE_REPO" KIPI_NOTIFY="$ROOT/notify.sh" \
      KIPI_DISPATCH_DAILY_MAX=9 KIPI_DISPATCH_MAX=999 \
      bash "${1:-$DISPATCH}" >/dev/null 2>&1 )
}

# Pages ABOUT SELECTOR DRIFT only. The beacon is seeded away below, but counting
# the whole file would still make this assertion hostage to any unrelated page a
# future guard adds -- and then it would fail for a reason that is not this code.
selector_pages() { grep -c 'redrive selector' "$PAGES" 2>/dev/null | tr -d ' \n'; }

reset_state() {
  rm -rf -- "$ROOT/home/.config/kipi"
  mkdir -p "$ROOT/home/.config/kipi"
  # Seed the liveness beacon so the one-off "heartbeat STARTED" page does not
  # fire and get mistaken for a drift page.
  date -u +%s > "$ROOT/home/.config/kipi/dispatch-lastbeat"
  : > "$PAGES"
  seed_selectors
}

# A mutant must actually differ from its source, or a mutation check grades
# nothing and reports SURVIVED for a mutation that was never applied.
mutate() {  # mutate <dst> <sed-expr>...
  local dst="$1"; shift
  sed "$@" "$DISPATCH" > "$dst"
  if cmp -s "$DISPATCH" "$dst"; then
    echo "FATAL: mutation changed nothing -- this check would grade nothing" >&2
    exit 1
  fi
}

echo "test-dispatch-capability-drift.sh"

# --- 1. A RUN RECORDS WHAT IT RESOLVED, AND SAYS NOTHING ---------------------
# There is no previous run to compare against, so a first beat must be silent.
# A guard that pages on its own first sighting pages once per fresh machine and
# once per state-file loss, which is how an alert becomes noise.
reset_state
run_dispatch
STATE="$ROOT/home/.config/kipi/redrive-selectors.state"
if [ -f "$STATE" ]; then
  ok "1a the run recorded the selectors it resolved to a state file"
else
  bad "THE DEFECT: nothing records which redrive selectors the running dispatcher resolved"
fi
grep -q '^ci-redrive.py present$' "$STATE" 2>/dev/null \
  && ok "1b ci-redrive.py recorded as resolved" \
  || bad "ci-redrive.py was not recorded as resolved: $(cat "$STATE" 2>/dev/null | tr '\n' ' ')"
grep -q '^review-redrive.py present$' "$STATE" 2>/dev/null \
  && ok "1c review-redrive.py recorded as resolved" \
  || bad "review-redrive.py was not recorded as resolved: $(cat "$STATE" 2>/dev/null | tr '\n' ' ')"
[ "$(selector_pages)" = "0" ] \
  && ok "1d the first run pages nothing (no previous run to have lost anything)" \
  || bad "the first run paged $(selector_pages) time(s) with nothing to compare against"

# --- 2. A SELECTOR THAT WAS THERE AND IS GONE PAGES ONCE ---------------------
# THE REGRESSION. Before this guard the run below was indistinguishable from a
# healthy one: exit 0, no error, strictly less work done.
rm -f "$SCRIPTS/review-redrive.py"
run_dispatch
N="$(selector_pages)"
if [ "$N" = "1" ]; then
  ok "2a a selector that vanished between two runs pages exactly once"
else
  bad "THE DEFECT: a vanished redrive selector produced $N page(s), expected 1"
fi
grep -q 'review-redrive.py' "$PAGES" 2>/dev/null \
  && ok "2b the page names the selector that went missing" \
  || bad "the page does not name the selector; an operator cannot act on it"
grep -q 'sana/ask-355' "$PAGES" 2>/dev/null \
  && ok "2c the page names the checked-out branch" \
  || bad "the page does not name the branch, which is the thing that has to change"
grep -q "$HEAD_SHORT" "$PAGES" 2>/dev/null \
  && ok "2d the page names HEAD" \
  || bad "the page does not name HEAD"
grep -q '^review-redrive.py absent$' "$STATE" 2>/dev/null \
  && ok "2e the state file now records the selector as absent" \
  || bad "the state file did not record the loss, so the next run re-detects it forever"

# --- 3. THE SAME UNCHANGED STATE DOES NOT PAGE AGAIN -------------------------
# On a 900s timer, a state-based page is 96 identical Slack lines a day. The
# founder's own detect-act-learn rule: one summary line, never one ping per
# finding. The cost of the noise is not annoyance, it is that it trains him to
# skim the channel, which is how the one page that matters gets missed.
run_dispatch
N="$(selector_pages)"
[ "$N" = "1" ] \
  && ok "3a a second run with the selector still gone stays quiet (1 page total)" \
  || bad "THE DEFECT: an unchanged degraded state paged again ($N total)"

# --- 4. RECOVERY IS REPORTED TOO --------------------------------------------
# An operator who never hears the recovery cannot tell a degraded loop from a
# healthy one. Same posture as note_degraded_transition in pr-review-agent.sh.
seed_selectors
run_dispatch
N="$(selector_pages)"
[ "$N" = "2" ] \
  && ok "4a the selector coming back pages once (2 pages total)" \
  || bad "recovery was silent or noisy: $N selector page(s) total, expected 2"
tail -1 "$PAGES" 2>/dev/null | grep -q 'review-redrive.py' \
  && ok "4b the recovery page names the selector that came back" \
  || bad "the recovery page does not name the selector: $(tail -1 "$PAGES" 2>/dev/null)"

run_dispatch
N="$(selector_pages)"
[ "$N" = "2" ] \
  && ok "4c a healthy run after recovery stays quiet" \
  || bad "a healthy run paged again ($N total)"

# --- 5. THE CALL-SITE HALF, NOT JUST THE FILE --------------------------------
# The branch-switch shape drops BOTH the selector script and the block that calls
# it. A guard that only stats the path would report a selector as resolved while
# the running dispatcher no longer invokes it -- the silent downgrade with a
# green light on it. Driven through a COPY of the real dispatcher whose call site
# is re-pointed, because the file has to stay present for this case to mean
# anything: file there, call site gone.
reset_state
NOCALL="$ROOT/dispatch-nocallsite.sh"
mutate "$NOCALL" -e 's|scripts/review-redrive\.py"|scripts/review-redrive-RENAMED.py"|'
run_dispatch                # baseline: both resolved, recorded, silent
run_dispatch "$NOCALL"
N="$(selector_pages)"
if [ "$N" = "1" ] && grep -q 'review-redrive.py' "$PAGES" 2>/dev/null; then
  ok "5a a selector whose FILE exists but whose call site is gone is reported missing"
else
  bad "THE DEFECT: the guard stats the path only -- a dispatcher that no longer calls the selector reported healthy ($N page(s))"
fi

# --- 6. MUTATION: DELETE THE PAGE -> CASE 2 GOES RED -------------------------
# A check that cannot fail for the reason it exists is decoration.
reset_state
NOPAGE="$ROOT/dispatch-nopage.sh"
mutate "$NOPAGE" -e '/page_once "selector-gone-/d'
run_dispatch "$NOPAGE"
rm -f "$SCRIPTS/review-redrive.py"
run_dispatch "$NOPAGE"
N="$(selector_pages)"
[ "$N" = "0" ] \
  && ok "6a removing the page call takes case 2 red (0 pages), so case 2 grades the page" \
  || bad "MUTANT SURVIVED: the loss still paged $N time(s) with the page call deleted"

# --- 7. MUTATION: PAGE ON STATE, NOT ON TRANSITION -> CASE 3 GOES RED --------
# The wrong-but-plausible implementation: look at the current state each run and
# page if a selector is absent. It satisfies case 2 exactly and fails case 3.
reset_state
EVERY="$ROOT/dispatch-everyrun.sh"
mutate "$EVERY" \
  -e 's|prev="\$(selector_prev "\$sel")"|prev="present"|' \
  -e 's|page_once "selector-gone-\$sel" |page |'
run_dispatch "$EVERY"
rm -f "$SCRIPTS/review-redrive.py"
run_dispatch "$EVERY"
run_dispatch "$EVERY"
N="$(selector_pages)"
[ "$N" -ge 2 ] 2>/dev/null \
  && ok "7a paging on state instead of on transition takes case 3 red ($N pages), so case 3 grades once-only" \
  || bad "MUTANT SURVIVED: a state-based pager produced $N page(s); case 3 does not grade once-only"

# --- 8. THE GUARD MUST NOT GO BLIND SILENTLY ---------------------------------
# The defect this case exists for was live in the first cut of the guard: the awk
# that skips the guard's own block was anchored on text the marker line does not
# contain, so the skip never armed, the guard's own SELECTOR_NAMES line counted as
# a live call site, and every selector read as resolved forever. Fully green,
# structurally blind. A range that matches nothing must be a fault, not a number.
reset_state
BLIND="$ROOT/dispatch-nomarker.sh"
# ANCHORED TO THE MARKER LINE ONLY (`^# --- `). Unanchored, the same expression
# also rewrote the awk pattern that LOOKS for the marker -- a self-consistent
# rename that leaves the guard working, so the mutant survived for the one reason
# a mutation must never survive: it never mutated the thing under test.
mutate "$BLIND" -e 's|^# --- SELECTOR-DRIFT GUARD \(.*\):BEGIN|# --- SELECTOR-DRIFT MOVED:BEGIN|'
run_dispatch "$BLIND"
if grep -q 'cannot read its own block markers' "$PAGES" 2>/dev/null; then
  ok "8a a guard that cannot find its own markers pages about itself"
else
  bad "MUTANT SURVIVED: the guard lost its block markers and reported nothing"
fi
[ -f "$STATE" ] \
  && bad "the blind run wrote a state file, overwriting a baseline with a measurement it never made" \
  || ok "8b the blind run changed no state, so a good baseline is not overwritten by a non-measurement"

# --- 9. THE TEST NEVER TOUCHES THE REAL NOTIFIER -----------------------------
# Structural, not a promise in a comment. $NOTIFY defaults to "$REPO/.../
# slack-notify.sh", and $REPO here is the sandbox -- so even with KIPI_NOTIFY
# unset every page resolves inside the temp dir, where no notifier exists. This
# goes red the moment someone points KIPI_REPO at the real checkout.
[ "$FAKE_REPO" != "$REPO_ROOT" ] \
  && ok "9a the dispatcher under test runs against the sandbox, not the real checkout" \
  || bad "KIPI_REPO points at the real repo; a page here would reach the founder"
[ -e "$SCRIPTS/slack-notify.sh" ] \
  && bad "a notifier exists at the sandbox's default notify path; pages are no longer stub-only" \
  || ok "9b the default notify path resolves inside the sandbox and holds no notifier"

echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ]
