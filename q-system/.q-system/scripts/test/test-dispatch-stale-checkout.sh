#!/usr/bin/env bash
# Reproducer for sp-c775b116: the dispatcher ran the founder's working tree with
# no freshness check, so a merge alone never reached the running loop.
#
# And for ASK-283: the check WORKED and then paged about it repeatedly. Measured
# from ~/.config/kipi/dispatch.log on 2026-08-01 -- 19 refusing cycles, 9 Slack
# pages, gap growing 7 -> 10 commits, zero automated action. The 9 came from a
# dedupe keyed on the REMOTE SHA, so every new commit on main counted as a fresh
# fault. The fault is one unchanged thing: this checkout is behind and cannot
# dispatch. One episode, one page.
#
# WHY THERE IS NO AUTO-MERGE HERE. One was built and removed the same night after
# three review rounds each found a new way for it to lose data (ASK-284 owns the
# redesign). The measurement that killed it, reproduced in a scratch repo:
#   untracked + NOT ignored, upstream starts tracking the path
#     -> "would be overwritten by merge ... Aborting", exit 1, file intact.
#   IGNORED, upstream starts tracking the same path
#     -> "Fast-forward ... create mode", exit 0, LOCAL CONTENT GONE, no reflog.
# `git ls-files --others --exclude-standard` cannot see the second class at all,
# which is why the 5488 that made it look safe was the wrong number; the ignored
# count on that checkout is 3982.
#
# The states that matter, and only SOME may refuse:
#   behind   -> REFUSE + page once per episode
#   diverged -> REFUSE (origin/main holds commits this tree lacks)
#   ahead    -> RUN (an agent commits locally before opening a PR)
#   equal    -> RUN, and clear the page state so the next episode is heard at once
#   no answer (fetch fails / offline) -> RUN. Fail closed on staleness, fail open
#             on not knowing. Offline is NOT proof of recovery, so it clears nothing.
set -uo pipefail

# The founder was paged by tests three times on 2026-08-01. The harness stubs the
# notifier outright; this is the second belt for anything that shells the real script.
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
for fn in stale_check page_once page_clear; do
  grep -q "^$fn() {" "$DISPATCH" || {
    echo "  FAIL: THE DEFECT: kipi-dispatch.sh has no $fn"
    echo "-------- 0 passed, 1 failed --------"; exit 1; }
done

# Extract the REAL functions and drive them directly. Running the whole dispatcher
# would reach Linear and could dispatch REAL work -- never let a test touch a live
# data path (fable-discipline lint blocks it, and this is why). page_once and
# page_clear are the code under test, so only the notifier itself is stubbed.
HARNESS="$WORK/stale_check.sh"
{
  echo 'set -uo pipefail'
  echo 'REPO="$PWD"'
  # say() goes to STDERR, matching production where it appends to $LOG. On stdout it
  # would be swallowed by any command substitution around the code under test.
  echo 'say()  { printf "SAY %s\n"  "$*" >&2; }'
  # KIPI_TEST_PAGE_FAILS=1 makes delivery fail, so "a failed page must not dedupe"
  # can be reproduced at all.
  echo 'page_ok() { printf "PAGE %s\n" "$1"; [ "${KIPI_TEST_PAGE_FAILS:-0}" = "1" ] && return 1; return 0; }'
  echo 'PAGE_REPING_SECONDS="${KIPI_PAGE_REPING_SECONDS:-86400}"'
  # The self-heal handler (ASK-294). $REPO is the fixture clone in here, so the
  # production $REPO-relative path resolves to a file that does not exist and the
  # handler is silently INERT -- which is how it first shipped, with every case
  # below still green because a missing script reads as "declined to merge".
  echo "FF_MERGE=\"$(cd "$(dirname "$DISPATCH")" && pwd)/q-system/.q-system/scripts/ff-merge-if-safe.sh\""
  awk '/^page_lock\(\) \{/,/^\}/'   "$DISPATCH"
  awk '/^page_clear\(\) \{/,/^\}/'  "$DISPATCH"
  awk '/^page_once\(\) \{/,/^\}/'   "$DISPATCH"
  awk '/^stale_check\(\) \{/,/^\}/' "$DISPATCH"
  echo 'stale_check && echo "VERDICT=RUN" || echo "VERDICT=REFUSE"'
} > "$HARNESS"
# Guard the extraction. An awk range that silently matched nothing would make every
# case below pass against an empty function.
for fn in page_lock page_clear page_once stale_check; do
  grep -q "^$fn() {" "$HARNESS" || { echo "harness did not extract $fn"; exit 1; }
