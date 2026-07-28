#!/usr/bin/env bash
# Reproducer + acceptance criterion for the agent claim-lock (ASK-113).
#
# Two agent sessions sharing one checkout overwrite each other's working tree.
# 2026-07-26: commit 53f2eeb came from a different session in the same checkout
# and the collision was only noticed afterwards, by hand.
#
# A mutex with no test is WORSE than no mutex, because it is trusted. So this
# file spends its cases on the REFUSAL path.
#
# THE FIXTURE RULE (scar, adversarial review 2026-07-26): the remote fixtures
# below are the VERBATIM shape of a real `mcp__linear__get_issue` response,
# captured from live Linear. v1 of this suite hand-rolled a `{"state": ...}`
# shape that no producer emits, so 3 of 21 checks were green against fiction
# while the remote half of the lock -- the ONLY cover for a cross-checkout
# collision -- read a key that never existed and granted every time. A fixture
# invented by the author from the same mental model as the code tests nothing.
#
# Isolation: KIPI_LINEAR_CLAIMS points at a temp dir throughout. This suite
# never touches live Linear and never reads or writes the live lock.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
CLAIM="$ROOT/q-system/.q-system/scripts/linear-claim.py"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

WORK="$(mktemp -d)"
export KIPI_LINEAR_CLAIMS="$WORK/claims.json"
# Never let an ambient session id from the surrounding agent leak in.
unset KIPI_SESSION_ID CLAUDE_SESSION_ID 2>/dev/null || true

EXIT_OK=0
EXIT_USAGE=1
EXIT_COLLISION=3

run() { python3 "$CLAIM" "$@" >"$WORK/out" 2>"$WORK/err"; }
rc()  { set +e; run "$@"; local r=$?; set -e; echo "$r"; }

[ -f "$CLAIM" ] || fail "linear-claim.py does not exist at $CLAIM"

# Snapshot the live repo-root lock before anything runs, so case 21 can assert the
# suite did not MUTATE it. A real worker may legitimately hold a claim while this
# suite runs; that is the system working, not a leak.
LIVE_LOCK_BEFORE="$(cat "$ROOT/.linear-claims.json" 2>/dev/null || echo '<absent>')"

# --- REAL Linear payload, captured verbatim from mcp__linear__get_issue ------
# Note `status` + `statusType`, NOT `state`. This is the shape that broke v1.
cat > "$WORK/remote-started-other.json" <<'JSON'
{"id":"ASK-113","title":"EPIC · Fleet-wide Linear rollout","status":"In Progress",
 "statusType":"started","labels":[],"assignee":"Assaf Kipnis",
 "team":"ASK_Consulting","url":"https://linear.app/ask-consulting/issue/ASK-113"}
JSON
cat > "$WORK/remote-free.json" <<'JSON'
{"id":"ASK-900","title":"unstarted","status":"Todo","statusType":"unstarted",
 "labels":[],"assignee":null}
JSON
cat > "$WORK/remote-claimed-other.json" <<'JSON'
{"id":"ASK-901","title":"claimed elsewhere","status":"Todo","statusType":"unstarted",
 "labels":["claimed:other-agent"],"assignee":null}
JSON
# Linear also emits labels as objects in some responses.
cat > "$WORK/remote-claimed-objects.json" <<'JSON'
{"id":"ASK-902","title":"object labels","status":"Todo","statusType":"unstarted",
 "labels":[{"id":"l1","name":"claimed:other-agent","color":"#fff"}],"assignee":null}
JSON
cat > "$WORK/remote-mine.json" <<'JSON'
{"id":"ASK-903","title":"mine","status":"In Progress","statusType":"started",
 "labels":["claimed:agent-a"],"assignee":"agent-a"}
JSON

# --- 1. a first claim succeeds ---------------------------------------------
r=$(rc claim ASK-100 --agent agent-a --session sess-A)
[ "$r" = "$EXIT_OK" ] || fail "first claim failed (exit $r): $(cat "$WORK/err")"
ok "agent-a/sess-A claims ASK-100"

