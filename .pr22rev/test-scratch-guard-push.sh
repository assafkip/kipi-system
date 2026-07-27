#!/usr/bin/env bash
# Reproducer + acceptance criterion for "git commit --no-verify bypasses the
# scratch guard, and the prompt names the mechanism" (ASK-208, PR #22 review
# round 4, finding 3).
#
# THE DEFECT, in two halves:
#
#   a) The guard was a pre-commit hook and nothing else. `git commit -n` walked
#      straight past it -- measured by the reviewer end to end: the same staged
#      scratch file the guard had just refused went in on the retry.
#
#   b) The agent prompt said "a commit hook in this worktree refuses them",
#      which is the standard cue for a model to reach for -n. Naming the
#      constraint without naming the mechanism costs nothing.
#
# WHY THE FIX IS NOT ONLY THE WORDING. Every git hook is bypassable, so this is
# not an argument against the design -- but a reworded prompt is prompt-only
# enforcement, which this repo does not accept as a fix. The guard is now
# installed as BOTH pre-commit and pre-push from one generator, so scratch that
# slipped past the commit gate is caught before it reaches the remote and the PR.
# That does not make it unbypassable (`git push --no-verify` exists); it makes
# one lazy -n insufficient, which is the shape actually observed.
#
# THE NEGATIVE CASES ARE ASSERTED HARDER THAN THE POSITIVE ONE. A pre-push hook
# that over-refuses stops every instance's agent from ever opening a PR, so case
# 2 pushes a real deliverable, case 4 sweeps every path tracked on main, and
# case 5 pins that an existing repo pre-push still runs.
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
G() { git -c user.email=t@t.t -c user.name=t "$@"; }

git init -q --bare "$WORK/origin"
git -C "$WORK/origin" symbolic-ref HEAD refs/heads/main
git init -q "$WORK/skel"
G -C "$WORK/skel" commit -q --allow-empty -m c1
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "$WORK/origin"
git -C "$WORK/skel" push -q -u origin main

STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home" "$WORK/state/pr-reviews"
cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '{"ready":[{"id":"ASK-AAA","title":"t","project":"p"}],"total_open":1}\n'
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "pr list"*)                      echo 888 ;;
  "pr view 888 --json mergeable"*) echo MERGEABLE ;;
esac
exit 0
EOF
# The agent's whole prompt is the only honest witness for half (b): the claim is
# about what the agent is TOLD, so grepping the generator's source would prove
# nothing about the string that actually reaches the model.
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
case "\$*" in
  *"You are Sana"*) printf '%s\n' "\$*" >> "$WORK/prompts.txt" ;;
esac
exit 0
EOF
chmod +x "$STUB/python3" "$STUB/gh" "$STUB/claude"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub; real hooks are the subject"

printf '{"verdict":"REQUEST CHANGES","pr":888}\n' > "$WORK/state/pr-reviews/pr-888.verdict.json"
: > "$WORK/prompts.txt"; : > "$WORK/run.out"
( cd "$WORK/skel" \
  && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state" \
     bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) >>"$WORK/run.out" 2>&1

TREE="$WORK/state/worktrees/ask-aaa"
[ -d "$TREE" ] || fail "no worktree was created: $(tail -5 "$WORK/run.out")"
HOOKS="$(git -C "$TREE" config core.hooksPath)"
[ -n "$HOOKS" ] || fail "the worktree has no core.hooksPath; no guard was installed"

# --- 1. scratch committed with --no-verify cannot reach the remote ----------
# git's own property, stated rather than argued with: -n skips pre-commit. The
# question this case answers is what happens NEXT.
mkdir -p "$TREE/q-system/output"
printf 'print("one-off helper")\n' > "$TREE/q-system/output/ask208-helper.py"
G -C "$TREE" add -f q-system/output/ask208-helper.py
G -C "$TREE" commit -q --no-verify -m "wip: scratch via -n (ASK-208)" >"$WORK/commit-n.out" 2>&1 \
  || fail "the --no-verify commit itself failed; this case cannot measure the push gate:
      $(head -3 "$WORK/commit-n.out")"

BRANCH="$(git -C "$TREE" rev-parse --abbrev-ref HEAD)"
if G -C "$TREE" push -q origin "$BRANCH" >"$WORK/push-n.out" 2>&1; then
  fail "SCRATCH PUSHED: q-system/output/ask208-helper.py was committed with
      --no-verify and then pushed with nothing refusing it. The guard is a
      pre-commit hook only, so one -n puts agent scratch on the PR -- the exact
      shape of the seven files swept out of main in PR #20."
fi
ok "scratch committed with --no-verify is refused at push"

grep -qi "scratch" "$WORK/push-n.out" \
  || fail "the push refusal does not say why. It printed: $(head -3 "$WORK/push-n.out")"
ok "the push refusal names the reason (the agent can act on it, not just retry)"

# Back the offending commit out so the later cases push from a clean branch.
G -C "$TREE" reset -q --soft HEAD~1
G -C "$TREE" reset -q
"$REAL_PY" -c "import os; os.remove('$TREE/q-system/output/ask208-helper.py')"

# --- 2. a real deliverable still pushes ------------------------------------
# The negative self-test. A pre-push hook that over-refuses stops every agent in
# the fleet from opening a PR at all, which is strictly worse than the leak.
mkdir -p "$TREE/q-system/output/rca" "$TREE/q-system/.q-system/scripts"
printf '# rca\n'  > "$TREE/q-system/output/rca/rca-y-2026-07-27.md"
printf '# plan\n' > "$TREE/q-system/output/plan-y-2026-07-27.md"
printf 'x = 1\n'  > "$TREE/q-system/.q-system/scripts/real-harness.py"
G -C "$TREE" add -f q-system/output/rca/rca-y-2026-07-27.md \
                    q-system/output/plan-y-2026-07-27.md \
                    q-system/.q-system/scripts/real-harness.py
G -C "$TREE" commit -q -m "feat: real deliverables (ASK-208)" >"$WORK/commit-ok.out" 2>&1 \
  || fail "a legitimate commit was refused: $(head -5 "$WORK/commit-ok.out")"
G -C "$TREE" push -q origin "$BRANCH" >"$WORK/push-ok.out" 2>&1 \
  || fail "FALSE REFUSAL: a legitimate commit (an RCA, a top-level .md, a real
      harness) was blocked at push: $(head -5 "$WORK/push-ok.out")"
