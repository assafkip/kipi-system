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
# preceded by that announcement. One instance announced 3 files (plugins/prd-os,
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
  #   TRACKED and modified -- a skeleton-owned plugin file, dirty because an
  #   EARLIER FANOUT WROTE IT AND FAILED TO COMMIT. That is the real shape on the
  #   fleet (ASK-728 did exactly this to plugins/prd-os), and the signature is
  #   that the working-tree content equals the SKELETON's, not that it is some
  #   arbitrary local rewrite. Corrected 2026-08-14: the first version of this
  #   fixture used a local rewrite, which the authorship rule added in round 3
  #   correctly refuses -- so it was testing a case the code is right to block.
  cp "$sk/plugins/demo/content.txt" "$inst/plugins/demo/content.txt"
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
  # `|| true` inside the substitution is load-bearing. Under `set -e` a FAILING
  # command substitution kills the script AT the assignment, printing nothing --
  # so when no carve-out commit exists (exactly the case an assertion below wants
  # to report) this file exited silently mid-run and looked like a pass with
  # fewer lines. Caught 2026-08-14 while running this very test against a
  # deliberately broken updater. Same silent-failure class the code under test
  # has; a test that dies quietly cannot police one.
  carve="$(G -C "$inst" log --format='%H %s' 2>/dev/null \
             | grep -F 'commit system-written state' | head -1 | cut -d' ' -f1 || true)"
  if [ -n "$carve" ]; then
    if G -C "$inst" show --name-only --format= "$carve" 2>/dev/null \
         | grep -qx "q-system/tracked.md"; then
      fail "founder work was swept into the system-state commit $carve"
    fi
  fi

  echo "PASS: founder work is not swept into the system-state commit"
}

# ------------------------------------------------------------------ property 3
# The add must never reach untracked SOURCE inside a managed plugin.
#
# Codex review of #151, major. sys_owned_dirty carries DIRECTORY entries --
# `plugins/<name>` for every managed plugin -- and `git add <dir>` recursively
# stages everything untracked beneath it, walking straight past the
# source-by-extension refusal at auto-commit.py:170 (ASK-712). On this repo that
# is 91 candidate paths under plugins/kipi-core alone.
#
# The shape that matters: a plugin that IS dirty for a legitimate system reason,
# with a founder's untracked .py sitting next to the dirt. The carve-out must
# take the first and leave the second.
assert_untracked_source_in_a_managed_plugin_is_never_staged() {
  local work sk inst carve; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"

  # Founder's work in progress, untracked, inside the managed plugin dir.
  printf 'def half_written():\n    pass\n' > "$inst/plugins/demo/scratch_wip.py"

  bash "$sk/kipi-update.sh" >"$work/out" 2>&1 || true

  carve="$(G -C "$inst" log --format='%H %s' 2>/dev/null \
             | grep -F 'commit system-written state' | head -1 | cut -d' ' -f1 || true)"
  if [ -n "$carve" ]; then
    if G -C "$inst" show --name-only --format= "$carve" 2>/dev/null \
         | grep -qx "plugins/demo/scratch_wip.py"; then
      fail "untracked founder source was staged and committed by the carve-out"
    fi
  fi
  # Committed is the headline, but STAGED is the real line: a staged file would
  # be swept by the next commit in that repo, by us or by anyone.
  if G -C "$inst" diff --cached --name-only 2>/dev/null \
       | grep -qx "plugins/demo/scratch_wip.py"; then
    fail "untracked founder source was left STAGED by the carve-out"
  fi
  # And it must still be there, untouched.
  [ -f "$inst/plugins/demo/scratch_wip.py" ] || \
    fail "the founder's untracked source file was destroyed"

  echo "PASS: untracked source inside a managed plugin is neither staged nor committed"
}