done

ORIGIN="$WORK/origin.git"
git init -q --bare -b main "$ORIGIN"
git init -q -b main "$WORK/seed"
( cd "$WORK/seed"
  git config user.email t@e.com; git config user.name t
  echo one > f.txt; git add -A; git commit -qm one
  git remote add origin "$ORIGIN"; git push -q origin main ) >/dev/null 2>&1

advance_origin() { ( cd "$WORK/seed"; echo "$1" >> f.txt; git commit -qam "$1"; git push -q origin main ) >/dev/null 2>&1; }
fresh_clone() {
  local d="$WORK/$1"
  git clone -q "$ORIGIN" "$d" >/dev/null 2>&1
  ( cd "$d"; git config user.email t@e.com; git config user.name t )
  echo "$d"
}
# A clone that is behind AND CANNOT be brought current unattended, so it still
# pages. Cases 6, 7 and 9 test page_once mechanics -- dedupe, clear-on-recovery,
# failed-delivery -- which say nothing about WHY the loop refused. Before ASK-294
# a plain behind-clone was enough to make it page; now that shape self-heals and
# is silent, so those cases would have been asserting against zero pages and
# passing for the wrong reason once someone "fixed" them. The collision is on a
# path origin ADDS, so recovery is just moving the local file aside.
advance_origin_add() {
  ( cd "$WORK/seed"; echo blocked > "$1"; git add "$1"; git commit -qm "add $1"; git push -q origin main ) >/dev/null 2>&1
}
# THE BLOCKER PATH IS UNIQUE PER FIXTURE. With one shared name the second caller
# cloned an origin that ALREADY tracked blocker.txt, so the local file was tracked
# (no collision at all), the re-add was an empty commit (origin never moved), and
# cases 7 and 9 measured zero pages against a checkout that was not even stale --
# green for a reason that had nothing to do with what they assert.
pageable_clone() {
  local d; d="$(fresh_clone "$1")"
  printf 'local untracked work\n' > "$d/blocker-$1.txt"
  advance_origin_add "blocker-$1.txt"
  echo "$d"
}
# LOG is set even though say() is stubbed: page_once derives its marker dir from
# $(dirname "$LOG"), so an unset LOG trips `set -u` inside the code under test.
CHECKSTATE="$WORK/checkstate"; mkdir -p "$CHECKSTATE"
run_check() { ( cd "$1" && LOG="${2:-$CHECKSTATE}/dispatch.log" bash "$HARNESS" 2>&1 ); }

echo "== 1. equal: HEAD == origin/main -> RUN =="
C1="$(fresh_clone c-equal)"
OUT="$(run_check "$C1")"
echo "$OUT" | grep -q 'VERDICT=RUN' \
  && ok "an up-to-date checkout runs" \
  || bad "an up-to-date checkout was refused: $(echo "$OUT" | tr '\n' ' ')"

echo
# CONTRACT CHANGED DELIBERATELY, 2026-08-02, ASK-294. This case used to assert
# that a behind-but-clean checkout REFUSES, leaves the tree untouched, and pages
# the founder a `git merge --ff-only` command to type. That page fired 15 times in
# one measured 24h window; he asked twice why he keeps getting messages he cannot
# act on, then: "I just want the underlying issues to be dealt with so I don't get
# a message."
#
# The guard that stood here ("the guard must not grow hands") encoded ASK-284's
# finding that an automatic ff-merge loses data. That finding STANDS and is not
# being waved away -- it is answered. ASK-284's three rounds each tried to make an
# UNBOUNDED write safe. ff-merge-if-safe.sh does not attempt that: it merges only
# after proving the fast-forward cannot clobber anything over the EXACT finite set
# of paths it writes, and declines otherwise. The scar's protection now lives in
# test-ff-merge-if-safe.sh, case 4, which holds the specific thing that killed the
# last attempt -- a fast-forward silently overwriting a GITIGNORED file, exit 0,
# no reflog. Removing a guard is only honest if you can name what replaced it.
echo "== 2. behind + clean -> the loop merges it ITSELF and stays silent =="
C2="$(fresh_clone c-behind)"
B2="$(git -C "$C2" rev-parse HEAD)"
advance_origin two
S2="$WORK/s2"; mkdir -p "$S2"
OUT="$(run_check "$C2" "$S2")"
echo "$OUT" | grep -q 'VERDICT=RUN' \
  && ok "a behind-but-clean checkout is brought current and dispatches" \
  || bad "THE DEFECT: still refusing work the loop could unblock itself: $(echo "$OUT" | tr '\n' ' ')"
