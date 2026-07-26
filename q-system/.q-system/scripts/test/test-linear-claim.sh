#!/usr/bin/env bash
# Reproducer + acceptance criterion for the agent claim-lock (ASK-113).
#
# Two agent sessions sharing one checkout overwrite each other's working tree.
# It happened on 2026-07-26: commit 53f2eeb came from a different session in the
# same checkout and the collision was only noticed afterwards, by hand.
#
# A mutex with no test is WORSE than no mutex, because it is trusted. So the
# refusal path is what this file spends its cases on: a lock that grants under
# doubt has failed, and a lock that cannot distinguish "refused" from "crashed"
# cannot be depended on by a caller.
#
# Isolation: every case runs against KIPI_LINEAR_CLAIMS pointed at a temp dir and
# a --remote-state FIXTURE. This suite never touches live Linear and never reads
# or writes the live lock -- same env-override discipline as KIPI_LINEAR_LEDGER
# and KIPI_LINEAR_QUEUE.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
CLAIM="$ROOT/q-system/.q-system/scripts/linear-claim.py"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

WORK="$(mktemp -d)"
export KIPI_LINEAR_CLAIMS="$WORK/claims.json"

# Exit-code vocabulary shared with linear-sync.py. A refusal MUST be
# distinguishable from a crash, or a caller cannot branch on it.
EXIT_OK=0
EXIT_USAGE=1
EXIT_COLLISION=3

run() { python3 "$CLAIM" "$@" >"$WORK/out" 2>"$WORK/err"; }
rc()  { set +e; run "$@"; local r=$?; set -e; echo "$r"; }

fixture() {  # $1=path $2=state $3=labels-json $4=assignee
  printf '{"identifier":"ASK-999","state":"%s","labels":%s,"assignee":"%s"}\n' \
    "$2" "$3" "$4" > "$1"
}

[ -f "$CLAIM" ] || fail "linear-claim.py does not exist at $CLAIM"

# --- 1. a first claim succeeds ---------------------------------------------
r=$(rc claim ASK-100 --agent agent-a)
[ "$r" = "$EXIT_OK" ] || fail "first claim did not succeed (exit $r): $(cat "$WORK/err")"
ok "agent-a claims ASK-100"

# --- 2. a second agent is REFUSED, with exit 3 not a crash ------------------
# This is the whole point of the lock. Refusing is the feature.
r=$(rc claim ASK-100 --agent agent-b)
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "second agent got exit $r, expected $EXIT_COLLISION (refusal, not crash)"
grep -qi "agent-a" "$WORK/err" || \
  fail "refusal does not name the holder, so the operator cannot act on it"
ok "agent-b is refused with exit $EXIT_COLLISION and told who holds it"

# --- 3. re-claiming as the SAME agent is idempotent, not a collision --------
# A resumed session must not be locked out by its own earlier claim.
r=$(rc claim ASK-100 --agent agent-a)
[ "$r" = "$EXIT_OK" ] || fail "agent-a was refused its OWN claim (exit $r)"
ok "re-claim by the holder is idempotent"

# --- 4. same-checkout guard: the tree is the resource, not just the issue ---
# The Linear label CANNOT see this case: two sessions in one working tree share
# one MCP user and one label set. Even on a DIFFERENT issue they still stomp
# each other's files, so one active claim per working tree.
r=$(rc claim ASK-200 --agent agent-b)
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "a second issue was claimed in the same working tree (exit $r)"
ok "a different issue in the same checkout is refused"

# --- 5. release, then the next agent can take it ---------------------------
r=$(rc release ASK-100 --agent agent-a)
[ "$r" = "$EXIT_OK" ] || fail "release by the holder failed (exit $r)"
r=$(rc claim ASK-100 --agent agent-b)
[ "$r" = "$EXIT_OK" ] || fail "claim after release failed (exit $r)"
ok "release by holder, then agent-b claims successfully"

# --- 6. a non-holder cannot release someone else's claim -------------------
r=$(rc release ASK-100 --agent agent-a)
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "agent-a released a claim it does not hold (exit $r)"
ok "a non-holder cannot release another agent's claim"
run release ASK-100 --agent agent-b

