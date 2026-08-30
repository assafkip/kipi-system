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
echo "== 2. behind -> REFUSE, and the page carries the remedy =="
C2="$(fresh_clone c-behind)"
B2="$(git -C "$C2" rev-parse HEAD)"
advance_origin two
S2="$WORK/s2"; mkdir -p "$S2"
OUT="$(run_check "$C2" "$S2")"
echo "$OUT" | grep -q 'VERDICT=REFUSE' \
  && ok "a checkout behind origin/main refuses to dispatch" \
  || bad "THE DEFECT: a stale checkout dispatched, running superseded control code"
# THE GUARD MUST NOT GROW HANDS. The auto-merge was removed for losing data; if a
# future edit puts one back, this catches it.
[ "$(git -C "$C2" rev-parse HEAD)" = "$B2" ] \
  && ok "the working tree was NOT touched (no auto-merge; ASK-284 owns that)" \
  || bad "THE DEFECT: something rewrote the founder's working tree"
echo "$OUT" | grep -q '^PAGE ' \
  && ok "the refusal pages the founder" \
  || bad "refused silently: an unattended refusal nobody is told about is a dead loop"
echo "$OUT" | grep -q 'git merge --ff-only' \
  && ok "the page carries the fix command" \
  || bad "the page does not say what to do"

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
C6="$(fresh_clone c-episode)"
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
C7="$(fresh_clone c-recover)"
S7="$WORK/s7"; mkdir -p "$S7"
advance_origin rec-1
R1="$(run_check "$C7" "$S7" | grep -c '^PAGE ' || true)"
R2="$(run_check "$C7" "$S7" | grep -c '^PAGE ' || true)"          # unchanged -> muted
( cd "$C7"; git merge -q --ff-only origin/main ) >/dev/null 2>&1  # a human fixes it
RCLR="$(run_check "$C7" "$S7" 2>&1)"                              # healthy -> clears
advance_origin rec-2                                              # a NEW episode
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
C9="$(fresh_clone c-pagefail)"
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
echo "== 15. ASK-358: a dispatch must not land on a branch no open PR is on =="
# THE DEFECT, measured on ASK-352. That issue has TWO branches: sana/ask-352
# backs PR #90 (CLOSED) and is what the live checkout sits on, while
# sana/ask-352-clean backs PR #91 (OPEN). converge.sh:83 derives the branch it
# works from the issue id alone -- BRANCH="sana/$(lower ISSUE)" -- so a rework
# dispatched for ASK-352 commits onto the CLOSED branch, where no PR and no
# reviewer will ever read it. That is silent-wrong-target, which is worse than a
# stall: the work looks done and is unreachable.
#
# review-redrive.py's candidate dict already carries the selected PR's
# headRefName and drops it before dispatch, so the one fact that would have
# caught this was fetched and thrown away.
#
# Two halves, both driven here: the RESOLVER (review-redrive.py branch-for,
# which answers "what branch is this issue's open PR on") and the GUARD
# (branch_guard in kipi-dispatch.sh, which refuses a mismatch before the attempt
# is claimed). Neither touches a live data path: gh is stubbed via KIPI_GH.
REDRIVE="$REPO/q-system/.q-system/scripts/review-redrive.py"
BG="$WORK/bg"; mkdir -p "$BG"

# A gh stub that answers `pr list` from a fixture file, and can be told to fail.
cat > "$BG/gh" <<'GH'
#!/usr/bin/env bash
if [ "${GH_STUB_FAIL:-0}" = "1" ]; then
  echo "gh: could not resolve to a Repository" >&2; exit 1
fi
for a in "$@"; do [ "$a" = "list" ] && { cat "$GH_STUB_PRS"; exit 0; }; done
exit 0
GH
chmod +x "$BG/gh"
export KIPI_GH="$BG/gh"

# ASK-352 as it actually is: ONE open PR, on the -clean branch. gh pr list is
# already --state open, so the closed PR #90 is simply absent from the answer --
# which is exactly why "the issue's branch" and "the open PR's branch" differ.
cat > "$BG/prs-clean.json" <<'J'
[{"number":91,"headRefName":"sana/ask-352-clean","headRefOid":"aaaa111",
  "url":"u","title":"Rework, clean branch (ASK-352)","statusCheckRollup":[],
  "isDraft":false,"isCrossRepository":false}]