# ------------------------------------------------------------------ property 4
# TRACKED founder edits inside a managed plugin, the mirror of property 3.
# Codex review of #151 round 2: `git add -u -- plugins/<name>` stages every
# tracked modification under the directory, so a founder editing a .py in a
# managed plugin had it committed under a chore message. Property 3 could not
# catch it (untracked only) and the founder-work fixture put its edit at
# q-system/tracked.md, outside the plugin dir.
#
# Both halves in ONE run, because they are the same decision made twice and a
# fix that gets one right by breaking the other is not a fix:
#
#   FLEET-WRITTEN  content byte-identical to the skeleton's, i.e. an earlier
#                  fanout wrote it and failed to commit. MUST be committed --
#                  this is what unblocks the instances, and on the real fleet it
#                  is plugins/prd-os/tests/test_judgment_compiler.py, a .py the
#                  extension classifier would refuse.
#   LOCAL EDIT     content differs from the skeleton's. MUST be left alone at any
#                  extension, so the guard below refuses and protects it.
assert_tracked_plugin_edits_split_by_authorship() {
  local work sk inst carve; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"

  # A second managed-plugin file, tracked on both sides, so the run has one of
  # each to sort.
  printf 'def fleet_written():\n    return 1\n' > "$sk/plugins/demo/shipped.py"
  printf 'def fleet_written():\n    return 0\n' > "$inst/plugins/demo/shipped.py"
  printf 'def local():\n    return 0\n' > "$sk/plugins/demo/edited.py"
  printf 'def local():\n    return 0\n' > "$inst/plugins/demo/edited.py"
  ( cd "$sk" && G add -A -f && G commit -qm "skeleton ships two plugin files" )
  ( cd "$inst" && G add -A -f && G commit -qm "instance has both" )

  # FLEET-WRITTEN: instance working tree now matches the SKELETON exactly, the
  # signature of a fanout that wrote and never committed.
  cp "$sk/plugins/demo/shipped.py" "$inst/plugins/demo/shipped.py"
  # LOCAL EDIT: differs from the skeleton. Founder work, .py, same directory.
  printf 'def local():\n    return "founder was here"\n' > "$inst/plugins/demo/edited.py"

  bash "$sk/kipi-update.sh" >"$work/out" 2>&1 || true

  carve="$(G -C "$inst" log --format='%H %s' 2>/dev/null \
             | grep -F 'commit system-written state' | head -1 | cut -d' ' -f1 || true)"
  [ -n "$carve" ] || fail "no system-state commit was made at all: $(cat "$work/out")"

  G -C "$inst" show --name-only --format= "$carve" 2>/dev/null \
    | grep -qx "plugins/demo/shipped.py" || \
    fail "the FLEET-WRITTEN plugin file was not committed, so the instance stays blocked"

  if G -C "$inst" show --name-only --format= "$carve" 2>/dev/null \
       | grep -qx "plugins/demo/edited.py"; then
    fail "a tracked founder edit inside a managed plugin was committed by the carve-out"
  fi
  if G -C "$inst" diff --cached --name-only 2>/dev/null \
       | grep -qx "plugins/demo/edited.py"; then
    fail "a tracked founder edit inside a managed plugin was left STAGED"
  fi
  grep -q 'founder was here' "$inst/plugins/demo/edited.py" || \
    fail "the founder's edit was destroyed"

  echo "PASS: fleet-written plugin files commit; tracked founder edits in the same dir do not"
}

# ------------------------------------------------------------------ property 5
# Deletions are authored too. Codex review of #151 round 3: the equality test
# needs both sides to exist, so a file the FLEET deleted read as a local edit and
# blocked the instance permanently -- the same deadlock this file exists to
# break, reintroduced for the one case `cmp` could not express.
#
# Both halves again, because "commit every deletion" is as wrong as "commit none":
#   FLEET DELETION  skeleton no longer ships it, instance no longer has it.
#                   Record it.
#   LOCAL DELETION  skeleton still ships it. Someone local removed it and the sync
#                   will put it back. Not ours to record.
assert_deletions_split_by_authorship() {
  local work sk inst carve; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"

  # Two files tracked in BOTH, so each can be deleted independently.
  printf 'dropped by a later skeleton\n' > "$sk/plugins/demo/retired.txt"
  printf 'dropped by a later skeleton\n' > "$inst/plugins/demo/retired.txt"
  printf 'still shipped\n' > "$sk/plugins/demo/kept.txt"
  printf 'still shipped\n' > "$inst/plugins/demo/kept.txt"
  ( cd "$sk" && G add -A -f && G commit -qm "skeleton ships both" )
  ( cd "$inst" && G add -A -f && G commit -qm "instance has both" )

  # FLEET DELETION: the skeleton dropped it and the copy removed it.
  rm -f "$sk/plugins/demo/retired.txt" "$inst/plugins/demo/retired.txt"
  ( cd "$sk" && G add -A && G commit -qm "skeleton retires the file" )
  # LOCAL DELETION: the skeleton still ships kept.txt; someone local removed it.
  rm -f "$inst/plugins/demo/kept.txt"

  bash "$sk/kipi-update.sh" >"$work/out" 2>&1 || true

  carve="$(G -C "$inst" log --format='%H %s' 2>/dev/null \
             | grep -F 'commit system-written state' | head -1 | cut -d' ' -f1 || true)"
  [ -n "$carve" ] || fail "no system-state commit was made: $(cat "$work/out")"

  G -C "$inst" show --name-only --format= "$carve" 2>/dev/null \
    | grep -qx "plugins/demo/retired.txt" || \
    fail "the FLEET's deletion was not recorded, so the instance stays blocked"

  if G -C "$inst" show --name-only --format= "$carve" 2>/dev/null \
       | grep -qx "plugins/demo/kept.txt"; then
    fail "a local deletion of a still-shipped file was recorded as the fleet's"
  fi

  echo "PASS: a fleet deletion is recorded; a local deletion of a shipped file is not"
}