[ "$(git -C "$C2" rev-parse HEAD)" != "$B2" ] \
  && [ "$(git -C "$C2" rev-parse HEAD)" = "$(git -C "$C2" rev-parse origin/main)" ] \
  && ok "the checkout ACTUALLY advanced to origin/main" \
  || bad "THE DEFECT: reported RUN without merging (HEAD still $B2)"
echo "$OUT" | grep -q '^PAGE ' \
  && bad "THE DEFECT: paged the founder about something it handled itself" \
  || ok "no page: the condition was handled, so there is nothing to tell him"

echo
echo "== 2b. behind + a path the merge would clobber -> REFUSE and page =="
# The half that must STILL reach him. A file git is not tracking, sitting where
# the merge wants to write, is data only he can adjudicate. A gate that silences
# this is a worse outage than the noise it was built to stop.
C2B="$(fresh_clone c-collide)"
advance_origin threeee
( cd "$C2B" && git rm -q --cached f.txt && git commit -qm untrack ) >/dev/null 2>&1
printf 'LOCAL WORK GIT CANNOT SEE\n' > "$C2B/f.txt"
S2B="$WORK/s2b"; mkdir -p "$S2B"
OUT2B="$(run_check "$C2B" "$S2B")"
echo "$OUT2B" | grep -q 'VERDICT=REFUSE' \
  && ok "a checkout with a clobberable path refuses to dispatch" \
  || bad "THE DEFECT: merged over a path git is not tracking: $(echo "$OUT2B" | tr '\n' ' ')"
echo "$OUT2B" | grep -q '^PAGE ' \
  && ok "that refusal DOES page: it is a real founder decision" \
  || bad "refused silently: an unattended refusal nobody is told about is a dead loop"
grep -q 'LOCAL WORK GIT CANNOT SEE' "$C2B/f.txt" \
  && ok "the at-risk file is untouched" \
  || bad "THE DEFECT: the at-risk file was overwritten"

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
BROKEN="$WORK/broken"
git init -q -b main "$BROKEN"
( cd "$BROKEN"; git config user.email t@e.com; git config user.name t
  echo x > f.txt; git add -A; git commit -qm x
  git remote add origin "$WORK/does-not-exist.git" ) >/dev/null 2>&1
OUT="$(run_check "$BROKEN")"
echo "$OUT" | grep -q 'VERDICT=RUN' \
  && ok "an unanswerable freshness check proceeds instead of wedging" \
  || bad "a failed fetch refused to dispatch, so an offline machine kills the loop"
echo "$OUT" | grep -q 'SAY stale-check' \
  && ok "the unanswered check is logged, not silent" \
  || bad "the check failed with no log line, so the blind spot is invisible"

echo
echo "== 5. DIVERGED must REFUSE (codex round 2, major 1) =="
# The case a merge of this very branch produces: origin/main gains a commit while
# this tree keeps local commits. --is-ancestor is FALSE here, so an ancestry test
# would run on a checkout missing origin/main's newest control code.
DIV="$(fresh_clone c-diverged)"
( cd "$DIV"; echo local-only >> f.txt; git commit -qam "local only" ) >/dev/null 2>&1
advance_origin remote-only
DB="$(git -C "$DIV" rev-parse HEAD)"
S5="$WORK/s5"; mkdir -p "$S5"
OUT="$(run_check "$DIV" "$S5")"
echo "$OUT" | grep -q 'VERDICT=REFUSE' \
  && ok "a DIVERGED checkout refuses" \
  || bad "THE DEFECT: a diverged checkout dispatched after a concurrent merge"