J
# The ordinary shape: the open PR sits on the branch the naming rule produces.
cat > "$BG/prs-match.json" <<'J'
[{"number":92,"headRefName":"sana/ask-352","headRefOid":"bbbb222",
  "url":"u","title":"Ordinary (ASK-352)","statusCheckRollup":[],"isDraft":false,
  "isCrossRepository":false}]
J
# Two live branches for one issue. Picking either is a guess, so refuse.
cat > "$BG/prs-two.json" <<'J'
[{"number":91,"headRefName":"sana/ask-352-clean","headRefOid":"aaaa111",
  "url":"u","title":"Clean (ASK-352)","statusCheckRollup":[],"isDraft":false,
  "isCrossRepository":false},
 {"number":92,"headRefName":"sana/ask-352","headRefOid":"bbbb222",
  "url":"u","title":"Original (ASK-352)","statusCheckRollup":[],"isDraft":false,
  "isCrossRepository":false}]
J
# A different issue's PR only. ASK-352 has no open PR at all.
cat > "$BG/prs-none.json" <<'J'
[{"number":93,"headRefName":"sana/ask-999","headRefOid":"cccc333",
  "url":"u","title":"Elsewhere (ASK-999)","statusCheckRollup":[],"isDraft":false,
  "isCrossRepository":false}]
J
# PR #211 round 1, MAJOR 2. A fork PR is opened by anyone who can read a public
# repo, and BOTH facts attribute() reads are the forker's to choose: the head
# branch name and the PR title. So `sana/evil` + "(ASK-352)" from a fork
# impersonates the agent branch namespace, and the guard downstream then refuses
# the real ASK-352 every cycle until a human closes the external PR.
cat > "$BG/prs-fork.json" <<'J'
[{"number":666,"headRefName":"sana/evil","headRefOid":"dddd444",
  "url":"u","title":"Attacker-controlled title (ASK-352)","statusCheckRollup":[],
  "isDraft":false,"isCrossRepository":true},
 {"number":91,"headRefName":"sana/ask-352-clean","headRefOid":"aaaa111",
  "url":"u","title":"Rework, clean branch (ASK-352)","statusCheckRollup":[],
  "isDraft":false,"isCrossRepository":false}]
J
# The fork ALONE. Nothing trustworthy answers for ASK-352, which is rc 1 (no open
# PR I may believe), not rc 0 printing the forker's branch.
cat > "$BG/prs-fork-only.json" <<'J'
[{"number":666,"headRefName":"sana/evil","headRefOid":"dddd444",
  "url":"u","title":"Attacker-controlled title (ASK-352)","statusCheckRollup":[],
  "isDraft":false,"isCrossRepository":true}]
J
# The field absent entirely. NOT the same claim as "same repo": PR_FIELDS asks for
# it, so a missing value means the board did not tell us where the head lives, and
# an unconfirmed provenance is not a fact to route work on.
cat > "$BG/prs-unstated.json" <<'J'
[{"number":91,"headRefName":"sana/ask-352-clean","headRefOid":"aaaa111",
  "url":"u","title":"No provenance stated (ASK-352)","statusCheckRollup":[],
  "isDraft":false}]
J

bf() { GH_STUB_PRS="$1" python3 "$REDRIVE" --repo-dir "$WORK" branch-for --issue ASK-352 2>"$BG/err"; }

OUT="$(bf "$BG/prs-clean.json")"; RC=$?
[ "$RC" = "0" ] && [ "$OUT" = "sana/ask-352-clean" ] \
  && ok "branch-for reads the OPEN PR's branch (sana/ask-352-clean), not the issue id" \
  || bad "THE DEFECT: branch-for gave rc=$RC out='$OUT'; the open PR's branch is unreachable"

OUT="$(bf "$BG/prs-two.json")"; RC=$?
[ "$RC" = "3" ] \
  && ok "two live branches for one issue is rc 3 (ambiguous), never a guess" \
  || bad "THE DEFECT: two live branches answered rc=$RC out='$OUT' instead of refusing"

OUT="$(bf "$BG/prs-none.json")"; RC=$?
[ "$RC" = "1" ] \
  && ok "no open PR for the issue is rc 1, distinct from an unreadable board" \
  || bad "no-open-PR answered rc=$RC out='$OUT', not rc 1"