# ------------------------------------------------------------------ property 6
# A STAGED founder edit must survive, even when the working tree has since been
# overwritten with the skeleton's copy.
#
# Codex review of #151 round 4, major. The sequence is nastier than the unstaged
# case because it leaves no trace: founder stages an edit; a later fanout writes
# the skeleton's version over the working tree; the worktree-to-skeleton equality
# test says "fleet-written"; `git add` replaces the staged blob with the skeleton
# content. The staged work is gone and there is no diff left to show it existed.
assert_a_staged_founder_edit_is_never_overwritten() {
  local work sk inst staged; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"

  printf 'def shipped():\n    return 1\n' > "$sk/plugins/demo/shipped.py"
  printf 'def shipped():\n    return 0\n' > "$inst/plugins/demo/shipped.py"
  ( cd "$sk" && G add -A -f && G commit -qm "skeleton ships it" )
  ( cd "$inst" && G add -A -f && G commit -qm "instance has it" )

  # Founder stages an edit...
  printf 'def shipped():\n    return "founder staged this"\n' > "$inst/plugins/demo/shipped.py"
  ( cd "$inst" && G add plugins/demo/shipped.py )
  # ...then a fanout overwrites the WORKING TREE with the skeleton's copy. The
  # index still holds the founder's blob; only the file on disk was replaced.
  cp "$sk/plugins/demo/shipped.py" "$inst/plugins/demo/shipped.py"

  bash "$sk/kipi-update.sh" >"$work/out" 2>&1 || true

  # The staged blob must still be the founder's. This is the whole assertion:
  # a passing run leaves the index untouched, a failing one silently rewrites it.
  staged="$(G -C "$inst" show ":plugins/demo/shipped.py" 2>/dev/null || true)"
  case "$staged" in
    *"founder staged this"*) : ;;
    *) fail "the founder's STAGED blob was overwritten by the carve-out; index now holds: $staged" ;;
  esac

  echo "PASS: a staged founder edit survives a working tree overwritten with skeleton content"
}

# ------------------------------------------------------------------ property 7
# A staged founder edit must survive even when the file is DELETED from both the
# skeleton and the working tree.
#
# Codex review of #151 round 5, BLOCKER, and the hole was created by round 5's
# own fix: putting the deletion test before the index check meant "absent from
# both" never consulted the index at all, so a committed deletion landed straight
# on top of a staged founder blob. Two fixes in a row each opened the other's
# case, which is why the index is now asked once, up front.
assert_a_staged_edit_survives_deletion_from_both_sides() {
  local work sk inst staged carve; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"

  printf 'def doomed():\n    return 1\n' > "$sk/plugins/demo/doomed.py"
  printf 'def doomed():\n    return 1\n' > "$inst/plugins/demo/doomed.py"
  ( cd "$sk" && G add -A -f && G commit -qm "skeleton ships it" )
  ( cd "$inst" && G add -A -f && G commit -qm "instance has it" )

  # Founder stages an edit.
  printf 'def doomed():\n    return "founder staged this"\n' > "$inst/plugins/demo/doomed.py"
  ( cd "$inst" && G add plugins/demo/doomed.py )
  # The skeleton retires the file and the copy removes it from the working tree.
  rm -f "$sk/plugins/demo/doomed.py"
  ( cd "$sk" && G add -A && G commit -qm "skeleton retires it" )
  rm -f "$inst/plugins/demo/doomed.py"

  bash "$sk/kipi-update.sh" >"$work/out" 2>&1 || true

  staged="$(G -C "$inst" show ":plugins/demo/doomed.py" 2>/dev/null || true)"
  case "$staged" in
    *"founder staged this"*) : ;;
    *) fail "the founder's STAGED blob was destroyed by the deletion path; index holds: '$staged'" ;;
  esac

  carve="$(G -C "$inst" log --format='%H %s' 2>/dev/null \
             | grep -F 'commit system-written state' | head -1 | cut -d' ' -f1 || true)"
  if [ -n "$carve" ] && G -C "$inst" show --name-only --format= "$carve" 2>/dev/null \
       | grep -qx "plugins/demo/doomed.py"; then
    fail "a deletion was committed over a staged founder edit"
  fi

  echo "PASS: a staged founder edit survives deletion from both the skeleton and the working tree"
}

