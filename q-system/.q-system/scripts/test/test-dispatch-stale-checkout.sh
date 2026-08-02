#!/usr/bin/env bash
# Reproducer for sp-c775b116: the dispatcher ran the founder's working tree with
# no freshness check, so a merge alone never reached the running loop.
#
# And for ASK-283 (2026-08-02): the freshness check WORKED and then asked a human
# to type the fix. Measured from ~/.config/kipi/dispatch.log that night -- 19
# refusing cycles, 9 Slack pages (per-sha dedupe already worked; it was the LOG
# line that repeated every cycle, not the page), the gap growing 7 -> 10 commits,
# zero automated action. The founder fixed it by hand in the morning.
#
# WHAT THIS DOES NOT FIX, kept here so nobody reads the green suite as "solved":
# that night's early HEAD 97e7fc7 was DIVERGED from origin/main, so a fast-forward
# could not have applied and it would still have paged. Only the later a5ac9c1 was
# fast-forwardable. This heals the tail of that incident. The head needed a human
# because the checkout was genuinely on the wrong history -- case 5 is that case,
# and it still refuses on purpose.
#
# Pairs with: stale_check() + attempt_ff() in kipi-dispatch.sh.
#
# The states that matter, and only SOME of them may refuse:
#   behind, clean, on main -> FAST-FORWARD, then RUN. No page. This is the fix.
#   behind, but the tree belongs to somebody (other branch / detached / staged
#           index / mid-merge) -> REFUSE + PAGE. Never move it under them.
#   behind, and git itself says the ff would overwrite local edits -> REFUSE + PAGE
#   diverged -> REFUSE + PAGE (ff cannot apply)
#   ahead   -> RUN    (an agent commits locally before opening a PR)
#   equal   -> RUN
#   no answer (fetch fails / offline) -> RUN, because a network blip must not
#             wedge the loop. Fail closed on staleness, fail open on not knowing.
#
# The ahead and offline cases are the point. A check that refuses whenever HEAD
# differs from origin/main passes a naive behind-test and wedges the loop on its
# own unpushed work, which is a worse bug than the one being fixed.
#
# EVERY REFUSE CASE ASSERTS HEAD DID NOT MOVE, not just that the log said so. A
# guard that logs "left untouched" while git quietly moved the tree is the exact
# failure this file exists to catch, and log text cannot see it.
set -uo pipefail

# The founder was paged by tests three times on 2026-08-01. The harness below
# stubs the notifier functions outright, so nothing here can reach Slack; this is
# the second belt for anything that ever shells the real script.
export KIPI_NOTIFY=/usr/bin/true

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Derive the repo from the SCRIPT, never from $PWD -- a test that asks the
# checkout it happens to run in proves nothing about the caller.
REPO="$(cd "$HERE" && git rev-parse --show-toplevel)"
DISPATCH="${KIPI_TEST_DISPATCH:-$REPO/kipi-dispatch.sh}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS: $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL: $1"; }

[ -f "$DISPATCH" ] || { echo "no kipi-dispatch.sh at $DISPATCH"; exit 1; }

if ! grep -q 'stale_check' "$DISPATCH"; then
  echo "  FAIL: THE DEFECT: kipi-dispatch.sh has no stale_check, so a merge never reaches the running loop"
  echo "-------- 0 passed, 1 failed --------"
  exit 1
fi
if ! grep -q 'attempt_ff' "$DISPATCH"; then
  echo "  FAIL: THE DEFECT: stale_check has no attempt_ff, so it prints the remedy and waits for a human"
  echo "-------- 0 passed, 1 failed --------"
  exit 1
fi

# Extract the two functions and drive them directly. Running the whole dispatcher
# would reach Linear and could dispatch REAL work -- never let a test touch a live
# data path (fable-discipline lint blocks it, and this is why).
#
# attempt_ff is extracted REAL, not stubbed: it is the code under test. Only
# relaunch_self is stubbed, because the shipped one execs and would replace this
# test process. Same pattern the file already uses for say/page.
HARNESS="$WORK/stale_check.sh"
{
  echo 'set -uo pipefail'
  echo 'REPO="$PWD"'
  echo 'SELF="/dev/null"'
  echo 'say()  { printf "SAY %s\n"  "$*"; }'
  echo 'page() { printf "PAGE %s\n" "$*"; }'
  # page_ok reports delivery, and its exit code is the thing under test in case 7:
  # KIPI_TEST_PAGE_FAILS=1 makes the notifier fail so the dedupe marker must NOT
  # be written. Without a failure knob the "failed page still dedupes" defect
  # cannot be reproduced at all.
  echo 'page_ok() { printf "PAGE %s\n" "$*"; [ "${KIPI_TEST_PAGE_FAILS:-0}" = "1" ] && return 1; return 0; }'
  echo 'relaunch_self() { printf "RELAUNCH\n"; return 0; }'
  awk '/^attempt_ff\(\) \{/,/^\}/' "$DISPATCH"
  awk '/^stale_check\(\) \{/,/^\}/' "$DISPATCH"
  echo 'stale_check && echo "VERDICT=RUN" || echo "VERDICT=REFUSE"'
} > "$HARNESS"