OUT="$(GH_STUB_FAIL=1 bf "$BG/prs-clean.json")"; RC=$?
[ "$RC" = "2" ] \
  && ok "gh failing is rc 2 (cannot answer), never read as 'no branch'" \
  || bad "an unreadable board answered rc=$RC, which a caller would read as a fact"

OUT="$(bf "$BG/prs-fork.json")"; RC=$?
[ "$RC" = "0" ] && [ "$OUT" = "sana/ask-352-clean" ] \
  && ok "a fork PR is not a second live branch -- the real one still resolves" \
  || bad "THE DEFECT: a fork made ASK-352 answer rc=$RC out='$OUT'; anyone can park the issue"

OUT="$(bf "$BG/prs-fork-only.json")"; RC=$?
[ "$RC" = "1" ] \
  && ok "a fork alone is rc 1 (nothing trusted answers), never the forker's branch" \
  || bad "THE DEFECT: the forker's branch answered rc=$RC out='$OUT' for someone else's issue"

OUT="$(bf "$BG/prs-unstated.json")"; RC=$?
[ "$RC" = "1" ] \
  && ok "provenance unstated is rc 1 -- absence is not a claim of same-repo" \
  || bad "an unconfirmed head answered rc=$RC out='$OUT', which trusts what was never said"

# --- the guard itself, extracted from the dispatcher and driven directly ------
grep -q "^branch_guard() {" "$DISPATCH" || {
  echo "  FAIL: THE DEFECT: kipi-dispatch.sh has no branch_guard"
  FAIL=$((FAIL+1)); }

