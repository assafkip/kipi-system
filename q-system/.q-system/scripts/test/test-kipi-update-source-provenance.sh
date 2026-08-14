#!/usr/bin/env bash
# The bytes fanned out to 23 instances must be the bytes that were reviewed.
#
# q-system/ is copied with `git archive` from HEAD, and two preflights already
# refuse when the index and HEAD disagree. `.claude/` and `plugins/` are NOT:
# they rsync from $SCRIPT_DIR, the skeleton's WORKING TREE, on whatever branch
# it happens to be checked out on. Nothing checked which branch that was.
#
# Measured 2026-08-14: kipi-system sat on sana/ask-728-plugin-parity with an
# uncommitted partial forward-port of plugins/kipi-core/voicekit/selector.py --
# the nearest-length ranking without the anchor-survives fix Codex caught in
# #147 and main already carried. A run from that state would have written code
# strictly older than main into every config-sync instance and printed PASS.
# That is the false-success shape with fleet blast radius, so it gets a
# preflight rather than a habit.
#
# Two properties:
#   1. a dirty .claude/ or plugins/ ABORTS before any instance is touched;
#   2. a skeleton off SKELETON_BRANCH ABORTS the same way.
#
# The branch half is armed only when an `origin` remote exists. SKELETON_BRANCH
# names a branch ON origin; a repo with no origin has no main to be stale
# against, and every kipi-update fixture in this directory is exactly that repo.
# The dirty half runs unconditionally, because staleness against HEAD needs no
# remote to be wrong.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

BASELINE_REL="q-system/.q-system/state/propagation-leak-baseline.json"

# A skeleton the updater will actually walk, with one instance registered.
# Deliberately the same shape as test-kipi-update-leak-preflight.sh's fixture:
# these two guards sit next to each other in the preflight and a divergent
# fixture would let one pass on a repo the other could not survive.
build_skeleton() {
  local work="$1" sk="$work/skel" inst="$work/inst"
  mkdir -p "$sk/q-system/.q-system/scripts" "$sk/q-system/.q-system/state" \
           "$sk/q-system/marketing" "$sk/plugins/demo" "$sk/.claude/rules"
  cp "$ROOT/kipi-update.sh" "$sk/kipi-update.sh"
  cp "$ROOT/kipi-update-preserve-scan.py" "$sk/kipi-update-preserve-scan.py"
  cp "$ROOT/kipi-update-deletion-guard.py" "$sk/kipi-update-deletion-guard.py"
  cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
     "$sk/q-system/.q-system/scripts/propagation-leak-gate.py"
  cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
     "$sk/q-system/.q-system/scripts/containment-targets.py"
  cp "$ROOT/validate-separation.py" "$sk/validate-separation.py"
  cat > "$sk/$BASELINE_REL" <<'BASELINE_JSON'
{
  "schema_version": 1,
  "blocking_classes": [
    "case_proof_gap",
    "client_identity",
    "dated_interaction",
    "pricing",
    "relationship",
    "source_identity",
    "sourced_interaction"
  ],
  "classifier_sha256": null,
  "entries": []
}
BASELINE_JSON
  printf 'generic skeleton content\n' > "$sk/q-system/marketing/outreach.md"
  printf '# demo plugin\n' > "$sk/plugins/demo/README.md"
  printf '# demo rule\n' > "$sk/.claude/rules/demo.md"
  ( cd "$sk" && G init -q && G add -A -f && G commit -qm skel )
  printf '{"instances":[{"name":"testinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
    "$inst" > "$sk/instance-registry.json"

  mkdir -p "$inst/q-system" "$inst/.claude"
  printf 'instance state\n' > "$inst/q-system/tracked.md"
  ( cd "$inst" && G init -q && G add -A -f && G commit -qm inst )
}

instance_fingerprint() {
  ( cd "$1" && G rev-parse HEAD && G status --porcelain && \
    find . -path ./.git -prune -o -type f -print0 2>/dev/null \
      | sort -z | xargs -0 shasum -a 256 2>/dev/null )
}

# Positional, not exit-code. This minimal fixture exits non-zero later in the
# run for unrelated reasons, so `run && fail` would prove nothing at all --
# the same trap the leak-preflight fixture documents at its assert helper.
assert_aborts_untouched() {
  local sk="$1" inst="$2" what="$3" needle="$4" before after out
  before="$(instance_fingerprint "$inst")"
  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  after="$(instance_fingerprint "$inst")"
  if echo "$out" | grep -q -- "--- testinst"; then
    fail "$what: the instance loop was ENTERED instead of aborting: $out"
  fi
  echo "$out" | grep -qi "ABORT" || fail "$what aborted without saying so: $out"
  echo "$out" | grep -q -- "$needle" || \
    fail "$what did not name what was wrong ('$needle'): $out"
  [ "$before" = "$after" ] || fail "$what: instance was touched"
}

