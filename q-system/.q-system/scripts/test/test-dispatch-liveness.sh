#!/usr/bin/env bash
# Pairs with kipi-dispatch.sh: a dispatch that DIED must not report success.
#
# THE SCAR (2026-07-28)
# ---------------------
# kipi-dispatch.sh launched converge with `nohup ... & disown`. That is right in
# an interactive shell and wrong under launchd, which reaps the job's whole
# process group when the main process exits -- nohup only blocks SIGHUP. Every
# launchd dispatch was killed the instant the dispatcher returned.
#
# It was invisible by construction, and every visible signal said healthy:
#   - the log file exists, because the redirect creates it before the child dies
#   - it is 0 bytes, which reads as "just started"
#   - `say "dispatched $NEXT"` runs unconditionally, so the log claims success
#   - the budget counter is already spent, because it is spent before launching
# The loop reported four healthy dispatches of ASK-224 and did no work at all.
#
# Proven with a launchd probe: a job whose only act was
#   nohup bash -c "sleep 25; touch F" & disown; exit
# never wrote F under launchd, wrote it from an interactive shell, and wrote it
# under launchd once the child was given its own session via setsid(2).
#
# WHAT THIS FILE CAN AND CANNOT TEST
# ----------------------------------
# It cannot reproduce the launchd reap: CI is Linux and has no launchd. So it
# tests the thing that makes the class of failure LOUD instead of silent -- the
# dispatcher must confirm the process is actually alive before claiming it
# dispatched, and must page and exit non-zero when it is not. That check fires
# for a reaped child, a converge that crashes on startup, a bad PATH, or any
# other reason the run does not survive: the assertion is on the outcome, not on
# one cause.
#
# A structural check that `start_new_session` is still there guards the specific
# fix from a silent revert (see the merge that restored RESET_HOUR for why that
# is not paranoia).
set -uo pipefail

PASS=0; FAIL=0
ok()  { printf '  PASS %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  FAIL %s\n     %s\n' "$1" "${2:-}"; FAIL=$((FAIL + 1)); }
check() { if [ "$2" = "$3" ]; then ok "$1"; else bad "$1" "expected [$3] got [$2]"; fi; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# FOUR levels: this file is <repo>/q-system/.q-system/scripts/test/, so the repo
# root is test -> scripts -> .q-system -> q-system -> repo. Three resolves to
# q-system/ and the dispatcher is not there. The assert below is what turns that
# into a loud failure instead of a suite that grades its own error message
# (the exact shape of the token-guard fixture bug fixed earlier the same day).
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
DISPATCH="$REPO_ROOT/kipi-dispatch.sh"
[ -f "$DISPATCH" ] || { echo "FATAL: kipi-dispatch.sh not found at $DISPATCH" >&2; exit 1; }

# A UNIQUE issue id per run. Every assertion here goes through the GLOBAL
# process table, so a hardcoded id makes two concurrent runs of this suite (the
# capability gate runs the fleet's tests together) see each other's decoys: one
# run's live converge satisfies the other run's duplicate guard, and cases fail
# for a reason that has nothing to do with the code under test. Observed exactly
# that way on 2026-07-28 -- 17/17 standalone, 15/17 under the gate.
ISS="ASK-9$$"

ROOT="$(mktemp -d)"
trap 'pkill -f "$ROOT/converge.sh" 2>/dev/null; rm -r -- "$ROOT" 2>/dev/null' EXIT

# --- the sandbox ------------------------------------------------------------
# A fake repo whose `kipi` responds to `work` with one ready issue, and to
# `converge` in whichever way the case under test needs.
FAKE_REPO="$ROOT/repo"
mkdir -p "$FAKE_REPO" "$ROOT/home/.config/kipi" "$ROOT/bin"

# gh must merely exist; the dispatcher only checks `command -v gh`.
printf '#!/bin/sh\nexit 0\n' > "$ROOT/bin/gh"; chmod +x "$ROOT/bin/gh"

# The page sink, so an alert is asserted on a file rather than on prose.
PAGES="$ROOT/pages.txt"
printf '#!/bin/sh\nprintf "%%s\\n" "$1" >> "%s"\n' "$PAGES" > "$ROOT/notify.sh"
chmod +x "$ROOT/notify.sh"

# A stand-in for the real converge.sh. Named so `pgrep -f "converge.sh --issue"`
# matches it exactly as it matches the real one -- the dispatcher's liveness
# check greps the process table, so the fixture has to be visible there.
cat > "$ROOT/converge.sh" <<'SH'
#!/usr/bin/env bash
sleep 30
SH
chmod +x "$ROOT/converge.sh"

make_kipi() {  # make_kipi <alive|dead>
  cat > "$FAKE_REPO/kipi" <<SH
#!/usr/bin/env bash
case "\$1" in
  work) printf '1 ready issue\n[dry] would work $ISS\n' ;;
  converge)
    if [ "$1" = "alive" ]; then
      exec bash "$ROOT/converge.sh" --issue $ISS --max-rounds 3
    fi
    # "dead": exit immediately, exactly like a child launchd has reaped.
    exit 0
    ;;
