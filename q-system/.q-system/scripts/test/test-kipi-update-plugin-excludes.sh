#!/usr/bin/env bash
# A plugin-root .env is copied into all 23 instances and committed there.
#
# The per-plugin rsync excludes exactly five classes -- .git/, __pycache__/,
# *.pyc, .venv/, .pytest_cache/ -- and nothing else. `.gitignore:3` is `*.env`,
# so a plugin .env is invisible to `git status` while rsync copies it happily.
# It is not hypothetical: plugins/kipi-design/skills/design/scripts/cip/
# generate.py reads a plugin-root .env for API keys.
#
# Found by Codex on PR #149 round 3, filed as ASK-772.
#
# THE DRIFT TRAP THIS FILE EXISTS TO CLOSE. The exclusion set was written down
# TWICE: once as rsync --exclude flags (~L1892) and once as a grep filter in the
# ASK-762 source-provenance preflight (~L451). The two must agree, because they
# answer halves of one question:
#
#   rsync excludes  = "never copy this"
#   preflight filter = "do not alarm about this, because it is never copied"
#
# Add `.env` to the rsync only and the preflight starts aborting the fleet over a
# file that can no longer leak. Add it to the preflight only and the leak stays
# open and silent. One value, two authorities, opposite failure modes.
#
# So this file does NOT compare the two lists as strings -- that only proves they
# were typed the same. It drives BOTH behaviours from the shared set and asserts
# each entry is excluded by the copy AND silent in the preflight. A new entry
# added to one consumer and not the other fails here.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
fail() { echo "FAIL: $1" >&2; exit 1; }
G() { git -c user.email=t@t.t -c user.name=test -c commit.gpgsign=false "$@"; }

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
  printf 'plugin content\n' > "$sk/plugins/demo/content.txt"
  printf '# demo rule\n' > "$sk/.claude/rules/demo.md"
  # The skeleton ignores secrets and caches, exactly as the real repo does. That
  # is the whole point: gitignored is not "absent", it is "invisible to git and
  # fully visible to rsync".
  printf '*.env\n.env\n__pycache__/\n*.pyc\n.venv/\n.pytest_cache/\n' > "$sk/.gitignore"
  ( cd "$sk" && G init -q -b main && G add -A -f && G commit -qm skel )
  printf '{"instances":[{"name":"testinst","path":"%s","subtree_prefix":"q-system","type":"subtree"}]}\n' \
    "$inst" > "$sk/instance-registry.json"

  mkdir -p "$inst/q-system" "$inst/plugins/demo" "$inst/.claude"
  printf 'instance state\n' > "$inst/q-system/tracked.md"
  ( cd "$inst" && G init -q -b main && G add -A -f && G commit -qm inst )
}

# The secret, plus one file per already-excluded class, so a regression in any
# of the five shows up here too rather than only the new entry.
plant_excludables() {
  local sk="$1"
  printf 'ANTHROPIC_API_KEY=sk-not-a-real-key\n' > "$sk/plugins/demo/.env"
  printf 'OPENAI_API_KEY=sk-also-not-real\n' > "$sk/plugins/demo/.env.local"
  mkdir -p "$sk/plugins/demo/__pycache__" "$sk/plugins/demo/.venv" \
           "$sk/plugins/demo/.pytest_cache"
  printf 'cache\n' > "$sk/plugins/demo/__pycache__/x.pyc"
  printf 'venv\n' > "$sk/plugins/demo/.venv/pyvenv.cfg"
  printf 'cache\n' > "$sk/plugins/demo/.pytest_cache/CACHEDIR.TAG"
  printf 'compiled\n' > "$sk/plugins/demo/stale.pyc"
}

EXCLUDABLES=(
  "plugins/demo/.env"
  "plugins/demo/.env.local"
  "plugins/demo/__pycache__/x.pyc"
  "plugins/demo/.venv/pyvenv.cfg"
  "plugins/demo/.pytest_cache/CACHEDIR.TAG"
  "plugins/demo/stale.pyc"
)

# ------------------------------------------------------------------ property 1
# Nothing in the excluded set reaches an instance. The .env entries are the
# reason this file exists; the other four are regression cover.
assert_excluded_files_never_reach_an_instance() {
  local work sk inst; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"
  plant_excludables "$sk"

  bash "$sk/kipi-update.sh" >"$work/out" 2>&1 || true

  local rel leaked=0
  for rel in "${EXCLUDABLES[@]}"; do
    if [ -e "$inst/$rel" ]; then
      echo "  LEAKED: $rel" >&2
      leaked=1
    fi
  done
  [ "$leaked" -eq 0 ] || fail "excluded plugin files were copied into the instance"

  # The sync must actually have RUN, or "nothing leaked" is vacuous -- a run that
  # aborted early would satisfy the loop above while proving nothing.
  [ -e "$inst/plugins/demo/content.txt" ] || \
    fail "the plugin sync did not run at all, so the no-leak check proves nothing: $(cat "$work/out")"

  echo "PASS: no excluded plugin file reaches an instance (.env, .env.local, caches, pyc)"
}

# ------------------------------------------------------------------ property 2
# The other half of the same value. A file the copy can never carry must not
# abort the fleet in the ASK-762 preflight -- otherwise adding an exclusion to
# one consumer silently breaks the other.
assert_excluded_files_do_not_abort_the_preflight() {
  local work sk out; work="$(mktemp -d)"; sk="$work/skel"
  build "$work"
  plant_excludables "$sk"

  out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  if echo "$out" | grep -q "ABORT: the skeleton"; then
    fail "the source-provenance preflight aborted over files that can never be copied:
$(echo "$out" | grep -A8 'ABORT: the skeleton')"
  fi

  echo "PASS: excluded plugin files are silent in the source-provenance preflight"
}

# ------------------------------------------------------------------ property 3
# The guard must still fire on an untracked plugin file that IS copied. Without
# this, widening the exclusion set to silence the preflight would pass property 2
# by disarming the guard entirely.
assert_a_copied_untracked_plugin_file_still_aborts() {
  local work sk inst; work="$(mktemp -d)"; sk="$work/skel"; inst="$work/inst"
  build "$work"
  printf 'unreviewed, and rsync WILL copy this\n' > "$sk/plugins/demo/scratch.md"

  local out; out="$(bash "$sk/kipi-update.sh" 2>&1)" || true
  echo "$out" | grep -q "ABORT: the skeleton" || \
    fail "an untracked plugin file that IS copied did not abort the preflight: $out"
  echo "$out" | grep -q "plugins/demo/scratch.md" || \
    fail "the abort did not name the file: $out"

  echo "PASS: an untracked plugin file that IS copied still aborts"
}

assert_excluded_files_never_reach_an_instance
assert_excluded_files_do_not_abort_the_preflight
assert_a_copied_untracked_plugin_file_still_aborts
echo "PASS: one exclusion set, both consumers agree, and the guard stays armed"
