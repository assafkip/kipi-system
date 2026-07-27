#!/usr/bin/env bash
# Reproducer + acceptance criterion for two ASK-208 defects that both live in
# what the worker hands its agent:
#
#   sp-fd76af2f  an operator directive dies after one round.
#     The rework spec was whatever the newest review .md said. Each round the
#     reviewer regenerates findings, so anything an operator injected was
#     silently replaced. OBSERVED: a REQUEST CHANGES verdict scoped to "resolve
#     the merge conflict, nothing else" dispatched round 1; the round-1 reviewer
#     wrote its own findings, and rounds 1 and 2 both did code polish while the
#     conflict -- the only merge blocker -- was never touched.
#
#   sp-1aae7516  the worker commits its own scratch.
#     Seven agent working files reached main through PRs #18 and #19 before being
#     swept in #20: per-run helper scripts, message drafts, and a reproducer
#     whose default target was never on the branch. It recurred in three
#     consecutive PRs, which makes it a process defect, not an accident.
#
# The scratch shape is derived from the real payload, not invented: all seven
# were dropped directly at the root of q-system/output/ with .py/.sh/.txt
# extensions, and NO such file has ever been legitimately tracked there (the 24
# tracked top-level files are .md/.patch/.out/.err). Case 6 re-proves that
# against every path tracked on main, so the guard cannot quietly widen.
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
git init -q "$WORK/skel"
G -C "$WORK/skel" commit -q --allow-empty -m c1
git -C "$WORK/skel" branch -M main
git -C "$WORK/skel" remote add origin "$WORK/origin"
git -C "$WORK/skel" push -q -u origin main

STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home" "$WORK/state/pr-reviews" "$WORK/state/directives"
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
cat > "$STUB/gh" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  "pr list"*)                    echo 888 ;;
  "pr view 888 --json mergeable"*) echo MERGEABLE ;;
esac
exit 0
EOF
# THE PROBE: the agent's whole prompt, captured per round. The directive claim is
# about what the agent is actually told, so the prompt is the only honest witness.
# Only the WORKER's prompt counts. pr-review-agent.sh drives claude too, so
# counting every invocation would report two rounds as four and the directive
# assertion would be measuring the reviewer.
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
ARGS="\$*"
case "\$ARGS" in
  *"You are Sana"*) { echo "=== PROMPT ROUND ==="; printf '%s\n' "\$ARGS"; } >> "$WORK/prompts.txt" ;;
esac
exit 0
EOF
chmod +x "$STUB/python3" "$STUB/gh" "$STUB/claude"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub; real hooks are the subject"

DIRECTIVE="RESOLVE THE MERGE CONFLICT AND NOTHING ELSE (operator, round zero)"
printf '%s\n' "$DIRECTIVE" > "$WORK/state/directives/ask-aaa.md"