esac
SH
  chmod +x "$FAKE_REPO/kipi"
}

# KIPI_DISPATCH_MAX IS PINNED HIGH ON PURPOSE (PR #39 review r3, finding 2).
# The dispatcher's concurrency cap counts live converge runs from the GLOBAL
# process table, so without this the suite is at the mercy of whatever else is
# running on the box: two unrelated converge runs and the dispatcher skips
# before it reaches anything under test, taking 8 of 16 cases red. That is the
# flakiness previously blamed on one case; it was the cap all along.
run_dispatch() {
  ( cd "$FAKE_REPO" && HOME="$ROOT/home" PATH="$ROOT/bin:$PATH" \
      KIPI_REPO="$FAKE_REPO" KIPI_NOTIFY="$ROOT/notify.sh" \
      KIPI_DISPATCH_DAILY_MAX=9 KIPI_DISPATCH_MAX=999 \
      bash "$DISPATCH" 2>&1 )
}

# `say` writes to the dispatch LOG, not to stdout, so every assertion about what
# the dispatcher reported has to read the log. Asserting on stdout would pass
# vacuously against an empty string -- which is how a check ends up grading
# nothing at all.
dlog() { cat "$ROOT/home/.config/kipi/dispatch.log" 2>/dev/null; }

reset_state() {
  rm -r -- "$ROOT/home/.config/kipi" 2>/dev/null
  mkdir -p "$ROOT/home/.config/kipi"
  # Seed the liveness beacon so the one-off "heartbeat STARTED" page does not
  # fire and get mistaken for a fault page by the assertions below.
  date -u +%s > "$ROOT/home/.config/kipi/dispatch-lastbeat"
  : > "$PAGES"
  pkill -f "$ROOT/converge.sh" 2>/dev/null
}

echo "test-dispatch-liveness.sh"

# --- 1. a dispatch that dies immediately is reported as DIED ----------------
# THE REGRESSION. With the old code this case printed "dispatched $ISS" and
# exited 0 while nothing ran.
reset_state
make_kipi dead
run_dispatch >/dev/null; RC=$?

check "1a a died dispatch exits non-zero" "$RC" "1"

if dlog | grep -q "DISPATCH DIED"; then
  ok "1b the log says the dispatch died"
else
  bad "1b the log says the dispatch died" "$(dlog)"
fi

if dlog | grep -q "dispatched $ISS (confirmed running)"; then
  bad "1c it does NOT claim the run is confirmed" "$(dlog)"
else
  ok "1c it does NOT claim the run is confirmed"
fi

# LOUD MEANS THE FOUNDER HEARS IT. A dead loop that only writes its own log is
# the silent failure again, one layer down: nobody reads dispatch.log.
if grep -q "died immediately" "$PAGES" 2>/dev/null; then
  ok "1d the founder is paged, naming the symptom"
else
  bad "1d the founder is paged, naming the symptom" "$(cat "$PAGES" 2>/dev/null)"
fi