[ "$(git -C "$DIV" rev-parse HEAD)" = "$DB" ] \
  && ok "the diverged tree was not moved" \
  || bad "THE DEFECT: it rewrote a diverged tree"

echo
echo "== 6. THE ASK-283 REGRESSION: one page per EPISODE, not one per commit =="
# The measured complaint. A per-sha key sent 9 pages for one unchanged problem
# because main kept moving. Four heartbeats across four different remote shas must
# produce exactly ONE page.
C6="$(pageable_clone c-episode)"
S6="$WORK/s6"; mkdir -p "$S6"
advance_origin ep-1
P_TOTAL=0
for extra in ep-2 ep-3 ep-4; do
  N="$(run_check "$C6" "$S6" | grep -c '^PAGE ' || true)"
  P_TOTAL=$(( P_TOTAL + N ))
  advance_origin "$extra"
done
N="$(run_check "$C6" "$S6" | grep -c '^PAGE ' || true)"
P_TOTAL=$(( P_TOTAL + N ))
if [ "$P_TOTAL" -eq 1 ]; then
  ok "four heartbeats across four different origin/main shas sent 1 page, not 4"
else
  bad "THE DEFECT (ASK-283): $P_TOTAL pages for one unchanged problem -- this is the 9-a-night shape"
fi
# The refusal must still be logged every cycle even while the page is muted.
# CAPTURED, NOT PIPED. `run_check | grep -q` fails for a reason unrelated to the
# code: grep -q exits on first match, the writing subshell takes SIGPIPE (141), and
# `set -o pipefail` reports 141 for the pipeline. The assertion then inverts and
# blames the dispatcher. Written twice in this file's history; hence this note.
MUTED_OUT="$(run_check "$C6" "$S6")"
echo "$MUTED_OUT" | grep -q 'SAY STALE' \
  && ok "the refusal is logged on every heartbeat even when the page is deduped" \
  || bad "a deduped page also silenced the log line, so the refusal is invisible"

echo
echo "== 7. recovery clears the page state, so the NEXT episode is heard at once =="
C7="$(pageable_clone c-recover)"
S7="$WORK/s7"; mkdir -p "$S7"
advance_origin rec-1
R1="$(run_check "$C7" "$S7" | grep -c '^PAGE ' || true)"
R2="$(run_check "$C7" "$S7" | grep -c '^PAGE ' || true)"          # unchanged -> muted
( cd "$C7"; mv blocker-c-recover.txt blocker.kept; git merge -q --ff-only origin/main ) >/dev/null 2>&1  # a human fixes it
RCLR="$(run_check "$C7" "$S7" 2>&1)"                              # healthy -> clears
# The NEW episode has to be a PAGEABLE one. A plain `advance_origin` now leaves the
# clone behind-but-clean, which self-heals silently -- so this case would read 1/0/0
# and blame page_clear for a mute that never happened.
printf 'more local untracked work\n' > "$C7/blocker2-c-recover.txt"
advance_origin_add blocker2-c-recover.txt                         # a NEW episode
R3="$(run_check "$C7" "$S7" | grep -c '^PAGE ' || true)"
if [ "${R1:-0}" -eq 1 ] && [ "${R2:-0}" -eq 0 ] && [ "${R3:-0}" -eq 1 ]; then
  ok "pages, mutes the repeat, and pages again on a new episode ($R1/$R2/$R3)"
else
  bad "THE DEFECT: page state survived recovery ($R1/$R2/$R3) -- the next outage is swallowed"
fi
echo "$RCLR" | grep -q 'SAY page state cleared' \
  && ok "the recovery is logged" \
  || bad "recovery cleared state with no trace"