# --- 2. a second SESSION is refused with exit 3, not a crash ----------------
r=$(rc claim ASK-100 --agent agent-b --session sess-B)
[ "$r" = "$EXIT_COLLISION" ] || fail "second session got exit $r, want $EXIT_COLLISION"
grep -qi "agent-a" "$WORK/err" || fail "refusal does not name the holder"
ok "a second session is refused with exit $EXIT_COLLISION and told who holds it"

# --- 3. THE SCAR: same agent NAME, different session, must still refuse -----
# v1 treated `--agent` as the whole identity, so two Claude sessions in one
# checkout that both called themselves "claude" were BOTH granted -- the exact
# case this lock exists to stop, and the likely case rather than the edge one.
r=$(rc claim ASK-100 --agent agent-a --session sess-DIFFERENT)
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "same agent name from a DIFFERENT session was granted (exit $r) -- this is the 53f2eeb scar"
ok "same agent name from a different session is refused"

# --- 4. re-claiming from the SAME session is idempotent --------------------
r=$(rc claim ASK-100 --agent agent-a --session sess-A)
[ "$r" = "$EXIT_OK" ] || fail "the holding session was refused its own claim (exit $r)"
ok "re-claim by the holding session is idempotent"

# --- 5. same-checkout guard: the tree is the resource ----------------------
r=$(rc claim ASK-200 --agent agent-b --session sess-B)
[ "$r" = "$EXIT_COLLISION" ] || fail "a second issue was claimed in the same tree (exit $r)"
ok "a different issue in the same checkout is refused"

# --- 6. a session id from the environment counts as identity ---------------
r=$(KIPI_SESSION_ID=sess-A rc claim ASK-100 --agent agent-a)
[ "$r" = "$EXIT_OK" ] || fail "KIPI_SESSION_ID was not honored as the session (exit $r)"
r=$(KIPI_SESSION_ID=sess-OTHER rc claim ASK-100 --agent agent-a)
[ "$r" = "$EXIT_COLLISION" ] || fail "a different KIPI_SESSION_ID was granted (exit $r)"
ok "KIPI_SESSION_ID is honored, and a different one still collides"

# --- 7. an anonymous claim is a usage error, never a silent grant ----------
r=$(rc claim ASK-300 --agent agent-x)
[ "$r" = "$EXIT_USAGE" ] || fail "a claim with no session gave exit $r, want $EXIT_USAGE"
ok "a claim with no session identity is refused as a usage error"

# --- 8. release: wrong session, and wrong issue, both refuse ---------------
r=$(rc release ASK-100 --agent agent-b --session sess-B)
[ "$r" = "$EXIT_COLLISION" ] || fail "a non-holding session released the claim (exit $r)"
ok "a non-holding session cannot release"
r=$(rc release ASK-999 --agent agent-a --session sess-A)
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "release accepted the WRONG issue id (exit $r); it must not drop whatever is held"
ok "release refuses an issue id the tree does not hold"
r=$(rc release ASK-100 --agent agent-a --session sess-A)
[ "$r" = "$EXIT_OK" ] || fail "the holder could not release (exit $r)"
ok "the holding session releases successfully"

# --- 9. --break-stale is a compare-and-swap, not a blind steal -------------
# v1 let --break-stale take a demonstrably LIVE claim, on the tool's own
# advice, and two agents could ping-pong it forever.
run claim ASK-400 --agent agent-a --session sess-LIVE
r=$(rc claim ASK-400 --agent agent-b --session sess-B --break-stale)
[ "$r" = "$EXIT_COLLISION" ] || fail "--break-stale with no --holder stole the claim (exit $r)"
ok "--break-stale without --holder is refused"
r=$(rc claim ASK-400 --agent agent-b --session sess-B --break-stale --holder sess-WRONG)
[ "$r" = "$EXIT_COLLISION" ] || fail "--break-stale accepted a WRONG holder token (exit $r)"
ok "--break-stale with the wrong holder token is refused"
r=$(rc claim ASK-400 --agent agent-b --session sess-B --break-stale --holder sess-LIVE)
[ "$r" = "$EXIT_OK" ] || fail "--break-stale naming the real holder failed (exit $r)"
ok "--break-stale naming the exact holder succeeds"
run release ASK-400 --agent agent-b --session sess-B

