#!/usr/bin/env bash
# Reproducer + acceptance criterion for "the worker never fetches, and when the
# fetch fails it goes dark" (ASK-211, sp-28ced3d6; re-file of fix 1 of ASK-208).
#
# THE DEFECT: linear-worker.sh contains no `git fetch` anywhere. It runs
#   git -C "$SKEL" worktree add -q -B "$BRANCH" "$TREE" origin/main
# against whatever local `origin/main` remote-tracking ref happens to exist, so
# the agent is dispatched against a base that can be arbitrarily old.
#
# OBSERVED (2026-07-27): ASK-150 was dispatched to resolve a conflict against
# main, merged 3b60af0, and the conflict survived -- main was already 72c782d.
# The agent did the right thing to the wrong target and two rounds were burned.
#
# THE SECOND HALF, which failed review the first time this fix was attempted
# (PR #22, round 3, finding 1 -- major): a fetch guard whose failure path is
# `say` + `exit 0` makes an expired credential at 3am byte-for-byte
# indistinguishable from a healthy run with nothing ready -- same rc, no Slack,
# one line in a log nobody reads. MAX_ATTEMPTS counts only DISPATCHED runs, so
# the issue never becomes stuck and never pages that way either. A fleet-wide
# worker that goes permanently dark while reporting success cannot ride a
# follow-up. self-healing-retry.md rule 5 says an environmental failure is
# surfaced IMMEDIATELY, and a log line is not surfacing.
#
# WHY THIS DRIVES THE REAL SCRIPT: both claims are about side effects, so both
# are read back for real. Case 1 stales the local remote-tracking ref and asserts
# the SHA the worktree actually landed on -- a grep for "git fetch" in the source
# would pass on a fetch placed AFTER the worktree is created, i.e. on a script
# that still has the bug. Cases 4-6 run against a genuinely unreachable origin
# and redirect $NOTIFY to a recorder rather than stubbing it out, so "did anyone
# get paged, and did the page say what broke?" is answered by a file with the
# message in it and never by a grep.
#
# Case 7 asserts the healthy contrast in the same run. A non-zero exit is only
# worth something if the healthy path still exits 0 and still pages nobody --
# otherwise the fix trades a silent failure for a permanent false alarm, which is
# the same defect wearing the other hat.
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

STUB="$WORK/bin"; mkdir -p "$STUB" "$WORK/home"

# NEVER LET A TEST REACH THE REAL REVIEWER (sp-cb48c3c0). This suite drives
# linear-worker.sh for real, and the worker's review step shells
# pr-review-agent.sh, whose DEFAULT ENGINE IS CODEX. $STUB carries no `codex`, so
# the call fell through to /opt/homebrew/bin/codex: real spend, real `gh --post`
# attempts against a PR number that does not exist, and codex running
# workspace-write inside the founder's live checkout. Caught live 2026-07-30 by
# finding `pr-review-agent.sh 807 --issue ASK-AAA --post --engine codex` in ps.
#
# KIPI_PR_REVIEWER is the override linear-worker.sh:72 already exposes, so one
# export closes the whole path -- strictly better than adding a `codex` stub,
# which would still run the real reviewer script against real `gh`.
KIPI_PR_REVIEWER="$STUB/reviewer-noop"
export KIPI_PR_REVIEWER
cat > "$STUB/reviewer-noop" <<'NOOP'
#!/usr/bin/env bash
# Stands in for pr-review-agent.sh. Prints what it was asked to do so a test can
# assert the worker TRIED to review, and exits 0 without touching any network.
echo "  [stub reviewer] would review PR $1 ($*)"
exit 0
NOOP
chmod +x "$STUB/reviewer-noop"

# No PR exists and none may be created.
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/gh"
chmod +x "$STUB/gh"
# THE PROBE for "did anyone get paged". Not a no-op stub: the message has to be
# readable, because a page that says nothing is the failure in a different coat.
cat > "$WORK/notify-recorder.sh" <<EOF
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$WORK/pages.txt"
EOF
chmod +x "$WORK/notify-recorder.sh"
export PATH="$STUB:$PATH"
[ "$(command -v git)" = "$REAL_GIT" ] || fail "git was shadowed by a stub; real refs are the subject"

# picker_stub <json-for-the-heredoc-call>
# The worker feeds its picker to `python3 -` and calls linear-sync.py for the
# progress notes. Everything else (linear-claim.py, the ledger helpers) must run
# for real, so the stub falls through to the real interpreter.
picker_stub() {
  cat > "$STUB/python3" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  -)  cat >/dev/null
      printf '%s\n' '$1'
      exit 0 ;;
  *linear-sync.py) exit 0 ;;
esac
exec "$REAL_PY" "\$@"
EOF
  chmod +x "$STUB/python3"
}

# ===========================================================================
# PART A -- a reachable origin that has moved. Does the tree get the new base?
# ===========================================================================
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

# The work phase is a no-op here: this part asks only where the tree was based.
printf '#!/usr/bin/env bash\nexit 0\n' > "$STUB/claude"
chmod +x "$STUB/claude"
picker_stub '{"ready":[{"id":"ASK-AAA","title":"t","project":"p"}],"total_open":1}'

