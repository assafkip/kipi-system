#!/usr/bin/env bash
# The worker commits for Codex, saves a timed-out tree, and bills a hand run to
# the plan (ASK-5847).
#
# WHY THIS EXISTS. Measured 2026-11-27:
#   - Codex's workspace-write sandbox keeps .git read-only ("sandbox denied
#     creation of Git's index.lock"), so a Codex run could never commit and
#     parked its ticket blocked:capability for 14 days.
#   - 14 of about 20 worker runs died at the 1800s wall clock; each kill threw
#     the tree away and the retry restarted from scratch.
#   - a manual `linear-worker.sh --issue` run billed the API key unless someone
#     remembered KIPI_FLEET_API_KEYS=0.
#
# The functions are lifted out of linear-worker.sh by name, so the cases follow
# the shipped code. Everything runs in a temp git repo; no network, no runner.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
WORKER="${KIPI_WORKER_UNDER_TEST:-$ROOT/q-system/.q-system/scripts/linear-worker.sh}"
DISPATCH="$ROOT/kipi-dispatch.sh"
PASS=0; FAIL=0
ok()  { PASS=$((PASS + 1)); echo "  ok   $1"; }
bad() { FAIL=$((FAIL + 1)); echo "  FAIL $1"; [ -n "${2:-}" ] && printf '       %s\n' "$2"; }
[ -f "$WORKER" ] || { echo "FATAL: linear-worker.sh not found at $WORKER"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
lift() {  # lift <function-name>: print that function's definition from the worker
  awk -v n="$1" '$0 ~ "^"n"\\(\\) \\{" {on=1} on {print} on && /^}/ {exit}' "$WORKER"
}
LIB="$WORK/lib.sh"
{
  echo 'TS() { date -u +%Y-%m-%dT%H:%M:%SZ; }'
  echo 'say() { echo "$(TS) $*" | tee -a "$LOG"; }'
  grep '^RUNNER_SENTINEL_EXCLUDES=' "$WORKER"
  for f in manual_issue_run_bills_plan run_bounded reap_group commit_runner_edits tree_fingerprint edits_in_last_10m codex_runner_note; do
    body="$(lift "$f")"
    [ -n "$body" ] || { echo "FATAL: could not lift $f() from $WORKER" >&2; exit 1; }
    printf '%s\n' "$body"
  done
} > "$LIB"
LOG="$WORK/worker.log"; : > "$LOG"
export LOG
# shellcheck disable=SC1090
. "$LIB"

# 1. A hand --issue run bills the plan; a dispatched run, a set switch, or a
#    non --issue run are left alone.
( unset KIPI_FLEET_API_KEYS KIPI_WORKER_INVOKER; manual_issue_run_bills_plan --apply --issue ASK-1 ) \
  && ok "hand --issue run with no switch set bills the plan" \
  || bad "hand --issue run did not default to the plan"
( unset KIPI_FLEET_API_KEYS; KIPI_WORKER_INVOKER=dispatcher manual_issue_run_bills_plan --apply --issue ASK-1 ) \
  && bad "a dispatched run was forced onto the plan; the dispatcher decides its billing" \
  || ok "a dispatched run keeps the dispatcher's billing decision"
( unset KIPI_WORKER_INVOKER; KIPI_FLEET_API_KEYS=1 manual_issue_run_bills_plan --issue ASK-1 ) \
  && bad "an explicit KIPI_FLEET_API_KEYS=1 was overridden" \
  || ok "an explicit KIPI_FLEET_API_KEYS is honoured"
( unset KIPI_FLEET_API_KEYS KIPI_WORKER_INVOKER; manual_issue_run_bills_plan --apply --limit 1 ) \
  && bad "a run without --issue was forced onto the plan" \
  || ok "a run without --issue is not a hand run"
grep -q '^if manual_issue_run_bills_plan "\$@"; then export KIPI_FLEET_API_KEYS=0; fi$' "$WORKER" \
  && ok "the worker calls it on its own argv before fleet_keyed is read" \
  || bad "the worker never calls manual_issue_run_bills_plan on its argv"
grep -q '^export KIPI_WORKER_INVOKER=dispatcher$' "$DISPATCH" \
  && ok "kipi-dispatch.sh marks its runs" \
  || bad "kipi-dispatch.sh does not export KIPI_WORKER_INVOKER=dispatcher"

# 2. KIPI_WORKER_TIMEOUT overrides the 1800s default; junk falls back.
TBLOCK="$(awk '/^TIMEOUT_SECONDS=1800$/ {on=1} on {print} on && /^esac$/ {exit}' "$WORKER")"
[ -n "$TBLOCK" ] || bad "could not lift the TIMEOUT_SECONDS block"
t_for() { ( if [ -n "$1" ]; then export KIPI_WORKER_TIMEOUT="$1"; else unset KIPI_WORKER_TIMEOUT; fi
            eval "$TBLOCK" 2>/dev/null; echo "$TIMEOUT_SECONDS" ); }
[ "$(t_for '')" = "1800" ] && ok "default wall clock stays 1800s" || bad "default is $(t_for '')"
[ "$(t_for 5400)" = "5400" ] && ok "KIPI_WORKER_TIMEOUT=5400 is read" || bad "override read as $(t_for 5400)"
[ "$(t_for abc)" = "1800" ] && ok "a non-number falls back to 1800" || bad "junk read as $(t_for abc)"

# A tree to work in.
G() { git -c user.email=t@t.t -c user.name=t "$@"; }
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t.t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t.t
TREE="$WORK/tree"; git init -q "$TREE"; echo base > "$TREE/a.txt"
G -C "$TREE" add -A; G -C "$TREE" commit -q -m base
BASE_SHA="$(git -C "$TREE" rev-parse HEAD)"

# 3. A clean tree makes no commit.
commit_runner_edits "$TREE" ASK-9 "nothing" && bad "a clean tree produced a commit" \
  || ok "a clean tree makes no commit"
[ "$(git -C "$TREE" rev-parse HEAD)" = "$BASE_SHA" ] || bad "HEAD moved on a clean tree"

# 3b. Sentinels and their .probe files alone are not edits to commit.
( cd "$TREE" && echo "bin:x" > .codex-blocked-capability.probe && echo why > .sana-blocked-capability.probe )
commit_runner_edits "$TREE" ASK-9 "sentinels only" && bad "sentinel files alone produced a commit" \
  || ok "a tree holding only runner sentinels makes no commit"

# 4. Codex-style run: edits only, no commit. The worker commits it.
( cd "$TREE" && echo "codex edit" > b.txt )
commit_runner_edits "$TREE" ASK-9 "Codex edits, committed by the worker" \
  && ok "the worker commits a runner's uncommitted edits" \
  || bad "the worker did not commit the runner's edits" "$(tail -3 "$LOG")"
git -C "$TREE" log -1 --pretty=%s | grep -q '(ASK-9)$' \
  && ok "the commit message carries the issue id (the commit-msg gate needs it)" \
  || bad "commit subject: $(git -C "$TREE" log -1 --pretty=%s)"
git -C "$TREE" show --name-only --pretty= HEAD | grep -qx b.txt || bad "b.txt not in the commit"
git -C "$TREE" show --name-only --pretty= HEAD | grep -q 'probe' \
  && bad "a .probe sentinel rode along in the runner commit (PR #912 round 1)" \
  || ok "the .probe sentinels stay out of the runner commit"

# 5. A run that hits the wall clock: RUN_TIMED_OUT=1, and the partial tree is
#    saved as a WIP commit the next attempt starts from.
run_bounded 1 bash -c "cd '$TREE' && echo partial > c.txt && sleep 10"
[ "${RUN_TIMED_OUT:-}" = "1" ] && ok "a run killed at the wall clock reads RUN_TIMED_OUT=1 (elapsed ${RUN_ELAPSED}s)" \
  || bad "a killed run read RUN_TIMED_OUT='${RUN_TIMED_OUT:-}' elapsed='${RUN_ELAPSED:-}'"
commit_runner_edits "$TREE" ASK-9 "WIP: wall clock ended this run" || bad "no WIP commit after the timeout"
NEXT="$WORK/next"; git -C "$TREE" worktree add -q "$NEXT" HEAD 2>/dev/null
[ "$(cat "$NEXT/c.txt" 2>/dev/null)" = "partial" ] \
  && ok "the next attempt starts from the WIP commit and has the partial work" \
  || bad "the WIP commit does not carry the partial tree"
run_bounded 5 true
[ "${RUN_TIMED_OUT:-}" = "0" ] && ok "a run that finishes in time reads RUN_TIMED_OUT=0" \
  || bad "a fast run read RUN_TIMED_OUT='${RUN_TIMED_OUT:-}'"

# 6. The Codex prompt carries the issue and says not to call Linear or commit.
SYNC="$WORK/sync.py"
printf 'import sys\nprint("DOR_MARKER for", sys.argv[2])\n' > "$SYNC"
NOTE="$(codex_runner_note ASK-9)"
printf '%s' "$NOTE" | grep -q 'Do NOT call Linear' && ok "the Codex note says not to call Linear" || bad "no Linear line in the note"
printf '%s' "$NOTE" | grep -q 'Do NOT run git add or git commit' && ok "the Codex note says not to commit" || bad "no commit line in the note"
printf '%s' "$NOTE" | grep -q 'DOR_MARKER for ASK-9' && ok "the note carries the issue the worker read" || bad "the issue text is not in the note: $NOTE"

# 7. Call sites: both Codex launches are followed by the worker's commit, and the
#    duration line is written.
grep -c 'commit_runner_edits "\$TREE" "\$ISSUE" "Codex' "$WORKER" | grep -qx 2 \
  && ok "both Codex launches (rung 2 and second runner) commit through the worker" \
  || bad "expected 2 Codex commit sites, found $(grep -c 'commit_runner_edits "\$TREE" "\$ISSUE" "Codex' "$WORKER")"
grep -q 'say "run-duration \$ISSUE secs=' "$WORKER" && ok "every run logs a run-duration line" || bad "no run-duration line"
grep -A1 '^      \[ "\${RUN_TIMED_OUT:-0}" = "1" \] \\$' "$WORKER" \
  | grep -q '^        || commit_runner_edits "\$TREE" "\$ISSUE" "Codex (cap-ladder rung 2)' \
  && ok "a rung-2 Codex run commits unless it timed out (then the WIP commit owns the tree)" \
  || bad "the rung-2 Codex commit is not exactly 'skip on timeout, commit otherwise'"
[ "$(grep -c 'if \[ "\$(tree_fingerprint "\$TREE")" != "\$PRE_SECOND_RUNNER_TREE" \]; then' "$WORKER")" = "2" ] \
  && ok "both second-runner commits fire only on a tree the runner changed" \
  || bad "a second-runner commit is not gated on the fingerprint"

# 8. The fingerprint: still on an untouched tree, moves on a real edit, blind to
#    sentinels. Leftovers nobody touched must not score as a continuation.
FP="$WORK/fp"; git init -q "$FP"; echo a > "$FP/a.txt"; G -C "$FP" add -A; G -C "$FP" commit -q -m a
echo leftover >> "$FP/a.txt"
F0="$(tree_fingerprint "$FP")"
[ "$(tree_fingerprint "$FP")" = "$F0" ] && ok "an untouched dirty tree keeps its fingerprint" || bad "fingerprint is not stable"
echo probe > "$FP/.codex-blocked-capability.probe"
[ "$(tree_fingerprint "$FP")" = "$F0" ] && ok "a sentinel does not move the fingerprint" || bad "a sentinel moved the fingerprint"
echo new > "$FP/n.txt"
[ "$(tree_fingerprint "$FP")" != "$F0" ] && ok "a new file moves the fingerprint" || bad "a new file did not move the fingerprint"
F1="$(tree_fingerprint "$FP")"; echo changed > "$FP/n.txt"
[ "$(tree_fingerprint "$FP")" != "$F1" ] && ok "editing an untracked file moves the fingerprint" || bad "untracked edit not seen"

# 9. A refused commit returns 2 and leaves nothing staged.
printf '#!/bin/sh\nexit 1\n' > "$FP/.git/hooks/pre-commit"; chmod +x "$FP/.git/hooks/pre-commit"
commit_runner_edits "$FP" ASK-9 "refused"; rc=$?
[ "$rc" = "2" ] && [ -z "$(git -C "$FP" diff --cached --name-only)" ] \
  && ok "a refused commit returns 2 and unstages, edits kept" \
  || bad "refused commit: rc=$rc staged=$(git -C "$FP" diff --cached --name-only | tr '\n' ' ')"
[ -f "$FP/n.txt" ] || bad "a refused commit lost the edit"

echo "PASS: $PASS  FAIL: $FAIL"
[ "$FAIL" = 0 ]