# --- 10. REAL remote payload: started under someone else is refused --------
# The case v1 could not see, because it read `state` and Linear emits `status`.
r=$(rc claim ASK-113 --agent agent-a --session sess-A \
      --remote-state "$WORK/remote-started-other.json")
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "a REAL Linear payload showing In Progress under another user was granted (exit $r)"
grep -qi "Assaf Kipnis" "$WORK/err" || fail "the refusal does not name the remote holder"
ok "real payload: statusType=started under another user is refused"

# --- 11. remote claimed:* label, both shapes Linear emits ------------------
r=$(rc claim ASK-901 --agent agent-a --session sess-A \
      --remote-state "$WORK/remote-claimed-other.json")
[ "$r" = "$EXIT_COLLISION" ] || fail "a string claimed:* label was granted (exit $r)"
ok "remote claimed:* as a string label is refused"
r=$(rc claim ASK-902 --agent agent-a --session sess-A \
      --remote-state "$WORK/remote-claimed-objects.json")
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "an OBJECT-shaped claimed:* label was granted (exit $r); Linear emits both shapes"
ok "remote claimed:* as an object label is refused"

# --- 12. our own remote claim is not a collision, and a free issue passes --
r=$(rc claim ASK-903 --agent agent-a --session sess-A --remote-state "$WORK/remote-mine.json")
[ "$r" = "$EXIT_OK" ] || fail "agent-a was refused its OWN remote claim (exit $r)"
run release ASK-903 --agent agent-a --session sess-A
r=$(rc claim ASK-900 --agent agent-a --session sess-A --remote-state "$WORK/remote-free.json")
[ "$r" = "$EXIT_OK" ] || fail "an unstarted, unclaimed issue was refused (exit $r)"
run release ASK-900 --agent agent-a --session sess-A
ok "our own remote claim passes, and so does a genuinely free issue"

# --- 13. an unrecognized remote shape FAILS CLOSED -------------------------
# A gate that cannot judge must not grant. An empty object is the shape an
# agent gets when its MCP fetch quietly failed.
for bad in '{}' \
           '{"status":{"unexpected":"object"}}' \
           '{"statusType":"unstarted","labels":"claimed:other,foo"}' \
           '{"statusType":"unstarted","labels":[123]}' \
           '{"statusType":"started","assignee":{"no":"name"}}'; do
  printf '%s\n' "$bad" > "$WORK/bad.json"
  r=$(rc claim ASK-950 --agent agent-a --session sess-A --remote-state "$WORK/bad.json")
  [ "$r" = "$EXIT_COLLISION" ] || \
    fail "an unjudgeable remote shape gave exit $r (want $EXIT_COLLISION): $bad"
done
ok "5 unrecognized remote shapes all fail closed"

# --- 14. a corrupt lock file fails closed ---------------------------------
printf '{not valid json' > "$KIPI_LINEAR_CLAIMS"
r=$(rc claim ASK-500 --agent agent-a --session sess-A)
[ "$r" = "$EXIT_COLLISION" ] || fail "a corrupt lock did not fail closed (exit $r)"
ok "a corrupt lock file fails closed"
rm -f "$KIPI_LINEAR_CLAIMS"

# --- 15. status reports the holder; quiet when free -----------------------
run claim ASK-600 --agent agent-a --session sess-A
run status
grep -q "ASK-600" "$WORK/out" || fail "status does not report the held issue"
grep -q "sess-A"  "$WORK/out" || fail "status does not report the holding session"
run release ASK-600 --agent agent-a --session sess-A
r=$(rc status)
[ "$r" = "$EXIT_OK" ] || fail "status on a free tree should exit 0 (got $r)"
ok "status names issue + session, and exits 0 on a free tree"

