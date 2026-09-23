#!/usr/bin/env bash
# ASK-605: tracked hook state under a never-commit directory blocks the sync forever.
#
# The real case, measured 2026-09-23 by the read-only fleet-reach-audit.py:
#
#   REACH: 21 of 24 would sync now
#   <instance A>  [BLOCKED-FOUNDER]   M  wtree  founder  .claude/state/kb-graph-guard.json
#   <instance B>  [BLOCKED-FOUNDER]   M  wtree  founder  .claude/state/kb-graph-guard.json
#   <instance C>  [BLOCKED-FOUNDER]   M  wtree  founder  .claude/state/stop-gate-firings.json
#
# The skeleton .gitignore ignores .claude/state/, but root .gitignore does not
# sync, and those copies were committed before the rule reached the instances.
# An ignore rule cannot untrack a file. A hook rewrites the file every session,
# so it is dirty on every run and the dirty-tree guard refuses every run.
#
# The fixture reproduces that shape: a tracked, then modified,
# .claude/state/kb-graph-guard.json in an otherwise clean instance. It drives the
# REAL kipi-update.sh from a throwaway skeleton against a throwaway instance.
# Nothing here reads or writes a live instance.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }
STATE=".claude/state/kb-graph-guard.json"

build() {
  local work="$1" sk="$work/skel" inst="$work/inst"
  mkdir -p "$sk/q-system/.q-system/scripts" "$sk/q-system/.q-system/state" \
           "$sk/q-system/hooks" "$sk/.claude/rules"
  for f in kipi-update.sh kipi-update-preserve-scan.py kipi-update-deletion-guard.py \
           kipi-update-gitignore-block.py validate-separation.py; do
    cp "$ROOT/$f" "$sk/$f"
  done
  # The REAL shipped .gitignore, so the never-commit stanza under test is the one
  # the skeleton actually ships. A hand-written stanza would pass while the real
  # one still lacked the directory.
  cp "$ROOT/.gitignore" "$sk/.gitignore"
  cp "$ROOT/q-system/.q-system/scripts/propagation-leak-gate.py" \
     "$sk/q-system/.q-system/scripts/propagation-leak-gate.py"
  cp "$ROOT/q-system/.q-system/scripts/containment-targets.py" \
     "$sk/q-system/.q-system/scripts/containment-targets.py"
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
  printf '# demo rule\n' > "$sk/.claude/rules/demo.md"
  ( cd "$sk" && G init -q -b main && G add -A -f && G commit -qm skel )
  printf '{"instances":[{"name":"testinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
    "$inst" > "$sk/instance-registry.json"

  mkdir -p "$inst/q-system" "$inst/.claude/state"
  printf 'instance state\n' > "$inst/q-system/tracked.md"
  # Committed before the ignore rule could reach it: the live shape.
  printf '{"checked": 1, "last": "2026-09-10T00:00:00Z"}\n' > "$inst/$STATE"
  ( cd "$inst" && G init -q -b main && G add -A -f && G commit -qm inst )
  # A hook rewrote it this session. Tracked AND modified.
  printf '{"checked": 2, "last": "2026-09-23T00:00:00Z"}\n' > "$inst/$STATE"
  cp "$inst/$STATE" "$work/state.before"
}

tracked() { [ -n "$(G -C "$1" ls-files -- "$2")" ]; }

# ------------------------------------------------------------------ property 1
# The real run untracks the state file, keeps its bytes, and the sync goes on.
assert_tracked_state_is_untracked_and_the_sync_proceeds() {
  local work sk inst out; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"
  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  printf '%s\n' "$out" > "$work/out1"

  case "$out" in *"--- testinst"*) ;; *) fail "the run never reached the instance: $out" ;; esac
  case "$out" in
    *"refusing to commit unrelated work"*)
      fail "refused over tracked hook state under .claude/state/:
