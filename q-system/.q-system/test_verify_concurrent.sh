#!/usr/bin/env bash
# Concurrency test for verify.sh --staged (ASK-1900).
#
# THE FAILURE THIS PINS. Four times in one evening, in two different worktrees of
# one repo, `git commit` was refused by lefthook's verify step in 0.10-0.17s --
# faster than any check can run -- and the identical commit succeeded on a retry
# with nothing changed. The refusal text said the change "will not pass later",
# which is false: nothing about the staged content was wrong. Two other sessions
# were active on the same repo.
#
# `verify.sh --staged` registers a throwaway worktree, and the NAME git derives
# for it is the basename of the path. mktemp -d gives a unique parent, so the
# basename was the constant `wt` for every run in the fleet. Two runs racing on
# one repo therefore raced on ONE name in the shared .git/worktrees, and the
# loser got "fatal: '.../wt' is already registered" or lost its metadata to the
# winner's prune.
#
# Same shape as the adversarial suite next door: fresh throwaway repos, the real
# script, assert the exit code. No mocks.
set -uo pipefail
VERIFY_SRC="${1:?usage: test_verify_concurrent.sh /path/to/verify.sh}"
SELECT_SRC="$(dirname "$VERIFY_SRC")/verify_select.py"
pass=0; fail=0

check() {
  if [ "$2" = "$3" ]; then printf '  PASS  %-44s %s\n' "$1" "$3"; pass=$((pass+1))
  else printf '  FAIL  %-44s got=%s want=%s\n' "$1" "$3" "$2"; fail=$((fail+1)); fi
}

# One repo, N worktrees of it, each with something staged. This is the real
# topology: the founder runs one session per worktree off a shared object store.
newrepo_with_worktrees() {
  local n="$1" d i
  d="$(mktemp -d)"
  git -C "$d/" init -q main-checkout 2>/dev/null || { mkdir -p "$d/main-checkout"; git -C "$d/main-checkout" init -q; }
  local R="$d/main-checkout"
  git -C "$R" config user.email t@t; git -C "$R" config user.name t
  mkdir -p "$R/q-system/.q-system"
  cp "$VERIFY_SRC" "$R/q-system/.q-system/verify.sh"
  if [ -f "$SELECT_SRC" ]; then cp "$SELECT_SRC" "$R/q-system/.q-system/verify_select.py"; fi
  printf "print('ok')\n" > "$R/good.py"
  # A tracked .json and .sh, same as the adversarial suite's fixture. NOT padding:
  # with no tracked .json the JSONFILES `grep -v` matches nothing, exits 1, and
  # under `set -euo pipefail` that kills verify.sh at exit 1 with no diagnosis --
  # which is the very symptom under test and would mask the concurrency result.
  # Case 4 below pins that separately.
  printf '{"a": 1}\n' > "$R/good.json"
  printf 'echo hi\n'  > "$R/good.sh"
  git -C "$R" add -A; git -C "$R" commit -qm init
  for i in $(seq 1 "$n"); do
    git -C "$R" worktree add -q --detach "$d/wt-$i" HEAD
    printf "print('session %s')\n" "$i" > "$d/wt-$i/staged-$i.py"
    git -C "$d/wt-$i" add "staged-$i.py"
  done
  printf '%s' "$d"
}

# --- CASE 1: two --staged runs started at the same instant ------------------
# Today at least one is expected to exit non-zero in well under a second with no
# check output. Done means both print "verify.sh ok".
D="$(newrepo_with_worktrees 2)"
( cd "$D/wt-1" && bash q-system/.q-system/verify.sh --staged >"$D/out1" 2>&1 ) &
P1=$!
( cd "$D/wt-2" && bash q-system/.q-system/verify.sh --staged >"$D/out2" 2>&1 ) &
P2=$!
wait $P1; RC1=$?
wait $P2; RC2=$?
check "2 concurrent --staged: run 1 exits 0" 0 "$RC1"
check "2 concurrent --staged: run 2 exits 0" 0 "$RC2"
for i in 1 2; do
  if grep -q '^verify.sh ok' "$D/out$i"; then
    check "2 concurrent --staged: run $i ran checks" 0 0
  else
    printf '    --- run %s output ---\n' "$i"; sed 's/^/    /' "$D/out$i"
    check "2 concurrent --staged: run $i ran checks" 0 1
  fi
done
rm -rf "$D"

# --- CASE 2: four at once, the observed fleet load -------------------------
# Two sessions plus the dispatcher plus a worker is four writers on one repo.
D="$(newrepo_with_worktrees 4)"
PIDS=()
for i in 1 2 3 4; do
  ( cd "$D/wt-$i" && bash q-system/.q-system/verify.sh --staged >"$D/out$i" 2>&1 ) &
  PIDS+=($!)
done
bad=0
for idx in 0 1 2 3; do
  wait "${PIDS[$idx]}" || bad=$((bad+1))
done
check "4 concurrent --staged: zero failures" 0 "$bad"
if [ "$bad" -ne 0 ]; then
  for i in 1 2 3 4; do
    printf '    --- run %s ---\n' "$i"; sed 's/^/    /' "$D/out$i"
  done
fi
# A leaked registration is the other half of the same bug: every --staged run
# must leave the shared worktree list exactly as it found it.
LEFT="$(git -C "$D/main-checkout" worktree list | grep -c '/wt$\|verify' || true)"
check "4 concurrent --staged: no leaked wt registration" 0 "$LEFT"
rm -rf "$D"

