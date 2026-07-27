#!/usr/bin/env bash
# Reproducer + acceptance criterion for "the worker never fetches" (ASK-208, sp-28ced3d6).
#
# THE DEFECT: linear-worker.sh contained no `git fetch` anywhere. It ran
#   git -C "$SKEL" worktree add -q -B "$BRANCH" "$TREE" origin/main
# against whatever local `origin/main` remote-tracking ref happened to exist, so
# the agent was dispatched against a base that could be arbitrarily old.
#
# OBSERVED (2026-07-27): ASK-150 was dispatched to resolve a conflict against
# main, merged 3b60af0, and the conflict survived -- main was already 72c782d.
# The agent did the right thing to the wrong target and two rounds were burned.
#
# WHY THIS DRIVES THE REAL SCRIPT: the bug is a missing side effect, and the
# thing that proves it is the SHA the worktree actually landed on. A grep for
# "git fetch" in the source would pass on a fetch placed after the worktree is
# created -- i.e. on a script that still has the bug. So this stales the local
# remote-tracking ref for real and reads back where the tree was based.
#
# Isolation: KIPI_SKEL / KIPI_STATE_DIR / HOME all point inside a temp dir, and
# python3 / gh / claude are stubbed. `git` stays REAL: real refs are the subject.
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
unset KIPI_LINEAR_CLAIMS KIPI_SESSION_ID CLAUDE_SESSION_ID 2>/dev/null || true

# HOME is redirected because the run must not be able to reach the founder's
# real ~/.config/kipi (pr-review-agent.sh writes there). Identity therefore has
# to be passed per-command rather than read from a global config.
G() { git -c user.email=t@t.t -c user.name=t "$@"; }

# --- a skeleton whose origin/main ref is STALE ------------------------------
git init -q --bare "$WORK/origin"
# The bare repo's default HEAD is refs/heads/master, so a clone of it would land
# on an unborn branch and its push would fail -- leaving the "true remote head"
# this test asserts against sitting in a clone that never reached origin.
git -C "$WORK/origin" symbolic-ref HEAD refs/heads/main
git init -q "$WORK/skel"
G -C "$WORK/skel" commit -q --allow-empty -m c1
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "$WORK/origin"
git -C "$WORK/skel" push -q -u origin main
C1="$(git -C "$WORK/skel" rev-parse HEAD)"

# A DIFFERENT clone advances the real remote. $WORK/skel is never told.
git clone -q "$WORK/origin" "$WORK/other"
G -C "$WORK/other" commit -q --allow-empty -m c2
git -C "$WORK/other" push -q origin main
C2="$(git -C "$WORK/other" rev-parse HEAD)"

[ "$C1" != "$C2" ] || fail "fixture: the remote did not actually advance"
[ "$(git -C "$WORK/skel" rev-parse origin/main)" = "$C1" ] \
  || fail "fixture: skel's origin/main was not stale to begin with"

# --- stubs ------------------------------------------------------------------
STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home"
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
# No PR exists and none may be created.
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/gh"
# The work phase is a no-op: this test asks only where the tree was based.
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/claude"
chmod +x "$STUB/python3" "$STUB/gh" "$STUB/claude"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub; real refs are the subject"

# cwd is the skeleton, which is where launchd runs this from.
( cd "$WORK/skel" \
  && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state" \
     bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) >"$WORK/run.out" 2>&1
RC=$?

TREE="$WORK/state/worktrees/ask-aaa"
[ -d "$TREE" ] || fail "no worktree was created (rc=$RC): $(tail -5 "$WORK/run.out")"

# --- 1. the tree is based on the TRUE remote head, not the stale local ref ---
BASE="$(git -C "$TREE" rev-parse HEAD)"
if [ "$BASE" = "$C1" ]; then
  fail "STALE BASE: the worktree was cut from the stale origin/main ($C1).
      The true remote head is $C2. The worker branched without fetching, which is
      how ASK-150 resolved a conflict against a main that had already moved."
fi
[ "$BASE" = "$C2" ] || fail "worktree base $BASE is neither the stale ref nor the remote head $C2"
ok "the worktree was cut from the TRUE remote head (fetch happened before worktree add)"

# --- 2. the local remote-tracking ref was actually updated ------------------
# The mechanism behind case 1, asserted directly: a fetch that did not move
# refs/remotes/origin/main would leave every later `origin/main..HEAD` count wrong.
[ "$(git -C "$WORK/skel" rev-parse origin/main)" = "$C2" ] \
  || fail "refs/remotes/origin/main in the skeleton was not updated by the run"
ok "the skeleton's refs/remotes/origin/main was updated to the remote head"

# --- 3. ONE fetch per run, not one per issue -------------------------------
# Counted by wrapping git in a counting stub for a 2-issue run. A per-issue fetch
# is a real cost on a 50-issue board and the DoR asks for one.
CSTUB="$WORK/bin2"; mkdir -p "$CSTUB"
cat > "$CSTUB/git" <<EOF
#!/usr/bin/env bash
for a in "\$@"; do [ "\$a" = "fetch" ] && { echo x >> "$WORK/fetches.txt"; break; }; done
exec "$REAL_GIT" "\$@"
EOF
chmod +x "$CSTUB/git"
: > "$WORK/fetches.txt"
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '{"ready":[{"id":"ASK-AAA","title":"t","project":"p"},{"id":"ASK-BBB","title":"t","project":"p"}],"total_open":2}\n'
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
( cd "$WORK/skel" \
  && PATH="$CSTUB:$PATH" HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state2" \
     bash "$WORKER" --apply --limit 2 ) >"$WORK/run2.out" 2>&1

FETCHES="$(grep -c . "$WORK/fetches.txt" 2>/dev/null || echo 0)"
[ "${FETCHES:-0}" -ge 1 ] || fail "a 2-issue run performed no fetch at all"
[ "${FETCHES:-0}" -le 1 ] \
  || fail "a 2-issue run fetched $FETCHES times; the DoR asks for one fetch per run, not per issue"
ok "a 2-issue run fetched exactly once"

# --- 4. the script still parses --------------------------------------------
bash -n "$WORKER" || fail "linear-worker.sh does not parse"
ok "linear-worker.sh parses (bash -n)"

echo "PASS: linear-worker fetch ($PASS checks)"