if grep -q "spending budget and doing no work" "$PAGES" 2>/dev/null; then
  ok "1e the page says the cost is real, not just that something is wrong"
else
  bad "1e the page says the cost is real" "$(cat "$PAGES" 2>/dev/null)"
fi

# --- 2. control: a dispatch that survives is reported as running ------------
# Without this the suite would pass by simply always failing, which is the
# no-teeth shape the reviewer keeps catching.
reset_state
make_kipi alive
run_dispatch >/dev/null; RC=$?

check "2a a surviving dispatch exits 0" "$RC" "0"

if dlog | grep -q "confirmed running"; then
  ok "2b it reports the run as confirmed"
else
  bad "2b it reports the run as confirmed" "$(dlog)"
fi

check "2c no page is sent on the healthy path" \
  "$([ -s "$PAGES" ] && echo paged || echo silent)" "silent"

pkill -f "$ROOT/converge.sh" 2>/dev/null

# --- 3. the child is still given its own session ----------------------------
# Structural, and deliberately so: the launchd reap cannot be reproduced on CI
# (Linux, no launchd), so this is what stops a rewrite quietly restoring
# `nohup ... & disown` and taking the loop back down to zero work per night.
if grep -q "start_new_session=True" "$DISPATCH"; then
  ok "3a the converge child is launched in a new session (setsid)"
else
  bad "3a the converge child is launched in a new session (setsid)" \
    "start_new_session=True is gone from kipi-dispatch.sh; launchd will reap every run"
fi

if grep -qE '^\s*nohup \./kipi converge' "$DISPATCH"; then
  bad "3b the reaped nohup form has not come back" "nohup ./kipi converge is back in kipi-dispatch.sh"
else
  ok "3b the reaped nohup form has not come back"
fi

# --- 4. an unrelated live converge must not vouch for a dead child ----------
# PR #39 review, finding 1. The first cut of this liveness check asked "is SOME
# converge for this issue in the process table?" -- so any other converge on the
# same issue answered on the dead child's behalf, rebuilding the exact
# silent-success hole one layer up.
#
# The reviewer's chain, reproduced here: the child is launched, it spawns a
# DECOY that matches the process-table pattern and then dies itself. A
# table-grep sees the decoy and reports "confirmed running". A pid-bound check
# sees the child it actually launched is gone and reports DIED.
#
# The decoy is started by the child rather than beforehand on purpose: started
# beforehand, the duplicate-dispatch guard would skip the issue and the
# liveness check would never run at all.
reset_state
cat > "$FAKE_REPO/kipi" <<SH
#!/usr/bin/env bash
case "\$1" in
  work) printf '1 ready issue\n[dry] would work $ISS\n' ;;
  converge)
    # Spawn something that LOOKS like a live converge for this issue...
    # Plain background, not setsid: macOS ships no setsid(1), so that spelling
    # is a command-not-found and the decoy never starts, which would make this
    # whole case pass for the wrong reason. The child is already in its own
    # session (the dispatcher put it there), so its children survive anyway.
    # NOTE: no backticks anywhere in this heredoc -- it is unquoted (<<SH) so
    # backticks would run as command substitution while the stub is WRITTEN.
    bash "$ROOT/converge.sh" --issue $ISS --max-rounds 3 >/dev/null 2>&1 &
    disown 2>/dev/null || true
    # ...then die, exactly as a reaped child does.
    exit 0
    ;;
esac
SH
chmod +x "$FAKE_REPO/kipi"
run_dispatch >/dev/null; RC=$?

check "4a a decoy converge does not make a dead dispatch succeed" "$RC" "1"

if dlog | grep -q "DISPATCH DIED"; then
  ok "4b the dead child is still reported as died"
else
  bad "4b the dead child is still reported as died" "$(dlog)"
fi

if grep -q "died immediately" "$PAGES" 2>/dev/null; then
  ok "4c the founder is still paged"
else
  bad "4c the founder is still paged" "$(cat "$PAGES" 2>/dev/null)"
fi

pkill -f "$ROOT/converge.sh" 2>/dev/null