ok "an RCA, a top-level .md and a real harness still push"

# A second push onto an EXISTING remote branch takes the other code path (the
# remote sha is real, not all-zeros), so it is exercised rather than assumed.
printf '# more\n' >> "$TREE/q-system/output/rca/rca-y-2026-07-27.md"
G -C "$TREE" commit -q -am "feat: more (ASK-208)" >/dev/null 2>&1
G -C "$TREE" push -q origin "$BRANCH" >"$WORK/push-ok2.out" 2>&1 \
  || fail "the second push onto an existing remote branch was refused:
      $(head -5 "$WORK/push-ok2.out")"
ok "a follow-up push onto an existing remote branch is not refused"

# --- 3. one guard, two names ------------------------------------------------
# Two copies of the refusal regex that could drift apart is the defect, not the
# fix. They are generated from one heredoc and must stay byte-identical.
[ -x "$HOOKS/pre-push" ] || fail "no pre-push guard was installed in $HOOKS"
cmp -s "$HOOKS/pre-commit" "$HOOKS/pre-push" \
  || fail "pre-commit and pre-push differ; two copies of the scratch regex will drift"
ok "pre-commit and pre-push are the same generated guard, byte for byte"

# --- 4. the push guard refuses nothing main actually tracks ----------------
TRACKED="$(git -C "$ROOT" ls-files | wc -l | tr -d ' ')"
if ! git -C "$ROOT" ls-files | "$HOOKS/pre-push" --check-paths >"$WORK/sweep.out" 2>&1; then
  fail "FALSE POSITIVE: the push guard refuses paths main already tracks:
      $(head -5 "$WORK/sweep.out")"
fi
ok "the push guard refuses none of the $TRACKED paths tracked on main"

# --- 5. an existing pre-push still runs ------------------------------------
# Adding a gate must never subtract one. pre-push left the mirror allowlist when
# the guard took the name, so the delegation has to be real, not assumed.
COMMON="$(git -C "$TREE" rev-parse --git-common-dir)/hooks"
printf '#!/bin/sh\nexit 9\n' > "$COMMON/pre-push"
chmod +x "$COMMON/pre-push"
printf '# z\n' > "$TREE/q-system/output/plan-z-2026-07-27.md"
G -C "$TREE" add -f q-system/output/plan-z-2026-07-27.md
G -C "$TREE" commit -q -m "feat: z (ASK-208)" >/dev/null 2>&1
G -C "$TREE" push -q origin "$BRANCH" >"$WORK/push-chain.out" 2>&1 \
  && fail "the repo's own pre-push (exit 9) never ran; the guard replaced it
      instead of chaining to it"
ok "the repo's existing pre-push still runs after the guard (chained, not replaced)"
"$REAL_PY" -c "import os; os.remove('$COMMON/pre-push')"

# --- 6. the prompt states the rule without handing over the mechanism -------
[ -s "$WORK/prompts.txt" ] || fail "no agent prompt was captured; case 6 cannot measure anything"
grep -qi "no-verify" "$WORK/prompts.txt" \
  && fail "the prompt names --no-verify to the agent outright"
grep -qi "commit hook" "$WORK/prompts.txt" \
  && fail "the prompt tells the agent the constraint is a commit hook, which is the
      standard cue to reach for -n. State the rule, not the mechanism."
ok "the agent prompt does not name the hook as the mechanism"
grep -qi "refused" "$WORK/prompts.txt" \
  || fail "the prompt no longer tells the agent the commit WILL be refused; dropping
      the mechanism must not drop the constraint with it"
grep -q "q-system/output/" "$WORK/prompts.txt" \
  || fail "the prompt no longer names the directory the agent must keep clean"
ok "the prompt still states the rule and where working files go instead"

bash -n "$WORKER" || fail "linear-worker.sh does not parse"
ok "linear-worker.sh parses (bash -n)"

echo "PASS: scratch guard at push ($PASS checks)"