# --- 7. remote state: already In Progress under someone else ---------------
fixture "$WORK/remote-inprogress.json" "In Progress" '[]' "someone-else"
r=$(rc claim ASK-999 --agent agent-a --remote-state "$WORK/remote-inprogress.json")
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "claimed an issue already In Progress under another user (exit $r)"
ok "remote In Progress under another user is refused"

# --- 8. remote state: already carries a claimed:* label --------------------
fixture "$WORK/remote-claimed.json" "Todo" '["claimed:other-agent"]' ""
r=$(rc claim ASK-999 --agent agent-a --remote-state "$WORK/remote-claimed.json")
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "claimed an issue already carrying claimed:other-agent (exit $r)"
ok "remote claimed:* held by someone else is refused"

# --- 9. remote state: OUR OWN claim label is not a collision ---------------
fixture "$WORK/remote-mine.json" "In Progress" '["claimed:agent-a"]' "agent-a"
r=$(rc claim ASK-999 --agent agent-a --remote-state "$WORK/remote-mine.json")
[ "$r" = "$EXIT_OK" ] || fail "agent-a refused its own remote claim (exit $r)"
ok "our own remote claim is not a collision"
run release ASK-999 --agent agent-a

# --- 10. a corrupt lock file REFUSES, it never silently grants -------------
# Fail closed. A lock that grants when it cannot read its own state is worse
# than no lock, because callers trust it.
printf '{not valid json' > "$KIPI_LINEAR_CLAIMS"
r=$(rc claim ASK-300 --agent agent-a)
[ "$r" = "$EXIT_COLLISION" ] || \
  fail "a corrupt lock file did not refuse (exit $r) -- it must fail closed"
ok "a corrupt lock file fails closed"

# --- 11. a stale claim is broken only DELIBERATELY -------------------------
# A session that died leaves a claim behind. It must not auto-expire (that is a
# race), and it must not be permanent (that is a deadlock). It takes a flag.
printf '{"issue_id":"ASK-400","agent":"dead-session","acquired_at":"2020-01-01T00:00:00Z"}\n' \
  > "$KIPI_LINEAR_CLAIMS"
r=$(rc claim ASK-400 --agent agent-a)
[ "$r" = "$EXIT_COLLISION" ] || fail "a stale claim auto-expired (exit $r)"
ok "a stale claim does not auto-expire"
r=$(rc claim ASK-400 --agent agent-a --break-stale)
[ "$r" = "$EXIT_OK" ] || fail "--break-stale could not break a stale claim (exit $r)"
ok "--break-stale breaks it deliberately"
run release ASK-400 --agent agent-a

# --- 12. status reports the holder, and is quiet when unheld ---------------
run claim ASK-500 --agent agent-a
run status
grep -q "ASK-500" "$WORK/out" || fail "status does not report the held issue"
grep -q "agent-a" "$WORK/out" || fail "status does not report the holder"
ok "status reports issue and holder"
run release ASK-500 --agent agent-a
r=$(rc status)
[ "$r" = "$EXIT_OK" ] || fail "status on an unheld tree should exit 0 (got $r)"
ok "status on an unheld tree exits 0"

# --- 13. usage errors are exit 1, distinct from a refusal ------------------
r=$(rc claim ASK-600)
[ "$r" = "$EXIT_USAGE" ] || \
  fail "a missing --agent gave exit $r, expected $EXIT_USAGE (not a refusal)"
ok "a usage error is exit $EXIT_USAGE, distinct from a refusal"

# --- 14. isolation proof: the live lock was never touched ------------------
[ ! -e "$ROOT/.linear-claims.json" ] || \
  fail "the suite wrote the LIVE lock at repo root; env override is not honored"
ok "the live lock at repo root was never created"