# --- 16. a leaked guard whose writer is DEAD is reclaimable ----------------
# v1 bricked the tree permanently: a claimant SIGKILLed inside the critical
# section leaked the guard, and --break-stale was unreachable behind it.
DEADPID=999999
printf '%s:0\n' "$DEADPID" > "${KIPI_LINEAR_CLAIMS}.guard"
r=$(rc claim ASK-700 --agent agent-a --session sess-A)
[ "$r" = "$EXIT_OK" ] || \
  fail "a guard left by a DEAD writer bricked the tree (exit $r); v1's permanent deadlock"
ok "a guard leaked by a dead writer is reclaimed, not a permanent deadlock"
run release ASK-700 --agent agent-a --session sess-A

# --- 17. a guard held by a LIVE process still refuses ---------------------
printf '%s:0\n' "$$" > "${KIPI_LINEAR_CLAIMS}.guard"
r=$(rc claim ASK-701 --agent agent-a --session sess-A)
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "a guard held by a LIVE process was barged into (exit $r)"
ok "a guard held by a live process is still respected"
rm -f "${KIPI_LINEAR_CLAIMS}.guard"

# --- 18. leftover .tmp files from dead writers are swept ------------------
touch "${KIPI_LINEAR_CLAIMS}.tmp.999998" "${KIPI_LINEAR_CLAIMS}.tmp.999997"
run claim ASK-702 --agent agent-a --session sess-A
[ ! -e "${KIPI_LINEAR_CLAIMS}.tmp.999998" ] || fail "a dead writer's .tmp file was not swept"
ok "leftover .tmp files from dead writers are swept"
run release ASK-702 --agent agent-a --session sess-A

# --- 19. the lock follows the CALLER's tree, and fails closed without one --
TREE_A="$WORK/tree-a"; TREE_B="$WORK/tree-b"; NOREPO="$WORK/norepo"
mkdir -p "$TREE_A" "$TREE_B" "$NOREPO"
for t in "$TREE_A" "$TREE_B"; do
  ( cd "$t" && git init -q . && git -c user.email=t@t.t -c user.name=t commit -q \
      --allow-empty -m init )
done
( cd "$TREE_A" && env -u KIPI_LINEAR_CLAIMS python3 "$CLAIM" claim ASK-800 \
    --agent agent-a --session sess-A >/dev/null )
[ -f "$TREE_A/.linear-claims.json" ] || fail "the default lock missed the caller's tree"
[ ! -f "$TREE_B/.linear-claims.json" ] || fail "claiming in tree-a wrote into tree-b"
ok "the default lock lands in the caller's tree"

set +e
( cd "$TREE_B" && env -u KIPI_LINEAR_CLAIMS python3 "$CLAIM" claim ASK-801 \
    --agent agent-b --session sess-B >/dev/null 2>&1 ); r=$?
set -e
[ "$r" = "$EXIT_OK" ] || fail "a separate working tree was refused (exit $r); worktrees are the fix"
ok "a separate working tree is claimable independently"

# v1 fell back to os.getcwd() whenever git could not answer, which handed out
# one lock PER SUBDIRECTORY of a single tree and granted every session.
set +e
( cd "$NOREPO" && env -u KIPI_LINEAR_CLAIMS python3 "$CLAIM" claim ASK-802 \
    --agent agent-a --session sess-A >/dev/null 2>&1 ); r=$?
set -e
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "outside a git tree the lock granted (exit $r) instead of failing closed"
ok "outside a git working tree the claim fails closed"

# --- 20. THE RACE: N claimants at once, exactly one may win ---------------
# Sequential cases cannot see the TOCTOU race, which is the actual failure
# this lock exists to stop.
rm -f "$KIPI_LINEAR_CLAIMS"
RACERS=12
for i in $(seq 1 $RACERS); do
  (
    # `set +e` is load-bearing: this file runs under `set -e`, which the
    # subshell inherits, so a REFUSED racer (exit 3) would die before recording
    # its code and the missing file would read as "crashed".
    set +e
    python3 "$CLAIM" claim ASK-RACE --agent "racer-$i" --session "sess-$i" \
      >"$WORK/race.$i.out" 2>"$WORK/race.$i.err"
    echo "$?" > "$WORK/race.$i.rc"
  ) &
done
wait