if grep -q "^branch_guard() {" "$DISPATCH"; then
  # What the reviewer selector picked, as the dispatcher would have it at the
  # moment the guard runs. Empty is the fresh-pick path, which is what every
  # pre-existing case below drives.
  G_ACTION=""; G_BRANCH=""
  # And what the RED-CI selector picked (ASK-358 round 3, MAJOR 2). Same shape,
  # earlier lane: ci-redrive runs first and, when it offers, the reviewer lane is
  # skipped entirely. Empty is the fresh-pick path.
  G_REDRIVE=""; G_REDRIVE_BRANCH=""
  guard() {
    : > "$BG/pages"
    GH_STUB_PRS="$1" GH_STUB_FAIL="${2:-0}" \
    G_REDRIVE="$G_REDRIVE" G_REDRIVE_BRANCH="$G_REDRIVE_BRANCH" \
    G_ACTION="$G_ACTION" G_BRANCH="$G_BRANCH" bash -c '
      set -uo pipefail
      say() { printf "SAY %s\n" "$*" >&2; }
      # The real pair is section 14 above (dedupe, re-ping window, lock reaping).
      # Here they only RECORD, because what is under test is whether the guard
      # reaches for them at all -- the defect was that it reached for neither.
      page_once() { printf "PAGE %s | %s\n" "$1" "$2" >> "'"$BG"'/pages"; }
      page_clear() { printf "CLEAR %s\n" "$1" >> "'"$BG"'/pages"; }
      NEXT="ASK-352"; TARGET_PATH="'"$WORK"'"
      # The dispatcher initialises all four before any selector runs (:1170) and
      # the guard reads them, so the harness carries the same shape or `set -u`
      # kills the guard and the fail-OPEN arm reads exactly like a pass.
      REVIEW_ACTION="$G_ACTION"; REVIEW_BRANCH="$G_BRANCH"
      REVIEW_NEXT="${G_ACTION:+ASK-352}"; REVIEW_PR="${G_ACTION:+91}"
      # The red-CI lane initialises its three at :1132, ahead of every selector,
      # for exactly the reason the note above gives: an unset name under `set -u`
      # kills the guard mid-arm and the caller reads the corpse as a pass. Adding
      # the arm without adding these here is what turned 15 green cases red.
      REDRIVE_NEXT="$G_REDRIVE"; REDRIVE_BRANCH="$G_REDRIVE_BRANCH"
      REDRIVE_PR="${G_REDRIVE:+91}"
      # LOG is where the guard appends the resolver stderr. Production always
      # sets it; leaving it unset here made `2>>"$LOG"` trip set -u, so the
      # resolver call died and the guard took its fail-OPEN arm -- a harness gap
      # that reads exactly like the guard passing a mismatch through.
      LOG="'"$BG"'/guard.log"
      REVIEW_REDRIVE="'"$REDRIVE"'"
      '"$(awk '/^branch_guard\(\) \{/,/^\}/' "$DISPATCH")"'
      branch_guard && echo "VERDICT=RUN" || echo "VERDICT=REFUSE"' 2>"$BG/gerr"
  }

  V="$(guard "$BG/prs-clean.json")"
  [ "$V" = "VERDICT=REFUSE" ] \
    && ok "THE REPRODUCER: dispatch REFUSES ASK-352 while its open PR is on sana/ask-352-clean" \
    || bad "THE DEFECT: dispatch said $V -- converge would commit onto the CLOSED sana/ask-352"
  grep -q 'sana/ask-352-clean' "$BG/gerr" \
    && ok "the refusal names the branch the open PR is actually on" \
    || bad "the refusal does not say which branch to work, so nobody can act on it"

  V="$(guard "$BG/prs-match.json")"
  [ "$V" = "VERDICT=RUN" ] \
    && ok "the ordinary shape (open PR on sana/ask-352) still dispatches" \
    || bad "THE DEFECT: the guard refuses a correct dispatch -- a gate this noisy gets switched off"

  V="$(guard "$BG/prs-two.json")"
  [ "$V" = "VERDICT=REFUSE" ] \
    && ok "two live branches for one issue refuses rather than picking one" \
    || bad "THE DEFECT: the guard picked a branch when two were live"

  V="$(guard "$BG/prs-none.json")"
  [ "$V" = "VERDICT=RUN" ] \
    && ok "an issue with no open PR still dispatches (round one has no PR yet)" \
    || bad "THE DEFECT: the guard blocks every first round, which stops the loop entirely"

  V="$(guard "$BG/prs-clean.json" 1)"
  [ "$V" = "VERDICT=RUN" ] \
    && ok "gh unable to answer fails OPEN, same posture stale_check takes on a failed fetch" \
    || bad "an unreadable board refused the dispatch, so one gh outage halts the loop"

  # PR #211 round 1, MAJOR 1. A re-review runs pr-review-agent.sh against a PR
  # NUMBER and commits nothing, so converge's branch rule never applies to it.
  # Refusing one parks a PR overnight over a condition it cannot cause.
  G_ACTION="re-review"; G_BRANCH="sana/ask-352-clean"
  V="$(guard "$BG/prs-clean.json")"
  [ "$V" = "VERDICT=RUN" ] \
    && ok "a re-review is not gated on the branch -- it commits nothing" \
    || bad "THE DEFECT: the guard parked a re-review, which no branch rule applies to"

  # A rework DOES become a converge, so the same mismatch must still refuse.
  G_ACTION="rework"; G_BRANCH="sana/ask-352-clean"
  V="$(guard "$BG/prs-clean.json")"
  [ "$V" = "VERDICT=REFUSE" ] \
    && ok "a rework on a mismatched branch still refuses -- the exemption is action-scoped" \
    || bad "THE DEFECT: exempting re-review exempted rework too, which is the whole bug"

  # PR #211 round 1, MAJOR 3. The selector already READ the branch. Asking gh a
  # second time re-opens the window: PR #91 closing in between makes the board
  # answer "no open PR", the fail-OPEN arm fires, and converge lands on the very
  # branch the guard exists to reject. The fix is to stop asking twice.
  G_ACTION="rework"; G_BRANCH="sana/ask-352-clean"
  V="$(guard "$BG/prs-none.json")"
  [ "$V" = "VERDICT=REFUSE" ] \
    && ok "THE RACE: a PR closing after selection cannot un-refuse the dispatch" \
    || bad "THE DEFECT: the guard re-queried, saw the PR gone, and ran on sana/ask-352"

  # And in the other direction. The carried branch is the branch of the PR whose
  # one attempt is about to be spent; a second query answers a DIFFERENT question
  # ("what branches does this issue have right now"), so the board disagreeing
  # here must not overrule the observation the dispatch is actually about.
  G_ACTION="rework"; G_BRANCH="sana/ask-352"
  V="$(guard "$BG/prs-clean.json")"
  [ "$V" = "VERDICT=RUN" ] \
    && ok "a matching carried branch dispatches -- the board is not asked a second time" \
    || bad "THE DEFECT: the guard re-queried and refused, so the selector's observation is discarded"
  G_ACTION=""; G_BRANCH=""

  # --- PR #211 round 3, MAJOR 2: THE SAME RACE, IN THE OTHER LANE ------------
  # Round 1 fixed the re-query for the reviewer redrive and left the red-CI
  # redrive on the old path: ci-redrive.py READ the branch, dropped it, and the
  # guard fell through to the `elif` and asked gh again. That second answer is
  # the fail-OPEN one. Note the failure mode: not a crash, not a refusal, but the
  # dispatch being WAVED THROUGH onto the branch this whole PR exists to reject.
  # A fail-open hole inside the guard whose thesis is "refuse a dispatch that
  # would land on a branch no open PR is on" is the PR contradicting itself,
  # which is why this is not a null check.
  #
  # `prs-none.json` IS the race: it is the board a moment after the PR closed.
  # If the carried branch is not read, the resolver answers rc 1 (no open PR),
  # the fail-open arm runs, and converge commits onto sana/ask-352.
  G_REDRIVE="ASK-352"; G_REDRIVE_BRANCH="sana/ask-352-clean"
  V="$(guard "$BG/prs-none.json")"
  [ "$V" = "VERDICT=REFUSE" ] \
    && ok "THE RACE, RED-CI LANE: a PR closing after selection cannot un-refuse it" \
    || bad "THE DEFECT: the red-CI guard re-queried, saw the PR gone, and ran on sana/ask-352"

  # The refusal has to be actionable, and it has to name the PR whose attempt is
  # about to be spent -- field 5 of the offer exists for this line.
  V="$(guard "$BG/prs-none.json")"
  if grep -q "sana/ask-352-clean" "$BG/gerr" && grep -q "PR #91" "$BG/gerr"; then
    ok "the red-CI refusal names both the branch to work and the PR it read"
  else
    bad "the red-CI refusal names both the branch to work and the PR it read" \
        "$(cat "$BG/gerr" 2>/dev/null)"
  fi

  # A refusal that cannot self-heal earns a page in this lane too. Without it the
  # red-CI queue starves exactly the way the reviewer queue did.
  if grep -q "^PAGE branch-guard-ASK-352" "$BG/pages"; then
    ok "a red-CI branch mismatch pages a human, not just dispatch.log"
  else
    bad "a red-CI branch mismatch pages a human, not just dispatch.log" \
        "$(cat "$BG/pages" 2>/dev/null)"
  fi

  # The other direction: a matching carried branch runs, and the board is never
  # consulted. `prs-none.json` would say rc 1 here too, so a guard that still
  # asked would be indistinguishable -- `prs-two.json` is used instead, which
  # would answer rc 3 (ambiguous) and REFUSE if the second query happened.
  G_REDRIVE="ASK-352"; G_REDRIVE_BRANCH="sana/ask-352"
  V="$(guard "$BG/prs-two.json")"
  [ "$V" = "VERDICT=RUN" ] \
    && ok "a matching carried branch dispatches without asking the board again" \
    || bad "THE DEFECT: the red-CI guard re-queried, so the selector's observation is discarded"

  # AN UNCONFIRMED HEAD RUNS, AND IT DOES NOT ASK THE BOARD AGAIN. ci-redrive
  # leaves field 4 empty when the board did not confirm the head lives in this
  # repo, and this lane then behaves exactly as the reviewer lane already does
  # with an empty REVIEW_BRANCH: fail open. Two reasons, and the second is the
  # one that decides it.
  #
  #   - Treating "" as a mismatch would park every unconfirmed head forever, and
  #     a gate that blocks the harmless case is a gate that gets switched off.
  #   - Falling through to the resolver buys nothing and costs the fix: branch_for
  #     itself only believes same-repo heads, so it answers rc 1 for exactly the
  #     PR we could not vouch for -- fail open by a longer road -- while for any
  #     OTHER board state it would overrule the dispatch with an answer to a
  #     different question. That re-query is the defect this case sits under.
  #
  # `prs-clean.json` is the discriminating fixture: an open PR on
  # sana/ask-352-clean, which the resolver WOULD refuse on. RUN here is the proof
  # that no second query happened.
  G_REDRIVE="ASK-352"; G_REDRIVE_BRANCH=""
  V="$(guard "$BG/prs-clean.json")"
  [ "$V" = "VERDICT=RUN" ] \
    && ok "an unconfirmed head runs on the naming rule, with no second query" \
    || bad "THE DEFECT: the empty-branch arm fell through and re-queried the board"
  if grep -q "PAGE" "$BG/pages" 2>/dev/null; then
    bad "an unconfirmed head pages nobody" "$(cat "$BG/pages")"
  else
    ok "an unconfirmed head pages nobody -- it dispatched, so there is no stall"
  fi
  G_REDRIVE=""; G_REDRIVE_BRANCH=""

  # --- PR #211 round 2, MAJOR 2: a refusal nobody is told about --------------
  # Every arm above ends in `say`, which appends to dispatch.log and nothing
  # else. So the guard doing its job looked identical, from outside, to the loop
  # having nothing to do: the same candidate is refused every 15 minutes, the
  # issue never moves, and the queue starves behind it with no operator ever
  # learning why. A branch mismatch needs a HUMAN (rename the branch, or reopen
  # the PR) -- it is the one refusal here that cannot self-heal, which makes a
  # log-only refusal an indefinite silent park.
  #
  # page_once, not page: this fires on every beat while the condition holds, and
  # `founder-notifications.md` is explicit that a "still waiting" ping each cycle
  # is noise rather than a page. The dedupe already exists in this file (section
  # 14) and is what makes it safe to page from a per-beat code path at all.
  V="$(guard "$BG/prs-clean.json")"
  [ "$V" = "VERDICT=REFUSE" ] && grep -q '^PAGE ' "$BG/pages" \
    && ok "THE REPRODUCER: a branch-mismatch park reaches the operator, not just the log" \
    || bad "THE DEFECT: the guard refused and paged nobody -- the queue starves in silence"
  grep -q 'ASK-352' "$BG/pages" && grep -q 'sana/ask-352-clean' "$BG/pages" \
    && ok "the page names the issue and the branch, so the fix is one line long" \
    || bad "the page says too little to act on: $(cat "$BG/pages")"
  [ "$(grep -c '^PAGE ' "$BG/pages")" = "1" ] \
    && ok "exactly one page per refusal -- the beat does not multiply it" \
    || bad "one refusal produced $(grep -c '^PAGE ' "$BG/pages") pages"

  # Ambiguity is the other refusal that needs a human, and it was equally silent.
  V="$(guard "$BG/prs-two.json")"
  [ "$V" = "VERDICT=REFUSE" ] && grep -q '^PAGE ' "$BG/pages" \
    && ok "the two-live-branches refusal pages too -- it also cannot self-heal" \
    || bad "THE DEFECT: an ambiguous park is refused silently forever"

  # THE OTHER HALF, or the dedupe becomes a mute. A key that is paged and never
  # cleared suppresses the NEXT episode for the whole re-ping window, which is
  # the guard-that-can-never-fire shape section 14 exists because of.
  V="$(guard "$BG/prs-match.json")"
  [ "$V" = "VERDICT=RUN" ] && grep -q '^CLEAR ' "$BG/pages" \
    && ok "a healthy dispatch CLEARS the key, so a recurrence pages immediately" \
    || bad "THE DEFECT: recovery left the marker set -- the next park is swallowed"
  grep -q '^PAGE ' "$BG/pages" \
    && bad "THE DEFECT: a dispatch that RAN paged the founder anyway" \
    || ok "a healthy dispatch pages nobody"

  # Fail-open arms are not parks. gh being unable to answer runs the dispatch, so
  # there is no stall to report and a page there is pure noise on an outage.
  V="$(guard "$BG/prs-clean.json" 1)"
  grep -q '^PAGE ' "$BG/pages" \
    && bad "THE DEFECT: a gh outage paged the founder about a park that did not happen" \
    || ok "the fail-open arm pages nobody -- an outage is not a mismatch"

  # And the re-review exemption, which returns 0 without ever being a refusal.
  G_ACTION="re-review"; G_BRANCH="sana/ask-352-clean"
  V="$(guard "$BG/prs-clean.json")"
  grep -q '^PAGE ' "$BG/pages" \
    && bad "THE DEFECT: an exempted re-review paged as though it were parked" \
    || ok "an exempted re-review pages nobody"
  G_ACTION=""; G_BRANCH=""
fi
unset KIPI_GH

echo
echo "-------- $PASS passed, $FAIL failed --------"
[ "$FAIL" -eq 0 ] || exit 1
echo "PASS: stale_check refuses without touching the tree, and pages once per episode"
