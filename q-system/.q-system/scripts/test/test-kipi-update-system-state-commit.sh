#!/usr/bin/env bash
# The carve-out that exists to PREVENT the dirty-tree refusal is what causes it.
#
# Before the guard at kipi-update.sh:~1534 judges an instance, a block above it
# commits the fleet's own exhaust -- the sycophancy stamp, the integrity
# baseline, hook state, and every skeleton-managed plugin dir -- so that
# machine-written files are never mistaken for founder work. It builds a list
# and runs ONE pathspec-limited commit over it.
#
# That list mixes TRACKED and UNTRACKED paths, and `git commit -- <pathspec>`
# fails outright on a path git does not know:
#
#   error: pathspec 'untracked.txt' did not match any file(s) known to git
#
# git commits NOTHING when that happens, so the tracked half of the list stays
# dirty too. The call ends in `2>/dev/null || true`, so the failure is invisible,
# and the "Committing N system-written file(s)" line prints either way. The guard
# then refuses the instance over the very files the carve-out just announced it
# had handled.
#
# Measured 2026-08-14, full dry sweep of 23 instances: 11 refusals, 10 of them
# preceded by that announcement. ktlyst-website announced 3 files (plugins/prd-os,
# .claude-integrity-armed, claude-integrity-baseline.json) and then refused with
# all 3 still dirty. Two of the three were untracked, which is what poisoned the
# commit that would have cleared the third.
#
# This is why ASK-775's original theory looked right: the untracked integrity
# artifacts ARE implicated. Not because the guard sees them -- it only reads
# `git diff`, which is blind to untracked files -- but because their presence in
# the pathspec kills the commit that would have cleared the tracked dirt.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

# ------------------------------------------------------------------ property 0
# The git behaviour the whole bug rests on. Pinned separately so that if a future
# git ever changes it, this file says which assumption moved rather than leaving
# the integration test failing for an unexplained reason.
assert_a_mixed_pathspec_commit_commits_nothing() {
  local work; work="$(mktemp -d)"
  ( cd "$work" && G init -q
    printf 'v1\n' > tracked.txt && G add -A && G commit -qm init
    printf 'v2\n' > tracked.txt
    printf 'new\n' > untracked.txt
    if G commit -q -m mixed -- tracked.txt untracked.txt 2>/dev/null; then
      echo "MIXED_COMMIT_SUCCEEDED"
    fi
    G status --porcelain )> "$work/out" 2>&1

  if grep -q "MIXED_COMMIT_SUCCEEDED" "$work/out"; then
    fail "git accepted a mixed tracked/untracked pathspec commit; the premise moved"
  fi
  grep -q "^ M tracked.txt" "$work/out" || \
    fail "the TRACKED half should still be dirty after the failed commit: $(cat "$work/out")"

  echo "PASS: one untracked path makes git commit -- <pathspec> commit nothing at all"
}