WON=0; REFUSED=0; OTHER=0
for i in $(seq 1 $RACERS); do
  case "$(cat "$WORK/race.$i.rc" 2>/dev/null)" in
    "$EXIT_OK")        WON=$((WON + 1)) ;;
    "$EXIT_COLLISION") REFUSED=$((REFUSED + 1)) ;;
    *)                 OTHER=$((OTHER + 1)) ;;
  esac
done
[ "$WON" = "1" ] || fail "race: $WON winners out of $RACERS, want exactly 1 (mutex broken)"
[ "$OTHER" = "0" ] || fail "race: $OTHER claimants neither won nor were refused -- crashed"
ok "race of $RACERS concurrent claimants: exactly 1 won, $REFUSED refused, 0 crashed"

WINNER="$(python3 "$CLAIM" status | sed -n 's/.*session \([^)]*\)).*/\1/p')"
grep -q "session $WINNER" "$WORK"/race.*.out || \
  fail "the recorded holder ($WINNER) is not the claimant that was told it won"
ok "the recorded holder is the claimant that was told it won"
[ ! -e "${KIPI_LINEAR_CLAIMS}.guard" ] || fail "the O_EXCL guard leaked after the race"
ok "no guard file leaked after the race"

# --- 21-25. LIVENESS: a claim whose holder is provably gone (ASK-189) ------
# Measured twice on 2026-07-27: a run was killed, the claim stayed held by a dead
# session with zero processes alive, and every issue on the board was blocked
# until a human ran `release --holder`. SIGKILL CANNOT BE TRAPPED, so no
# in-process cleanup can ever close this -- converge.sh's TERM/INT/HUP trap is
# real and still never ran. The lock has to be able to tell, ON READ, that its
# holder is gone.
#
# These cases spend most of their weight on the OPPOSITE failure, which is the
# worse one: a liveness check that reads "dead" for a HEALTHY long-running worker
# silently disables the mutex while the suite stays green. So every case that
# proves a reclaim is paired with one that proves a live or unknown holder is
# still respected.
spawn_holder() {   # a process that lives until this suite kills it
  sh -c 'exec sleep 300' >/dev/null 2>&1 &
  echo $!
}
reap() { kill -9 "$1" 2>/dev/null || true; wait "$1" 2>/dev/null || true; }

# --- 21. a LIVE holder is respected ---------------------------------------
rm -f "$KIPI_LINEAR_CLAIMS"
HOLDER="$(spawn_holder)"
r=$(rc claim ASK-KILL --agent agent-a --session sess-DEAD --holder-pid "$HOLDER")
[ "$r" = "$EXIT_OK" ] || fail "a claim carrying --holder-pid was refused (exit $r): $(cat "$WORK/err")"
r=$(rc claim ASK-KILL2 --agent agent-b --session sess-B)
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "a claim whose holder pid is ALIVE was reclaimed (exit $r) -- the mutex is off, which is worse than the leak"
ok "a claim whose holder process is alive is still refused"

reap "$HOLDER"

# --- 21b. THE ZOMBIE: os.kill says alive while the process is dead ---------
# `os.kill(pid, 0)` SUCCEEDS on a SIGKILLed process until its parent reaps it, so
# a pid-only liveness check reads the measured scar as "holder alive" and the
# board stays wedged. That is the half of the check `ps -o state=` earns.
#
# THE FIXTURE IS THE WHOLE CASE. v1 spawned the holder as a direct child of this
# suite; bash reaps its own children in its SIGCHLD handler before the claim ever
# runs, so the case travelled the pid-is-GONE path and stayed green with zombie
# detection deleted -- proven by mutation in the PR #31 review, finding 3. A
# zombie needs a parent that is alive and never wait()s: `sh` forks the holder,
# then execs into `sleep`, which has no SIGCHLD handling at all.
#
# The preconditions are ASSERTED, not assumed, so this can never silently decay
# back into a duplicate of case 22.
rm -f "$KIPI_LINEAR_CLAIMS"
ZPIDFILE="$WORK/zombie.pid"
: > "$ZPIDFILE"
sh -c 'sleep 300 & echo $! > "$1"; exec sleep 600' sh "$ZPIDFILE" >/dev/null 2>&1 &
ZPARENT=$!
i=0
while [ ! -s "$ZPIDFILE" ] && [ "$i" -lt 200 ]; do sleep 0.05; i=$((i + 1)); done
ZOMBIE="$(cat "$ZPIDFILE" 2>/dev/null || echo '')"
[ -n "$ZOMBIE" ] || fail "the zombie fixture never reported a holder pid"