$(grep -A8 -- '--- testinst' "$work/out1" || true)" ;;
  esac
  tracked "$inst" "$STATE" && fail "$STATE is still tracked after the run"
  cmp -s "$inst/$STATE" "$work/state.before" || fail "$STATE bytes changed on disk"
  # Positive proof the sync ran to completion, not merely that no refusal printed.
  tracked "$inst" ".claude/rules/demo.md" || fail "the skeleton rule never landed: the sync did not run"
  G -C "$inst" check-ignore -q -- "$STATE" || fail "$STATE is untracked but NOT ignored: the next auto-commit re-adds it"

  # Run twice: the hook rewrites the file again, and the second run must be clean.
  printf '{"checked": 3}\n' > "$inst/$STATE"
  local before_head; before_head="$(G -C "$inst" rev-parse HEAD)"
  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  case "$out" in *"refusing to commit unrelated work"*) fail "second run refused: $out" ;; esac
  case "$out" in *"--- testinst"*) ;; *) fail "second run never reached the instance" ;; esac
  if G -C "$inst" log --format=%s "$before_head..HEAD" | grep -c 'never-commit' >/dev/null; then
    fail "the second run untracked again: the first untrack did not hold"
  fi
  echo "PASS: tracked hook state is untracked, kept on disk, ignored, and the sync proceeds (twice)"
}

# ------------------------------------------------------------------ property 2
# Control: founder work in the sync scope must still be refused. Founder SOURCE,
# because auto-commit.py --system-state refuses source by extension (ASK-712);
# a .claude/rules edit is NOT a valid control, the classifier calls it chore and
# the carve-out commits it (observed while writing this test).
assert_founder_source_edit_still_refuses() {
  local work sk inst out; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"
  mkdir -p "$inst/q-system/tools"
  printf 'def local():\n    return 1\n' > "$inst/q-system/tools/local_tool.py"
  ( cd "$inst" && G add q-system/tools/local_tool.py && G commit -qm "founder tool" )
  printf 'def local():\n    return 2\n' > "$inst/q-system/tools/local_tool.py"
  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  case "$out" in
    *"refusing to commit unrelated work"*) ;;
    *) fail "a modified founder source file was NOT refused: $out" ;;
  esac
  G -C "$inst" diff --name-only | grep -cx 'q-system/tools/local_tool.py' >/dev/null \
    || fail "the founder edit was committed or reverted"
  echo "PASS: a modified founder source file still refuses"
}

# ------------------------------------------------------------------ property 3
# Staged founder work: the untrack must not run (its commit takes no pathspec).
assert_staged_work_blocks_the_untrack() {
  local work sk inst out; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"
  printf 'founder staged\n' > "$inst/q-system/tracked.md"
  ( cd "$inst" && G add q-system/tracked.md )
  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  tracked "$inst" "$STATE" || fail "untracked while founder work was staged"
  G -C "$inst" diff --cached --name-only | grep -cx 'q-system/tracked.md' >/dev/null \
    || fail "the founder's staged edit is no longer staged"
  echo "PASS: staged founder work leaves the untrack alone"
}

# ------------------------------------------------------------------ property 4
# --dry-run models the untrack and changes nothing real.
assert_dry_run_models_it_and_touches_nothing() {
  local work sk inst out head0; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"
  head0="$(G -C "$inst" rev-parse HEAD)"
  out="$(bash "$sk/kipi-update.sh" --dry-run 2>&1)" || true
  case "$out" in *"--- testinst"*) ;; *) fail "dry run never reached the instance: $out" ;; esac
  case "$out" in *"dirty working tree"*) fail "dry run still refuses on tracked hook state: $out" ;; esac
  [ "$(G -C "$inst" rev-parse HEAD)" = "$head0" ] || fail "dry run moved the real HEAD"
  tracked "$inst" "$STATE" || fail "dry run untracked the file in the REAL instance"
  echo "PASS: --dry-run models the untrack and leaves the real instance alone"
}

assert_tracked_state_is_untracked_and_the_sync_proceeds
assert_founder_source_edit_still_refuses
assert_staged_work_blocks_the_untrack
assert_dry_run_models_it_and_touches_nothing
echo "PASS: tracked never-commit state cannot block the fleet sync (ASK-605)"