run_round() {
  # A fresh REQUEST CHANGES record each round: this models the reviewer
  # regenerating its findings, which is exactly what used to erase the directive.
  printf '{"verdict":"REQUEST CHANGES","pr":888}\n' > "$WORK/state/pr-reviews/pr-888.verdict.json"
  ( cd "$WORK/skel" \
    && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state" \
       bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) >>"$WORK/run.out" 2>&1
}

: > "$WORK/prompts.txt"; : > "$WORK/run.out"
run_round
run_round

ROUNDS="$(grep -c '=== PROMPT ROUND ===' "$WORK/prompts.txt" 2>/dev/null || echo 0)"
[ "${ROUNDS:-0}" = "2" ] \
  || fail "expected 2 rework rounds to reach the agent, got ${ROUNDS:-0}: $(tail -5 "$WORK/run.out")"
ok "two rework rounds reached the agent"

# --- 1. the directive survives BOTH rounds, verbatim ------------------------
SEEN="$(grep -c -F "$DIRECTIVE" "$WORK/prompts.txt" 2>/dev/null || echo 0)"
if [ "${SEEN:-0}" -lt 2 ]; then
  fail "DIRECTIVE LOST: the operator directive appeared in ${SEEN:-0} of 2 rework
      prompts. The review regenerated its findings and replaced it -- the exact
      failure where 'resolve the merge conflict, nothing else' was overwritten
      and two rounds did code polish instead."
fi
ok "the operator directive appears verbatim in BOTH rework prompts"

# --- 2. the directive does not replace the review ---------------------------
# "alongside the findings, not instead of them" -- a directive that suppressed
# the review would trade one lost spec for another.
grep -q "THIS IS A REWORK" "$WORK/prompts.txt" \
  || fail "the rework framing vanished; the directive must sit ALONGSIDE the review, not replace it"
ok "the rework framing survives alongside the directive"

# --- 3. no directive file -> no phantom directive block ---------------------
python3 -c "import os; os.remove('$WORK/state/directives/ask-aaa.md')"
: > "$WORK/prompts.txt"
run_round
grep -q -F "$DIRECTIVE" "$WORK/prompts.txt" \
  && fail "a deleted directive still reached the prompt; it must be clearable"
ok "removing the directive file clears it from the next prompt"

# --- 4. the worktree refuses a scratch-shaped commit ------------------------
TREE="$WORK/state/worktrees/ask-aaa"
[ -d "$TREE" ] || fail "no worktree was created: $(tail -5 "$WORK/run.out")"
mkdir -p "$TREE/q-system/output"
printf 'print("one-off helper")\n' > "$TREE/q-system/output/ask208-triage.py"
G -C "$TREE" add -f q-system/output/ask208-triage.py
if G -C "$TREE" commit -q -m "wip: scratch (ASK-208)" >"$WORK/commit.out" 2>&1; then
  fail "SCRATCH COMMITTED: q-system/output/ask208-triage.py was accepted. That is
      the exact shape of the seven files swept out of main in PR #20."
fi
ok "a scratch-shaped path at the root of q-system/output/ is refused at commit"

grep -qi "scratch" "$WORK/commit.out" \
  || fail "the refusal did not say why. It printed: $(head -3 "$WORK/commit.out")"
ok "the refusal names the reason (so the agent can act on it, not just retry)"

G -C "$TREE" reset -q

# --- 5. real deliverables still commit --------------------------------------
# A wrong refusal here stalls every instance's worker, so the negative case is
# asserted as hard as the positive one.
mkdir -p "$TREE/q-system/output/rca" "$TREE/q-system/.q-system/scripts"
printf '# rca\n'  > "$TREE/q-system/output/rca/rca-x-2026-07-27.md"
printf '# plan\n' > "$TREE/q-system/output/plan-x-2026-07-27.md"
printf 'x = 1\n'  > "$TREE/q-system/.q-system/scripts/real-harness.py"
G -C "$TREE" add -f q-system/output/rca/rca-x-2026-07-27.md \
                    q-system/output/plan-x-2026-07-27.md \
                    q-system/.q-system/scripts/real-harness.py
G -C "$TREE" commit -q -m "feat: real deliverables (ASK-208)" >"$WORK/commit-ok.out" 2>&1 \
  || fail "a legitimate commit was refused: $(head -5 "$WORK/commit-ok.out")"
ok "an RCA, a top-level .md and a real harness still commit"

# --- 6. the guard refuses nothing that main actually tracks -----------------
# The negative self-test at scale: every path tracked on the REAL repo, piped
# through the REAL installed hook. One false positive here wedges the fleet.
HOOK="$(git -C "$TREE" config core.hooksPath)/pre-commit"
[ -x "$HOOK" ] || fail "no scratch guard was installed in the worktree"
TRACKED="$(git -C "$ROOT" ls-files | wc -l | tr -d ' ')"
if ! git -C "$ROOT" ls-files | "$HOOK" --check-paths >"$WORK/sweep.out" 2>&1; then
  fail "FALSE POSITIVE: the guard refuses paths that main already tracks:
      $(head -5 "$WORK/sweep.out")"
fi
ok "the guard refuses none of the $TRACKED paths tracked on main"

# --- 7. the guard must not disable the repo's other hooks -------------------
# core.hooksPath is per-worktree, so a naive install would silently switch off
# lefthook -- taking gitleaks and the commit-msg linear gate with it. Quieting a
# gate to add a gate is a net loss, so the passthrough is asserted.
COMMON="$(git -C "$TREE" rev-parse --git-common-dir)/hooks"
printf '#!/bin/sh\nexit 9\n' > "$COMMON/pre-commit"
chmod +x "$COMMON/pre-commit"
printf 'ok\n' > "$TREE/q-system/output/plan-y-2026-07-27.md"
G -C "$TREE" add -f q-system/output/plan-y-2026-07-27.md
G -C "$TREE" commit -q -m "feat: y (ASK-208)" >"$WORK/commit-chain.out" 2>&1 \
  && fail "the repo's own pre-commit (exit 9) never ran; the guard replaced lefthook instead of chaining to it"
ok "the repo's existing pre-commit still runs after the guard (chained, not replaced)"

# --- 8. the founder's main checkout is untouched ---------------------------
[ -z "$(git -C "$WORK/skel" config core.hooksPath || true)" ] \
  || fail "core.hooksPath leaked to the main checkout; the founder's commits would hit the agent's guard"
ok "the main checkout's core.hooksPath is untouched (per-worktree only)"

# --- 9. the directive has a PRODUCER, not just a reader ---------------------
# Round-3 review, finding 3: $KIPI_STATE_DIR/directives/<issue>.md shipped with a
# reader and nothing anywhere that writes one. The kipi CLI had zero occurrences
# of "directive" and DIRECTIVES_DIR was the one path constant never passed to
# mkdir -p, so the feature worked only for someone who had read linear-worker.sh
# and inferred the path convention by hand. wiring-check.md: a new state file
# needs both a producer and a consumer.
#
# BOTH ENDS IN ONE TEST on purpose. This is a cross-process handshake -- a CLI
# writes, a worker reads -- and a test that pins only one end passes happily
# while the two disagree about the path.
KIPI="$ROOT/kipi"
[ -x "$KIPI" ] || fail "the kipi CLI is not executable at $KIPI"
CLI_TEXT="DIRECTIVE SET THROUGH THE CLI, NOT BY HAND (round 3)"

KIPI_STATE_DIR="$WORK/state" bash "$KIPI" directive ASK-AAA "$CLI_TEXT" >"$WORK/cli.out" 2>&1 \
  || fail "kipi directive exited non-zero: $(cat "$WORK/cli.out")"
[ -s "$WORK/state/directives/ask-aaa.md" ] \
  || fail "NO PRODUCER: kipi directive wrote nothing to the path the worker reads
      ($WORK/state/directives/ask-aaa.md). It printed: $(cat "$WORK/cli.out")"
ok "kipi directive writes the file the worker reads (producer exists)"

: > "$WORK/prompts.txt"
run_round
grep -q -F "$CLI_TEXT" "$WORK/prompts.txt" \
  || fail "HANDSHAKE BROKEN: the CLI wrote a directive the worker did not pick up.
      The two ends disagree about the path or the format."
ok "a directive set through the CLI reaches the agent's prompt verbatim"

KIPI_STATE_DIR="$WORK/state" bash "$KIPI" directive ASK-AAA --clear >"$WORK/cli-clear.out" 2>&1 \
  || fail "kipi directive --clear exited non-zero: $(cat "$WORK/cli-clear.out")"
: > "$WORK/prompts.txt"
run_round
grep -q -F "$CLI_TEXT" "$WORK/prompts.txt" \
  && fail "--clear did not clear: the directive still reached the prompt. A standing
      instruction that cannot be retired is worse than none."
ok "kipi directive --clear retires it, and the next prompt is clean"

# The directory has to exist for the path to be usable at all -- including by an
# operator who edits the file directly rather than going through the CLI.
[ -d "$WORK/state/directives" ] \
  || fail "the directives directory does not exist after a worker run"
ok "the worker creates the directives directory it reads from"

# --- 10. the hook mirror copies only hooks git will actually invoke ----------
# Round-3 review, finding 5 (nit): the mirror used a suffix DENYLIST
# (*.sample|*.old|*.bak|pre-commit), so this repo's real .git/hooks/
# pre-commit.before-gitleaks was copied into every agent worktree as a file git
# can never invoke. A denylist has to predict every name anyone will ever leave
# lying around; an allowlist of git's actual hook names does not.
COMMON2="$(git -C "$TREE" rev-parse --git-common-dir)/hooks"
printf '#!/bin/sh\nexit 0\n' > "$COMMON2/pre-commit.before-gitleaks"
printf '#!/bin/sh\nexit 0\n' > "$COMMON2/post-checkout"
chmod +x "$COMMON2/pre-commit.before-gitleaks" "$COMMON2/post-checkout"
run_round
HOOKS_DIR="$(git -C "$TREE" config core.hooksPath)"
[ -e "$HOOKS_DIR/pre-commit.before-gitleaks" ] \
  && fail "DEAD FILE MIRRORED: pre-commit.before-gitleaks was copied into the agent's
      hooks dir. git never invokes that name; the mirror is copying by suffix
      instead of by git's actual hook names."
ok "a backup file next to a real hook is not mirrored"
[ -x "$HOOKS_DIR/post-checkout" ] \
  || fail "post-checkout is a real git hook and was NOT mirrored; the allowlist
      must not be narrower than the hooks the repo actually installs"
ok "a real git hook (post-checkout) is still mirrored"

bash -n "$WORKER" || fail "linear-worker.sh does not parse"
ok "linear-worker.sh parses (bash -n)"

echo "PASS: worker directive + scratch guard ($PASS checks)"