# cwd is the skeleton, which is where launchd runs this from.
( cd "$WORK/skel" \
  && HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state" \
     KIPI_NOTIFY="/usr/bin/true" \
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
# refs/remotes/origin/main would leave every later `origin/main..HEAD` count wrong,
# which is what the worker's own "open the PR in code" branch counts.
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
picker_stub '{"ready":[{"id":"ASK-AAA","title":"t","project":"p"},{"id":"ASK-BBB","title":"t","project":"p"}],"total_open":2}'

( cd "$WORK/skel" \
  && PATH="$CSTUB:$PATH" HOME="$WORK/home" KIPI_SKEL="$WORK/skel" KIPI_STATE_DIR="$WORK/state2" \
     KIPI_NOTIFY="/usr/bin/true" \
     bash "$WORKER" --apply --limit 2 ) >"$WORK/run2.out" 2>&1

# `grep -c` exits 1 on a zero count, so the old `|| echo 0` idiom printed "0\n0"
# and the very branch that reports "no fetch at all" died on a bad integer
# comparison instead of failing cleanly. wc always exits 0.
FETCHES="$(wc -l < "$WORK/fetches.txt" | tr -d ' ')"
[ "${FETCHES:-0}" -ge 1 ] || fail "a 2-issue run performed no fetch at all"
[ "${FETCHES:-0}" -le 1 ] \
  || fail "a 2-issue run fetched $FETCHES times; the DoR asks for one fetch per run, not per issue"
ok "a 2-issue run fetched exactly once"

# ===========================================================================
# PART B -- an origin that cannot be reached. Does anyone find out?
# ===========================================================================
git init -q "$WORK/skel2"
G -C "$WORK/skel2" commit -q --allow-empty -m c1
git -C "$WORK/skel2" branch -M main
git -C "$WORK/skel2" remote add origin "$WORK/nowhere.git"   # never created
git -C "$WORK/skel2" fetch --quiet origin 2>/dev/null \
  && fail "fixture: the unreachable origin fetched anyway"

# Reaching the agent at all would mean the run did work on a stale base.
cat > "$STUB/claude" <<EOF
#!/usr/bin/env bash
echo "dispatched" >> "$WORK/worked.txt"
exit 0
EOF
chmod +x "$STUB/claude"
picker_stub '{"ready":[{"id":"ASK-AAA","title":"t","project":"p"}],"total_open":1}'
: > "$WORK/pages.txt"; : > "$WORK/worked.txt"

( cd "$WORK/skel2" \
  && HOME="$WORK/home" KIPI_SKEL="$WORK/skel2" KIPI_STATE_DIR="$WORK/state3" \
     KIPI_NOTIFY="$WORK/notify-recorder.sh" \
     bash "$WORKER" --apply --issue ASK-AAA --limit 1 ) >"$WORK/run3.out" 2>&1
RC_FAIL=$?

# --- 4. the run is distinguishable from a healthy no-work run ---------------
if [ "$RC_FAIL" = "0" ]; then
  fail "SILENT SUCCESS: the worker exited 0 after a fetch failure that stopped
      the entire run. A caller -- launchd, a wrapper, converge -- cannot tell
      this apart from a healthy run with nothing ready. It said:
      $(grep -i infra "$WORK/run3.out" | head -1)"
fi
ok "a fetch failure exits non-zero (rc=$RC_FAIL), so a caller can tell"

# --- 5. somebody was actually paged, and the page names the cause -----------
if [ ! -s "$WORK/pages.txt" ]; then
  fail "NOBODY WAS PAGED: the fetch failed, the run did no work, and \$NOTIFY was
      never called. self-healing-retry.md rule 5 says an environmental failure is
      surfaced immediately; the only trace was a line in the log."
fi
ok "the fetch failure pages the founder through \$NOTIFY"

grep -qi "fetch" "$WORK/pages.txt" \
  || fail "the page does not name the cause. It said: $(head -1 "$WORK/pages.txt")"
ok "the page names the cause (git fetch), not just 'something failed'"

# --- 6. it stopped BEFORE doing anything on a stale base --------------------
[ ! -s "$WORK/worked.txt" ] \
  || fail "the agent was dispatched anyway; the whole point of stopping is that a
      stale base produces plausible work aimed at the wrong target"
[ ! -d "$WORK/state3/worktrees/ask-aaa" ] \
  || fail "a worktree was cut despite the fetch failure"
ok "no worktree was cut and no agent was dispatched"

# --- 7. the HEALTHY path is unchanged: rc 0, and nobody is paged ------------
# Without this the fix could 'pass' by always failing and always paging, which
# trains the reader to ignore the channel -- the cry-wolf failure this fleet
# keeps killing.
git init -q --bare "$WORK/origin2"
git -C "$WORK/origin2" symbolic-ref HEAD refs/heads/main
git -C "$WORK/skel2" remote set-url origin "$WORK/origin2"
git -C "$WORK/skel2" push -q -u origin main
picker_stub '{"ready":[],"total_open":0}'
: > "$WORK/pages.txt"

( cd "$WORK/skel2" \
  && HOME="$WORK/home" KIPI_SKEL="$WORK/skel2" KIPI_STATE_DIR="$WORK/state4" \
     KIPI_NOTIFY="$WORK/notify-recorder.sh" \
     bash "$WORKER" --apply --limit 1 ) >"$WORK/run4.out" 2>&1
RC_OK=$?

[ "$RC_OK" = "0" ] \
  || fail "a healthy run with nothing ready must still exit 0, got rc=$RC_OK: $(tail -3 "$WORK/run4.out")"
ok "a healthy run with nothing ready still exits 0"

[ ! -s "$WORK/pages.txt" ] \
  || fail "a healthy no-work run paged the founder: $(head -1 "$WORK/pages.txt")"
ok "a healthy no-work run pages nobody"

# --- 8. the script still parses --------------------------------------------
bash -n "$WORKER" || fail "linear-worker.sh does not parse"
ok "linear-worker.sh parses (bash -n)"

echo "PASS: linear-worker fetch ($PASS checks)"