run claim ASK-ZOMB --agent agent-a --session sess-DEAD --holder-pid "$ZOMBIE"
kill -9 "$ZOMBIE" 2>/dev/null || true
ZSTATE=""
i=0
while [ "$i" -lt 200 ]; do
  ZSTATE="$(ps -p "$ZOMBIE" -o state= 2>/dev/null | tr -d ' ')"
  case "$ZSTATE" in Z*) break ;; esac
  sleep 0.05
  i=$((i + 1))
done
case "$ZSTATE" in
  Z*) : ;;
  *)  fail "the fixture did not produce a zombie (ps state=[$ZSTATE]); without one this case silently duplicates case 22" ;;
esac
python3 -c 'import os,sys; os.kill(int(sys.argv[1]), 0)' "$ZOMBIE" 2>/dev/null \
  || fail "os.kill reports the zombie GONE, so this case would not exercise the zombie path at all"
ok "the fixture really makes a zombie: ps says Z while os.kill(pid,0) still succeeds"

r=$(rc claim ASK-ZOMB2 --agent agent-b --session sess-B)
[ "$r" = "$EXIT_OK" ] || \
  fail "a SIGKILLed holder that is still an unreaped zombie blocked the tree (exit $r): $(cat "$WORK/err")"
ok "a claim whose SIGKILLed holder is an unreaped zombie is reclaimable"
kill -9 "$ZPARENT" 2>/dev/null || true
wait "$ZPARENT" 2>/dev/null || true
reap "$ZOMBIE"
run release ASK-ZOMB2 --agent agent-b --session sess-B

# --- 22. the measured scar end-state: holder fully gone, no human needed ---
rm -f "$KIPI_LINEAR_CLAIMS"
HOLDER="$(spawn_holder)"
run claim ASK-KILL3 --agent agent-a --session sess-DEAD --holder-pid "$HOLDER"
reap "$HOLDER"
r=$(rc claim ASK-KILL4 --agent agent-b --session sess-B)
[ "$r" = "$EXIT_OK" ] || \
  fail "a claim held by a session with zero processes alive still needed --break-stale (exit $r); this is the ASK-189 scar"
grep -qi "reclaim" "$WORK/err" || \
  fail "the reclaim was SILENT; a mutex that hands a resource to someone else says so out loud"
ok "a claim whose holder is fully gone is reclaimed without --break-stale, and says so"
run release ASK-KILL4 --agent agent-b --session sess-B

# --- 23. a record with NO liveness field is still respected ---------------
# Every claim written before this change, and every claim from a caller that has
# no long-lived process to name. Missing must read as alive, never as dead.
rm -f "$KIPI_LINEAR_CLAIMS"
cat > "$KIPI_LINEAR_CLAIMS" <<'JSON'
{"issue_id":"ASK-OLD","agent":"agent-a","session":"sess-OLD","acquired_at":"2026-07-01T00:00:00Z"}
JSON
r=$(rc claim ASK-NEW --agent agent-b --session sess-B)
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "a pre-liveness record with no holder_pid was reclaimed (exit $r); old records must stay respected"
ok "a claim record with no liveness field is still respected"

# --- 24. THE PID-RECYCLING TRAP -------------------------------------------
# Pid numbers wrap. An unrelated process that inherits the dead holder's number
# makes the leak permanent again -- the whole reason the record carries the
# holder's START TIME and not just its pid.
rm -f "$KIPI_LINEAR_CLAIMS"
IMPOSTOR="$(spawn_holder)"
python3 - "$KIPI_LINEAR_CLAIMS" "$IMPOSTOR" <<'PY'
import json, sys
json.dump({"issue_id": "ASK-RECYCLE", "agent": "agent-a", "session": "sess-OLD",
           "acquired_at": "2026-07-01T00:00:00Z",
           "holder_pid": int(sys.argv[2]),
           # the key name carries the render format; see HOLDER_START_KEY
           "holder_pid_start_utc": "Thu Jan  1 00:00:00 1970"}, open(sys.argv[1], "w"))