# Guard the extraction itself. An awk range that silently matched nothing would
# make every case below "pass" against an empty function.
for fn in attempt_ff stale_check; do
  grep -q "^$fn() {" "$HARNESS" || { echo "harness did not extract $fn from $DISPATCH"; exit 1; }
done

# --- a real origin + clone, because stale_check asks git real questions ------
ORIGIN="$WORK/origin.git"
git init -q --bare -b main "$ORIGIN"
git init -q -b main "$WORK/seed"
( cd "$WORK/seed"
  git config user.email t@e.com; git config user.name t
  echo one > f.txt; echo side > other.txt; git add -A; git commit -qm one
  git remote add origin "$ORIGIN"; git push -q origin main ) >/dev/null 2>&1

# One commit onto origin/main. Every "behind" case calls this after cloning.
advance_origin() { ( cd "$WORK/seed"; echo "$1" >> f.txt; git commit -qam "$1"; git push -q origin main ) >/dev/null 2>&1; }

# A FRESH CLONE PER CASE. Cases used to share one clone, which coupled them in
# order and meant a failure early on cascaded into unrelated noise below.
fresh_clone() {
  local d="$WORK/$1"
  git clone -q "$ORIGIN" "$d" >/dev/null 2>&1
  ( cd "$d"; git config user.email t@e.com; git config user.name t )
  echo "$d"
}
head_of() { git -C "$1" rev-parse HEAD 2>/dev/null; }

run_check() { ( cd "$1" && bash "$HARNESS" 2>&1 ); }

echo "== 1. equal: HEAD == origin/main -> RUN =="
C1="$(fresh_clone c-equal)"
OUT="$(run_check "$C1")"
echo "$OUT" | grep -q 'VERDICT=RUN' \
  && ok "an up-to-date checkout runs" \
  || bad "an up-to-date checkout was refused: $(echo "$OUT" | tr '\n' ' ')"

echo
echo "== 2. THE FIX: behind + clean + on main -> FAST-FORWARD, RUN, no page =="
C2="$(fresh_clone c-behind)"
BEFORE="$(head_of "$C2")"
advance_origin two
OUT="$(run_check "$C2")"
AFTER="$(head_of "$C2")"
REMOTE="$(git -C "$C2" rev-parse origin/main)"
echo "$OUT" | grep -q 'VERDICT=RUN' \
  && ok "a stale checkout now proceeds instead of resting" \
  || bad "THE DEFECT: a stale checkout still refused instead of fixing itself"
# The load-bearing assertion: real git state, not the log line.
if [ "$AFTER" = "$REMOTE" ] && [ "$AFTER" != "$BEFORE" ]; then
  ok "the checkout was actually fast-forwarded (${BEFORE:0:7} -> ${AFTER:0:7})"
else
  bad "THE DEFECT: HEAD is still ${AFTER:0:7} (was ${BEFORE:0:7}, origin/main ${REMOTE:0:7}) -- it logged a fix it did not perform"
fi
echo "$OUT" | grep -q '^PAGE ' \
  && bad "THE DEFECT: it paged the founder for something it fixed itself -- that is the alert-with-no-hands shape" \
  || ok "no page: a fix that worked does not interrupt anyone"
echo "$OUT" | grep -q 'SAY self-heal: fast-forwarded' \
  && ok "the automated action is logged, so it is auditable after the fact" \
  || bad "the tree moved with no log line, which is a silent write"
echo "$OUT" | grep -q 'RELAUNCH' \
  && ok "it re-execs on the new control code (bash reads scripts lazily; continuing in-process runs the old byte offsets)" \
  || bad "no relaunch after the ff, so the rest of this run uses the superseded script text"