# ---------------------------------------------------------------- property 1
# A modification sitting in .claude/ or plugins/ is what actually rsyncs, so an
# uncommitted edit reaches the fleet without ever passing a review.
assert_dirty_sync_scope_aborts() {
  local work sk inst out
  work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build_skeleton "$work"

  # Clean baseline: the guard must not fire on a skeleton that is fine, or it
  # gets switched off and protects nothing.
  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  if echo "$out" | grep -q "ABORT: the skeleton"; then
    fail "the guard fired on a clean skeleton: $out"
  fi

  printf '# edited, never committed\n' >> "$sk/plugins/demo/README.md"
  assert_aborts_untouched "$sk" "$inst" "dirty plugins/" "plugins/demo/README.md"
  ( cd "$sk" && G checkout -q -- plugins/demo/README.md )

  printf '# edited, never committed\n' >> "$sk/.claude/rules/demo.md"
  assert_aborts_untouched "$sk" "$inst" "dirty .claude/" ".claude/rules/demo.md"
  ( cd "$sk" && G checkout -q -- .claude/rules/demo.md )

  # Staged-but-uncommitted is the same defect wearing a hat: rsync reads the
  # working tree either way, and `git add` is not a review.
  printf '# staged, never committed\n' >> "$sk/plugins/demo/README.md"
  ( cd "$sk" && G add plugins/demo/README.md )
  assert_aborts_untouched "$sk" "$inst" "staged plugins/" "plugins/demo/README.md"
  ( cd "$sk" && G reset -q -- plugins/demo/README.md && \
    G checkout -q -- plugins/demo/README.md )

  # An UNTRACKED file under plugins/ also rsyncs. It is not a modification, so
  # `git diff` is blind to it; the guard has to look for it on purpose.
  printf '# never added\n' > "$sk/plugins/demo/scratch.md"
  assert_aborts_untouched "$sk" "$inst" "untracked plugins/" "plugins/demo/scratch.md"
  rm -f "$sk/plugins/demo/scratch.md"

  echo "PASS: a dirty, staged, or untracked .claude/ or plugins/ aborts before any instance is touched"
}

# ------------------------------------------------------- scope, not wholesale
# The config sync copies .claude/{agents,output-styles,rules}/*.md and
# .claude/settings.json. NOTHING else under .claude/ reaches an instance, so
# nothing else may abort the fleet.
#
# This is the half that keeps the guard switched ON. `.claude/worktrees/` is the
# repo's own convention and is ignored only in a clone's .git/info/exclude, not
# in the committed .gitignore -- a wholesale `.claude` check fires on a fresh
# clone the first time anyone makes a worktree. A guard that cries wolf on the
# workflow it ships with gets deleted, and then it protects nothing.
assert_unsynced_claude_paths_do_not_abort() {
  local work sk out
  work="$(mktemp -d)"; sk="$work/skel"
  build_skeleton "$work"

  mkdir -p "$sk/.claude/worktrees/some-branch"
  printf 'a whole checkout lives here\n' > "$sk/.claude/worktrees/some-branch/file.md"
  printf '{"permissions":{"allow":["Read"]}}\n' > "$sk/.claude/settings.local.json"

  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  if echo "$out" | grep -q "ABORT: the skeleton"; then
    fail "the guard fired on .claude/ paths that never rsync: $out"
  fi

  echo "PASS: dirty .claude/ paths outside the synced set do not abort"
}

# ---------------------------------------------------------------- property 2
# The branch half. Arming needs an origin remote, so the fixture grows one --
# a bare repo, no network.
assert_off_branch_aborts() {
  local work sk inst bare out
  work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"; bare="$work/origin.git"
  build_skeleton "$work"
  G init -q --bare "$bare"
  ( cd "$sk" && G remote add origin "$bare" && G push -q origin HEAD:refs/heads/main )

  # On main with an origin: still clean, still must not fire.
  ( cd "$sk" && G checkout -q -B main )
  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  if echo "$out" | grep -q "ABORT: the skeleton"; then
    fail "the guard fired on a clean skeleton sitting on main: $out"
  fi

  ( cd "$sk" && G checkout -q -b sana/some-feature )
  assert_aborts_untouched "$sk" "$inst" "off SKELETON_BRANCH" "sana/some-feature"

  # Detached HEAD is off-branch too, and reads as "" rather than a wrong name.
  ( cd "$sk" && G checkout -q --detach HEAD )
  assert_aborts_untouched "$sk" "$inst" "detached HEAD" "detached"

  echo "PASS: a skeleton off SKELETON_BRANCH, attached or detached, aborts before any instance is touched"
}

# ---------------------------------------------------------------- no-origin
# Every other kipi-update fixture is a repo with no origin. The branch half
# must stay disarmed there -- and must SAY it is disarmed, because a guard that
# goes quiet is indistinguishable from a guard that passed.
assert_no_origin_disarms_the_branch_half_loudly() {
  local work sk out
  work="$(mktemp -d)"; sk="$work/skel"
  build_skeleton "$work"
  ( cd "$sk" && G checkout -q -b sana/some-feature )
  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  if echo "$out" | grep -q "ABORT: the skeleton"; then
    fail "the branch half fired on a repo with no origin: $out"
  fi
  echo "$out" | grep -q "no origin remote" || \
    fail "the disarmed branch half did not announce itself: $out"

  echo "PASS: no origin disarms the branch half and says so"
}

assert_dirty_sync_scope_aborts
assert_unsynced_claude_paths_do_not_abort
assert_off_branch_aborts
assert_no_origin_disarms_the_branch_half_loudly
echo "PASS: kipi update refuses to fan bytes that were never reviewed"