echo
echo "== 8. offline is NOT recovery: an unanswerable check must clear nothing =="
# Clearing on a failed fetch would re-page a still-broken checkout every cycle the
# network flapped, which is the storm this whole change exists to stop.
C8="$(fresh_clone c-offline)"
S8="$WORK/s8"; mkdir -p "$S8"
advance_origin off-1
run_check "$C8" "$S8" >/dev/null 2>&1                        # page + marker
git -C "$C8" remote set-url origin "$WORK/gone.git"          # now unreachable
run_check "$C8" "$S8" >/dev/null 2>&1                        # no answer
git -C "$C8" remote set-url origin "$ORIGIN"                 # back online, still behind
N8="$(run_check "$C8" "$S8" | grep -c '^PAGE ' || true)"
[ "${N8:-0}" -eq 0 ] \
  && ok "a network blip did not reset the dedupe (still muted)" \
  || bad "THE DEFECT: an offline cycle cleared the marker, so a flapping network re-pages forever"

echo
echo "== 9. a FAILED page must not create the dedupe marker (codex round 4, major 2) =="
# Writing the marker for a page that never went out permanently silences the founder
# about a refusing loop. A storm is annoying; silence is invisible, and worse.
C9="$(pageable_clone c-pagefail)"
S9="$WORK/s9"; mkdir -p "$S9"
advance_origin pf-1
F1="$( cd "$C9" && KIPI_TEST_PAGE_FAILS=1 LOG="$S9/dispatch.log" bash "$HARNESS" 2>/dev/null | grep -c '^PAGE ' || true )"
F2="$( cd "$C9" && LOG="$S9/dispatch.log" bash "$HARNESS" 2>/dev/null | grep -c '^PAGE ' || true )"
if [ "${F1:-0}" -ge 1 ] && [ "${F2:-0}" -ge 1 ]; then
  ok "a failed page leaves the marker unset, so the next heartbeat retries it ($F1 then $F2)"
else
  bad "THE DEFECT: failed page still deduped -- founder goes permanently silent ($F1 then $F2)"
fi
S9B="$WORK/s9b"; mkdir -p "$S9B"
( cd "$C9" && KIPI_TEST_PAGE_FAILS=1 LOG="$S9B/dispatch.log" bash "$HARNESS" 2>&1 >/dev/null ) | grep -q 'did NOT go out' \
  && ok "the undelivered page is logged" \
  || bad "an undelivered page is not logged, so the silence has no trace"

echo
echo "== 10. MAJOR: an ORPHANED page lock must age out, not mute the key forever =="
# A notifier killed between the mkdir and its cleanup (launchd reaping the job, a
# reboot, SIGKILL) left a lock dir behind. Reproduced before the fix: the next three
# runs paged 0, 0, 0 while the log reported "another dispatcher is already deciding
# it" with nobody there. This was introduced BY the lock added to fix duplicate
# pages -- a guard that can never fire, born from the fix for the previous one.
PL="$WORK/plock"; mkdir -p "$PL"
PH="$WORK/prim.sh"
{
  echo 'set -uo pipefail'
  echo 'say() { printf "SAY %s\n" "$*" >&2; }'
  echo 'page_ok() { printf "PAGE %s\n" "$1"; return 0; }'
  echo 'PAGE_REPING_SECONDS=86400'
  awk '/^page_lock\(\) \{/,/^\}/'  "$DISPATCH"
  awk '/^page_clear\(\) \{/,/^\}/' "$DISPATCH"
  awk '/^page_once\(\) \{/,/^\}/'  "$DISPATCH"
  echo 'page_once "$@"'
} > "$PH"
grep -q '^page_lock() {' "$PH" && grep -q '^page_once() {' "$PH" || { echo "primitive harness did not extract page_once"; exit 1; }
# A FRESH lock is respected (the duplicate-page fix must still hold).
mkdir -p "$PL/paged-korph.lock"
FRESH="$( LOG="$PL/dispatch.log" bash "$PH" korph "real fault" 2>/dev/null | grep -c '^PAGE ' || true )"
[ "${FRESH:-0}" -eq 0 ] \
  && ok "a FRESH lock is respected, so concurrent dispatchers still do not duplicate" \
  || bad "the lock is ignored outright, which reintroduces duplicate pages"