# --- CASE 3: a --staged run beside a plain `git worktree add` --------------
# The prune in verify.sh's EXIT trap runs against the SHARED metadata, so it can
# reach a registration another process is midway through creating.
D="$(newrepo_with_worktrees 1)"
( cd "$D/wt-1" && bash q-system/.q-system/verify.sh --staged >"$D/outv" 2>&1 ) &
PV=$!
( git -C "$D/main-checkout" worktree add -q --detach "$D/other" HEAD >"$D/outw" 2>&1 ) &
PW=$!
wait $PV; RCV=$?
wait $PW; RCW=$?
check "--staged beside a real worktree add: verify ok" 0 "$RCV"
check "--staged beside a real worktree add: add ok" 0 "$RCW"
[ "$RCV" = 0 ] || sed 's/^/    /' "$D/outv"
[ "$RCW" = 0 ] || sed 's/^/    /' "$D/outw"
rm -rf "$D"

# --- CASE 4: a held index.lock -------------------------------------------
# The pinpointed cause. `git write-tree` takes index.lock with LOCK_DIE_ON_ERROR,
# so one sibling holding it for milliseconds killed the script at its second
# command. Measured before the fix: exit 128 in 0.04s, ZERO check output.
D="$(newrepo_with_worktrees 1)"
: > "$D/main-checkout/.git/worktrees/wt-1/index.lock"
( cd "$D/wt-1" && bash q-system/.q-system/verify.sh --staged >"$D/outl" 2>&1 )
RCL=$?
check "index.lock held: still exits 0 (reads a copy)" 0 "$RCL"
if grep -q '^verify.sh ok' "$D/outl"; then
  check "index.lock held: checks actually ran" 0 0
else
  sed 's/^/    /' "$D/outl"; check "index.lock held: checks actually ran" 0 1
fi
rm -f "$D/main-checkout/.git/worktrees/wt-1/index.lock"
rm -rf "$D"

# --- CASE 5: a collision is named a collision, never a failed check --------
# The snapshot machinery can still lose a race this script does not own, so the
# classification has to be exercised, not just the avoidance. A directory sitting
# where the throwaway worktree goes makes `worktree add` clash on shared state.
# 75 is EX_TEMPFAIL: non-zero (the commit is still refused) and distinguishable
# from 1 (a real check failed), which is what lets a caller tell retry from edit.
#
# The lever is a `git` STUB ON PATH that fails only `worktree add` with git's own
# lock wording and execs the real binary for everything else. Stubbing the
# external tool keeps the test-only branch OUT of verify.sh -- a production script
# carrying a `if $KIPI_FORCE_...` hook is a second code path nobody runs in anger.
D="$(newrepo_with_worktrees 1)"
REALGIT="$(command -v git)"
mkdir -p "$D/stub"
{
  # SCAN EVERY ARG, never just $1: verify.sh calls `git -C "$REPO" worktree add`,
  # so the subcommand is not in position 1. The first version of this stub checked
  # $1/$2, never matched, and the case passed at exit 0 -- a test that measured
  # nothing while looking green.
  echo '#!/usr/bin/env bash'
  echo 'prev=""'
  echo 'for a in "$@"; do'
  echo '  if [ "$prev" = "worktree" ] && [ "$a" = "add" ]; then'
  echo '    echo "fatal: Unable to create '"'"'.git/worktrees/wt/index.lock'"'"': File exists." >&2'
  echo '    exit 128'
  echo '  fi'
  echo '  prev="$a"'
  echo 'done'
  echo "exec $REALGIT \"\$@\""
} > "$D/stub/git"
chmod +x "$D/stub/git"
OUT="$( cd "$D/wt-1" && PATH="$D/stub:$PATH" \
        bash q-system/.q-system/verify.sh --staged 2>&1 )"
RCC=$?
check "forced worktree clash: exit 75, not 1" 75 "$RCC"
if printf '%s' "$OUT" | grep -q 'COLLISION, not a failed check'; then
  check "forced worktree clash: named a collision" 0 0
else
  printf '%s\n' "$OUT" | sed 's/^/    /'
  check "forced worktree clash: named a collision" 0 1
fi
if printf '%s' "$OUT" | grep -q 'NOTHING WAS CHECKED'; then
  check "forced worktree clash: says no verdict reached" 0 0
else
  check "forced worktree clash: says no verdict reached" 0 1
fi
rm -rf "$D"

# --- CASE 6: no tracked .json is not a silent exit 1 ----------------------
# The other route to the same symptom. `grep -v` matching nothing returns 1, and
# under `set -euo pipefail` that killed the script with no message at all.
D="$(mktemp -d)"
git -C "$D" init -q
git -C "$D" config user.email t@t; git -C "$D" config user.name t
mkdir -p "$D/q-system/.q-system"
cp "$VERIFY_SRC" "$D/q-system/.q-system/verify.sh"
[ -f "$SELECT_SRC" ] && cp "$SELECT_SRC" "$D/q-system/.q-system/verify_select.py"
printf "print('ok')\n" > "$D/good.py"
git -C "$D" add -A; git -C "$D" commit -qm init
OUT="$( cd "$D" && bash q-system/.q-system/verify.sh --full 2>&1 )"
RCJ=$?
check "repo with no tracked .json: --full exits 0" 0 "$RCJ"
if printf '%s' "$OUT" | grep -q '^verify.sh ok'; then
  check "repo with no tracked .json: reached its summary" 0 0
else
  printf '%s\n' "$OUT" | sed 's/^/    /'
  check "repo with no tracked .json: reached its summary" 0 1
fi
rm -rf "$D"

echo
echo "concurrent: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