# --- 15. the lock follows the CALLER's tree, not the script's repo ---------
# `kipi` runs fleet scripts out of $KIPI_HOME (the skeleton), so a lock path
# derived from the script's own location would lock the SKELETON no matter
# which instance the agent is working in: every instance would share one lock
# and the tree actually at risk would have none. Runs with the env override
# UNSET, which is the only way to exercise the default path.
TREE_A="$WORK/tree-a"; TREE_B="$WORK/tree-b"
mkdir -p "$TREE_A" "$TREE_B"
for t in "$TREE_A" "$TREE_B"; do
  ( cd "$t" && git init -q . && git -c user.email=t@t.t -c user.name=t commit -q \
      --allow-empty -m init )
done
( cd "$TREE_A" && env -u KIPI_LINEAR_CLAIMS python3 "$CLAIM" claim ASK-700 \
    --agent agent-a >/dev/null )
[ -f "$TREE_A/.linear-claims.json" ] || \
  fail "the default lock was not written into the caller's working tree"
[ ! -f "$TREE_B/.linear-claims.json" ] || \
  fail "claiming in tree-a wrote a lock into tree-b"
ok "the default lock lands in the caller's tree"

# a DIFFERENT working tree is a different resource and must not be blocked
set +e
( cd "$TREE_B" && env -u KIPI_LINEAR_CLAIMS python3 "$CLAIM" claim ASK-800 \
    --agent agent-b >/dev/null 2>&1 )
r=$?
set -e
[ "$r" = "$EXIT_OK" ] || \
  fail "a claim in a SEPARATE working tree was refused (exit $r); worktrees are the fix, not a deadlock"
ok "a separate working tree can be claimed independently"

# --- 16. THE RACE: N claimants at once, exactly one may win ----------------
# Every case above is sequential, and a sequential test cannot see a TOCTOU
# race -- which is the actual failure this lock exists to stop (two sessions
# starting at the same moment both read "free" and both proceed). Without this
# case the mutex would look correct while being broken under the only
# conditions that matter.
rm -f "$KIPI_LINEAR_CLAIMS"
RACERS=12
for i in $(seq 1 $RACERS); do
  (
    # `set +e` is load-bearing: this file runs under `set -e`, which the
    # subshell inherits, so a REFUSED racer (exit 3) would kill its own
    # subshell before recording its code -- and the missing file would then
    # read as "crashed". The refusals are the expected result here.
    set +e
    python3 "$CLAIM" claim ASK-RACE --agent "racer-$i" \
      >"$WORK/race.$i.out" 2>"$WORK/race.$i.err"
    echo "$?" > "$WORK/race.$i.rc"
  ) &
done
wait

WON=0; REFUSED=0; OTHER=0
for i in $(seq 1 $RACERS); do
  case "$(cat "$WORK/race.$i.rc")" in
    "$EXIT_OK")        WON=$((WON + 1)) ;;
    "$EXIT_COLLISION") REFUSED=$((REFUSED + 1)) ;;
    *)                 OTHER=$((OTHER + 1)) ;;
  esac
done
[ "$WON" = "1" ] || \
  fail "race: $WON winners out of $RACERS, expected exactly 1 (mutex is broken)"
[ "$OTHER" = "0" ] || \
  fail "race: $OTHER claimants neither won nor were refused -- they crashed"
[ "$REFUSED" = "$((RACERS - 1))" ] || \
  fail "race: $REFUSED refusals, expected $((RACERS - 1))"
ok "race of $RACERS concurrent claimants: exactly 1 won, $REFUSED refused, 0 crashed"

# and the recorded holder must be the one that was actually told it won
WINNER="$(python3 "$CLAIM" status | sed -n 's/.*claimed by \([^ ]*\).*/\1/p')"
grep -q "claimed ASK-RACE for $WINNER" "$WORK"/race.*.out \
  || fail "the recorded holder ($WINNER) is not the claimant that was told it won"
ok "the recorded holder is the claimant that was told it won"

# no guard file may survive a race, or the next claim deadlocks
[ ! -e "${KIPI_LINEAR_CLAIMS}.guard" ] || \
  fail "the O_EXCL guard leaked after the race; the next claim would deadlock"
ok "no guard file leaked after the race"

echo "PASS: linear-claim ($PASS checks)"