PY
r=$(rc claim ASK-FRESH --agent agent-b --session sess-B)
[ "$r" = "$EXIT_OK" ] || \
  fail "a RECYCLED pid impersonated the dead holder and wedged the tree forever (exit $r)"
ok "a live pid whose start time does not match the record is a recycled pid, not the holder"
run release ASK-FRESH --agent agent-b --session sess-B

# --- 25. UNKNOWN reads as ALIVE, never as dead ----------------------------
# holder_pid recorded, holder_pid_start absent (ps could not answer at claim
# time), holder still running. Nothing here PROVES death, so the claim stands.
rm -f "$KIPI_LINEAR_CLAIMS"
python3 - "$KIPI_LINEAR_CLAIMS" "$IMPOSTOR" <<'PY'
import json, sys
json.dump({"issue_id": "ASK-NOSTART", "agent": "agent-a", "session": "sess-OLD",
           "acquired_at": "2026-07-01T00:00:00Z",
           "holder_pid": int(sys.argv[2])}, open(sys.argv[1], "w"))
PY
r=$(rc claim ASK-FRESH2 --agent agent-b --session sess-B)
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "a LIVE holder with no recorded start time was reclaimed (exit $r); unknown must read as alive"
ok "a live holder with no recorded start time is respected (unknown is not proof of death)"
reap "$IMPOSTOR"

# A --holder-pid that is not a pid is a USAGE error, not a silently dropped
# field: a caller that thinks it recorded liveness and did not has a mutex that
# leaks exactly as before, with nothing to show for it.
rm -f "$KIPI_LINEAR_CLAIMS"
r=$(rc claim ASK-BADPID --agent agent-a --session sess-A --holder-pid not-a-pid)
[ "$r" = "$EXIT_USAGE" ] || fail "--holder-pid with a non-integer gave exit $r, want $EXIT_USAGE"
r=$(rc claim ASK-BADPID --agent agent-a --session sess-A --holder-pid 0)
[ "$r" = "$EXIT_USAGE" ] || fail "--holder-pid 0 gave exit $r, want $EXIT_USAGE"
ok "a --holder-pid that is not a usable pid is a usage error, never a silent drop"
rm -f "$KIPI_LINEAR_CLAIMS"

# --- 26. isolation proof: the live lock was never TOUCHED -----------------
# Asserts the suite did not CHANGE the live lock, not that no lock exists.
#
# Scar 2026-07-27: this used to assert `! -e $ROOT/.linear-claims.json`, which
# cannot distinguish "the suite wrote the live lock" (the real defect) from "a
# real worker legitimately holds a claim right now" (the system working). It went
# RED the first time linear-worker.sh ran for real, because the worker holds the
# repo-root claim while it works. A test that fails whenever the product is in use
# is a false-alarm generator, and false alarms are what teach an operator to skip
# the gate -- the exact failure this fleet spent the day removing elsewhere.
LIVE_LOCK="$ROOT/.linear-claims.json"
if [ "$(cat "$LIVE_LOCK" 2>/dev/null || echo '<absent>')" = "$LIVE_LOCK_BEFORE" ]; then
  ok "the live lock at repo root is byte-identical to before the suite ran"
else
  fail "the suite MUTATED the live lock at repo root; the env override is not honored"
fi