echo
echo "== 3. ahead: local commits not yet pushed -> RUN (must not wedge) =="
C3="$(fresh_clone c-ahead)"
( cd "$C3"; echo three >> f.txt; git commit -qam three ) >/dev/null 2>&1
OUT="$(run_check "$C3")"
echo "$OUT" | grep -q 'VERDICT=RUN' \
  && ok "a checkout AHEAD of origin/main still runs" \
  || bad "being ahead was treated as stale, which wedges the loop on its own unpushed work"

echo
echo "== 4. no answer: fetch fails -> RUN (fail open on not knowing) =="
# A repo with no reachable remote is the offline case without needing the network.
BROKEN="$WORK/broken"
git init -q -b main "$BROKEN"
( cd "$BROKEN"; git config user.email t@e.com; git config user.name t
  echo x > f.txt; git add -A; git commit -qm x
  git remote add origin "$WORK/does-not-exist.git" ) >/dev/null 2>&1
OUT="$(run_check "$BROKEN")"
if echo "$OUT" | grep -q 'VERDICT=RUN'; then
  ok "an unanswerable freshness check proceeds instead of wedging"
else
  bad "a failed fetch refused to dispatch, so an offline machine kills the loop"
fi
echo "$OUT" | grep -q 'SAY stale-check' \
  && ok "the unanswered check is logged, not silent" \
  || bad "the check failed with no log line, so the blind spot is invisible"

echo
echo "== 5. DIVERGED must still REFUSE, and the page must name the failed attempt =="
# The case the first cut got wrong, and the one a merge of this very branch
# produces: origin/main gains a commit while this tree keeps local commits of its
# own. A fast-forward CANNOT apply here, so this is a genuine human case.
DIV="$(fresh_clone c-diverged)"
( cd "$DIV"; echo local-only >> f.txt; git commit -qam "local only" ) >/dev/null 2>&1
advance_origin remote-only
DIV_BEFORE="$(head_of "$DIV")"
OUT="$(run_check "$DIV")"
if echo "$OUT" | grep -q 'VERDICT=REFUSE'; then
  ok "a DIVERGED checkout refuses (origin/main holds commits it lacks)"
else
  bad "THE DEFECT: a diverged checkout dispatched, so superseded control code runs after a concurrent merge"
fi
[ "$(head_of "$DIV")" = "$DIV_BEFORE" ] \
  && ok "the diverged tree was not moved" \
  || bad "THE DEFECT: it rewrote a diverged tree -- local commits are now on a different base"
echo "$OUT" | grep -q '^PAGE ' \
  && ok "the case that genuinely needs a human does page" \
  || bad "refused silently: an unattended refusal nobody is told about is a dead loop"
echo "$OUT" | grep -qi 'PAGE.*tried' \
  && ok "the page says the fix was ATTEMPTED, not just that something is wrong" \
  || bad "the page does not name the attempt, so the founder retypes a command that already failed"
echo "$OUT" | grep -q 'PAGE.*did not apply' \
  && ok "the page carries git's own reason for the failure" \
  || bad "the page does not say WHY the automatic fix failed"

echo
echo "== 6. the page is deduped per remote sha (codex round 2, major 2) =="
# At a 900s interval an unrepaired checkout paged 96 times a day with the
# identical message, which trains the founder to ignore the channel.
STATE="$WORK/pagestate"; mkdir -p "$STATE"
# Point the function's state dir at a scratch dir by overriding $LOG, which is
# what the marker path is derived from.
run_dedupe() { ( cd "$1" && LOG="$STATE/dispatch.log" bash "$HARNESS" 2>&1 ); }
P1="$(run_dedupe "$DIV" | grep -c '^PAGE ' || true)"
P2="$(run_dedupe "$DIV" | grep -c '^PAGE ' || true)"
if [ "${P1:-0}" -ge 1 ] && [ "${P2:-0}" -eq 0 ]; then
  ok "pages once for a given origin/main sha, silent on the repeat ($P1 then $P2)"
else
  bad "THE DEFECT: paged $P1 then $P2 for the same remote sha -- 96 identical pages a day"
fi
# A NEW divergence must page again, or a second, different staleness goes unreported.
advance_origin remote-two
P3="$(run_dedupe "$DIV" | grep -c '^PAGE ' || true)"
if [ "${P3:-0}" -ge 1 ]; then
  ok "a NEW origin/main sha pages again (dedupe is per-sha, not permanent)"
else
  bad "dedupe is permanent: a second, different divergence would never be reported"