# An OLD lock is reaped. Backdate it well past the 300s bound.
touch -t 202501010000 "$PL/paged-korph.lock" 2>/dev/null
AGED="$( LOG="$PL/dispatch.log" bash "$PH" korph "real fault" 2>/dev/null | grep -c '^PAGE ' || true )"
[ "${AGED:-0}" -ge 1 ] \
  && ok "an ORPHANED lock is reaped and the alert gets through ($AGED page)" \
  || bad "THE DEFECT: an orphaned lock mutes this key forever -- a dedupe that became a permanent silence"

echo
echo "== 11. concurrent page_once must not duplicate the same alert =="
PC="$WORK/pconc"; mkdir -p "$PC"
( LOG="$PC/dispatch.log" bash "$PH" kconc "same line" 2>/dev/null > "$WORK/c1.out" ) &
( LOG="$PC/dispatch.log" bash "$PH" kconc "same line" 2>/dev/null > "$WORK/c2.out" ) &
wait
TOTAL=$(( $(grep -c '^PAGE ' "$WORK/c1.out" || true) + $(grep -c '^PAGE ' "$WORK/c2.out" || true) ))
[ "$TOTAL" -le 1 ] \
  && ok "two dispatchers deciding the same key produced $TOTAL page(s), not 2" \
  || bad "THE DEFECT: unlocked marker check let concurrent dispatchers send $TOTAL duplicate pages"

echo
echo "== 12. the Linear outage guard vs the PRODUCER'S REAL OUTPUT =="
# FIXTURES COME FROM PRODUCERS. The previous pattern was
# (infra_error|authentication|unauthorized) and matched NONE of the loop-stopping
# lines linear-worker.sh actually prints, so a real outage fell through to
# page_clear and ERASED the state that would have paged. Silence dressed as health.
#
# Every string below is copied from linear-worker.sh, not invented, and case 13
# re-derives them from the file so this cannot drift.
GUARD="$WORK/guard.sh"
{
  echo 'set -uo pipefail'
  echo 'say() { printf "SAY %s\n" "$*" >&2; }'
  echo 'page_once() { printf "PAGE %s\n" "$1"; }'
  echo 'page_clear() { printf "CLEAR %s\n" "$1"; }'
  echo 'WORK_OUT="$1"'
  # Sliced on STABLE marker comments, never on the matcher line itself. Anchoring
  # the range to the text under test meant a mutant that reworded the matcher made
  # the range match nothing: the harness bailed rather than asserting, and two
  # mutants restoring the round-3 defect were scored SURVIVED. Caught by mutation,
  # not review.
  awk '/^# --- LINEAR-OUTAGE-GUARD:BEGIN ---$/,/^# --- LINEAR-OUTAGE-GUARD:END ---$/' "$DISPATCH"
} > "$GUARD"
grep -q 'page_clear linear-down' "$GUARD" \
  || bad "the outage guard block is missing its BEGIN/END markers or its page_clear"
guard() { bash "$GUARD" "$1" 2>&1; }

# The exact line linear-worker.sh:417 emits, and the one that was missed.
G="$(guard 'INFRA: linear unreachable (HTTPSConnectionPool: Max retries exceeded). Not counted against any issue.')"
echo "$G" | grep -q '^PAGE linear-down' \
  && ok "a real 'INFRA: linear unreachable' outage PAGES" \
  || bad "THE DEFECT: the producer's real outage line does not match the guard"
echo "$G" | grep -q '^CLEAR ' \
  && bad "THE DEFECT: a live outage also CLEARED the outage state -- silence dressed as health" \
  || ok "a live outage does not clear the state that would page later"

# linear-worker.sh:251 -- stops the run BEFORE Linear, and self-pages. Must not
# double-page, and must not clear (a run that never reached Linear proves nothing).
G="$(guard 'INFRA: git fetch failed in /Users/x/repo. Stopping before any worktree is cut from a stale base.')"
echo "$G" | grep -q '^PAGE ' \
  && bad "double-paged: linear-worker.sh:251 already notifies the founder itself" \
  || ok "a pre-Linear environment failure does not double-page"
echo "$G" | grep -q '^CLEAR ' \
  && bad "THE DEFECT: a run that never reached Linear cleared the outage state" \
  || ok "a run that never reached Linear does not count as recovery"