# ------------------------------------------------------------------ property 8
# Content from an OLDER skeleton version is still the fleet's.
#
# Codex review of #151 round 6, major, and it was the difference between this PR
# working and doing nothing. Instances hold what an earlier fanout wrote while
# the skeleton has moved on, so a current-skeleton-only equality test attributes
# real fleet content to the founder and leaves the instance blocked forever.
# Measured on a live blocked instance: both prd-os files DIFFER from the current
# skeleton, so the current-only rule would have unblocked zero of them.
#
# The founder half is in the same run, because "accept anything that was ever
# shipped" must not become "accept anything".
assert_older_fleet_content_is_attributed_to_the_fleet() {
  local work sk inst carve; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"

  # v1 of a plugin file, shipped and committed by the skeleton.
  printf 'def api():\n    return "v1"\n' > "$sk/plugins/demo/api.py"
  printf 'def api():\n    return "v1"\n' > "$inst/plugins/demo/api.py"
  ( cd "$sk" && G add -A -f && G commit -qm "skeleton ships v1" )
  ( cd "$inst" && G add -A -f && G commit -qm "instance commits v1" )

  # An earlier fanout wrote v2 into the instance and failed to commit...
  printf 'def api():\n    return "v2"\n' > "$sk/plugins/demo/api.py"
  ( cd "$sk" && G add -A && G commit -qm "skeleton ships v2" )
  cp "$sk/plugins/demo/api.py" "$inst/plugins/demo/api.py"
  # ...and the skeleton has since MOVED ON to v3. The instance's dirty content
  # now matches no current skeleton file -- only a historical one.
  printf 'def api():\n    return "v3"\n' > "$sk/plugins/demo/api.py"
  ( cd "$sk" && G add -A && G commit -qm "skeleton ships v3" )

  # A founder edit that was never any skeleton revision, in the same directory.
  printf 'def local():\n    return "never shipped"\n' > "$inst/plugins/demo/local.py"
  ( cd "$inst" && G add plugins/demo/local.py && G commit -qm "instance adds its own" )
  printf 'def local():\n    return "founder changed it"\n' > "$inst/plugins/demo/local.py"

  bash "$sk/kipi-update.sh" >"$work/out" 2>&1 || true

  carve="$(G -C "$inst" log --format='%H %s' 2>/dev/null \
             | grep -F 'commit system-written state' | head -1 | cut -d' ' -f1 || true)"
  [ -n "$carve" ] || fail "no system-state commit: older fleet content stayed blocked: $(cat "$work/out")"

  G -C "$inst" show --name-only --format= "$carve" 2>/dev/null \
    | grep -qx "plugins/demo/api.py" || \
    fail "content from an OLDER skeleton version was not attributed to the fleet"

  if G -C "$inst" show --name-only --format= "$carve" 2>/dev/null \
       | grep -qx "plugins/demo/local.py"; then
    fail "a founder edit that was never a skeleton revision was committed"
  fi

  echo "PASS: content from any shipped skeleton revision is the fleet's; never-shipped content is not"
}

assert_a_mixed_pathspec_commit_commits_nothing
assert_older_fleet_content_is_attributed_to_the_fleet
assert_a_staged_founder_edit_is_never_overwritten
assert_a_staged_edit_survives_deletion_from_both_sides
assert_deletions_split_by_authorship
assert_the_carve_out_clears_tracked_system_dirt
assert_founder_work_is_never_swept
assert_untracked_source_in_a_managed_plugin_is_never_staged
assert_tracked_plugin_edits_split_by_authorship
echo "PASS: the system-state carve-out cannot be defeated by an untracked path"