# The check must be bound to the launched pid, not to a table search. Structural
# because the race above is the only behavioural way in, and it is easy to
# "simplify" this back to a grep while every case still passes.
if grep -q 'kill -0 "$CHILD_PID"' "$DISPATCH"; then
  ok "4d the liveness check watches the pid it launched"
else
  bad "4d the liveness check watches the pid it launched" \
    "kill -0 \$CHILD_PID is gone; an unrelated converge can vouch for a dead child again"
fi

# --- 5. the duplicate guard no longer uses the \b that never fires ---------
# PR #39 review, finding 2. The guard used `pgrep -f "...ASK-n\b"`, and BSD
# pgrep reads \b as a literal b, so it has never fired on macOS -- the only
# platform it runs on. Harmless only while every child was being reaped anyway;
# children surviving is exactly what makes it reachable.
#
# STRUCTURAL, NOT BEHAVIOURAL, AND THAT IS A DELIBERATE LIMIT. Driving it for
# real means putting a decoy converge in the GLOBAL process table and asserting
# the dispatcher sees it -- which races against any other run of this suite and
# against real converge runs on the machine. That version was written first and
# was flaky under the capability gate (17/17 alone, 15/17 alongside the fleet's
# other tests), and a flaky gate is worse than a narrow one: it teaches everyone
# to re-run until green. The regex itself is verified by hand against a live
# process; this pins the spelling so the \b cannot come back.
# A non-racy behavioural version is captured as spillover.
if grep -qE 'pgrep -f "converge\.sh --issue \$NEXT' "$DISPATCH"; then
  bad "5a the duplicate guard does not use the \\b that BSD pgrep ignores" \
    "the pgrep+\\b form is back in kipi-dispatch.sh; the guard will never fire on macOS"
else
  ok "5a the duplicate guard does not use the \\b that BSD pgrep ignores"
fi

if grep -c 'ps -Ao args=' "$DISPATCH" | grep -q '[1-9]'; then
  ok "5b the guard matches on full command lines, portably"
else
  bad "5b the guard matches on full command lines, portably" "ps -Ao args= is gone from kipi-dispatch.sh"
fi

# --- 6. the duplicate guard actually fires, driven for real -----------------
# The behavioural half of case 5, restored once BOTH causes of its earlier
# flakiness were understood and fixed: the issue id is unique per run (so two
# runs of this suite cannot see each other's decoy) and run_dispatch pins
# KIPI_DISPATCH_MAX (so the concurrency cap cannot skip before the guard is
# reached). Blaming the process table was wrong; it was the cap.
#
# THIS IS THE CASE THAT CATCHES THE SIGPIPE BUG. A structural grep cannot: the
# `ps ... | grep -q` spelling looked correct and failed ~35% of the time because
# pipefail turned grep -q's early exit into a 141 for the whole pipeline. Only
# running it can tell.
reset_state
make_kipi alive
bash "$ROOT/converge.sh" --issue "$ISS" --max-rounds 3 >/dev/null 2>&1 &
DECOY2=$!
disown "$DECOY2" 2>/dev/null || true
sleep 1

# Run it several times: the SIGPIPE race is load-dependent, so a single green
# pass proves nothing. Every one of them must skip.
GUARD_FIRED=0; GUARD_RUNS=5
for _ in $(seq 1 "$GUARD_RUNS"); do
  run_dispatch >/dev/null
  if dlog | grep -q "skip $ISS: a converge run for it is already live"; then
    GUARD_FIRED=$((GUARD_FIRED + 1))
  fi
  : > "$ROOT/home/.config/kipi/dispatch.log"
done

check "6a the guard fires on EVERY attempt, not most of them" \
  "$GUARD_FIRED" "$GUARD_RUNS"

check "6b no budget slot is spent while the issue is already live" \
  "$(cat "$ROOT/home/.config/kipi/dispatch-count-"* 2>/dev/null || echo 0)" "0"

kill "$DECOY2" 2>/dev/null
pkill -f "$ROOT/converge.sh" 2>/dev/null

echo
printf '== %s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
