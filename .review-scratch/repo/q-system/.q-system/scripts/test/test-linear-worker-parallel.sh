#!/usr/bin/env bash
# Reproducer + acceptance criterion for the claim-lock serializing the whole
# board (ASK-188).
#
# THE DEFECT: linear-worker.sh took its claim at step 1, BEFORE it created or
# entered $TREE. `linear-claim.py::claims_path()` resolves the lock from
# `git rev-parse --show-toplevel` OF THE CALLER'S CWD, so every issue contended
# for one file at the skeleton root. Board throughput was capped at one issue at
# a time -- measured 2026-07-27, ASK-150 25 min, ASK-183 67 min, with 50+ ready
# issues behind them.
#
# WHY THIS DRIVES THE REAL SCRIPT INSTEAD OF ASSERTING ON ITS SOURCE
# ------------------------------------------------------------------
# The bug IS the cwd the claim runs in. A grep for line ordering cannot see a
# cwd, and a re-implementation of the sequence in this file would test a copy
# that agrees with whatever I believed while writing it. So this boots the real
# linear-worker.sh twice, concurrently, and asserts on where the lock files
# actually landed and which runs actually reached the work phase.
#
# Isolation (nothing here touches the founder's checkout or the live state):
#   KIPI_SKEL       -> a throwaway clone; worktrees and sana/* branches land there
#   KIPI_STATE_DIR  -> a temp dir; worktrees, log and attempts ledger land there
#   KIPI_LINEAR_CLAIMS is UNSET on purpose -- the per-tree default path is the
#   exact thing under test, so pinning it to one file would hide the defect.
#   PATH stubs for python3/gh/claude keep Linear, GitHub and the model out of it;
#   `git` stays REAL, because real linked worktrees are the fix's mechanism.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
WORKER="$ROOT/q-system/.q-system/scripts/linear-worker.sh"

PASS=0
fail() { echo "FAIL: $1" >&2; exit 1; }
ok()   { PASS=$((PASS + 1)); echo "  ok: $1"; }

[ -f "$WORKER" ] || fail "linear-worker.sh does not exist at $WORKER"
REAL_PY="$(command -v python3)" || fail "python3 not on PATH"
REAL_GIT="$(command -v git)"    || fail "git not on PATH"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Never let the surrounding agent's session id or a claims override leak in.
unset KIPI_LINEAR_CLAIMS KIPI_SESSION_ID CLAUDE_SESSION_ID 2>/dev/null || true

# --- a throwaway skeleton with a real origin/main ---------------------------
git init -q --bare "$WORK/origin"
git init -q "$WORK/skel"
git -C "$WORK/skel" -c user.email=t@t.t -c user.name=t commit -q --allow-empty -m init
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "$WORK/origin"
git -C "$WORK/skel" push -q -u origin main

# --- stubs ------------------------------------------------------------------
# python3: the ONLY calls that must not run for real are the Linear ones.
#   `python3 - ASK-xxx`   the issue picker heredoc -> a fixed ready list
#   `python3 .../linear-sync.py`  progress notes    -> no-op
# Everything else -- crucially linear-claim.py, the subject of this test --
# is the real interpreter running the real script.
STUB="$WORK/bin"; mkdir -p "$STUB"
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '{"ready":[{"id":"%s","title":"t","project":"p"}],"total_open":1}\n' "\${2:-ASK-AAA}"
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF

# gh: no PR exists for these branches, and none may be created.
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF

# claude: THE WORK PHASE. Records the tree it was invoked in, which is the
# signal this whole test reads: a run that never reaches here was serialized out.
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
echo "\$(pwd)" >> "$WORK/worked.txt"
[ -n "\${STUB_HOLD:-}" ] && { touch "\$STUB_HOLD.started"; while [ ! -e "\$STUB_HOLD.go" ]; do sleep 0.05; done; }
exit 0
EOF
chmod +x "$STUB/python3" "$STUB/gh" "$STUB/claude"
export PATH="$STUB:$PATH"

