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

# --- 21. isolation proof: the live lock was never TOUCHED -----------------
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

echo "PASS: linear-claim ($PASS checks)"