# --- 26. A TIMEZONE CHANGE IS NOT A RECYCLED PID --------------------------
# `ps -o lstart=` renders in the READING process's timezone. The claim is written
# by one process and read by another hours later, so an unpinned render made a
# LIVE holder read as "the pid was recycled" the moment the system zone moved --
# macOS sets the zone automatically, and a laptop that travels flips it. That is
# the mutex handing a live worker's tree to a second worker (scar 53f2eeb), the
# one direction this feature must never go. PR #31 review, finding 1.
rc_tz() {
  local z="$1"; shift
  set +e; TZ="$z" python3 "$CLAIM" "$@" >"$WORK/out" 2>"$WORK/err"; local r=$?; set -e
  echo "$r"
}
rm -f "$KIPI_LINEAR_CLAIMS"
HOLDER="$(spawn_holder)"
r=$(rc_tz UTC claim ASK-TZ --agent agent-a --session sess-A --holder-pid "$HOLDER")
[ "$r" = "$EXIT_OK" ] || fail "the claim recording the holder's start time was refused (exit $r): $(cat "$WORK/err")"
r=$(rc_tz Asia/Tokyo claim ASK-TZ2 --agent agent-b --session sess-B)
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "a LIVE holder was reclaimed because the timezone changed between claim and read (exit $r): $(cat "$WORK/err")"
ok "a timezone change between claim and read does not make a live holder look recycled"
reap "$HOLDER"

# --- 27. A PRE-PIN RECORD IS NOT READ AS A RECYCLED PID -------------------
# The layer ABOVE the fix in case 26. Records written before the pin hold a
# local-time render; a UTC-pinned reader compares those two strings, sees a
# difference, and reclaims a holder that is alive and working -- the fix causing
# the exact defect it fixes, for the length of the upgrade window (`kipi update`
# can replace the script while a claim is held). The recorded format therefore
# lives in the KEY NAME, so an old record simply has no start time under the new
# key: unknown, which reads as alive.
rm -f "$KIPI_LINEAR_CLAIMS"
HOLDER="$(spawn_holder)"
TZ=Asia/Tokyo python3 - "$KIPI_LINEAR_CLAIMS" "$HOLDER" <<'PY'
import json, subprocess, sys
pid = int(sys.argv[2])
# byte-for-byte what the pre-pin build wrote: ps rendered in the WRITER's zone
started = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="],
                         capture_output=True, text=True).stdout.strip()
json.dump({"issue_id": "ASK-PREPIN", "agent": "agent-a", "session": "sess-OLD",
           "acquired_at": "2026-07-27T00:00:00Z", "holder_pid": pid,
           "holder_pid_start": started}, open(sys.argv[1], "w"))
PY
r=$(rc claim ASK-PREPIN2 --agent agent-b --session sess-B)
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "a LIVE holder recorded in the pre-pin start-time format was reclaimed (exit $r); upgrading must not steal a running worker's tree"
ok "a claim record in the pre-pin start-time format is respected, not read as recycled"
reap "$HOLDER"

# --- 28. `status` must not call a dead holder's claim live ----------------
# `status` is the command a human runs on a board that looks wedged. Saying
# "claimed by ..." about a holder that `claim` reclaims one line later is the
# report contradicting the detector. PR #31 review, finding 4.
rm -f "$KIPI_LINEAR_CLAIMS"
HOLDER="$(spawn_holder)"
run claim ASK-STAT --agent agent-a --session sess-STAT --holder-pid "$HOLDER"
python3 "$CLAIM" status >"$WORK/out" 2>&1
if grep -qi "stale" "$WORK/out"; then
  fail "status called a LIVE holder's claim stale: $(cat "$WORK/out")"
fi
ok "status does not call a live holder's claim stale"
reap "$HOLDER"
python3 "$CLAIM" status >"$WORK/out" 2>&1
grep -qi "stale" "$WORK/out" || \
  fail "status reported a holder with zero processes alive as a live claim: $(cat "$WORK/out")"
ok "status says so when the holder it reports is provably gone"
# The note is APPENDED, never substituted: case 20 reads the session token out of
# this exact line with sed, and a rewritten line would break that reader while
# every assertion above still passed.
S_PARSED="$(python3 "$CLAIM" status | sed -n 's/.*session \([^)]*\)).*/\1/p')"
[ "$S_PARSED" = "sess-STAT" ] || fail "the status line's session field stopped parsing (got '$S_PARSED')"
ok "the status line still parses for its existing reader"
rm -f "$KIPI_LINEAR_CLAIMS"

echo "PASS: linear-claim ($PASS checks)"