[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub; worktrees must be real"

# run_worker <issue> <run-label> [hold-token]
# cwd is the skeleton on purpose: that is where launchd runs this from, and it
# is the cwd that made every issue share one lock.
run_worker() {
  local issue="$1" label="$2" hold="${3:-}"
  ( cd "$WORK/skel" \
    && KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state-$label" STUB_HOLD="$hold" \
       bash "$WORKER" --apply --issue "$issue" --limit 1 ) \
    >"$WORK/$label.out" 2>&1
  echo "$?" > "$WORK/$label.rc"
}

worked_count() { grep -c . "$WORK/worked.txt" 2>/dev/null || echo 0; }

# --- 1. TWO DIFFERENT ISSUES, CONCURRENTLY: both must reach the work phase ---
# A is held inside its work phase while B runs start-to-finish, so this is the
# real overlap, not two runs that merely happened not to collide.
: > "$WORK/worked.txt"
HOLD="$WORK/hold-a"
run_worker ASK-AAA a "$HOLD" &
A_PID=$!
DEADLINE=$((SECONDS + 60))
while [ ! -e "$HOLD.started" ]; do
  [ "$SECONDS" -ge "$DEADLINE" ] && fail "worker A never reached its work phase; see $(cat "$WORK/a.out" 2>/dev/null)"
  sleep 0.05
done

# A is inside its work phase RIGHT NOW, so this is the only window in which its
# claim is observable -- the worker releases at the end of the run. Assert the
# mechanism here: the lock is in A's own worktree and NOT at the skeleton root.
HELD_IN_TREE="$([ -f "$WORK/state-a/worktrees/ask-aaa/.linear-claims.json" ] && echo yes || echo no)"
HELD_AT_SKEL="$([ -f "$WORK/skel/.linear-claims.json" ] && echo yes || echo no)"

run_worker ASK-BBB b
touch "$HOLD.go"
wait "$A_PID"

grep -q "ask-aaa" "$WORK/worked.txt" || fail "worker A never worked: $(cat "$WORK/a.out")"
if ! grep -q "ask-bbb" "$WORK/worked.txt"; then
  fail "SERIALIZED: worker B on ASK-BBB never reached the work phase while A held
      the lock on ASK-AAA. B said: $(grep -i 'skip\|INFRA' "$WORK/b.out" | head -2)"
fi
ok "two workers on DIFFERENT issues both reached the work phase concurrently"

# --- 2. the lock landed in the issue's own worktree, not at the skeleton -----
# The mechanism behind case 1, asserted directly. A lock at the skeleton root is
# the defect itself: one file, every issue, total serialization.
[ "$HELD_IN_TREE" = "yes" ] \
  || fail "while ASK-AAA was being worked, no claim existed in its own worktree"
ok "the claim was held in the issue's OWN worktree while it was being worked"

[ "$HELD_AT_SKEL" = "no" ] \
  || fail "a claim was written at the skeleton root; that single file is what serialized the board"
ok "no claim was taken at the skeleton root"

# --- 3. release must key on the SAME tree the claim was taken in ------------
# A claim taken in one cwd and released in another does NOT error: release reads
# a different file, finds nothing, prints "not held" and exits 0, while the real
# lock sits in the worktree forever and wedges that issue permanently. So the
# proof is the lock files being gone after the runs, not the release's exit code.
for t in "$WORK/state-a/worktrees/ask-aaa" "$WORK/state-b/worktrees/ask-bbb" "$WORK/skel"; do
  held="$(cat "$t/.linear-claims.json" 2>/dev/null || echo '')"
  [ -z "$held" ] || fail "a claim was left behind in $t; the worker leaked a permanent lock: $held"
done
ok "both claims were released in the tree they were taken in (no leaked lock)"

# --- 4. SAME issue, concurrently: still a collision, exit 3, not a grant -----
# The mutex must not be weakened. Two workers on one issue share one worktree,
# so they must still contend -- and the skip must SAY so, not report infra.
: > "$WORK/worked.txt"
HOLD2="$WORK/hold-c"
run_worker ASK-CCC c "$HOLD2" &
C_PID=$!
DEADLINE=$((SECONDS + 60))
while [ ! -e "$HOLD2.started" ]; do
  [ "$SECONDS" -ge "$DEADLINE" ] && fail "worker C never reached its work phase"
  sleep 0.05
done

# d shares c's state dir, so it lands on the SAME worktree for the same issue.
( cd "$WORK/skel" \
  && KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state-c" \
     bash "$WORKER" --apply --issue ASK-CCC --limit 1 ) >"$WORK/d.out" 2>&1
touch "$HOLD2.go"
wait "$C_PID"

[ "$(worked_count)" = "1" ] \
  || fail "same-issue: $(worked_count) runs reached the work phase, want exactly 1 -- the mutex was weakened"
ok "same issue, same tree: exactly one worker reached the work phase"

grep -qi "claimed by another session" "$WORK/d.out" \
  || fail "the refused run did not report a collision. It said: $(grep -i 'skip\|INFRA' "$WORK/d.out" | head -2)"
ok "the refused run reports the collision (exit 3), not a generic infra failure"

# --- 5. the script still parses -------------------------------------------
bash -n "$WORKER" || fail "linear-worker.sh does not parse"
ok "linear-worker.sh parses (bash -n)"

echo "PASS: linear-worker parallel ($PASS checks)"
