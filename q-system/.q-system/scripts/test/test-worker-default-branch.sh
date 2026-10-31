#!/usr/bin/env bash
# Reproducer + acceptance for ASK-3550: the worker hardcoded origin/main.
#
# THE DEFECT, measured 2026-10-31: two client repos opted in under
# RULE-2026-10-30-A have default branch `master` and no origin/main at all.
# linear-worker.sh cut every issue tree from "origin/main" and opened every PR
# with `--base main`, so in those repos `git worktree add` failed on every issue
# ("INFRA: could not create worktree") and no work could ever start.
#
# What this asserts, through the REAL worker with git real and gh/claude/python3
# stubbed (same harness shape as test-gh-repo-scope-worker.sh):
#   A. origin/HEAD -> master: the issue branch is cut from origin/master and the
#      PR the worker opens targets master.
#   B. origin/HEAD unset: the remote's own HEAD (ls-remote) answers master.
#   C. origin/HEAD unset and the remote's HEAD dangles: GitHub's answer is used.
#   D. nobody answers: the worker refuses to cut a tree (fail closed) and says why.
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
unset KIPI_LINEAR_CLAIMS KIPI_SESSION_ID CLAUDE_SESSION_ID KIPI_TARGET_REPO KIPI_DISPATCH_TARGETS 2>/dev/null || true

G() { git -c user.email=t@t.t -c user.name=t "$@"; }
STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home"

# mkrepo <dir> <name> <default-branch>: a bare origin whose HEAD is <default>,
# reached through insteadOf so the configured URL stays github-shaped.
mkrepo() {
  git init -q --bare "$WORK/origin-$2.git"
  git -C "$WORK/origin-$2.git" symbolic-ref HEAD "refs/heads/$3"
  git init -q "$1"
  git -C "$1" config "url.$WORK/origin-.insteadOf" "https://github.com/assafkip/"
  G -C "$1" commit -q --allow-empty -m c1
  git -C "$1" branch -M "$3"
  git -C "$1" remote add origin "https://github.com/assafkip/$2.git"
  git -C "$1" push -q -u origin "$3"
}
mkrepo "$WORK/skel" homerepo main

# The fake gh logs argv. `api repos/<slug>` answers the default branch from
# $GH_DEFAULT (empty means GitHub gave no answer). No PR exists anywhere.
GH_LOG="$WORK/gh.txt"
cat > "$STUB/gh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$GH_LOG"
case "\$*" in
  "api repos/"*default_branch*) [ -n "\${GH_DEFAULT:-}" ] && echo "\$GH_DEFAULT"; exit 0 ;;
esac
exit 0
EOF
chmod +x "$STUB/gh"
# The agent stub makes one commit in its worktree, so the worker has something
# to push and a PR to open.
cat > "$STUB/claude" <<'EOF'
#!/usr/bin/env bash
git -c user.email=t@t.t -c user.name=t commit -q --allow-empty -m "agent work"
exit 0
EOF
chmod +x "$STUB/claude"
cat > "$STUB/reviewer-noop" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
chmod +x "$STUB/reviewer-noop"
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '%s\n' '{"ready":[{"id":"ASK-MMM","title":"t","project":"targetproj"}],"total_open":1}'
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
chmod +x "$STUB/python3"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub; real remotes are the subject"