# ------------------------------------------------------------------ the fixture
# A skeleton plus one instance that reproduces the live shape: a tracked,
# skeleton-owned plugin file modified (what the guard actually trips on) AND
# untracked integrity artifacts (what poisons the carve-out's commit).
build() {
  local work="$1" sk="$work/skel" inst="$work/inst"
  mkdir -p "$sk/q-system/.q-system/scripts" "$sk/q-system/.q-system/state" \
           "$sk/q-system/hooks" "$sk/plugins/demo" "$sk/.claude/rules"
  for f in kipi-update.sh kipi-update-preserve-scan.py kipi-update-deletion-guard.py \
           validate-separation.py; do
    cp "$ROOT/$f" "$sk/$f"
  done
  cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
     "$sk/q-system/.q-system/scripts/propagation-leak-gate.py"
  cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
     "$sk/q-system/.q-system/scripts/containment-targets.py"
  # THE CLASSIFIER IS LOAD-BEARING FOR THIS FIXTURE. Without it the
  # `[ -f "$sys_classifier" ]` branch is skipped, no UNTRACKED path ever enters
  # sys_owned_dirty, the carve-out commits a single tracked path and succeeds --
  # and the bug does not reproduce at all. Omitting it is how this test passed
  # while the live fleet was failing (caught 2026-08-14 by instrumenting the
  # fixture rather than trusting the green).
  cp "$ROOT/q-system/hooks/auto-commit.py" "$sk/q-system/hooks/auto-commit.py"
  cat > "$sk/q-system/.q-system/state/propagation-leak-baseline.json" <<'JSON'
{
  "schema_version": 1,
  "blocking_classes": ["case_proof_gap", "client_identity", "dated_interaction",
                       "pricing", "relationship", "source_identity",
                       "sourced_interaction"],
  "classifier_sha256": null,
  "entries": []
}
JSON
  printf 'generic skeleton content\n' > "$sk/q-system/tracked.md"
  # v2 of the managed plugin: the sync will want to write this into the instance.
  printf 'plugin v2\n' > "$sk/plugins/demo/content.txt"
  printf '# demo rule\n' > "$sk/.claude/rules/demo.md"
  ( cd "$sk" && G init -q -b main && G add -A -f && G commit -qm skel )
  printf '{"instances":[{"name":"testinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
    "$inst" > "$sk/instance-registry.json"

  # The instance: v1 of the managed plugin, TRACKED and about to be modified.
  mkdir -p "$inst/q-system/.q-system" "$inst/plugins/demo" "$inst/.claude"
  printf 'instance state\n' > "$inst/q-system/tracked.md"
  printf 'plugin v1\n' > "$inst/plugins/demo/content.txt"
  ( cd "$inst" && G init -q -b main && G add -A -f && G commit -qm inst )

  # The live shape, both halves:
  #   TRACKED and modified -- a skeleton-owned plugin file. This is what the
  #   guard reads, and what the carve-out is supposed to clear.
  printf 'plugin v1-locally-rewritten\n' > "$inst/plugins/demo/content.txt"
  #   UNTRACKED -- the integrity artifacts the tripwire writes into the synced
  #   tree. Invisible to the guard, fatal to the carve-out's pathspec.
  printf 'armed\n' > "$inst/q-system/.q-system/.claude-integrity-armed"
  printf '{}\n' > "$inst/q-system/.q-system/claude-integrity-baseline.json"
}

# ------------------------------------------------------------------ property 1
# The integration case. The carve-out must actually clear the tracked
# skeleton-owned dirt so the instance syncs, and it must not be defeated by an
# untracked path sharing its list.
assert_the_carve_out_clears_tracked_system_dirt() {
  local work sk inst out; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"

  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true

  if echo "$out" | grep -q "refusing to commit unrelated work"; then
    fail "the instance was refused over dirt the carve-out announced it handled:
$(echo "$out" | grep -A12 -- '--- testinst')"
  fi

  # Positive, not merely the absence of the error: prove the tracked file is no
  # longer dirty. "Did not print the failure" is how a skipped carve-out passes.
  if ! G -C "$inst" diff --quiet -- plugins/demo/content.txt; then
    fail "plugins/demo/content.txt is STILL dirty after the carve-out ran"
  fi

  echo "PASS: the carve-out commits tracked system-owned dirt even when untracked paths share its list"
}

# ------------------------------------------------------------------ property 2
# The carve-out must never become a founder-work sweeper while being taught to
# handle untracked paths. This is the rule the original `NO git add` comment was
# protecting (Codex review, PR #98), and widening the add is exactly how it would
# be lost.
assert_founder_work_is_never_swept() {
  local work sk inst out; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"

  # Founder work, tracked and STAGED, in a path the sync is permitted to write.
  printf 'founder edit, not the updater to take\n' > "$inst/q-system/tracked.md"
  ( cd "$inst" && G add q-system/tracked.md )

  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true

  # Ask the carve-out commit itself what it contains, by subject. `grep -B5`
  # over a flat log guesses at which commit a filename belongs to and was
  # reporting a false positive on the sync commit two entries away.
  local carve
  carve="$(G -C "$inst" log --format='%H %s' 2>/dev/null \
             | grep -F 'commit system-written state' | head -1 | cut -d' ' -f1)"
  if [ -n "$carve" ]; then
    if G -C "$inst" show --name-only --format= "$carve" 2>/dev/null \
         | grep -qx "q-system/tracked.md"; then
      fail "founder work was swept into the system-state commit $carve"
    fi
  fi

  echo "PASS: founder work is not swept into the system-state commit"
}

assert_a_mixed_pathspec_commit_commits_nothing
assert_the_carve_out_clears_tracked_system_dirt
assert_founder_work_is_never_swept
echo "PASS: the system-state carve-out cannot be defeated by an untracked path"