fi
# The refusal itself must still be logged every time, even when the page is muted.
# CAPTURED FIRST, NOT PIPED. `run_dedupe | grep -q` fails here for a reason that has
# nothing to do with the code under test: grep -q exits on the first match, the
# subshell writing to the closed pipe takes SIGPIPE (141), and `set -o pipefail`
# then reports 141 for the whole pipeline. The assertion inverts and blames the
# dispatcher for a bug in the assertion. Caught by this line failing green code.
DEDUPED_OUT="$(run_dedupe "$DIV")"
echo "$DEDUPED_OUT" | grep -q 'SAY REFUSING' \
  && ok "the refusal is logged on every heartbeat even when the page is deduped" \
  || bad "a deduped page also silenced the log line, so the refusal is invisible"

echo
echo "== 7. a FAILED page must not create the dedupe marker (codex round 4, major 2) =="
# Writing the marker for a page that never went out permanently silences the
# founder about a refusing loop. A storm is annoying; silence is invisible, and
# strictly worse than the bug the dedupe was added to fix.
STATE2="$WORK/pagefail"; mkdir -p "$STATE2"
run_failing() { ( cd "$1" && KIPI_TEST_PAGE_FAILS=1 LOG="$STATE2/dispatch.log" bash "$HARNESS" 2>&1 ); }
run_ok2()     { ( cd "$1" && LOG="$STATE2/dispatch.log" bash "$HARNESS" 2>&1 ); }
F1="$(run_failing "$DIV" | grep -c '^PAGE ' || true)"
# Now let the notifier succeed. If the failed attempt wrote a marker, this is muted.
F2="$(run_ok2 "$DIV" | grep -c '^PAGE ' || true)"
if [ "${F1:-0}" -ge 1 ] && [ "${F2:-0}" -ge 1 ]; then
  ok "a failed page leaves the marker unset, so the next heartbeat retries it ($F1 then $F2)"
else
  bad "THE DEFECT: failed page still deduped -- founder goes permanently silent ($F1 then $F2)"
fi
# FRESH state dir. The successful page above wrote a marker, so re-running against
# the same dir skips the whole block and emits nothing -- which is correct
# behaviour and a broken assertion. Caught by this case failing on its first run.
STATE3="$WORK/pagefail-log"; mkdir -p "$STATE3"
LOGLINE="$( cd "$DIV" && KIPI_TEST_PAGE_FAILS=1 LOG="$STATE3/dispatch.log" bash "$HARNESS" 2>&1 )"
echo "$LOGLINE" | grep -q 'did NOT go out' \
  && ok "the undelivered page is logged" \
  || bad "an undelivered page is not logged, so the silence has no trace"

echo
echo "== 8. a NON-MAIN branch is never fast-forwarded (parallel-sessions scar) =="
# Two sessions sharing one checkout yank each other's tree on a branch move. The
# remedy the detector computed is for main; applying it to somebody's feature
# branch is not that remedy.
C8="$(fresh_clone c-branch)"
( cd "$C8"; git checkout -qb sana/some-work ) >/dev/null 2>&1
advance_origin branch-case
B8="$(head_of "$C8")"
OUT="$(run_check "$C8")"
[ "$(head_of "$C8")" = "$B8" ] \
  && ok "the feature branch was left where it was" \
  || bad "THE DEFECT: it moved a non-main branch onto origin/main under a live session"
echo "$OUT" | grep -q 'VERDICT=REFUSE' \
  && ok "it refuses rather than dispatching on a stale feature branch" \
  || bad "it dispatched from a stale non-main branch"
echo "$OUT" | grep -q 'PAGE.*sana/some-work' \
  && ok "the page names the branch it declined to touch" \
  || bad "the page does not say which branch blocked the fix"

echo
echo "== 9. a DETACHED HEAD is never fast-forwarded =="
C9="$(fresh_clone c-detached)"
( cd "$C9"; git checkout -q --detach HEAD ) >/dev/null 2>&1
advance_origin detached-case
B9="$(head_of "$C9")"
OUT="$(run_check "$C9")"
[ "$(head_of "$C9")" = "$B9" ] \
  && ok "the detached checkout was left where it was" \
  || bad "THE DEFECT: it moved a detached HEAD"
echo "$OUT" | grep -q 'PAGE.*detached HEAD' \
  && ok "the page names the detached HEAD as the blocker" \
  || bad "the page does not explain that a detached HEAD blocked the fix"

echo
echo "== 10. a STAGED index is never fast-forwarded (someone is composing a commit) =="
C10="$(fresh_clone c-staged)"
( cd "$C10"; echo staged >> other.txt; git add other.txt ) >/dev/null 2>&1
advance_origin staged-case
B10="$(head_of "$C10")"
OUT="$(run_check "$C10")"
[ "$(head_of "$C10")" = "$B10" ] \
  && ok "the tree with a staged commit was left alone" \
  || bad "THE DEFECT: it fast-forwarded over someone's staged hunks"