# linear-worker.sh:989 / :1049 -- these print INFRA: and then `continue`. The worker
# is still working, so paging "the loop is stopped" would be a false alarm. This is
# why the matcher is not a bare `INFRA:` prefix.
for line in 'INFRA: could not create worktree for ASK-1 (not counted against the issue)' \
            'INFRA: claim failed rc=1 on ASK-1 (not counted against the issue)'; do
  G="$(guard "$line")"
  echo "$G" | grep -q '^PAGE ' \
    && bad "false alarm: '${line:0:34}...' does not stop the worker but paged an outage" \
    || ok "a non-stopping INFRA line does not page an outage (${line:0:28}...)"
done

# A healthy run must still clear.
G="$(guard '3 ready issues; dispatching ASK-9')"
echo "$G" | grep -q '^CLEAR linear-down' \
  && ok "a healthy run clears the outage state" \
  || bad "a healthy run no longer clears, so the outage page is stuck on"

echo
echo "== 13. the guard's strings still exist in linear-worker.sh (anti-drift) =="
# A fixture copied from a producer rots when the producer is reworded. This
# re-derives the claim from the file itself, so a rename breaks the test instead of
# silently restoring the round-3 defect.
WORKER="$REPO/q-system/.q-system/scripts/linear-worker.sh"
if [ -f "$WORKER" ]; then
  grep -q 'INFRA: linear unreachable' "$WORKER" \
    && ok "linear-worker.sh still prints 'INFRA: linear unreachable'" \
    || bad "the producer was reworded: the outage guard now matches nothing again"
  grep -q 'INFRA: git fetch failed' "$WORKER" \
    && ok "linear-worker.sh still prints 'INFRA: git fetch failed'" \
    || bad "the producer was reworded: the pre-Linear guard now matches nothing"
  # say() must reach stdout, or none of this text ever arrives in WORK_OUT.
  grep -qE '^say\(\).*tee' "$WORKER" \
    && ok "the worker's say() still tees to stdout, so the dispatcher can see it" \
    || bad "the worker's say() no longer writes to stdout -- WORK_OUT gets nothing to match"
else
  ok "linear-worker.sh not present in this checkout; producer anti-drift skipped"
fi

echo
echo "== 14. MINOR: a clear cannot interleave with an in-flight page decision =="
# page_clear used to run while page_once was mid-decision: the clear found no
# marker, page_once wrote one a moment later, and that marker then described an
# already-recovered condition -- muting the next real episode for up to 24h.
PR="$WORK/prace"; mkdir -p "$PR"
# Simulate page_once holding the lock (a slow notifier) by taking the lock by hand.
mkdir -p "$PR/paged-krace.lock"
printf 'oldhash\n1\n' > "$PR/paged-krace"
CL="$( LOG="$PR/dispatch.log" bash -c '
  set -uo pipefail
  say() { printf "SAY %s\n" "$*" >&2; }
  '"$(awk '/^page_lock\(\) \{/,/^\}/' "$DISPATCH")"'
  '"$(awk '/^page_clear\(\) \{/,/^\}/' "$DISPATCH")"'
  page_clear krace' 2>&1 )"
[ -f "$PR/paged-krace" ] \
  && ok "a clear held off while a notifier is mid-decision (no interleave)" \
  || bad "THE DEFECT: page_clear removed a marker while page_once was still deciding"
echo "$CL" | grep -q 'NOT cleared' \
  && ok "the deferred clear is logged, so the <=15m window is visible" \
  || bad "the clear was skipped with no log line"
# Once the holder is gone (orphan aged out), the clear must actually happen.
touch -t 202501010000 "$PR/paged-krace.lock" 2>/dev/null
LOG="$PR/dispatch.log" bash -c '
  set -uo pipefail
  say() { printf "SAY %s\n" "$*" >&2; }
  '"$(awk '/^page_lock\(\) \{/,/^\}/' "$DISPATCH")"'
  '"$(awk '/^page_clear\(\) \{/,/^\}/' "$DISPATCH")"'
  page_clear krace' >/dev/null 2>&1
[ -f "$PR/paged-krace" ] \
  && bad "THE DEFECT: the marker survived an uncontended clear, so recovery never resets" \
  || ok "an uncontended clear removes the marker"

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: stale_check refuses without touching the tree, and pages once per episode"