# run_case <name> <origin-head:set|unset|dangle> <gh-default>
# dangle = origin/HEAD unset AND the bare origin's HEAD names a branch that does
# not exist, so neither local source can answer.
run_case() {
  local name="$1" head="$2" ghdef="$3" tgt="$WORK/target-$1"
  mkrepo "$tgt" "target$1" master
  [ "$head" = "dangle" ] && git -C "$WORK/origin-target$1.git" symbolic-ref HEAD refs/heads/nope
  if [ "$head" = "set" ]; then
    git -C "$tgt" remote set-head origin master
  else
    git -C "$tgt" remote set-head origin -d >/dev/null 2>&1 || true
  fi
  cat > "$WORK/skel/instance-registry.json" <<JSON
{"instances":[{"name":"targetproj","path":"$tgt","has_git":true,
  "dispatch":{"enabled":true,"expected_remote":"https://github.com/assafkip/target$1.git"}}]}
JSON
  : > "$GH_LOG"
  ( cd "$WORK/skel" \
    && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state-$1" \
       KIPI_NOTIFY="/usr/bin/true" KIPI_PR_REVIEWER="$STUB/reviewer-noop" \
       KIPI_LINEAR_PROJECT="targetproj" GH_DEFAULT="$ghdef" \
       bash "$WORKER" --apply --repo "$tgt" --issue ASK-MMM --limit 1 \
  ) >"$WORK/run-$1.out" 2>&1
  echo $? > "$WORK/rc-$1"
}

# --- A. origin/HEAD names master ---------------------------------------------
run_case A set ""
grep -qE 'pr create .*--base master( |$)' "$GH_LOG" \
  || fail "A: the worker did not open its PR against master. gh calls:
$(sed 's/^/        /' "$GH_LOG")
      worker output:
$(tail -12 "$WORK/run-A.out")"
ok "A: the PR the worker opens targets master, the repo's default branch"
MASTER_TIP="$(git -C "$WORK/origin-targetA.git" rev-parse master)"
PUSHED="$(git -C "$WORK/origin-targetA.git" for-each-ref --format='%(refname:short)' refs/heads | grep -v '^master$' | head -1)"
[ -n "$PUSHED" ] || fail "A: no issue branch reached origin. Output:
$(tail -12 "$WORK/run-A.out")"
[ "$(git -C "$WORK/origin-targetA.git" rev-parse "$PUSHED^")" = "$MASTER_TIP" ] \
  || fail "A: the issue branch $PUSHED was not cut from origin/master"
ok "A: the issue branch was cut from origin/master"
grep -q 'origin/main' "$WORK/run-A.out" \
  && fail "A: the worker still names origin/main for a master repo:
$(grep -n 'origin/main' "$WORK/run-A.out" | head -3)"
ok "A: nothing in the run names origin/main"

# --- B. origin/HEAD unset, the remote's HEAD answers -------------------------
run_case B unset ""
grep -qE 'pr create .*--base master( |$)' "$GH_LOG" \
  || fail "B: with origin/HEAD unset the worker did not read the remote's HEAD. Output:
$(tail -12 "$WORK/run-B.out")"
grep -q 'api repos/' "$GH_LOG" \
  && fail "B: the worker asked GitHub although the remote's HEAD already answered"
ok "B: with origin/HEAD unset, the remote's own HEAD gives master, no API call"

# --- C. both local sources fail, GitHub answers --------------------------------
run_case C dangle master
grep -qE 'pr create .*--base master( |$)' "$GH_LOG" \
  || fail "C: with no local answer the worker did not use GitHub's default branch. Output:
$(tail -12 "$WORK/run-C.out")"
ok "C: with no local answer, the default branch comes from GitHub"

# --- D. nobody can say: fail closed ------------------------------------------
run_case D dangle ""
grep -q 'pr create' "$GH_LOG" \
  && fail "D: the worker opened a PR although it could not determine the default branch"
[ ! -d "$WORK/state-D/worktrees/ASK-MMM" ] \
  || fail "D: the worker cut an issue tree with no known base branch"
grep -q 'default branch' "$WORK/run-D.out" \
  || fail "D: the refusal does not say why. Output:
$(tail -8 "$WORK/run-D.out")"
[ "$(cat "$WORK/rc-D")" != "0" ] || fail "D: the worker exited 0 after refusing to work"
ok "D: no default branch means no tree, no PR, a stated reason and a non-zero exit"

echo "PASS ($PASS checks) test-worker-default-branch.sh"