echo "$OUT" | grep -q 'PAGE.*staged changes' \
  && ok "the page names the staged index as the blocker" \
  || bad "the page does not explain that a staged index blocked the fix"

echo
echo "== 11. a merge in progress is never fast-forwarded =="
C11="$(fresh_clone c-midmerge)"
# Fabricate the marker rather than orchestrating a real conflict: the guard reads
# the marker, so the marker IS the condition under test.
( cd "$C11"; git rev-parse HEAD > "$(git rev-parse --git-path MERGE_HEAD)" ) >/dev/null 2>&1
advance_origin midmerge-case
B11="$(head_of "$C11")"
OUT="$(run_check "$C11")"
[ "$(head_of "$C11")" = "$B11" ] \
  && ok "the mid-merge tree was left alone" \
  || bad "THE DEFECT: it moved HEAD out from under an in-progress merge"
echo "$OUT" | grep -q 'PAGE.*in progress' \
  && ok "the page names the in-progress operation" \
  || bad "the page does not explain that a mid-merge tree blocked the fix"

echo
echo "== 12. git's own overwrite check is respected: a modified file the merge touches =="
# The ff would clobber an uncommitted edit. git refuses; we must surface that
# rather than force it.
C12="$(fresh_clone c-conflict)"
advance_origin conflict-case
( cd "$C12"; echo "uncommitted local edit" >> f.txt ) >/dev/null 2>&1
B12="$(head_of "$C12")"
OUT="$(run_check "$C12")"
[ "$(head_of "$C12")" = "$B12" ] \
  && ok "the tree was not moved when the ff would overwrite a local edit" \
  || bad "THE DEFECT: it discarded an uncommitted edit to fast-forward"
grep -q "uncommitted local edit" "$C12/f.txt" \
  && ok "the founder's uncommitted edit survived" \
  || bad "THE DEFECT: the local edit is gone"
echo "$OUT" | grep -q 'VERDICT=REFUSE' \
  && ok "it refuses and hands this one to a human" \
  || bad "it dispatched despite being stale and unable to heal"

echo
echo "== 13. NOT INERT ON A DIRTY TREE: unrelated modified files still heal =="
# The founder's real checkout carries 3 modified tracked files and ~5.5k untracked
# ones as its RESTING state. A blanket dirty-tree refusal would make this whole
# feature never fire on the one checkout it exists for. So the arbiter is git's
# per-file answer, not a whole-tree guess. This case is what keeps that honest.
C13="$(fresh_clone c-dirty-unrelated)"
advance_origin dirty-case
( cd "$C13"; echo "unrelated founder edit" >> other.txt ) >/dev/null 2>&1
mkdir -p "$C13/untracked-junk"; echo junk > "$C13/untracked-junk/x"
OUT="$(run_check "$C13")"
R13="$(git -C "$C13" rev-parse origin/main)"
[ "$(head_of "$C13")" = "$R13" ] \
  && ok "a tree dirty in UNRELATED files still fast-forwards (the feature is not inert in production)" \
  || bad "THE DEFECT: dirty-but-unrelated blocked the fix, so this never fires on the founder's real checkout"
grep -q "unrelated founder edit" "$C13/other.txt" \
  && ok "the unrelated local edit was carried forward, not discarded" \
  || bad "THE DEFECT: the ff discarded an unrelated local edit"
echo "$OUT" | grep -q '^PAGE ' \
  && bad "it paged for a case it healed" \
  || ok "no page for a healed dirty tree"

echo
echo "== 14. one heal per launch: a re-exec that is STILL behind pages instead of spinning =="
C14="$(fresh_clone c-respin)"
advance_origin respin-case
OUT="$( cd "$C14" && KIPI_DISPATCH_SELFHEALED=1 bash "$HARNESS" 2>&1 )"
echo "$OUT" | grep -q 'VERDICT=REFUSE' \
  && ok "a second staleness in the same launch refuses instead of re-execing again" \
  || bad "THE DEFECT: it would exec itself repeatedly while origin/main keeps moving"
echo "$OUT" | grep -q 'RELAUNCH' \
  && bad "THE DEFECT: it re-execed a second time in one launch" \
  || ok "no second re-exec"

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: stale_check fixes what it can fast-forward, refuses and pages only what needs a human"
